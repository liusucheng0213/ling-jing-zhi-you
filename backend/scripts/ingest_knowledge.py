#!/usr/bin/env python3
"""
灵境智游 - 知识库文档分块与入库脚本

功能说明：
- 读取 knowledge_docs.json
- 对每篇文档进行智能分块（chunk_size=500, overlap=50）
- 插入 KnowledgeDocument 和 KnowledgeChunk 记录
- embedding 字段暂时留空，后续可通过 API 或本地模型生成
- 支持幂等执行（根据文档标题判断，已存在则先删除再插入）

使用方法：
    cd backend
    python -m scripts.ingest_knowledge

环境变量：
    DATABASE_URL - 数据库连接字符串，默认 postgresql+asyncpg://user:pass@localhost:5432/lingjing
"""

import asyncio
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

# 将项目根目录加入 Python 路径，以便导入 app 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from app.models.spot import Spot


# 数据库连接字符串（从环境变量读取，使用默认值）
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/lingjing"
)

# JSON 数据文件路径
SCRIPTS_DIR = Path(__file__).resolve().parent
KNOWLEDGE_JSON = SCRIPTS_DIR / "knowledge_docs.json"
FAQ_JSON = SCRIPTS_DIR / "faq_data.json"
ENHANCED_JSON = SCRIPTS_DIR / "lingshan_enhanced_knowledge.json"
VERIFIED_JSON = SCRIPTS_DIR / "verified_official_knowledge.json"
A5_OFFICIAL_JSON = SCRIPTS_DIR / "a5_official_materials.json"
PUBLIC_MATERIAL_DIR = Path(
    os.getenv("PUBLIC_MATERIAL_DIR", str(PROJECT_ROOT.parent / "示范景区公开资料包"))
)

# 分块参数：与管理端上传保持一致，子块更短，父块上下文由文档元数据保留
CHUNK_SIZE = 420
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """
    对文本进行智能分块。

    分块策略：
    1. 如果文本长度小于 chunk_size，直接返回单一块
    2. 否则按滑动窗口切分，在窗口末端寻找最近的语义边界
    3. 优先按段落边界(\n\n)，其次按句末标点(。、？、！、；)，最后按换行(\n)切分
    4. 确保切分点位于 chunk_size 的后半段，避免块过小

    Args:
        text: 待分块的原始文本
        chunk_size: 每块最大字符数
        chunk_overlap: 块与块之间的重叠字符数

    Returns:
        分块后的文本列表
    """
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    start = 0
    prev_start = -1

    while start < len(text):
        # 计算当前块的结束位置
        end = min(start + chunk_size, len(text))

        if end < len(text):
            # 寻找最近的语义边界（优先段落，其次句子，最后换行）
            # 边界必须位于后半段（避免块过小）
            min_split_pos = start + chunk_size // 2

            for sep in ["\n\n", "。", "？", "！", "；", "\n"]:
                # rfind 从 end 往前找，返回最后一个匹配位置
                pos = text.rfind(sep, start, end)
                if pos > min_split_pos:
                    # 包含分隔符本身（句号等标点需要保留在块内）
                    end = pos + len(sep)
                    break

        # 提取当前块并去除首尾空白
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # 下一个块的起始位置（考虑重叠）
        prev_start = start
        start = end - chunk_overlap
        # 确保起始位置不会倒退或越界，且能推进（避免死循环）
        if start <= 0 or start >= len(text) or start <= prev_start:
            break

    return [c for c in chunks if c]


def build_parent_chunk_metadata(content: str, parent_size: int = 1400) -> list[dict[str, str | int]]:
    """构建父块标题和摘要，用于给子块补足上下文。"""

    paragraphs = [para.strip() for para in content.split("\n\n") if para.strip()]
    parents: list[dict[str, str | int]] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs or [content]:
        if current and current_len + len(para) > parent_size:
            parent_text = "\n\n".join(current)
            parents.append(summarize_parent(parent_text, len(parents)))
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)
    if current:
        parents.append(summarize_parent("\n\n".join(current), len(parents)))
    return parents


def summarize_parent(text: str, index: int) -> dict[str, str | int]:
    """生成无需外部模型的父块摘要。"""

    first_line = next((line.strip("# ").strip() for line in text.splitlines() if line.strip()), "")
    title = first_line[:48] or f"父块 {index + 1}"
    summary = text.replace("\n", " ")[:180]
    return {"index": index, "title": f"父块{index + 1}: {title}", "summary": summary, "content": text}


def find_parent_for_child(parents: list[dict[str, str | int]], child_text: str) -> dict[str, str | int] | None:
    """根据子块文本选择所属父块。"""

    for parent in parents:
        content = str(parent["content"])
        if child_text[:80] in content or child_text in content:
            return parent
    return parents[0] if parents else None


async def load_json(path: Path) -> list[dict[str, Any]]:
    """加载 JSON 文件并返回数据列表。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_docx_text(path: Path) -> str:
    """完整抽取 Word 段落与表格，保留字段名供 RAG 词面检索。"""

    from docx import Document

    document = Document(path)
    sections = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table_index, table in enumerate(document.tables, start=1):
        rows = []
        for row in table.rows:
            values = [cell.text.strip().replace("\n", "；") for cell in row.cells]
            if any(values):
                rows.append(" | ".join(values))
        if rows:
            sections.append(f"表格 {table_index}\n" + "\n".join(rows))
    return "\n\n".join(sections).strip()


def load_public_docx_materials() -> list[dict[str, Any]]:
    """加载示范景区 Word 资料，并记录文件来源与更新时间。"""

    if not PUBLIC_MATERIAL_DIR.exists():
        return []
    materials: list[dict[str, Any]] = []
    from docx import Document

    for path in sorted(PUBLIC_MATERIAL_DIR.glob("*.docx")):
        document = Document(path)
        structured_rows = 0
        for table in document.tables:
            if not table.rows:
                continue
            headers = [cell.text.strip() for cell in table.rows[0].cells]
            if "景点ID" not in headers or "景点名称" not in headers:
                continue
            for row in table.rows[1:]:
                values = [cell.text.strip().replace("\n", "；") for cell in row.cells]
                record = dict(zip(headers, values))
                spot_id = record.get("景点ID") or None
                spot_name = record.get("景点名称") or spot_id or "未命名景点"
                scenic_name = record.get("景区名称") or "灵山胜境"
                content = "\n".join(
                    f"{header}：{record.get(header, '')}"
                    for header in headers
                    if record.get(header)
                )
                if not content:
                    continue
                filled_fields = sum(1 for header in headers if record.get(header))
                materials.append(
                    {
                        "title": f"公开资料-{scenic_name}-{spot_name}",
                        "doc_type": "spot_reference",
                        "content": content,
                        "spot_id": spot_id,
                        "source_file": path.name,
                        "source_mtime": path.stat().st_mtime,
                        # 仅供补全流程使用的内部字段,不入库
                        "spot_name": spot_name,
                        "filled_fields": filled_fields,
                        "total_fields": len(headers),
                    }
                )
                structured_rows += 1

        paragraph_text = "\n\n".join(
            paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()
        )
        if structured_rows:
            content = paragraph_text
        else:
            content = _extract_docx_text(path)
        if content:
            materials.append(
                {
                    "title": f"公开资料-{path.stem}-总览",
                    "doc_type": "official_material",
                    "content": content,
                    "spot_id": None,
                    "source_file": path.name,
                    "source_mtime": path.stat().st_mtime,
                }
            )
    return materials


# 结构化行字段填充率低于该阈值时,从资料包其他叙述性文档中补全
SPARSE_FILL_RATIO = 0.75
# 单个景点最多补充的叙述段落数与总字数,避免稀释检索精度
ENRICH_MAX_PARAGRAPHS = 6
ENRICH_MAX_CHARS = 900


def enrich_sparse_spot_materials(materials: list[dict[str, Any]]) -> int:
    """
    补全结构化数据集中字段残缺的景点条目。

    策略:
    1. 收集资料包内所有叙述性 docx(非结构化表)的段落;
    2. 对每个填充率不足的 spot_reference 条目,按景点名匹配相关段落;
    3. 去重后追加为"导览资料补充"小节,并在文档元数据中标注补全来源。

    只补全资料包中真实存在的内容,不生成任何资料之外的新事实。

    Returns:
        实际补全的条目数。
    """

    if not PUBLIC_MATERIAL_DIR.exists():
        return 0

    sparse = [
        m for m in materials
        if m.get("doc_type") == "spot_reference"
        and m.get("filled_fields", 99) < m.get("total_fields", 11) * SPARSE_FILL_RATIO
    ]
    if not sparse:
        return 0

    # 建立 景点名 -> 叙述段落 索引(段落来自资料包中所有 docx 的非表格文本)
    from docx import Document

    spot_names = [m["spot_name"] for m in sparse if m.get("spot_name")]
    narrative: dict[str, list[str]] = {name: [] for name in spot_names}
    for path in sorted(PUBLIC_MATERIAL_DIR.glob("*.docx")):
        document = Document(path)
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if len(text) < 12:
                continue
            for name in spot_names:
                if name in text:
                    narrative[name].append(text)

    enriched = 0
    for item in sparse:
        name = item.get("spot_name")
        paragraphs = narrative.get(name) or []
        if not paragraphs:
            print(f"  补全提示: 《{item['title']}》字段残缺,但资料包中无更多叙述可参考,保持原样")
            continue
        additions: list[str] = []
        total = 0
        for text in paragraphs:
            if text in item["content"]:
                continue
            if len(additions) >= ENRICH_MAX_PARAGRAPHS or total + len(text) > ENRICH_MAX_CHARS:
                break
            additions.append(text)
            total += len(text)
        if not additions:
            continue
        item["content"] = (
            f"{item['content']}\n\n"
            f"导览资料补充(来自资料包叙述文档):\n" + "\n".join(additions)
        )
        item["enriched_from_narrative"] = True
        enriched += 1
        print(f"  补全: 《{item['title']}》追加 {len(additions)} 段导览资料(原 {item['filled_fields']}/{item['total_fields']} 字段)")
    return enriched


# Excel 聚合:只产出统计画像,绝不逐行入库,避免十万级行数据拖垮检索
XLSX_FOCUS_KEYWORDS = ("灵山", "拈花湾")
XLSX_TOP_N = 10


def load_public_xlsx_materials() -> list[dict[str, Any]]:
    """
    将游客行为 Excel 聚合为少量统计知识文档。

    性能原则:14 万行原始记录只做一次流式聚合(O(n) 单遍扫描),
    入库的是聚合后的画像与基准文档(个位数篇),运行时检索零额外开销。
    """

    if not PUBLIC_MATERIAL_DIR.exists():
        return []
    materials: list[dict[str, Any]] = []

    for path in sorted(PUBLIC_MATERIAL_DIR.glob("*.xlsx")):
        try:
            from openpyxl import load_workbook
        except ImportError:
            print("  警告: 未安装 openpyxl,跳过 Excel 公开资料聚合")
            return []

        workbook = load_workbook(path, read_only=True)
        sheet = workbook.active
        header = [str(cell).strip() if cell is not None else "" for cell in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))]
        index = {name: pos for pos, name in enumerate(header)}
        required = ["attraction_name", "age", "gender", "stay_duration", "ticket_cost",
                    "food_cost", "shopping_cost", "transport_cost", "entertainment_cost",
                    "total_cost", "group_size", "satisfaction", "visit_date"]
        if not all(name in index for name in required):
            print(f"  警告: {path.name} 缺少必需列,跳过")
            continue

        def new_stats() -> dict[str, Any]:
            return {
                "n": 0, "age": 0.0, "gender": Counter(), "stay": 0.0,
                "ticket": 0.0, "food": 0.0, "shopping": 0.0, "transport": 0.0,
                "entertainment": 0.0, "total": 0.0, "group": 0.0,
                "satisfaction": 0.0, "sat_dist": Counter(), "months": Counter(),
            }

        per_spot: dict[str, dict[str, Any]] = {}
        overall = new_stats()
        for row in sheet.iter_rows(min_row=2, values_only=True):
            name = row[index["attraction_name"]]
            if not name:
                continue
            name = str(name).strip()
            stats = per_spot.setdefault(name, new_stats())
            for target in (stats, overall):
                target["n"] += 1
                target["age"] += float(row[index["age"]] or 0)
                target["gender"][row[index["gender"]] or "未知"] += 1
                target["stay"] += float(row[index["stay_duration"]] or 0)
                target["ticket"] += float(row[index["ticket_cost"]] or 0)
                target["food"] += float(row[index["food_cost"]] or 0)
                target["shopping"] += float(row[index["shopping_cost"]] or 0)
                target["transport"] += float(row[index["transport_cost"]] or 0)
                target["entertainment"] += float(row[index["entertainment_cost"]] or 0)
                target["total"] += float(row[index["total_cost"]] or 0)
                target["group"] += float(row[index["group_size"]] or 0)
                sat = row[index["satisfaction"]]
                if isinstance(sat, (int, float)):
                    target["satisfaction"] += float(sat)
                    target["sat_dist"][int(sat)] += 1
                visit = row[index["visit_date"]]
                if visit:
                    target["months"][str(visit)[:7]] += 1
        workbook.close()

        if not overall["n"]:
            continue

        def fmt_profile(title: str, stats: dict[str, Any]) -> str:
            n = max(stats["n"], 1)
            gender_text = "、".join(f"{g} {c} 人" for g, c in stats["gender"].most_common())
            top_months = "、".join(f"{m} ({c} 人次)" for m, c in stats["months"].most_common(3))
            sat_dist = "、".join(f"{k}分 {v} 人" for k, v in sorted(stats["sat_dist"].items()))
            return (
                f"{title}\n"
                f"样本量:{stats['n']} 条游客记录。\n"
                f"游客画像:平均年龄 {stats['age']/n:.1f} 岁;性别分布 {gender_text};平均同行 {stats['group']/n:.1f} 人。\n"
                f"消费水平:人均总消费 {stats['total']/n:.0f} 元,其中门票 {stats['ticket']/n:.0f} 元、"
                f"餐饮 {stats['food']/n:.0f} 元、购物 {stats['shopping']/n:.0f} 元、"
                f"交通 {stats['transport']/n:.0f} 元、娱乐 {stats['entertainment']/n:.0f} 元。\n"
                f"游览行为:平均停留 {stats['stay']/n:.1f} 小时;客流高峰月份 {top_months or '数据不足'}。\n"
                f"满意度:平均 {stats['satisfaction']/n:.2f}/5 分(分布:{sat_dist})。"
            )

        # 1) 重点景区(示范景区相关)单独成篇,供运营类问答精确命中
        focus_groups: dict[str, list[str]] = {}
        for spot_name in per_spot:
            if any(keyword in spot_name for keyword in XLSX_FOCUS_KEYWORDS):
                key = "灵山胜境(含灵山大佛)" if "灵山" in spot_name else spot_name
                focus_groups.setdefault(key, []).append(spot_name)
        for group_title, members in sorted(focus_groups.items()):
            merged = new_stats()
            for member in members:
                stats = per_spot[member]
                merged["n"] += stats["n"]
                for field in ("age", "stay", "ticket", "food", "shopping", "transport",
                              "entertainment", "total", "group", "satisfaction"):
                    merged[field] += stats[field]
                merged["gender"].update(stats["gender"])
                merged["sat_dist"].update(stats["sat_dist"])
                merged["months"].update(stats["months"])
            member_text = "、".join(members)
            materials.append(
                {
                    "title": f"公开资料-游客行为画像-{group_title}",
                    "doc_type": "运营数据",
                    "content": (
                        f"数据来源:{path.name},统计口径:{member_text}。\n"
                        + fmt_profile(f"【{group_title}】游客行为画像", merged)
                    ),
                    "spot_id": None,
                    "source_file": path.name,
                    "source_mtime": path.stat().st_mtime,
                }
            )

        # 2) 全局基准一篇:供"客流/消费/满意度怎么样"类对标问答
        top_spots = sorted(per_spot.items(), key=lambda kv: kv[1]["n"], reverse=True)[:XLSX_TOP_N]
        top_text = "、".join(f"{name} {stats['n']} 人次" for name, stats in top_spots)
        benchmark = (
            f"数据来源:{path.name},共 {overall['n']} 条游客记录,覆盖 {len(per_spot)} 个景区。\n"
            + fmt_profile("【全国景区游客行为基准】", overall)
            + f"\n客流 Top{len(top_spots)} 景区:{top_text}。"
        )
        materials.append(
            {
                "title": "公开资料-游客行为基准-全国景区",
                "doc_type": "运营数据",
                "content": benchmark,
                "spot_id": None,
                "source_file": path.name,
                "source_mtime": path.stat().st_mtime,
            }
        )
    return materials


async def ingest_documents(session: AsyncSession, docs_data: list[dict]) -> dict[str, int]:
    """
    将知识文档分块并插入数据库。

    幂等策略：
    - 根据文档标题(title)判断是否已存在
    - 若存在则先删除旧文档（级联删除 chunks），再重新插入
    - 确保每次运行后数据库中的文档与 JSON 完全一致

    Args:
        session: 数据库异步会话
        docs_data: JSON 中的文档列表

    Returns:
        统计信息字典
    """
    docs_inserted = 0
    docs_updated = 0
    total_chunks = 0
    total_chars = 0
    spot_result = await session.execute(select(Spot.id))
    available_spot_ids = set(spot_result.scalars().all())

    # JSON 种子文档属于本脚本托管内容。标题改名或条目移除时同步清理旧版本，
    # 避免过期口径继续参与检索；后台人工上传的文档不在此范围内。
    managed_titles = {doc["title"] for doc in docs_data}
    normalized_official_ready = any((doc.get("metadata") or {}).get("source_package") for doc in docs_data)
    legacy_public_sources = {
        "灵山胜境 景点结构化数据集.docx",
        "灵山胜境：历史、文化、景点特色与个性化游览指南.docx",
        "景点景区旅游数据行为分析数据.xlsx",
    }
    existing_result = await session.execute(select(KnowledgeDocument))
    for existing_doc in existing_result.scalars().all():
        metadata = existing_doc.metadata_json or {}
        source = metadata.get("source")
        is_managed = source in {"init_script", "a5_official_package"} or (
            normalized_official_ready and source in legacy_public_sources
        )
        if not is_managed or existing_doc.title in managed_titles:
            continue
        await session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.document_id == existing_doc.id)
        )
        await session.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.id == existing_doc.id)
        )
    await session.flush()

    for doc in docs_data:
        title = doc["title"]
        doc_type = doc["doc_type"]
        content = doc["content"]
        source_spot_id = doc.get("spot_id")
        spot_id = source_spot_id if source_spot_id in available_spot_ids else None

        # 1. 检查是否已存在相同标题的文档
        result = await session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.title == title)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # 兼容旧数据库中未设置 ON DELETE CASCADE 的外键。
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == existing.id)
            )
            await session.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.id == existing.id)
            )
            await session.flush()
            docs_updated += 1
        else:
            docs_inserted += 1

        parent_chunks = build_parent_chunk_metadata(content)

        # 2. 插入新文档
        supplied_metadata = dict(doc.get("metadata") or {})
        source_kind = "a5_official_package" if supplied_metadata.get("source_package") else "init_script"
        new_doc = KnowledgeDocument(
            id=uuid.uuid4(),
            title=title,
            doc_type=doc_type,
            spot_id=spot_id,
            content=content,
            status="published",  # 直接发布
            version=1,
            metadata_json={
                **supplied_metadata,
                "source": source_kind,
                "source_file": doc.get("source_file"),
                "source_mtime": doc.get("source_mtime"),
                "effective_as_of": doc.get("effective_as_of"),
                "source_status": doc.get("source_status"),
                "source_spot_id": supplied_metadata.get("source_spot_id") or source_spot_id,
                "enriched_from_narrative": bool(doc.get("enriched_from_narrative")),
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "rag_strategy": "parent_child",
                "parent_chunk_count": len(parent_chunks),
            },
            lang="zh",
        )
        session.add(new_doc)
        await session.flush()

        # 3. 对文档内容进行分块
        chunks = chunk_text(content, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

        for idx, chunk_content in enumerate(chunks):
            parent = find_parent_for_child(parent_chunks, chunk_content)
            stored_content = (
                f"{parent['title']}\n{parent['summary']}\n\n{chunk_content}".strip()
                if parent
                else chunk_content
            )
            chunk = KnowledgeChunk(
                id=uuid.uuid4(),
                document_id=new_doc.id,
                chunk_index=idx,
                content=stored_content,
                # embedding 字段暂时不填充，后续通过 API 或本地模型生成
                char_count=len(chunk_content),
                token_count=max(1, len(chunk_content) // 2),
            )
            session.add(chunk)
            total_chunks += 1
            total_chars += len(chunk_content)

        await session.flush()

    return {
        "docs_inserted": docs_inserted,
        "docs_updated": docs_updated,
        "total_docs": docs_inserted + docs_updated,
        "total_chunks": total_chunks,
        "total_chars": total_chars,
    }


async def show_document_summary(session: AsyncSession):
    """打印数据库中知识文档的汇总信息。"""
    from sqlalchemy import func

    # 统计文档数量
    result = await session.execute(select(func.count()).select_from(KnowledgeDocument))
    doc_count = result.scalar()

    # 统计分块数量
    result = await session.execute(select(func.count()).select_from(KnowledgeChunk))
    chunk_count = result.scalar()

    # 统计各类型文档数量
    result = await session.execute(
        select(KnowledgeDocument.doc_type, func.count())
        .group_by(KnowledgeDocument.doc_type)
    )
    type_counts = result.all()

    print(f"\n  文档总数: {doc_count}")
    print(f"  分块总数: {chunk_count}")
    print("  按类型统计:")
    for doc_type, count in type_counts:
        print(f"    - {doc_type}: {count} 篇")

    # 打印每篇文档的分块详情
    print("\n  文档分块详情:")
    result = await session.execute(
        select(KnowledgeDocument).order_by(KnowledgeDocument.title)
    )
    docs = result.scalars().all()

    for doc in docs:
        result = await session.execute(
            select(func.count()).where(KnowledgeChunk.document_id == doc.id)
        )
        chunk_count_for_doc = result.scalar()
        print(f"    - 《{doc.title}》: {len(doc.content)} 字 -> {chunk_count_for_doc} 个分块")


async def main():
    """主入口函数。"""
    print("=" * 60)
    print("灵境智游 - 知识库文档分块与入库")
    print("=" * 60)

    # 检查数据文件是否存在
    if not KNOWLEDGE_JSON.exists():
        print(f"错误：找不到知识库数据文件 {KNOWLEDGE_JSON}")
        sys.exit(1)

    # 加载数据
    print(f"\n加载知识库数据: {KNOWLEDGE_JSON}")
    docs_data = await load_json(KNOWLEDGE_JSON)

    # 加载FAQ数据（如果存在）
    if FAQ_JSON.exists():
        print(f"加载FAQ数据: {FAQ_JSON}")
        faq_data = await load_json(FAQ_JSON)
        docs_data.extend(faq_data)
        print(f"  FAQ数据: {len(faq_data)} 条")

    if ENHANCED_JSON.exists():
        print(f"加载增强运营知识: {ENHANCED_JSON}")
        enhanced_data = await load_json(ENHANCED_JSON)
        docs_data.extend(enhanced_data)
        print(f"  增强知识: {len(enhanced_data)} 条")

    if VERIFIED_JSON.exists():
        print(f"加载权威核验知识: {VERIFIED_JSON}")
        verified_data = await load_json(VERIFIED_JSON)
        docs_data.extend(verified_data)
        print(f"  权威核验知识: {len(verified_data)} 条")

    if A5_OFFICIAL_JSON.exists():
        print(f"加载 A5 官方规范化资料: {A5_OFFICIAL_JSON}")
        a5_official_data = await load_json(A5_OFFICIAL_JSON)
        docs_data.extend(a5_official_data)
        print(f"  A5 官方资料: {len(a5_official_data)} 条")

    # 规范化 JSON 已可完成干净初始化。原始 16MB 资料包仅在明确开启时读取，
    # 避免本机同时存在原包和规范化数据时重复入库。
    use_raw_materials = os.getenv("INGEST_RAW_PUBLIC_MATERIALS", "false").lower() == "true"
    public_materials = load_public_docx_materials() if use_raw_materials else []
    enriched_count = enrich_sparse_spot_materials(public_materials)
    xlsx_materials = load_public_xlsx_materials() if use_raw_materials else []
    public_materials.extend(xlsx_materials)
    docs_data.extend(public_materials)
    print(f"加载公开 Word 资料: {len(public_materials) - len(xlsx_materials)} 份(补全残缺条目 {enriched_count} 条)")
    print(f"加载公开 Excel 聚合资料: {len(xlsx_materials)} 份")

    print(f"  总计: {len(docs_data)} 篇文档")

    # 预演分块（仅统计，不入库）
    print(f"\n分块参数: chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}")
    preview_chunks = 0
    for doc in docs_data:
        chunks = chunk_text(doc["content"], CHUNK_SIZE, CHUNK_OVERLAP)
        preview_chunks += len(chunks)
    print(f"  预计生成 {preview_chunks} 个分块")

    # 创建数据库引擎和会话
    print(f"\n连接数据库: {DATABASE_URL.replace('://', '://***:***@')}")
    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        try:
            # 执行入库
            print("\n开始入库...")
            stats = await ingest_documents(session, docs_data)

            # 提交事务
            await session.commit()

            # 输出统计信息
            print("\n" + "=" * 60)
            print("入库完成！")
            print("=" * 60)
            print(f"\n  新增文档: {stats['docs_inserted']} 篇")
            print(f"  更新文档: {stats['docs_updated']} 篇")
            print(f"  文档总计: {stats['total_docs']} 篇")
            print(f"  分块总计: {stats['total_chunks']} 个")
            print(f"  字符总计: {stats['total_chars']} 字")

            # 打印详细汇总
            await show_document_summary(session)

            print("\n" + "=" * 60)
            print("提示: 请继续运行 python -m scripts.generate_embeddings 生成缺失向量。")
            print("=" * 60)

        except Exception as e:
            await session.rollback()
            print(f"\n错误：知识库入库失败 - {e}")
            raise

    await engine.dispose()
    print("\n数据库连接已关闭。")


if __name__ == "__main__":
    asyncio.run(main())
