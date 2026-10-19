"""动态路线计划验收：当前点、已游排除、时长裁剪和节点真实性。"""

from __future__ import annotations

import argparse
import asyncio

import httpx


def _find_route(rows: list[dict], route_id: str) -> dict:
    return next((row for row in rows if str(row.get("id")) == route_id), {})


async def run(base_url: str, timeout: float) -> int:
    failures: list[str] = []
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        route_response = await client.get("/api/v1/routes")
        route_response.raise_for_status()
        route_rows = route_response.json()

        details: dict[str, dict] = {}
        for route in route_rows:
            route_id = str(route["id"])
            response = await client.get(f"/api/v1/routes/{route_id}")
            response.raise_for_status()
            details[route_id] = response.json()

        eligible = [
            detail
            for detail in details.values()
            if len([node for node in detail.get("nodes", []) if node.get("spot_name")]) >= 4
        ]
        if not eligible:
            print("FAIL | 数据库中没有至少包含4个有效节点的路线，无法执行动态路线验收。")
            return 1

        target = max(eligible, key=lambda item: len(item.get("nodes", [])))
        route_id = str(target["id"])
        valid_nodes = [node for node in target["nodes"] if node.get("spot_name")]

        current_spot = valid_nodes[1]["spot_id"]
        current_response = await client.post(
            "/api/v1/routes/recommend",
            json={"spot_id": current_spot, "duration": 720},
        )
        current_response.raise_for_status()
        current_route = _find_route(current_response.json(), route_id)
        current_plan_nodes = (current_route.get("dynamic_plan") or {}).get("nodes") or []
        current_ok = bool(current_plan_nodes) and current_plan_nodes[0]["spot_id"] == current_spot
        print(
            f"{'PASS' if current_ok else 'FAIL'} | 当前点优先 | "
            f"expected={current_spot} actual={current_plan_nodes[0]['spot_id'] if current_plan_nodes else None}"
        )
        if not current_ok:
            failures.append("当前景点未排在动态计划首位")

        visited_spots = [valid_nodes[0]["spot_id"], valid_nodes[2]["spot_id"]]
        visited_response = await client.post(
            "/api/v1/routes/recommend",
            json={"visited_spots": visited_spots, "duration": 720},
        )
        visited_response.raise_for_status()
        visited_route = _find_route(visited_response.json(), route_id)
        visited_plan_nodes = (visited_route.get("dynamic_plan") or {}).get("nodes") or []
        returned_spots = {node["spot_id"] for node in visited_plan_nodes}
        visited_ok = not returned_spots.intersection(visited_spots)
        print(
            f"{'PASS' if visited_ok else 'FAIL'} | 排除已游 | "
            f"excluded={visited_spots} returned={sorted(returned_spots.intersection(visited_spots))}"
        )
        if not visited_ok:
            failures.append("动态计划仍包含已游览景点")

        duration_limit = 30
        duration_response = await client.post(
            "/api/v1/routes/recommend",
            json={"duration": duration_limit},
        )
        duration_response.raise_for_status()
        duration_route = _find_route(duration_response.json(), route_id)
        duration_plan = duration_route.get("dynamic_plan") or {}
        duration_nodes = duration_plan.get("nodes") or []
        duration_ok = (
            bool(duration_nodes)
            and duration_plan.get("estimated_duration", duration_limit + 1) <= duration_limit
            and bool(duration_plan.get("is_trimmed"))
            and len(duration_nodes) < len(valid_nodes)
        )
        print(
            f"{'PASS' if duration_ok else 'FAIL'} | 时长裁剪 | limit={duration_limit} "
            f"estimated={duration_plan.get('estimated_duration')} nodes={len(duration_nodes)}/{len(valid_nodes)}"
        )
        if not duration_ok:
            failures.append("动态计划未按可用时长正确裁剪")

        active_response = await client.get("/api/v1/location/spots")
        active_response.raise_for_status()
        active_spots = {spot["id"]: spot["name"] for spot in active_response.json()}
        valid_response = await client.post("/api/v1/routes/recommend", json={})
        valid_response.raise_for_status()
        all_valid = True
        checked_nodes = 0
        for route in valid_response.json():
            detail_nodes = {
                (str(node["id"]), node["spot_id"])
                for node in details.get(str(route["id"]), {}).get("nodes", [])
            }
            for node in (route.get("dynamic_plan") or {}).get("nodes") or []:
                checked_nodes += 1
                node_key = (str(node["id"]), node["spot_id"])
                if (
                    node_key not in detail_nodes
                    or node["spot_id"] not in active_spots
                    or node.get("spot_name") != active_spots[node["spot_id"]]
                ):
                    all_valid = False
        print(
            f"{'PASS' if all_valid and checked_nodes else 'FAIL'} | 节点真实性 | "
            f"checked={checked_nodes} active_spots={len(active_spots)}"
        )
        if not all_valid or not checked_nodes:
            failures.append("动态计划包含不存在、未启用或不属于原路线的景点节点")

        constrained_response = await client.post(
            "/api/v1/routes/recommend",
            json={"mobility": "low", "accessibility_required": True, "duration": 720},
        )
        constrained_response.raise_for_status()
        constrained_route = _find_route(constrained_response.json(), route_id)
        constrained_plan = constrained_route.get("dynamic_plan") or {}
        constrained_nodes = constrained_plan.get("nodes") or []
        constrained_ok = len(constrained_nodes) <= 3 and bool(constrained_plan.get("is_trimmed"))
        print(
            f"{'PASS' if constrained_ok else 'FAIL'} | 低体力/无障碍减点 | "
            f"nodes={len(constrained_nodes)}"
        )
        if not constrained_ok:
            failures.append("低体力/无障碍计划未减少节点")

    print(f"\nDynamic route acceptance: {5 - len(failures)}/5")
    for failure in failures:
        print(f"- {failure}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    return asyncio.run(run(args.url, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
