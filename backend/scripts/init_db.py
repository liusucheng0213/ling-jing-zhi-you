#!/usr/bin/env python3
"""
灵境智游 - 数据库结构初始化脚本

功能：
- 创建所有SQLAlchemy模型对应的表
- 安装pgvector扩展
- 创建embedding向量列（pgvector）
- 创建必要的索引

使用方式：
    cd backend
    python -m scripts.init_db
"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.ext.asyncio import create_async_engine

from app.models.base import Base
from app.config import settings


DATABASE_URL = os.getenv("DATABASE_URL", settings.DATABASE_URL)


async def init_pgvector_extension(engine):
    """安装pgvector扩展"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        result = await conn.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
        row = result.fetchone()
        if row:
            print("  pgvector扩展已安装")
        else:
            print("  警告：pgvector扩展安装失败")


async def create_tables(engine):
    """创建所有SQLAlchemy模型对应的表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  SQLAlchemy模型表已创建")


async def create_embedding_column(engine):
    """为knowledge_chunks表添加embedding向量列"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        # 检查列是否存在
        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'knowledge_chunks' AND column_name = 'embedding'
        """))
        if result.fetchone():
            print("  embedding列已存在")
        else:
            # 添加embedding列（1024维，适配本地BGE-M3）
            await conn.execute(text("""
                ALTER TABLE knowledge_chunks
                ADD COLUMN embedding vector(1024)
            """))
            print("  embedding列已创建 (vector(1024))")

        # HNSW无需训练且小规模召回更稳定，适合知识持续更新的景区知识库。
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding_hnsw
            ON knowledge_chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """))
        print("  向量索引已创建 (HNSW)")


async def ensure_spot_coordinate_columns(engine):
    """兼容未使用 Alembic 的既有演示库，幂等补齐坐标来源字段。"""
    from sqlalchemy import text

    columns = {
        "coordinate_system": "VARCHAR(20)",
        "coordinate_status": "VARCHAR(20)",
        "coordinate_source": "TEXT",
        "coordinate_source_id": "VARCHAR(100)",
        "coordinate_accuracy_meters": "DOUBLE PRECISION",
        "coordinate_verified_at": "TIMESTAMPTZ",
        "source_latitude": "DOUBLE PRECISION",
        "source_longitude": "DOUBLE PRECISION",
        "source_coordinate_system": "VARCHAR(20)",
    }
    async with engine.begin() as conn:
        for name, sql_type in columns.items():
            await conn.execute(text(f"ALTER TABLE spots ADD COLUMN IF NOT EXISTS {name} {sql_type}"))
        await conn.execute(text("UPDATE spots SET coordinate_system = 'WGS84' WHERE coordinate_system IS NULL"))
        await conn.execute(text("UPDATE spots SET coordinate_status = 'estimated' WHERE coordinate_status IS NULL"))
    print("  景点坐标来源字段已检查")


async def create_other_indexes(engine):
    """创建其他常用索引"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        indexes = [
            ("idx_spots_scenic_area", "spots", "scenic_area"),
            ("idx_spots_active", "spots", "is_active"),
            ("idx_knowledge_docs_status", "knowledge_documents", "status"),
            ("idx_knowledge_docs_spot", "knowledge_documents", "spot_id"),
            ("idx_knowledge_chunks_doc", "knowledge_chunks", "document_id"),
            ("idx_chat_messages_session", "chat_messages", "session_id"),
            ("idx_chat_sessions_user", "sessions", "user_id"),
            ("idx_chat_sessions_started_at", "sessions", "started_at"),
            ("idx_chat_messages_created_at", "chat_messages", "created_at"),
            ("idx_emotion_history_created_at", "emotion_history", "created_at"),
            ("idx_behavior_logs_created_at", "behavior_logs", "created_at"),
            ("idx_creative_contents_type", "creative_contents", "content_type"),
            ("idx_routes_active", "routes", "is_active"),
        ]

        for idx_name, table, column in indexes:
            try:
                await conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {table} ({column})
                """))
            except Exception as e:
                print(f"  警告：索引 {idx_name} 创建失败: {e}")

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content_trgm
            ON knowledge_chunks USING gin (content gin_trgm_ops)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_docs_title_trgm
            ON knowledge_documents USING gin (title gin_trgm_ops)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sessions_status_started_at
            ON sessions (status, started_at DESC)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_role_created_at
            ON chat_messages (role, created_at DESC)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_spot_created_at
            ON chat_messages (spot_id, created_at DESC)
            WHERE spot_id IS NOT NULL
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_emotion_history_type_created_at
            ON emotion_history (emotion_type, created_at DESC)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_behavior_logs_type_created_at
            ON behavior_logs (event_type, created_at DESC)
        """))

    print("  常用索引已创建")


async def main():
    print("=" * 60)
    print("灵境智游 - 数据库结构初始化")
    print("=" * 60)

    print(f"\n连接数据库...")
    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        # 1. 安装pgvector扩展
        print("\n[1/5] 安装pgvector扩展...")
        await init_pgvector_extension(engine)

        # 2. 创建表
        print("\n[2/5] 创建数据表...")
        await create_tables(engine)

        # 3. 补齐演示库增量字段
        print("\n[3/5] 检查景点坐标字段...")
        await ensure_spot_coordinate_columns(engine)

        # 4. 创建embedding列和向量索引
        print("\n[4/5] 创建向量检索列...")
        await create_embedding_column(engine)

        # 5. 创建其他索引
        print("\n[5/5] 创建常用索引...")
        await create_other_indexes(engine)

        print("\n" + "=" * 60)
        print("数据库结构初始化完成！")
        print("=" * 60)
        print("\n下一步：")
        print("  1. 运行 python -m scripts.init_data    (初始化景点和路线)")
        print("  2. 运行 python -m scripts.ingest_knowledge (初始化知识库)")

    except Exception as e:
        print(f"\n错误：数据库初始化失败 - {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
