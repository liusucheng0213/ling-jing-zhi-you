from pydantic import ValidationInfo, field_validator
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

    # 数据库。user/pass 只是本机默认账号，生产环境请用 DATABASE_URL 覆盖。
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/lingjing"
    DATABASE_POOL_SIZE: int = 20

    # 缓存
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 3600

    # 向量库（pgvector已集成到PostgreSQL）
    VECTOR_DIMENSION: int = 1024  # BGE-M3维度（本地模型）

    # LLM（DeepSeek-V4）
    # 请配置 DEEPSEEK_API_KEY，获取方式：https://platform.deepseek.com/
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
    # 请配置 XFYUN_APP_ID、XFYUN_API_KEY、XFYUN_API_SECRET，获取方式：https://console.xfyun.cn/
    XFYUN_APP_ID: str = ""
    XFYUN_API_KEY: str = ""
    XFYUN_API_SECRET: str = ""
    XFYUN_TTS_URL: str = "wss://tts-api.xfyun.cn/v2/tts"
    XFYUN_TTS_VCN: str = "xiaoyan"
    XFYUN_TTS_AUE: str = "lame"
    XFYUN_TTS_SAMPLE_RATE: int = 16000
    XFYUN_AVATAR_SERVER_URL: str = "wss://avatar.cn-huadong-1.xf-yun.com/v1/interact"
    # 请配置 XFYUN_AVATAR_SCENE_ID，获取方式：https://www.xfyun.cn/ 虚拟人接口服务
    XFYUN_AVATAR_SCENE_ID: str = ""
    # 下面五个是形象资源编号回退值，不是密钥。换账号后在 .env 覆盖。
    XFYUN_AVATAR_LINGXIAOCHAN_ID: str = "111322001"
    XFYUN_AVATAR_WUCHANSHI_ID: str = "111182004"
    XFYUN_AVATAR_XUANZANG_ID: str = "111140001"
    XFYUN_AVATAR_ZHAOPUCHU_ID: str = "111286001"
    XFYUN_AVATAR_XIAOWAN_ID: str = "111259001"

    @field_validator(
        "XFYUN_AVATAR_LINGXIAOCHAN_ID",
        "XFYUN_AVATAR_WUCHANSHI_ID",
        "XFYUN_AVATAR_XUANZANG_ID",
        "XFYUN_AVATAR_ZHAOPUCHU_ID",
        "XFYUN_AVATAR_XIAOWAN_ID",
        mode="before",
    )
    @classmethod
    def use_default_for_blank_avatar_id(cls, value: object, info: ValidationInfo) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return cls.model_fields[info.field_name].default
        return value

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
    # 请配置 VISION_API_KEY，获取方式：https://bailian.console.aliyun.com/ 或 https://platform.kimi.com
    VISION_API_KEY: str = ""
    VISION_BASE_URL: str = ""
    VISION_MODEL: str = "qwen3.6-flash-2026-04-16"
    # 安全
    # 请配置 JWT_SECRET，获取方式：本地生成随机长字符串，不要把开发默认值用于公网
    JWT_SECRET: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    ADMIN_USERNAME: str = "admin"
    # 请配置 ADMIN_PASSWORD，获取方式：自行设置强密码，只写入根目录 .env
    ADMIN_PASSWORD: str = ""

    class Config:
        env_file = (BACKEND_DIR / ".env", PROJECT_DIR / ".env")
        env_file_encoding = "utf-8"
        # .env 同时承担 docker-compose 变量来源（如 PYTORCH_WHEEL_INDEX_URL、INGEST_RAW_PUBLIC_MATERIALS），
        # 这些键不属于后端配置，忽略多余键避免启动校验失败
        extra = "ignore"

settings = Settings()
