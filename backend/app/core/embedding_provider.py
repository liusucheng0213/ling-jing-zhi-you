"""本地 embedding 生成器。"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from app.config import settings


@dataclass(frozen=True)
class EmbeddingBackendInfo:
    """本地 embedding 后端信息。"""

    name: str
    model_path: str
    dimension: int
    real_semantic: bool
    device: str = "unknown"


class LocalEmbeddingProvider:
    """本地 BGE-M3 embedding provider，带模型缓存。"""

    def __init__(
        self,
        model_path: str | None = None,
        dimension: int | None = None,
        backend: str | None = None,
    ) -> None:
        self.model_path = self._resolve_model_path(model_path or settings.EMBEDDING_MODEL_PATH)
        self.dimension = dimension or settings.EMBEDDING_DIMENSION
        self.backend = (backend or settings.EMBEDDING_LOCAL_BACKEND or "auto").lower()
        self._model: Any | None = None
        self._onnx_session: Any | None = None
        self._onnx_tokenizer: Any | None = None
        self._backend_info: EmbeddingBackendInfo | None = None

    @property
    def backend_info(self) -> EmbeddingBackendInfo | None:
        """当前已加载后端信息。"""

        return self._backend_info

    def runtime_info(self) -> dict[str, Any]:
        """返回本地 embedding 运行时信息，用于确认 CUDA 是否真实可用。"""

        info: dict[str, Any] = {
            "configured_device": settings.EMBEDDING_DEVICE,
            "configured_backend": self.backend,
            "model_path": str(self.model_path),
            "dimension": self.dimension,
            "loaded_backend": self._backend_info.name if self._backend_info else None,
            "loaded_device": self._backend_info.device if self._backend_info else None,
        }
        try:
            import torch

            cuda_available = torch.cuda.is_available()
            device_count = torch.cuda.device_count() if cuda_available else 0
            info.update(
                {
                    "torch_version": torch.__version__,
                    "cuda_available": cuda_available,
                    "cuda_device_count": device_count,
                    "cuda_device_name": torch.cuda.get_device_name(0) if device_count else None,
                }
            )
        except Exception as exc:
            info.update(
                {
                    "torch_version": None,
                    "cuda_available": False,
                    "cuda_device_count": 0,
                    "cuda_device_name": None,
                    "torch_error": str(exc),
                }
            )
        return info

    async def embed(self, text: str) -> list[float]:
        """异步生成单条文本 embedding。"""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.embed_sync, text)

    def embed_sync(self, text: str) -> list[float]:
        """同步生成单条文本 embedding，供批处理脚本复用。"""

        clean_text = text.strip()
        if not clean_text:
            return [0.0] * self.dimension

        if self.backend in ("auto", "sentence-transformers", "sentence_transformers", "st"):
            try:
                return self._embed_sentence_transformers(clean_text)
            except Exception as exc:
                if self.backend not in ("auto",):
                    raise
                logger.warning(f"sentence-transformers 本地 embedding 不可用，尝试 ONNX: {exc}")

        if self.backend in ("auto", "onnx", "onnxruntime"):
            try:
                return self._embed_onnx(clean_text)
            except Exception as exc:
                if self.backend not in ("auto",):
                    raise
                logger.warning(f"ONNX 本地 embedding 不可用: {exc}")

        raise RuntimeError(
            "本地 BGE-M3 embedding 不可用：请安装 torch/sentence-transformers，"
            "或提供真实 ONNX 权重并安装 onnxruntime/tokenizers。"
        )

    def _embed_sentence_transformers(self, text: str) -> list[float]:
        """使用 sentence-transformers 加载本地 BGE-M3。"""

        if self._model is None:
            from sentence_transformers import SentenceTransformer
            import torch

            device = settings.EMBEDDING_DEVICE
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            logger.info(f"加载 BGE-M3 sentence-transformers 模型: {self.model_path}, device={device}")
            model = SentenceTransformer(str(self.model_path), local_files_only=True)
            self._model = model.to(device)
            self._backend_info = EmbeddingBackendInfo(
                name="sentence-transformers",
                model_path=str(self.model_path),
                dimension=self.dimension,
                real_semantic=True,
                device=device,
            )

        embedding = self._model.encode(
            text,
            normalize_embeddings=True,
            convert_to_tensor=False,
        )
        return self._validate_dimension(embedding.tolist())

    def _embed_onnx(self, text: str) -> list[float]:
        """使用本地 ONNX 权重生成 BGE-M3 embedding。"""

        onnx_dir = self.model_path / "onnx"
        model_file = onnx_dir / "model.onnx"
        tokenizer_file = self.model_path / "tokenizer.json"
        if not model_file.exists():
            raise FileNotFoundError(f"未找到 ONNX 模型: {model_file}")
        if self._is_lfs_pointer(model_file):
            raise RuntimeError(f"ONNX 模型仍是 Git LFS 指针文件，需下载真实权重: {model_file}")
        if not tokenizer_file.exists() or self._is_lfs_pointer(tokenizer_file):
            raise RuntimeError(f"tokenizer.json 不可用或仍是 Git LFS 指针文件: {tokenizer_file}")

        if self._onnx_session is None or self._onnx_tokenizer is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            logger.info(f"加载 BGE-M3 ONNX 模型: {model_file}")
            self._onnx_tokenizer = Tokenizer.from_file(str(tokenizer_file))
            self._onnx_session = ort.InferenceSession(
                str(model_file),
                providers=["CPUExecutionProvider"],
            )
            self._backend_info = EmbeddingBackendInfo(
                name="onnxruntime",
                model_path=str(model_file),
                dimension=self.dimension,
                real_semantic=True,
                device="cpu",
            )

        encoded = self._onnx_tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)
        input_map: dict[str, np.ndarray] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        input_names = {item.name for item in self._onnx_session.get_inputs()}
        if "token_type_ids" in input_names:
            input_map["token_type_ids"] = token_type_ids

        outputs = self._onnx_session.run(None, input_map)
        last_hidden_state = outputs[0]
        mask = attention_mask[..., None].astype(np.float32)
        pooled = (last_hidden_state * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
        vector = pooled[0]
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return self._validate_dimension(vector.tolist())

    def _validate_dimension(self, vector: list[float]) -> list[float]:
        """校验维度，避免写入 pgvector 时失败。"""

        if len(vector) != self.dimension:
            raise ValueError(f"embedding 维度不匹配：期望 {self.dimension}，实际 {len(vector)}")
        return [float(value) for value in vector]

    @staticmethod
    def _is_lfs_pointer(path: Path) -> bool:
        """判断模型文件是否仍是 Git LFS 指针。"""

        try:
            if path.stat().st_size > 1024:
                return False
            prefix = path.read_text(encoding="utf-8", errors="ignore")[:80]
            return prefix.startswith("version https://git-lfs.github.com/spec/v1")
        except OSError:
            return False

    @staticmethod
    def _resolve_model_path(model_path: str) -> Path:
        """解析模型路径，兼容 backend 工作目录和仓库根目录。"""

        raw_path = Path(os.path.expandvars(model_path)).expanduser()
        candidates = [raw_path]
        if not raw_path.is_absolute():
            backend_root = Path(__file__).resolve().parents[2]
            repo_root = backend_root.parent
            candidates.extend([backend_root / raw_path, repo_root / raw_path])
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return candidates[-1].resolve()


_local_embedding_provider: LocalEmbeddingProvider | None = None


def get_local_embedding_provider() -> LocalEmbeddingProvider:
    """获取本地 embedding provider 单例。"""

    global _local_embedding_provider
    if _local_embedding_provider is None:
        _local_embedding_provider = LocalEmbeddingProvider()
    return _local_embedding_provider
