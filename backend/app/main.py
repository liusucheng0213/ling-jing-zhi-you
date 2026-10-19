"""
灵境智游AI数字人导览系统 - FastAPI主入口

提供FastAPI应用实例创建、中间件配置、路由注册和全局异常处理。
"""

from contextlib import asynccontextmanager
from pathlib import Path
import traceback

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import settings
from app.database import init_db


# ==================== 生命周期管理 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时初始化数据库连接和表结构，关闭时清理资源。
    """
    logger.info(f"🚀 启动 {settings.APP_NAME} v{settings.APP_VERSION}")

    # 初始化数据库
    try:
        await init_db()
        logger.info("✅ 数据库初始化完成")
    except Exception as e:
        logger.warning(f"⚠️ 数据库初始化失败（首次运行可忽略）: {e}")

    from app.core.monthly_report_scheduler import monthly_report_scheduler
    from app.core.avatar_channel import avatar_channel_coordinator

    monthly_report_scheduler.start()
    yield
    await monthly_report_scheduler.stop()
    await avatar_channel_coordinator.close()

    logger.info(f"🛑 关闭 {settings.APP_NAME}")


# ==================== 创建FastAPI应用 ====================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="灵境智游AI数字人导览系统后端API - 基于FastAPI构建",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# ==================== CORS中间件 ====================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应配置具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# 管理后台截取的数字人预览图不含敏感信息，可作为游客端/管理端同源静态资源使用。
avatar_preview_dir = Path(__file__).resolve().parent / "static" / "avatar-previews"
avatar_preview_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/api/v1/avatar-previews",
    StaticFiles(directory=str(avatar_preview_dir)),
    name="avatar-previews",
)

# 游客主动发布的社区图片经过类型、签名和大小校验后保存在同源静态目录。
community_image_dir = Path(__file__).resolve().parent / "static" / "community-images"
community_image_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/api/v1/community-images",
    StaticFiles(directory=str(community_image_dir)),
    name="community-images",
)


# ==================== 全局异常处理 ====================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    全局异常处理器

    捕获所有未处理的异常，返回统一的错误响应格式。
    """
    logger.error(f"未捕获的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "detail": (
                {"error": str(exc), "traceback": traceback.format_exc()}
                if settings.DEBUG
                else "请稍后重试"
            ),
        },
    )


# ==================== 健康检查 ====================

@app.get("/health", tags=["健康检查"], summary="服务健康检查")
async def health_check():
    """
    服务健康检查端点

    返回服务运行状态和版本信息。
    """
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "debug": settings.DEBUG,
    }


@app.get("/", tags=["根路径"], summary="根路径")
async def root():
    """根路径欢迎信息"""
    return {
        "message": f"欢迎使用{settings.APP_NAME}",
        "docs": "/docs",
        "health": "/health",
    }


# ==================== 注册路由 ====================

from app.api.v1 import avatar, chat, route, location, story, creative, tts, system
from app.api.v1.admin import auth, knowledge, dashboard, rag_trace, analytics, avatars, community, users

# 游客端API（/api/v1前缀）
app.include_router(chat.router, prefix="/api/v1")
app.include_router(avatar.router, prefix="/api/v1")
app.include_router(route.router, prefix="/api/v1")
app.include_router(location.router, prefix="/api/v1")
app.include_router(story.router, prefix="/api/v1")
app.include_router(creative.router, prefix="/api/v1")
app.include_router(tts.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")

# 管理后台API（/api/v1前缀）
app.include_router(auth.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(rag_trace.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(avatars.router, prefix="/api/v1")
app.include_router(community.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

logger.info("✅ 所有路由已注册")
