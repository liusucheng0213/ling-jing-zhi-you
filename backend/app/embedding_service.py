from contextlib import asynccontextmanager

from loguru import logger
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException

from app.core.embedding_provider import get_local_embedding_provider


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动阶段预热模型，避免首个游客查询承担模型加载耗时。"""

    provider = get_local_embedding_provider()
    try:
        await provider.embed("灵山胜境知识检索预热")
        logger.info("BGE-M3 嵌入模型预热完成")
    except Exception as exc:
        logger.error(f"BGE-M3 嵌入模型预热失败: {exc}")
        raise
    yield


app = FastAPI(title="灵境智游本地嵌入服务", version="1.1.0", lifespan=lifespan)


class EmbedRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class EmbedResponse(BaseModel):
    embedding: list[float]
    dimension: int
    backend: str
    device: str | None = None


@app.get("/health")
async def health_check():
    provider = get_local_embedding_provider()
    runtime = provider.runtime_info()
    return {
        "status": "healthy",
        "model_path": str(provider.model_path),
        "dimension": provider.dimension,
        "runtime": runtime,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    provider = get_local_embedding_provider()
    try:
        embedding = await provider.embed(request.text)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    backend = provider.backend_info.name if provider.backend_info else "unknown"
    device = provider.backend_info.device if provider.backend_info else None
    return EmbedResponse(
        embedding=embedding,
        dimension=len(embedding),
        backend=backend,
        device=device,
    )
