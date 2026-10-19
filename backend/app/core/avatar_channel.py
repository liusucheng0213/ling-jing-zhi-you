"""讯飞数字人唯一并发通道的 Redis 租约协调器。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Literal

from redis.asyncio import Redis, from_url as redis_from_url

from app.config import settings


AvatarOwnerType = Literal["visitor", "admin_preview", "showcase_probe"]

VISITOR_LEASE_TTL_MS = 90_000
ADMIN_LEASE_TTL_MS = 45_000
CHANNEL_COOLDOWN_MS = 3_500
ADMIN_REVOKE_GRACE_MS = 8_000


@dataclass(slots=True)
class AvatarChannelResult:
    """一次通道状态变更的统一结果。"""

    status: str
    owner_type: AvatarOwnerType | None = None
    lease_token: str | None = None
    retry_after_ms: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        """转换为 API 可直接返回的字典。"""

        return asdict(self)


class AvatarChannelCoordinator:
    """使用 Redis 在游客端、后台预览和探针间协调唯一数字人通道。"""

    def __init__(
        self,
        redis: Redis | None = None,
        *,
        namespace: str = "lingjing:avatar-channel",
    ) -> None:
        self._redis = redis
        self._owns_redis = redis is None
        self._lease_key = f"{namespace}:lease"
        self._cooldown_key = f"{namespace}:cooldown"
        self._lock_key = f"{namespace}:lock"

    @property
    def redis(self) -> Redis:
        """延迟创建连接，避免模块导入阶段访问 Redis。"""

        if self._redis is None:
            self._redis = redis_from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
        return self._redis

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _ttl_for(owner_type: AvatarOwnerType) -> int:
        return VISITOR_LEASE_TTL_MS if owner_type == "visitor" else ADMIN_LEASE_TTL_MS

    async def _read_lease(self, now_ms: int) -> dict[str, object] | None:
        raw = await self.redis.get(self._lease_key)
        if not raw:
            return None
        try:
            lease = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            await self.redis.delete(self._lease_key)
            return None
        expires_at_ms = int(lease.get("expires_at_ms") or 0)
        revoke_deadline_ms = int(lease.get("revoke_deadline_ms") or 0)
        if max(expires_at_ms, revoke_deadline_ms) <= now_ms:
            await self.redis.delete(self._lease_key)
            return None
        return lease

    async def _write_lease(self, lease: dict[str, object], now_ms: int) -> None:
        keep_until = max(
            int(lease.get("expires_at_ms") or 0),
            int(lease.get("revoke_deadline_ms") or 0),
        )
        ttl_ms = max(1, keep_until - now_ms + 1_000)
        await self.redis.set(self._lease_key, json.dumps(lease), px=ttl_ms)

    async def _cooldown_remaining(self, now_ms: int) -> int:
        raw = await self.redis.get(self._cooldown_key)
        if not raw:
            return 0
        try:
            remaining = int(raw) - now_ms
        except (TypeError, ValueError):
            await self.redis.delete(self._cooldown_key)
            return 0
        if remaining <= 0:
            await self.redis.delete(self._cooldown_key)
            return 0
        return remaining

    async def _start_cooldown(self, now_ms: int) -> None:
        until_ms = now_ms + CHANNEL_COOLDOWN_MS
        await self.redis.set(
            self._cooldown_key,
            str(until_ms),
            px=CHANNEL_COOLDOWN_MS + 1_000,
        )

    async def status(self) -> AvatarChannelResult:
        """返回当前占用、撤销或冷却状态。"""

        now_ms = self._now_ms()
        async with self.redis.lock(self._lock_key, timeout=4, blocking_timeout=2):
            lease = await self._read_lease(now_ms)
            if lease:
                owner_type = str(lease.get("owner_type"))
                state = str(lease.get("state") or "active")
                deadline = int(
                    lease.get("revoke_deadline_ms")
                    if state == "revoking"
                    else lease.get("expires_at_ms")
                    or now_ms
                )
                return AvatarChannelResult(
                    status="revoking" if state == "revoking" else "occupied",
                    owner_type=owner_type,  # type: ignore[arg-type]
                    retry_after_ms=max(250, deadline - now_ms),
                    message=(
                        "后台连接正在为游客释放"
                        if state == "revoking"
                        else "数字人通道正在使用中"
                    ),
                )
            cooldown_ms = await self._cooldown_remaining(now_ms)
            if cooldown_ms:
                return AvatarChannelResult(
                    status="cooldown",
                    retry_after_ms=cooldown_ms,
                    message="数字人连接正在完成释放",
                )
            return AvatarChannelResult(status="idle", message="数字人通道空闲")

    async def acquire(
        self,
        owner_id: str,
        owner_type: AvatarOwnerType,
    ) -> AvatarChannelResult:
        """申请唯一租约；游客会撤销正在运行的后台租约。"""

        now_ms = self._now_ms()
        async with self.redis.lock(self._lock_key, timeout=4, blocking_timeout=2):
            lease = await self._read_lease(now_ms)
            if lease:
                current_type = str(lease.get("owner_type"))
                current_state = str(lease.get("state") or "active")
                if lease.get("owner_id") == owner_id and current_type == owner_type:
                    if current_state == "revoking":
                        return AvatarChannelResult(
                            status="revoked",
                            owner_type=owner_type,
                            retry_after_ms=max(
                                250,
                                int(lease.get("revoke_deadline_ms") or now_ms) - now_ms,
                            ),
                            message="当前后台租约已由游客请求撤销",
                        )
                    lease["expires_at_ms"] = now_ms + self._ttl_for(owner_type)
                    await self._write_lease(lease, now_ms)
                    return AvatarChannelResult(
                        status="acquired",
                        owner_type=owner_type,
                        lease_token=str(lease.get("lease_token")),
                        message="已继续使用当前数字人通道",
                    )

                if owner_type == "visitor" and current_type != "visitor":
                    revoke_deadline = int(lease.get("revoke_deadline_ms") or 0)
                    if current_state != "revoking":
                        revoke_deadline = now_ms + ADMIN_REVOKE_GRACE_MS
                        lease["state"] = "revoking"
                        lease["revoke_deadline_ms"] = revoke_deadline
                        await self._write_lease(lease, now_ms)
                    elif revoke_deadline <= now_ms:
                        await self.redis.delete(self._lease_key)
                        await self._start_cooldown(now_ms)
                        return AvatarChannelResult(
                            status="cooldown",
                            retry_after_ms=CHANNEL_COOLDOWN_MS,
                            message="后台连接撤销宽限结束，正在等待通道冷却",
                        )
                    return AvatarChannelResult(
                        status="revoking",
                        owner_type=current_type,  # type: ignore[arg-type]
                        retry_after_ms=max(250, min(800, revoke_deadline - now_ms)),
                        message="正在通知后台释放数字人通道",
                    )

                deadline = int(
                    lease.get("revoke_deadline_ms")
                    if current_state == "revoking"
                    else lease.get("expires_at_ms")
                    or now_ms
                )
                return AvatarChannelResult(
                    status="revoking" if current_state == "revoking" else "occupied",
                    owner_type=current_type,  # type: ignore[arg-type]
                    retry_after_ms=max(500, min(3_000, deadline - now_ms)),
                    message="游客端正在使用数字人，后台连接暂不可用"
                    if current_type == "visitor"
                    else "数字人通道正在使用中",
                )

            cooldown_ms = await self._cooldown_remaining(now_ms)
            if cooldown_ms:
                return AvatarChannelResult(
                    status="cooldown",
                    retry_after_ms=cooldown_ms,
                    message="数字人连接正在完成释放",
                )

            lease_token = uuid.uuid4().hex
            lease = {
                "owner_id": owner_id,
                "owner_type": owner_type,
                "lease_token": lease_token,
                "state": "active",
                "expires_at_ms": now_ms + self._ttl_for(owner_type),
                "revoke_deadline_ms": 0,
            }
            await self._write_lease(lease, now_ms)
            return AvatarChannelResult(
                status="acquired",
                owner_type=owner_type,
                lease_token=lease_token,
                message="已取得数字人唯一通道",
            )

    async def heartbeat(self, lease_token: str) -> AvatarChannelResult:
        """续租；被游客撤销的后台连接会立即收到 revoked。"""

        now_ms = self._now_ms()
        async with self.redis.lock(self._lock_key, timeout=4, blocking_timeout=2):
            lease = await self._read_lease(now_ms)
            if not lease or lease.get("lease_token") != lease_token:
                return AvatarChannelResult(status="revoked", message="数字人租约已失效")
            owner_type = str(lease.get("owner_type"))
            if lease.get("state") == "revoking":
                return AvatarChannelResult(
                    status="revoked",
                    owner_type=owner_type,  # type: ignore[arg-type]
                    retry_after_ms=max(
                        0,
                        int(lease.get("revoke_deadline_ms") or now_ms) - now_ms,
                    ),
                    message="游客请求已到达，请立即释放后台预览",
                )
            lease["expires_at_ms"] = now_ms + self._ttl_for(owner_type)  # type: ignore[arg-type]
            await self._write_lease(lease, now_ms)
            return AvatarChannelResult(
                status="acquired",
                owner_type=owner_type,  # type: ignore[arg-type]
                lease_token=lease_token,
                message="数字人租约已续期",
            )

    async def release(self, lease_token: str) -> AvatarChannelResult:
        """幂等释放；只有匹配令牌才会清理当前持有者。"""

        now_ms = self._now_ms()
        async with self.redis.lock(self._lock_key, timeout=4, blocking_timeout=2):
            lease = await self._read_lease(now_ms)
            if not lease:
                cooldown_ms = await self._cooldown_remaining(now_ms)
                return AvatarChannelResult(
                    status="cooldown" if cooldown_ms else "idle",
                    retry_after_ms=cooldown_ms,
                    message="数字人通道已经释放",
                )
            if lease.get("lease_token") != lease_token:
                return AvatarChannelResult(
                    status="occupied",
                    owner_type=str(lease.get("owner_type")),  # type: ignore[arg-type]
                    retry_after_ms=max(
                        500,
                        int(lease.get("expires_at_ms") or now_ms) - now_ms,
                    ),
                    message="释放令牌不属于当前通道，现有连接保持不变",
                )
            await self.redis.delete(self._lease_key)
            await self._start_cooldown(now_ms)
            return AvatarChannelResult(
                status="cooldown",
                retry_after_ms=CHANNEL_COOLDOWN_MS,
                message="数字人通道已释放，正在冷却",
            )

    async def clear(self) -> None:
        """清理指定命名空间，供定向测试收尾使用。"""

        await self.redis.delete(self._lease_key, self._cooldown_key, self._lock_key)

    async def close(self) -> None:
        """关闭由协调器自行创建的 Redis 客户端。"""

        if self._owns_redis and self._redis is not None:
            await self._redis.aclose()
            self._redis = None


avatar_channel_coordinator = AvatarChannelCoordinator()
