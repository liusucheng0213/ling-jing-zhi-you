"""
RAG检索引擎 - 基于pgvector的混合检索
支持向量检索、词法检索、混合融合检索
"""

import time
from dataclasses import asdict
from typing import Any, Optional, List
from dataclasses import dataclass
from uuid import UUID

try:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text
except ImportError:
    raise ImportError("请先安装 sqlalchemy: pip install sqlalchemy[asyncio]")

from loguru import logger

from app.config import settings


_embedding_cache: dict[str, tuple[float, list[float]]] = {}
_search_cache: dict[str, tuple[float, list[dict], dict]] = {}
_embedding_http_client = None


def invalidate_search_cache() -> int:
    """清空检索结果缓存，确保知识发布后同一问题立即使用新索引。"""

    cleared = len(_search_cache)
    _search_cache.clear()
    if cleared:
        logger.info(f"RAG检索缓存已失效: cleared={cleared}")
    return cleared


def _cache_get(cache: dict, key: str):
    """获取未过期缓存项。"""

    item = cache.get(key)
    if not item:
        return None
    expires_at = item[0]
    if expires_at < time.time():
        cache.pop(key, None)
        return None
    return item[1]


def _cache_set(cache: dict, key: str, value, ttl: int | None = None) -> None:
    """写入内存TTL缓存。"""

    cache[key] = (time.time() + (ttl or settings.CACHE_TTL), value)


@dataclass
class RetrievalResult:
    """检索结果"""

    chunk_id: str           # 片段ID
    document_id: str        # 文档ID
    content: str            # 片段内容
    score: float            # 综合得分
    vector_score: float     # 向量相似度得分
    text_score: float       # 全文检索得分
    doc_title: str = ""     # 文档标题
    doc_type: str = ""      # 文档类型
    spot_id: Optional[str] = None  # 关联景点ID
    metadata_json: dict[str, Any] | None = None  # 来源版本、景区范围和冲突状态


class RAGEngine:
    """
    RAG检索引擎

    实现基于pgvector的混合检索：
    1. 向量检索：使用余弦相似度在向量空间检索
    2. 全文检索：使用PostgreSQL的tsvector/tsquery进行全文搜索
    3. 混合融合：RRF(Reciprocal Rank Fusion)算法融合两种检索结果

    依赖：
    - PostgreSQL + pgvector扩展
    - 嵌入模型（本地BGE-M3或API）
    """

    # RRF融合参数
    RRF_K = 60

    def __init__(
        self,
        db_session: AsyncSession,
        vector_dimension: int = 1024,
    ):
        self.db = db_session
        self.vector_dimension = vector_dimension
        self.last_trace: dict = {}

    # ========================================================================
    # 嵌入向量生成
    # ========================================================================

    async def _get_embedding(self, query: str) -> list[float]:
        """
        获取查询文本的嵌入向量

        使用本地BGE-M3模型或嵌入服务

        Args:
            query: 查询文本

        Returns:
            向量列表
        """
        cache_key = f"embedding:{self.vector_dimension}:{query.strip()}"
        cached = _cache_get(_embedding_cache, cache_key)
        if cached is not None:
            self.last_trace["embedding_cache_hit"] = True
            return cached

        self.last_trace["embedding_cache_hit"] = False
        if settings.EMBEDDING_SERVICE_URL:
            embedding = await self._get_embedding_from_service(query)
            _cache_set(_embedding_cache, cache_key, embedding)
            return embedding
        if settings.USE_LOCAL_EMBEDDING:
            embedding = await self._get_local_embedding(query)
            _cache_set(_embedding_cache, cache_key, embedding)
            return embedding
        raise RuntimeError("未配置本地嵌入模型或 EMBEDDING_SERVICE_URL")

    async def _get_embedding_from_service(self, query: str) -> list[float]:
        """通过本地嵌入服务生成向量"""
        try:
            import httpx

            global _embedding_http_client
            timeout = httpx.Timeout(connect=1.0, read=3.5, write=1.0, pool=1.0)
            if _embedding_http_client is None:
                _embedding_http_client = httpx.AsyncClient(
                    timeout=timeout,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
            response = await _embedding_http_client.post(
                f"{settings.EMBEDDING_SERVICE_URL.rstrip('/')}/embed",
                json={"text": query},
            )
            response.raise_for_status()
            data = response.json()
            embedding = data["embedding"]
            logger.debug(f"嵌入服务生成成功: backend={data.get('backend')}, dim={len(embedding)}")
            return embedding
        except Exception as e:
            logger.error(f"嵌入服务调用失败: {e}")
            raise

    async def _get_local_embedding(self, query: str) -> list[float]:
        """使用本地BGE-M3模型生成嵌入向量"""
        try:
            from app.core.embedding_provider import get_local_embedding_provider

            provider = get_local_embedding_provider()
            embedding = await provider.embed(query)
            backend = provider.backend_info.name if provider.backend_info else "unknown"
            logger.debug(f"本地嵌入生成成功: backend={backend}, dim={len(embedding)}")
            return embedding
        except Exception as e:
            logger.error(f"本地嵌入模型失败: {e}")
            raise

    # ========================================================================
    # 向量检索
    # ========================================================================

    async def vector_search(
        self,
        query: str,
        top_k: int = 5,
        spot_id: Optional[str] = None,
        scenic_area: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """
        向量相似度检索

        使用pgvector的<=>操作符计算余弦距离（1 - 余弦相似度）

        Args:
            query: 查询文本
            top_k: 返回结果数量
            spot_id: 可选的景点过滤

        Returns:
            检索结果列表
        """
        embedding = await self._get_embedding(query)
        if not self._has_effective_embedding(embedding):
            logger.warning("查询向量为空或不可用，向量检索返回空结果")
            return []

        # 构建SQL查询
        # 注意：embedding字段假设为pgvector的vector类型
        # 需要在Alembic迁移中创建该字段
        sql = """
            SELECT
                kc.id as chunk_id,
                kc.document_id,
                kc.content,
                kc.embedding <=> :embedding as distance,
                kd.title as doc_title,
                kd.doc_type,
                kd.spot_id,
                kd.metadata_json
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kc.document_id = kd.id
            WHERE kd.status = 'published'
              AND kc.embedding IS NOT NULL
        """
        params = {"embedding": str(embedding), "top_k": top_k}

        if spot_id:
            sql += " AND kd.spot_id = :spot_id"
            params["spot_id"] = spot_id
        if scenic_area:
            sql += " AND COALESCE(kd.metadata_json ->> 'scenic_area', '灵山胜境') = :scenic_area"
            params["scenic_area"] = scenic_area

        sql += """
            ORDER BY kc.embedding <=> :embedding
            LIMIT :top_k
        """

        try:
            result = await self.db.execute(text(sql), params)
            rows = result.mappings().all()

            results: List[RetrievalResult] = []
            for row in rows:
                # distance = 1 - cosine_similarity, 所以 score = 1 - distance
                vector_score = 1.0 - float(row["distance"])
                results.append(
                    RetrievalResult(
                        chunk_id=str(row["chunk_id"]),
                        document_id=str(row["document_id"]),
                        content=row["content"],
                        score=vector_score,
                        vector_score=vector_score,
                        text_score=0.0,
                        doc_title=row["doc_title"] or "",
                        doc_type=row["doc_type"] or "",
                        spot_id=row["spot_id"],
                        metadata_json=dict(row["metadata_json"] or {}),
                    )
                )

            logger.debug(f"向量检索完成: query='{query[:30]}...', 找到 {len(results)} 条")
            return results

        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

    # ========================================================================
    # 全文检索
    # ========================================================================

    async def fulltext_search(
        self,
        query: str,
        top_k: int = 5,
        spot_id: Optional[str] = None,
        scenic_area: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """
        中文文本检索

        当前Docker镜像未安装zhparser，PostgreSQL默认也没有`chinese`全文检索配置。
        为避免tsvector配置错误污染当前事务，这里真实落地阶段先使用稳定的
        ILIKE检索；后续如安装zhparser，再切回tsvector/GIN索引。

        Args:
            query: 查询文本
            top_k: 返回结果数量
            spot_id: 可选的景点过滤

        Returns:
            检索结果列表
        """
        return await self.lexical_search(query, top_k, spot_id, scenic_area)

    async def lexical_search(
        self,
        query: str,
        top_k: int = 5,
        spot_id: Optional[str] = None,
        scenic_area: Optional[str] = None,
    ) -> List[RetrievalResult]:
        """
        中文词面检索

        Args:
            query: 查询文本
            top_k: 返回数量
            spot_id: 景点过滤

        Returns:
            检索结果列表
        """
        patterns = self._build_search_patterns(query)
        clauses = []
        score_terms = []
        params = {"top_k": top_k}
        for idx, pattern in enumerate(patterns):
            key = f"pattern_{idx}"
            params[key] = f"%{pattern}%"
            clauses.append(f"(kc.content ILIKE :{key} OR kd.title ILIKE :{key})")
            score_terms.append(f"CASE WHEN kd.title ILIKE :{key} THEN 1.5 ELSE 0 END")
            score_terms.append(f"CASE WHEN kc.content ILIKE :{key} THEN 1.0 ELSE 0 END")

        if not clauses:
            return []

        score_sql = " + ".join(score_terms)

        sql = f"""
            SELECT
                kc.id as chunk_id,
                kc.document_id,
                kc.content,
                ({score_sql}) as match_score,
                kd.title as doc_title,
                kd.doc_type,
                kd.spot_id,
                kd.metadata_json
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kc.document_id = kd.id
            WHERE kd.status = 'published'
              AND ({' OR '.join(clauses)})
        """

        if spot_id:
            sql += " AND kd.spot_id = :spot_id"
            params["spot_id"] = spot_id
        if scenic_area:
            sql += " AND COALESCE(kd.metadata_json ->> 'scenic_area', '灵山胜境') = :scenic_area"
            params["scenic_area"] = scenic_area

        sql += """
            ORDER BY match_score DESC, kc.chunk_index ASC
            LIMIT :top_k
        """

        try:
            result = await self.db.execute(text(sql), params)
            rows = result.mappings().all()

            results: List[RetrievalResult] = []
            for row in rows:
                raw_score = float(row["match_score"] or 0.0)
                text_score = min(1.0, raw_score / max(len(patterns), 1))
                results.append(
                    RetrievalResult(
                        chunk_id=str(row["chunk_id"]),
                        document_id=str(row["document_id"]),
                        content=row["content"],
                        score=text_score,
                        vector_score=0.0,
                        text_score=text_score,
                        doc_title=row["doc_title"] or "",
                        doc_type=row["doc_type"] or "",
                        spot_id=row["spot_id"],
                        metadata_json=dict(row["metadata_json"] or {}),
                    )
                )

            logger.debug(f"词面检索完成: 找到 {len(results)} 条")
            return results[:top_k]

        except Exception as e:
            logger.error(f"词面检索失败: {e}")
            return []

    @staticmethod
    def _build_search_patterns(query: str) -> list[str]:
        """为无embedding场景生成稳定的中文检索关键词。"""
        aliases = {
            "大佛": ["大佛", "灵山大佛", "佛像", "多高", "高度"],
            "梵宫": ["梵宫", "灵山梵宫", "演出", "吉祥颂"],
            "九龙": ["九龙", "九龙灌浴", "灌浴", "表演"],
            "坛城": ["坛城", "五印坛城", "藏传佛教"],
            "禅寺": ["禅寺", "祥符禅寺", "寺庙"],
            "门票": ["门票", "票价", "预约", "购票"],
            "开放": ["开放", "开放时间", "营业时间", "入园"],
            "路线": ["路线", "游线", "怎么走", "推荐"],
            "餐饮": ["餐饮", "吃饭", "素斋", "餐厅"],
            "适老": ["适老", "老人", "无障碍", "轮椅"],
            "拍照": ["拍照", "打卡", "取景", "机位", "照片"],
            "停车": ["停车", "停车场", "自驾"],
            "票价": ["票价", "门票", "多少钱", "收费"],
            "表演": ["表演", "演出", "场次", "时间"],
            "拈花湾": ["拈花湾", "香月花街", "拈花塔", "妙音台", "拈花堂", "五灯湖", "鹿鸣谷"],
        }
        known_terms = [
            "灵山大佛",
            "灵山胜境",
            "九龙灌浴",
            "灵山梵宫",
            "梵宫",
            "五印坛城",
            "祥符禅寺",
            "百子戏弥勒",
            "天下第一掌",
            "阿育王柱",
            "门票",
            "开放时间",
            "导游",
            "餐饮",
            "路线",
            "无障碍",
            "停车",
            "拍照",
            "表演时间",
            "拈花湾",
            "香月花街",
            "拈花塔",
            "妙音台",
            "拈花堂",
            "五灯湖",
            "鹿鸣谷",
        ]
        patterns = [term for term in known_terms if term in query]
        for key, values in aliases.items():
            if key in query or any(value in query for value in values):
                patterns.extend(values)
        cleaned = query
        for ch in "？?！!。，、；;：:“”\"'（）()[]【】":
            cleaned = cleaned.replace(ch, " ")
        stop_words = ["请问", "介绍", "一下", "多少", "多高", "哪里", "什么", "怎么", "如何", "有", "的", "吗", "呢"]
        for word in stop_words:
            cleaned = cleaned.replace(word, " ")
        patterns.extend([part.strip() for part in cleaned.split() if len(part.strip()) >= 2])
        unique: list[str] = []
        for pattern in patterns:
            if pattern and pattern not in unique:
                unique.append(pattern)
        return unique[:12]

    @staticmethod
    def _has_effective_embedding(embedding: list[float]) -> bool:
        """判断向量是否可用于真实检索，避免零向量污染排序。"""
        return any(abs(value) > 1e-12 for value in embedding)

    # ========================================================================
    # 混合检索（RRF融合）
    # ========================================================================

    async def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        spot_id: Optional[str] = None,
        scenic_area: Optional[str] = None,
        vector_weight: float = 0.6,
        text_weight: float = 0.4,
    ) -> List[RetrievalResult]:
        """
        混合检索：向量检索 + 全文检索 + RRF融合

        使用Reciprocal Rank Fusion算法融合两种检索结果：
        score = sum(1 / (k + rank)) for each list

        Args:
            query: 查询文本
            top_k: 返回结果数量
            spot_id: 可选的景点过滤
            vector_weight: 向量检索权重
            text_weight: 全文检索权重

        Returns:
            融合后的检索结果列表
        """
        started_at = time.time()
        cache_key = f"search:{top_k}:{spot_id or ''}:{scenic_area or ''}:{query.strip()}"
        cached = _cache_get(_search_cache, cache_key)
        if cached is not None:
            rows, trace = cached
            self.last_trace = {**trace, "cache_hit": True}
            return [RetrievalResult(**row) for row in rows]

        self.last_trace = {
            "cache_hit": False,
            "embedding_cache_hit": False,
            "vector_timeout": False,
            "mode": "hybrid",
        }

        lexical_started = time.time()
        lexical_first = await self.fulltext_search(
            query,
            top_k=top_k * 2,
            spot_id=spot_id,
            scenic_area=scenic_area,
        )
        self.last_trace["lexical_ms"] = int((time.time() - lexical_started) * 1000)
        if lexical_first and self._is_high_confidence_lexical(query, lexical_first):
            logger.info(f"高置信词面检索命中，跳过向量检索: query='{query[:30]}...'")
            self.last_trace["mode"] = "lexical_fast"
            self.last_trace["total_ms"] = int((time.time() - started_at) * 1000)
            results = self._rerank_results(query, lexical_first)[:top_k]
            _cache_set(_search_cache, cache_key, ([asdict(item) for item in results], dict(self.last_trace)))
            return results

        # 复用已完成的词面检索，只补一次向量检索，避免重复全文查询。
        vector_started = time.time()
        text_results = lexical_first
        try:
            vector_results = await self.vector_search(
                query,
                top_k=top_k * 2,
                spot_id=spot_id,
                scenic_area=scenic_area,
            )
        except Exception as exc:
            vector_results = exc
        self.last_trace["vector_ms"] = int((time.time() - vector_started) * 1000)

        if isinstance(vector_results, Exception):
            logger.error(f"向量检索异常，严格模式不使用词面兜底: {vector_results}")
            self.last_trace["vector_error"] = str(vector_results)
            self.last_trace["vector_timeout"] = "timeout" in str(vector_results).lower()
            raise RuntimeError(f"向量检索失败: {vector_results}") from vector_results

        # 如果只有一种检索有结果，直接返回
        if not vector_results and not text_results:
            logger.warning(f"混合检索无结果: query='{query[:30]}...'")
            self.last_trace["mode"] = "empty"
            self.last_trace["total_ms"] = int((time.time() - started_at) * 1000)
            return []

        if not vector_results:
            self.last_trace["mode"] = "vector_empty"
            self.last_trace["total_ms"] = int((time.time() - started_at) * 1000)
            raise RuntimeError("向量检索无结果，严格模式不使用词面兜底")
        if not text_results:
            self.last_trace["mode"] = "vector_only"
            self.last_trace["total_ms"] = int((time.time() - started_at) * 1000)
            results = self._rerank_results(query, vector_results)[:top_k]
            _cache_set(_search_cache, cache_key, ([asdict(item) for item in results], dict(self.last_trace)))
            return results

        # RRF融合
        fused_results = self._rrf_fusion(
            vector_results,
            text_results,
            vector_weight=vector_weight,
            text_weight=text_weight,
        )

        logger.info(
            f"混合检索完成: query='{query[:30]}...', "
            f"向量={len(vector_results)}条, 全文={len(text_results)}条, "
            f"融合后={len(fused_results)}条"
        )
        self.last_trace["total_ms"] = int((time.time() - started_at) * 1000)
        results = self._rerank_results(query, fused_results)[:top_k]
        _cache_set(_search_cache, cache_key, ([asdict(item) for item in results], dict(self.last_trace)))
        return results

    def _is_high_confidence_lexical(self, query: str, results: List[RetrievalResult]) -> bool:
        """直接事实问答优先使用词面命中，避免本地向量和LLM串行拖慢。"""

        if not results:
            return False
        # 票务、开放和演出属于动态信息，必须让向量通道召回最新核验规则，
        # 不能因旧FAQ词面分高就提前结束检索。
        dynamic_terms = {
            "今天",
            "今日",
            "现在",
            "实时",
            "门票",
            "票价",
            "多少钱",
            "开放时间",
            "营业时间",
            "表演时间",
            "演出时间",
            "场次",
            "几点",
        }
        if any(term in query for term in dynamic_terms):
            return False
        query_patterns = self._build_search_patterns(query)
        direct_terms = {
            "门票",
            "开放时间",
            "营业时间",
            "表演时间",
            "高度",
            "多高",
            "交通",
            "怎么到达",
            "餐饮",
            "素斋",
            "拍照",
            "打卡",
            "停车",
            "无障碍",
            "轮椅",
            "抱佛脚",
            "吉祥颂",
            "九龙灌浴",
        }
        complex_terms = {"为什么", "详细", "深入", "比较", "写", "创作", "规划", "路线", "故事"}
        if any(term in query for term in complex_terms):
            return False
        if not any(term in query for term in direct_terms):
            return False
        top = results[0]
        return top.text_score >= 0.8 or self._count_hits(top.doc_title, query_patterns) > 0

    def _rerank_results(self, query: str, results: List[RetrievalResult]) -> List[RetrievalResult]:
        tokens = self._build_search_patterns(query)
        doc_seen: dict[str, int] = {}
        reranked: list[RetrievalResult] = []
        asks_dynamic_status = any(
            term in query
            for term in (
                "今天",
                "今日",
                "实时",
                "门票",
                "票价",
                "多少钱",
                "开放时间",
                "演出时间",
                "表演时间",
                "场次",
                "几点",
            )
        )

        for index, item in enumerate(results):
            title_hits = self._count_hits(item.doc_title, tokens)
            content_hits = self._count_hits(item.content, tokens)
            title_boost = min(0.25, title_hits * 0.08)
            content_boost = min(0.20, content_hits * 0.03)
            metadata = item.metadata_json or {}
            source_boost = (
                0.20
                if metadata.get("source_package")
                else 0.18
                if item.doc_type == "official_web"
                else 0.08
                if item.doc_type == "spot_reference"
                else 0.0
            )
            dynamic_policy_boost = (
                0.42
                if asks_dynamic_status
                and item.doc_type == "official_web"
                and ("停服" in item.doc_title or "停止服务" in item.content)
                else 0.0
            )
            diversity_penalty = doc_seen.get(item.document_id, 0) * 0.08
            fused_score = (
                item.score
                + title_boost
                + content_boost
                + source_boost
                + dynamic_policy_boost
                - diversity_penalty
                - index * 0.001
            )
            doc_seen[item.document_id] = doc_seen.get(item.document_id, 0) + 1
            reranked.append(
                RetrievalResult(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    content=item.content,
                    score=max(fused_score, 0.0),
                    vector_score=item.vector_score,
                    text_score=item.text_score,
                    doc_title=item.doc_title,
                    doc_type=item.doc_type,
                    spot_id=item.spot_id,
                    metadata_json=item.metadata_json,
                )
            )

        return sorted(reranked, key=lambda result: result.score, reverse=True)

    @staticmethod
    def _count_hits(text_value: str, tokens: list[str]) -> int:
        if not text_value or not tokens:
            return 0
        return sum(1 for token in tokens if token and token in text_value)

    def _rrf_fusion(
        self,
        vector_results: List[RetrievalResult],
        text_results: List[RetrievalResult],
        vector_weight: float = 0.6,
        text_weight: float = 0.4,
    ) -> List[RetrievalResult]:
        """
        RRF (Reciprocal Rank Fusion) 融合算法

        Args:
            vector_results: 向量检索结果
            text_results: 全文检索结果
            vector_weight: 向量权重
            text_weight: 文本权重

        Returns:
            融合排序后的结果
        """
        # 构建chunk_id -> 结果映射
        scores: dict[str, dict] = {}

        # 向量检索打分
        for rank, result in enumerate(vector_results):
            chunk_id = result.chunk_id
            if chunk_id not in scores:
                scores[chunk_id] = {
                    "result": result,
                    "vector_score": result.vector_score,
                    "text_score": 0.0,
                    "rrf_score": 0.0,
                }
            # RRF分数: weight * 1/(k + rank)
            scores[chunk_id]["rrf_score"] += vector_weight / (self.RRF_K + rank + 1)

        # 全文检索打分
        for rank, result in enumerate(text_results):
            chunk_id = result.chunk_id
            if chunk_id not in scores:
                scores[chunk_id] = {
                    "result": result,
                    "vector_score": 0.0,
                    "text_score": result.text_score,
                    "rrf_score": 0.0,
                }
            else:
                scores[chunk_id]["text_score"] = result.text_score
            scores[chunk_id]["rrf_score"] += text_weight / (self.RRF_K + rank + 1)

        # 按RRF分数排序
        sorted_items = sorted(
            scores.items(),
            key=lambda x: x[1]["rrf_score"],
            reverse=True,
        )

        # 构建最终结果
        fused: List[RetrievalResult] = []
        for chunk_id, item in sorted_items:
            result = item["result"]
            fused.append(
                RetrievalResult(
                    chunk_id=result.chunk_id,
                    document_id=result.document_id,
                    content=result.content,
                    score=item["rrf_score"],
                    vector_score=item["vector_score"],
                    text_score=item["text_score"],
                    doc_title=result.doc_title,
                    doc_type=result.doc_type,
                    spot_id=result.spot_id,
                    metadata_json=result.metadata_json,
                )
            )

        return fused

    # ========================================================================
    # 文档入库
    # ========================================================================

    async def _insert_embedding(
        self,
        chunk_id: UUID,
        embedding: list[float],
    ) -> None:
        """
        插入向量到pgvector字段

        Args:
            chunk_id: 片段ID
            embedding: 向量数据
        """
        sql = """
            UPDATE knowledge_chunks
            SET embedding = CAST(:embedding AS vector)
            WHERE id = :chunk_id
        """
        await self.db.execute(
            text(sql),
            {
                "chunk_id": chunk_id,
                "embedding": str(embedding),
            },
        )

    # ========================================================================
    # 工具方法
    # ========================================================================

    def format_context(self, results: List[RetrievalResult]) -> str:
        """
        将检索结果格式化为LLM可用的上下文

        Args:
            results: 检索结果列表

        Returns:
            格式化后的上下文字符串
        """
        if not results:
            return ""

        context_parts: List[str] = []
        for i, r in enumerate(results, 1):
            metadata = r.metadata_json or {}
            part = f"[文档{i}] {r.doc_title or '未知文档'}\n"
            part += f"类型: {r.doc_type or '未知'}\n"
            part += f"片段ID: {r.chunk_id}\n"
            part += f"相关性: {r.score:.4f} (向量 {r.vector_score:.4f}, 文本 {r.text_score:.4f})\n"
            if r.spot_id:
                part += f"关联景点: {r.spot_id}\n"
            if metadata.get("scenic_area"):
                part += f"景区范围: {metadata['scenic_area']}\n"
            if metadata.get("source_package"):
                part += f"资料版本: {metadata['source_package']}\n"
            if metadata.get("conflict_status") not in {None, "none", "resolved"}:
                part += "冲突状态: 未核实；回答时必须并列展示不同口径，不得擅自选定。\n"
            part += f"内容: {r.content}\n"
            context_parts.append(part)

        return "\n---\n".join(context_parts)
