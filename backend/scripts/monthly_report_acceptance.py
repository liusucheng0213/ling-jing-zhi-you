"""自动月报自然月边界与数据库幂等验收。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import delete, select

from app.api.v1.admin.analytics import (
    MONTHLY_REPORT_EVENT_TYPE,
    archive_monthly_report_snapshot,
    ensure_automatic_monthly_report,
    previous_calendar_month_window,
)
from app.database import AsyncSessionLocal
from app.models import BehaviorLog


TEST_NOW = datetime(2099, 4, 15, 12, 30)
TEST_AUTOMATION_KEY = "completed-calendar-month:v2:2099-03"
TEST_MARKER = "monthly-report-acceptance"


def check_calendar_boundaries() -> None:
    cases = [
        (datetime(2026, 1, 1), datetime(2025, 12, 1), datetime(2026, 1, 1), 31),
        (datetime(2024, 3, 31), datetime(2024, 2, 1), datetime(2024, 3, 1), 29),
        (datetime(2025, 3, 15), datetime(2025, 2, 1), datetime(2025, 3, 1), 28),
        (datetime(2026, 7, 11), datetime(2026, 6, 1), datetime(2026, 7, 1), 30),
    ]
    for current, expected_start, expected_end, expected_days in cases:
        start, end = previous_calendar_month_window(current)
        assert start == expected_start, (current, start, expected_start)
        assert end == expected_end, (current, end, expected_end)
        assert (end.date() - start.date()).days == expected_days


async def _delete_test_rows() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(BehaviorLog)
            .where(BehaviorLog.event_type == MONTHLY_REPORT_EVENT_TYPE)
            .where(
                (BehaviorLog.event_data["automation_key"].as_string() == TEST_AUTOMATION_KEY)
                | (BehaviorLog.event_data["generated_by"].as_string() == TEST_MARKER)
            )
        )
        await db.execute(
            delete(BehaviorLog)
            .where(BehaviorLog.event_type == "feedback")
            .where(BehaviorLog.event_data["test_marker"].as_string() == TEST_MARKER)
        )
        await db.commit()


async def _seed_boundary_feedback() -> None:
    cases = [
        (datetime(2099, 2, 28, 23, 59, 59), 1),
        (datetime(2099, 3, 1, 0, 0, 0), 4),
        (datetime(2099, 3, 31, 23, 59, 59), 2),
        (datetime(2099, 4, 1, 0, 0, 0), 5),
    ]
    async with AsyncSessionLocal() as db:
        db.add_all([
            BehaviorLog(
                event_type="feedback",
                event_data={"test_marker": TEST_MARKER, "rating": rating},
                created_at=created_at,
            )
            for created_at, rating in cases
        ])
        await db.commit()


async def _automatic_attempt() -> BehaviorLog | None:
    async with AsyncSessionLocal() as db:
        return await ensure_automatic_monthly_report(db, now=TEST_NOW)


async def check_database_idempotency() -> None:
    await _delete_test_rows()
    try:
        await _seed_boundary_feedback()
        results = await asyncio.gather(*(_automatic_attempt() for _ in range(8)))
        assert sum(row is not None for row in results) == 1

        async with AsyncSessionLocal() as db:
            query = await db.execute(
                select(BehaviorLog)
                .where(BehaviorLog.event_type == MONTHLY_REPORT_EVENT_TYPE)
                .where(BehaviorLog.event_data["automation_key"].as_string() == TEST_AUTOMATION_KEY)
            )
            rows = query.scalars().all()
            assert len(rows) == 1
            data = rows[0].event_data or {}
            assert data["archive_mode"] == "automatic"
            assert data["period_start"] == "2099-03-01"
            assert data["period_end"] == "2099-03-31"
            assert data["period_days"] == 31
            assert data["label"] == "2099年03月自动月报（2099-03-01 至 2099-03-31）"
            overview = (data.get("snapshot") or {}).get("overview") or {}
            assert overview.get("feedback_count") == 2
            assert overview.get("avg_satisfaction") == 3.0

        async with AsyncSessionLocal() as db:
            manual = await archive_monthly_report_snapshot(
                db,
                generated_by=TEST_MARKER,
                archive_mode="manual",
                now=TEST_NOW,
            )
            manual_data = manual.event_data or {}
            assert manual_data["archive_mode"] == "manual"
            assert manual_data["period_days"] == 30
            assert manual_data["period_start"] == "2099-03-16"
            assert manual_data["period_end"] == "2099-04-15"
    finally:
        await _delete_test_rows()


async def main() -> None:
    check_calendar_boundaries()
    await check_database_idempotency()
    print("monthly report acceptance: PASS (calendar boundaries + 8-way database idempotency)")


if __name__ == "__main__":
    asyncio.run(main())
