from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.utils.jwt import create_access_token

router = APIRouter(prefix="/admin/auth", tags=["管理后台认证"])


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class AdminLoginResponse(BaseModel):
    token: str
    user: dict


@router.post("/login", response_model=AdminLoginResponse, summary="管理员登录")
async def admin_login(payload: AdminLoginRequest):
    if not settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员密码未配置，请设置 ADMIN_PASSWORD",
        )
    if payload.username != settings.ADMIN_USERNAME or payload.password != settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    admin_id = str(UUID("00000000-0000-0000-0000-000000000001"))
    token = create_access_token(
        {
            "sub": admin_id,
            "phone": payload.username,
            "role": "admin",
        }
    )
    return AdminLoginResponse(
        token=token,
        user={
            "id": 1,
            "username": payload.username,
            "nickname": "系统管理员",
            "role": "admin",
        },
    )
