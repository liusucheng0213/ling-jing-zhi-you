"""游客感受度月报自动归档调度器。"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from loguru import logger

from app.database import AsyncSessionLocal


class MonthlyReportScheduler:
    """每6小时检查上一个完整自然月，跨进程幂等由数据库锁保证。"""

    def __init__(self, interval_seconds: int = 6 * 60 * 60) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="monthly-report-scheduler")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        from app.api.v1.admin.analytics import ensure_automatic_monthly_report

        while True:
            try:
                async with AsyncSessionLocal() as db:
                    archived = await ensure_automatic_monthly_report(db)
                    if archived:
                        data = archived.event_data or {}
                        logger.info(
                            "游客感受度完整自然月自动归档已生成: "
                            f"period={data.get('period_start')}..{data.get('period_end')}, "
                            f"report_id={archived.id}"
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"游客感受度自动月报检查失败: {exc}")
            await asyncio.sleep(self.interval_seconds)


monthly_report_scheduler = MonthlyReportScheduler()
