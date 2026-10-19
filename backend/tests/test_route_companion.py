"""实时路线陪伴的动态规划回归测试。"""

import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace

from app.api.v1.route import _build_dynamic_route_plan, record_route_journey_event
from app.schemas.route import RouteJourneyEventRequest, RouteNodeInfo


def _nodes(count: int = 5, stay_time: int = 20) -> list[RouteNodeInfo]:
    return [
        RouteNodeInfo(
            id=uuid.uuid4(),
            spot_id=f"LS-{index:03d}",
            spot_name=f"景点{index}",
            order=index,
            stay_time=stay_time,
            description=f"景点{index}说明",
        )
        for index in range(1, count + 1)
    ]


class DynamicRoutePlanTests(unittest.TestCase):
    def build(self, nodes: list[RouteNodeInfo], **overrides):
        params = {
            "current_spot_id": None,
            "visited_spots": [],
            "skipped_spots": [],
            "duration": None,
            "mobility": "normal",
            "accessibility_required": False,
        }
        params.update(overrides)
        return _build_dynamic_route_plan(nodes, **params)

    def test_completed_current_spot_continues_forward_without_backtracking(self) -> None:
        plan = self.build(
            _nodes(5),
            current_spot_id="LS-003",
            visited_spots=["LS-003"],
        )

        self.assertEqual([node.spot_id for node in plan.nodes], ["LS-004", "LS-005"])
        self.assertTrue(any("避免折返" in reason for reason in plan.reasons))

    def test_visited_and_skipped_spots_are_both_excluded(self) -> None:
        plan = self.build(
            _nodes(4),
            visited_spots=["LS-001"],
            skipped_spots=["LS-002"],
        )

        self.assertEqual([node.spot_id for node in plan.nodes], ["LS-003", "LS-004"])
        self.assertTrue(any("已游览" in reason for reason in plan.reasons))
        self.assertTrue(any("主动跳过" in reason for reason in plan.reasons))

    def test_thirty_minute_plan_keeps_one_twenty_minute_stop(self) -> None:
        plan = self.build(_nodes(4), duration=30)

        self.assertEqual(len(plan.nodes), 1)
        self.assertEqual(plan.estimated_duration, 20)
        self.assertTrue(plan.is_trimmed)

    def test_low_mobility_limits_plan_to_three_nodes(self) -> None:
        plan = self.build(_nodes(6), mobility="low")

        self.assertEqual(len(plan.nodes), 3)
        self.assertTrue(any("低体力" in reason for reason in plan.reasons))

    def test_all_excluded_nodes_return_empty_plan(self) -> None:
        plan = self.build(
            _nodes(3),
            visited_spots=["LS-001", "LS-002"],
            skipped_spots=["LS-003"],
        )

        self.assertEqual(plan.nodes, [])
        self.assertEqual(plan.estimated_duration, 0)


class _JourneyEventDb:
    def __init__(self) -> None:
        self.event = None
        self.committed = False

    async def scalar(self, _query):
        return SimpleNamespace(name="历史文化爱好者路线")

    def add(self, event) -> None:
        self.event = event

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, event) -> None:
        event.id = uuid.uuid4()
        event.created_at = datetime(2026, 8, 17, 10, 0, 0)


class JourneyEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_journey_event_is_written_as_behavior_log(self) -> None:
        route_id = uuid.uuid4()
        database = _JourneyEventDb()
        request = RouteJourneyEventRequest(
            route_id=route_id,
            journey_id="journey-test",
            event_type="spot_completed",
            spot_id="LS-003",
            progress_percent=50,
            visited_spots=["LS-003"],
            estimated_remaining_minutes=45,
        )

        response = await record_route_journey_event(request, database)

        self.assertTrue(response.recorded)
        self.assertTrue(database.committed)
        self.assertEqual(database.event.event_type, "route_journey_spot_completed")
        self.assertEqual(database.event.spot_id, "LS-003")
        self.assertEqual(database.event.event_data["route_id"], str(route_id))
        self.assertEqual(database.event.event_data["progress_percent"], 50)


if __name__ == "__main__":
    unittest.main()
