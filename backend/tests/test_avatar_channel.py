"""数字人唯一通道租约与游客优先策略测试。"""

import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.api.v1.system import _check_avatar_ws_probe_leased
from app.core.avatar_channel import (
    ADMIN_LEASE_TTL_MS,
    CHANNEL_COOLDOWN_MS,
    AvatarChannelCoordinator,
    AvatarChannelResult,
)


class AvatarChannelCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now_ms = 1_800_000_000_000
        self.coordinator = AvatarChannelCoordinator(
            namespace=f"lingjing:test:avatar-channel:{uuid.uuid4().hex}"
        )
        self.coordinator._now_ms = lambda: self.now_ms  # type: ignore[method-assign]
        await self.coordinator.clear()

    async def asyncTearDown(self) -> None:
        await self.coordinator.clear()
        await self.coordinator.close()

    async def test_exclusive_acquire_and_same_holder_heartbeat(self) -> None:
        visitor = await self.coordinator.acquire("visitor-owner", "visitor")
        self.assertEqual(visitor.status, "acquired")
        self.assertTrue(visitor.lease_token)

        repeated = await self.coordinator.acquire("visitor-owner", "visitor")
        heartbeat = await self.coordinator.heartbeat(visitor.lease_token or "")
        admin = await self.coordinator.acquire("admin-owner", "admin_preview")

        self.assertEqual(repeated.lease_token, visitor.lease_token)
        self.assertEqual(heartbeat.status, "acquired")
        self.assertEqual(admin.status, "occupied")
        self.assertEqual(admin.owner_type, "visitor")

    async def test_wrong_token_does_not_release_current_holder(self) -> None:
        lease = await self.coordinator.acquire("admin-owner", "admin_preview")
        wrong = await self.coordinator.release("0" * 32)
        status = await self.coordinator.status()

        self.assertEqual(wrong.status, "occupied")
        self.assertEqual(status.status, "occupied")
        self.assertEqual(status.owner_type, "admin_preview")

        released = await self.coordinator.release(lease.lease_token or "")
        self.assertEqual(released.status, "cooldown")
        self.assertEqual(released.retry_after_ms, CHANNEL_COOLDOWN_MS)

    async def test_expired_lease_recovers_without_manual_release(self) -> None:
        first = await self.coordinator.acquire("stale-admin", "admin_preview")
        self.assertEqual(first.status, "acquired")

        self.now_ms += ADMIN_LEASE_TTL_MS + 1
        second = await self.coordinator.acquire("fresh-admin", "admin_preview")

        self.assertEqual(second.status, "acquired")
        self.assertNotEqual(second.lease_token, first.lease_token)

    async def test_visitor_revokes_admin_then_waits_for_cooldown(self) -> None:
        admin = await self.coordinator.acquire("admin-owner", "admin_preview")
        visitor = await self.coordinator.acquire("visitor-owner", "visitor")
        heartbeat = await self.coordinator.heartbeat(admin.lease_token or "")

        self.assertEqual(visitor.status, "revoking")
        self.assertEqual(heartbeat.status, "revoked")

        released = await self.coordinator.release(admin.lease_token or "")
        cooling = await self.coordinator.acquire("visitor-owner", "visitor")
        self.assertEqual(released.status, "cooldown")
        self.assertEqual(cooling.status, "cooldown")

        self.now_ms += CHANNEL_COOLDOWN_MS + 1
        acquired = await self.coordinator.acquire("visitor-owner", "visitor")
        self.assertEqual(acquired.status, "acquired")

    async def test_unresponsive_admin_is_recovered_after_revocation_grace(self) -> None:
        await self.coordinator.acquire("unresponsive-admin", "admin_preview")
        revoking = await self.coordinator.acquire("visitor-owner", "visitor")
        self.assertEqual(revoking.status, "revoking")

        self.now_ms += 8_001
        cooling = await self.coordinator.acquire("visitor-owner", "visitor")
        self.assertEqual(cooling.status, "cooldown")

        self.now_ms += CHANNEL_COOLDOWN_MS + 1
        acquired = await self.coordinator.acquire("visitor-owner", "visitor")
        self.assertEqual(acquired.status, "acquired")


class AvatarWsProbeLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_visitor_occupancy_skips_real_websocket_probe(self) -> None:
        occupied = AvatarChannelResult(
            status="occupied",
            owner_type="visitor",
            retry_after_ms=15_000,
            message="游客端正在使用数字人",
        )
        websocket_probe = AsyncMock()
        with (
            patch(
                "app.api.v1.system.avatar_channel_coordinator.acquire",
                new=AsyncMock(return_value=occupied),
            ),
            patch(
                "app.api.v1.system._check_avatar_ws_probe",
                new=websocket_probe,
            ),
        ):
            result = await _check_avatar_ws_probe_leased()

        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["channel_status"], "occupied")
        websocket_probe.assert_not_awaited()

    async def test_acquired_lease_runs_probe_and_releases_channel(self) -> None:
        acquired = AvatarChannelResult(
            status="acquired",
            owner_type="showcase_probe",
            lease_token="lease-token",
        )
        websocket_probe = AsyncMock(return_value={"ok": True, "handshake": "connected"})
        release = AsyncMock()
        with (
            patch(
                "app.api.v1.system.avatar_channel_coordinator.acquire",
                new=AsyncMock(return_value=acquired),
            ),
            patch(
                "app.api.v1.system._check_avatar_ws_probe",
                new=websocket_probe,
            ),
            patch(
                "app.api.v1.system.avatar_channel_coordinator.release",
                new=release,
            ),
        ):
            result = await _check_avatar_ws_probe_leased()

        self.assertEqual(result, {"ok": True, "handshake": "connected"})
        websocket_probe.assert_awaited_once()
        release.assert_awaited_once_with("lease-token")


if __name__ == "__main__":
    unittest.main()
