#!/usr/bin/env python3
"""
灵境智游 - 知识库分块嵌入向量生成脚本

功能说明：
- 查询 knowledge_chunks 表中 embedding 为空的记录
- 使用本地BGE-M3生成1024维向量
- 将向量写入数据库 pgvector 字段
- 支持幂等执行、并发请求、重试机制、进度显示

使用方法：
    cd backend
    python -m scripts.generate_embeddings

    # 强制重新生成所有chunk
    python -m scripts.generate_embeddings --force

    # 自定义并发数
    python -m scripts.generate_embeddings --concurrency 10

    # 自定义重试次数
    python -m scripts.generate_embeddings --retry 5

环境变量：
    DATABASE_URL              - 数据库连接字符串
    USE_LOCAL_EMBEDDING       - true 时使用本地模型
    EMBEDDING_MODEL_PATH      - 本地 BGE-M3 路径
    EMBEDDING_LOCAL_BACKEND   - auto / sentence-transformers / onnx
"""

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import UUID

# 将项目根目录加入 Python 路径，以便导入 app 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings
from app.models.knowledge import KnowledgeChunk


# 默认配置
DEFAULT_CONCURRENCY = 5
DEFAULT_RETRY = 3
DEFAULT_BATCH_SIZE = 1

# 本地BGE-M3 Embedding 配置
EMBEDDING_MODEL = "bge-m3-local"
EMBEDDING_DIMENSION = 1024

TOKEN_PER_CHAR = 1.5


@dataclass
class ProcessingStats:
    """处理统计信息"""

    total: int = 0          # 总chunk数
    processed: int = 0      # 已处理数
    success: int = 0        # 成功数
    failed: int = 0         # 失败数
    skipped: int = 0        # 跳过数（已有embedding）
    total_chars: int = 0    # 总字符数
    total_tokens: int = 0   # 估算总token数
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        """已耗时（秒）"""
        return time.time() - self.start_time

    def __str__(self) -> str:
        elapsed = self.elapsed
        rate = self.processed / elapsed if elapsed > 0 else 0
        return (
            f"\n"
            f"  总chunk数: {self.total}\n"
            f"  已处理: {self.processed} / {self.total}\n"
            f"  成功: {self.success}\n"
            f"  失败: {self.failed}\n"
            f"  跳过: {self.skipped}\n"
            f"  总字符数: {self.total_chars}\n"
            f"  估算token数: {self.total_tokens}\n"
            f"  耗时: {elapsed:.1f}s\n"
            f"  处理速率: {rate:.2f} chunk/s"
        )


async def ensure_embedding_column(session: AsyncSession) -> bool:
    """
    检查并创建 embedding 列。

    如果 knowledge_chunks 表中没有 embedding 列，
    则自动添加 pgvector 类型的 vector(1024) 列。

    Args:
        session: 数据库异步会话

    Returns:
        是否成功创建/确认列存在
    """
    # 检查列是否存在
    result = await session.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding'
    """))
    if result.fetchone():
        logger.info("embedding 列已存在")
        return True

    # 创建 pgvector 扩展（如果不存在）
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 添加 embedding 列
    await session.execute(text(f"""
        ALTER TABLE knowledge_chunks
        ADD COLUMN embedding vector({EMBEDDING_DIMENSION})
    """))
    await session.commit()

    logger.info(f"embedding 列已创建 (vector({EMBEDDING_DIMENSION}))")
    return True


async def get_chunks_to_process(
    session: AsyncSession,
    force: bool = False,
) -> list[tuple[UUID, str]]:
    """
    获取待处理的 chunk 列表。

    Args:
        session: 数据库异步会话
        force: 是否强制重新生成（忽略已有 embedding 的记录）

    Returns:
        (chunk_id, content) 元组列表
    """
    if force:
        # 强制模式：获取所有 chunk
        result = await session.execute(
            select(KnowledgeChunk.id, KnowledgeChunk.content)
            .order_by(KnowledgeChunk.chunk_index)
        )
    else:
        # 幂等模式：只获取 embedding 为空的 chunk（使用原始SQL，因为ORM模型未定义embedding字段）
        result = await session.execute(
            text("""
                SELECT id, content FROM knowledge_chunks
                WHERE embedding IS NULL
                ORDER BY chunk_index
            """)
        )

    return [(row.id, row.content) for row in result.all()]


async def generate_embedding_local(content: str) -> Optional[list[float]]:
    """使用本地BGE-M3模型生成嵌入向量"""
    try:
        from app.core.embedding_provider import get_local_embedding_provider

        provider = get_local_embedding_provider()
        embedding = await provider.embed(content)
        if provider.backend_info:
            logger.debug(f"本地 embedding 后端: {provider.backend_info.name}")
        return embedding
    except Exception as e:
        logger.error(f"本地嵌入模型生成失败: {e}")
        return None


async def generate_embedding(content: str) -> Optional[list[float]]:
    """生成嵌入向量。"""

    if settings.EMBEDDING_SERVICE_URL:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{settings.EMBEDDING_SERVICE_URL.rstrip('/')}/embed",
                    json={"text": content[:4000]},
                )
                response.raise_for_status()
                return response.json()["embedding"]
        except Exception as exc:
            logger.error(f"嵌入服务生成失败: {exc}")
            return None
    return await generate_embedding_local(content)


async def update_embedding(
    session: AsyncSession,
    chunk_id: UUID,
    embedding: list[float],
) -> bool:
    """
    更新数据库中的 embedding 字段。

    Args:
        session: 数据库异步会话
        chunk_id: chunk ID
        embedding: 向量数据

    Returns:
        是否成功
    """
    try:
        embedding_str = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
        sql = text("UPDATE knowledge_chunks SET embedding = CAST(:embedding AS vector) WHERE id = :chunk_id")
        await session.execute(sql, {"chunk_id": chunk_id, "embedding": embedding_str})
        await session.commit()
        return True
    except Exception as e:
        logger.error(f"更新 embedding 失败 (chunk_id={chunk_id}): {e}")
        await session.rollback()
        return False


async def process_single_chunk(
    db_url: str,
    chunk_id: UUID,
    content: str,
    stats: ProcessingStats,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    处理单个 chunk：生成 embedding 并写入数据库。

    Args:
        db_url: 数据库连接字符串
        chunk_id: chunk ID
        content: chunk 内容
        stats: 统计信息对象
        semaphore: 并发控制信号量
    """
    async with semaphore:
        embedding = await generate_embedding(content)

        if embedding is None:
            stats.failed += 1
            stats.processed += 1
            return

        # 写入数据库（每个任务独立会话）
        engine = create_async_engine(db_url, echo=False)
        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with AsyncSessionLocal() as session:
                success = await update_embedding(session, chunk_id, embedding)
                if success:
                    stats.success += 1
                    stats.total_chars += len(content)
                    stats.total_tokens += int(len(content) * TOKEN_PER_CHAR)
                else:
                    stats.failed += 1
        except Exception as e:
            logger.error(f"数据库操作失败 (chunk_id={chunk_id}): {e}")
            stats.failed += 1
        finally:
            await engine.dispose()
            stats.processed += 1


async def run(
    db_url: str,
    concurrency: int = DEFAULT_CONCURRENCY,
    retry: int = DEFAULT_RETRY,
    force: bool = False,
) -> ProcessingStats:
    """
    执行嵌入向量生成主流程。

    Args:
        db_url: 数据库连接字符串
        concurrency: 并发数
        retry: 重试次数
        force: 是否强制重新生成

    Returns:
        处理统计信息
    """
    stats = ProcessingStats()

    # 创建主会话用于查询
    engine = create_async_engine(db_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        # 1. 确保 embedding 列存在
        print("\n[1/3] 检查 embedding 列...")
        await ensure_embedding_column(session)

        # 2. 获取待处理的 chunk
        print("\n[2/3] 获取待处理 chunk...")
        chunks = await get_chunks_to_process(session, force=force)
        stats.total = len(chunks)

        if not chunks:
            print("  没有需要处理的 chunk（所有 chunk 已有 embedding）")
            await engine.dispose()
            return stats

        print(f"  共 {len(chunks)} 个 chunk 待处理")

        # 统计已有 embedding 的数量（幂等模式下）
        if not force:
            result = await session.execute(
                text("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL")
            )
            stats.skipped = result.scalar() or 0
            print(f"  已有 embedding 的 chunk: {stats.skipped} 个（已跳过）")

    await engine.dispose()

    # 3. 并发处理
    print(f"\n[3/3] 开始生成 embedding（并发数={concurrency}, 重试={retry}）...")
    print("-" * 60)

    semaphore = asyncio.Semaphore(concurrency)
    progress_interval = 10  # 每处理 10 个打印一次进度

    tasks = []
    for chunk_id, content in chunks:
        task = asyncio.create_task(
            process_single_chunk(
                db_url, chunk_id, content,
                stats, semaphore,
            )
        )
        tasks.append(task)

    for i, task in enumerate(asyncio.as_completed(tasks), 1):
        await task
        if i % progress_interval == 0 or i == len(tasks):
            print(
                f"  进度: {stats.processed}/{stats.total} "
                f"(成功 {stats.success}, 失败 {stats.failed})"
            )

    print("-" * 60)
    return stats


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="为 knowledge_chunks 表生成 embedding 向量",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python -m scripts.generate_embeddings
    python -m scripts.generate_embeddings --force
    python -m scripts.generate_embeddings --concurrency 10 --retry 5
        """,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新生成所有 chunk 的 embedding（覆盖已有数据）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"并发请求数（默认 {DEFAULT_CONCURRENCY}）",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=DEFAULT_RETRY,
        help=f"API 调用失败时的重试次数（默认 {DEFAULT_RETRY}）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每批处理的 chunk 数（默认 {DEFAULT_BATCH_SIZE}，当前仅支持 1）",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "sentence-transformers", "onnx"],
        default=None,
        help="本地 embedding 后端，默认读取 EMBEDDING_LOCAL_BACKEND",
    )
    return parser.parse_args()


async def main():
    """主入口函数。"""
    args = parse_args()

    print("=" * 60)
    print("灵境智游 - 知识库嵌入向量生成")
    print("=" * 60)

    # 读取配置
    db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
    if args.backend:
        os.environ["EMBEDDING_LOCAL_BACKEND"] = args.backend
        settings.EMBEDDING_LOCAL_BACKEND = args.backend

    print(f"\n配置信息:")
    print(f"  数据库: {db_url.replace('://', '://***:***@')}")
    print(f"  嵌入服务: {settings.EMBEDDING_SERVICE_URL or '进程内本地BGE-M3'}")
    print(f"  嵌入模型: {EMBEDDING_MODEL} ({EMBEDDING_DIMENSION} 维)")
    print(f"  并发数: {args.concurrency}")
    print(f"  重试次数: {args.retry}")
    if args.force:
        print(f"  模式: 强制重新生成（覆盖已有 embedding）")
    else:
        print(f"  模式: 幂等执行（跳过已有 embedding）")

    # 执行生成
    try:
        stats = await run(
            db_url=db_url,
            concurrency=args.concurrency,
            retry=args.retry,
            force=args.force,
        )

        # 输出最终统计
        print("\n" + "=" * 60)
        print("处理完成！")
        print("=" * 60)
        print(stats)

        if stats.failed > 0:
            print(f"\n警告: {stats.failed} 个 chunk 处理失败，可重新运行脚本进行补全")
            sys.exit(2)

    except KeyboardInterrupt:
        print("\n\n用户中断，已停止处理")
        sys.exit(130)
    except Exception as e:
        print(f"\n错误: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
