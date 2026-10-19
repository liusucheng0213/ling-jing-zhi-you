from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

class Settings(BaseSettings):
    """全局配置"""

    # 应用
    APP_NAME: str = "灵境智游AI导览系统"
    APP_VERSION: str = "1.1.0"
    DEBUG: bool = False

    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/lingjing"
    DATABASE_POOL_SIZE: int = 20

    # 缓存
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 3600

    # 向量库（pgvector已集成到PostgreSQL）
    VECTOR_DIMENSION: int = 1024  # BGE-M3维度（本地模型）

    # LLM（DeepSeek-V4）
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_MODEL_PRO: str = "deepseek-v4-pro"

    LLM_TIMEOUT: float = 12.0
    LLM_MAX_RETRIES: int = 3
    LLM_MAX_TOKENS: int = 650
    LLM_TEMPERATURE: float = 1.0
    LLM_TOP_P: float = 1.0

    # 讯飞开放平台
    XFYUN_APP_ID: str = ""
    XFYUN_API_KEY: str = ""
    XFYUN_API_SECRET: str = ""
    XFYUN_TTS_URL: str = "wss://tts-api.xfyun.cn/v2/tts"
    XFYUN_TTS_VCN: str = "xiaoyan"
    XFYUN_TTS_AUE: str = "lame"
    XFYUN_TTS_SAMPLE_RATE: int = 16000
    XFYUN_AVATAR_SERVER_URL: str = "wss://avatar.cn-huadong-1.xf-yun.com/v1/interact"
    XFYUN_AVATAR_SCENE_ID: str = ""
    XFYUN_AVATAR_LINGXIAOCHAN_ID: str = "111322001"
    XFYUN_AVATAR_WUCHANSHI_ID: str = "111182004"
    XFYUN_AVATAR_XUANZANG_ID: str = "111140001"
    XFYUN_AVATAR_ZHAOPUCHU_ID: str = "111286001"
    XFYUN_AVATAR_XIAOWAN_ID: str = "111259001"
    XFYUN_AVATAR_LINGXIAOCHAN_VCN: str = "x4_lingxiaoxuan_oral"
    XFYUN_AVATAR_WUCHANSHI_VCN: str = "x4_mingge"
    XFYUN_AVATAR_XUANZANG_VCN: str = "x4_lingfeizhe_oral"
    XFYUN_AVATAR_ZHAOPUCHU_VCN: str = "x4_mingge"
    XFYUN_AVATAR_XIAOWAN_VCN: str = "x4_lingxiaoyue_oral_emo"
    XFYUN_AVATAR_WIDTH: int = 1080
    XFYUN_AVATAR_HEIGHT: int = 1920
    XFYUN_AVATAR_FPS: int = 20
    XFYUN_AVATAR_BITRATE: int = 800000
    XFYUN_AVATAR_VCN: str = "x4_lingxiaoxuan_oral"
    XFYUN_AVATAR_STREAM_PROTOCOL: str = "xrtc"
    XFYUN_AVATAR_EXPOSE_SECRET_TO_FRONTEND: bool = False
    XFYUN_AVATAR_BACKGROUND_RES_KEY: str = ""
    XFYUN_AVATAR_BACKGROUND_TYPE: str = "res_key"

    # 嵌入模型（本地BGE-M3，可选）
    EMBEDDING_MODEL_PATH: str = "./models/bge-m3"
    EMBEDDING_DIMENSION: int = 1024
    EMBEDDING_DEVICE: str = "auto"
    EMBEDDING_LOCAL_BACKEND: str = "auto"  # auto / sentence-transformers / onnx
    EMBEDDING_SERVICE_URL: str = ""
    EMBEDDING_BASE_IMAGE: str = "pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime"
    USE_LOCAL_EMBEDDING: bool = False  # 是否使用本地嵌入模型

    # 多模态图片能力（默认关闭；未配置供应商时只返回明确未启用状态）
    VISION_PROVIDER: str = ""
    VISION_API_KEY: str = ""
    VISION_BASE_URL: str = ""
    VISION_MODEL: str = "qwen3.6-flash-2026-04-16"
    # 安全
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""

    class Config:
        env_file = (BACKEND_DIR / ".env", PROJECT_DIR / ".env")
        env_file_encoding = "utf-8"
        # .env 同时承担 docker-compose 变量来源（如 PYTORCH_WHEEL_INDEX_URL、INGEST_RAW_PUBLIC_MATERIALS），
        # 这些键不属于后端配置，忽略多余键避免启动校验失败
        extra = "ignore"

settings = Settings()
