"""
JWT令牌工具模块
提供访问令牌的创建、验证以及当前用户获取功能
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.config import settings

# 安全方案定义
security = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建JWT访问令牌

    参数:
        data: 要编码到令牌中的数据字典
        expires_delta: 自定义过期时间，默认使用配置中的JWT_EXPIRE_HOURS

    返回:
        编码后的JWT字符串
    """
    to_encode = data.copy()

    # 计算过期时间
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)

    to_encode.update({"exp": expire})

    # 编码JWT
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """
    验证JWT令牌的有效性

    参数:
        token: JWT令牌字符串

    返回:
        解码后的payload字典，验证失败返回None
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """
    FastAPI依赖：从请求头中提取并验证JWT令牌，获取当前用户信息

    参数:
        credentials: HTTP认证凭据

    返回:
        当前用户信息字典，未认证返回None（游客模式）

    异常:
        HTTPException: 令牌无效或过期时抛出401异常
    """
    # 无凭据时允许游客访问
    if not credentials:
        return None

    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌中未包含用户标识",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": user_id,
        "phone": payload.get("phone"),
        "role": payload.get("role", "user"),
    }


async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """
    FastAPI依赖：验证当前用户是否为管理员

    参数:
        credentials: HTTP认证凭据

    返回:
        管理员用户信息字典

    异常:
        HTTPException: 非管理员时抛出403异常
    """
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，需要管理员权限",
        )

    return user
