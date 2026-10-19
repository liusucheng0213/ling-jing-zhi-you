#!/usr/bin/env python3
"""
灵境智游 - 景点与路线数据初始化脚本

功能说明：
- 读取 spots.json 和 routes.json
- 将景点数据和路线数据插入 PostgreSQL 数据库
- 支持幂等执行（已存在则更新）
- 使用 SQLAlchemy async session

使用方法：
    cd backend
    python -m scripts.init_data

环境变量：
    DATABASE_URL - 数据库连接字符串，默认 postgresql+asyncpg://user:pass@localhost:5432/lingjing
"""

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 将项目根目录加入 Python 路径，以便导入 app 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.base import Base
from app.models.spot import Spot
from app.models.route import Route, RouteNode


# 数据库连接字符串（从环境变量读取，使用默认值）
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/lingjing"
)

# JSON 数据文件路径
SCRIPTS_DIR = Path(__file__).resolve().parent
SPOTS_JSON = SCRIPTS_DIR / "spots.json"
ROUTES_JSON = SCRIPTS_DIR / "routes.json"


async def load_json(path: Path) -> list[dict[str, Any]]:
    """加载 JSON 文件并返回数据列表。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def init_spots(session: AsyncSession, spots_data: list[dict]) -> dict[str, int]:
    """
    初始化景点数据。

    采用 PostgreSQL 的 ON CONFLICT DO UPDATE 实现 upsert，
    确保多次运行不会重复插入。

    返回统计信息：{"inserted": x, "updated": y}
    """
    inserted = 0
    updated = 0

    for spot in spots_data:
        spot_id = spot["id"]

        verified_at = spot.get("coordinate_verified_at")
        if isinstance(verified_at, str) and verified_at:
            verified_at = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))

        # 先查询判断记录是否存在
        result = await session.execute(select(Spot).where(Spot.id == spot_id))
        existing = result.scalar_one_or_none()

        # 构建 upsert 语句
        stmt = insert(Spot).values(
            id=spot_id,
            name=spot["name"],
            scenic_area=spot.get("scenic_area", "灵山胜境"),
            location=spot.get("location"),
            latitude=spot.get("latitude"),
            longitude=spot.get("longitude"),
            coordinate_system=spot.get("coordinate_system", "WGS84"),
            coordinate_status=spot.get("coordinate_status", "estimated"),
            coordinate_source=spot.get("coordinate_source"),
            coordinate_source_id=spot.get("coordinate_source_id"),
            coordinate_accuracy_meters=spot.get("coordinate_accuracy_meters"),
            coordinate_verified_at=verified_at,
            source_latitude=spot.get("source_latitude"),
            source_longitude=spot.get("source_longitude"),
            source_coordinate_system=spot.get("source_coordinate_system"),
            building_params=spot.get("building_params"),
            core_function=spot.get("core_function"),
            cultural_connotation=spot.get("cultural_connotation"),
            detailed_intro=spot.get("detailed_intro"),
            highlights=spot.get("highlights"),
            performance_info=spot.get("performance_info"),
            photos=spot.get("photos", []),
            tags=spot.get("tags", []),
            route_order=spot.get("route_order", 0),
            best_visit_time=spot.get("best_visit_time"),
            qr_code=spot.get("qr_code"),
            lang=spot.get("lang", "zh"),
            is_active=spot.get("is_active", True),
        )

        # 冲突时更新所有字段
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "name": stmt.excluded.name,
                "scenic_area": stmt.excluded.scenic_area,
                "location": stmt.excluded.location,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "coordinate_system": stmt.excluded.coordinate_system,
                "coordinate_status": stmt.excluded.coordinate_status,
                "coordinate_source": stmt.excluded.coordinate_source,
                "coordinate_source_id": stmt.excluded.coordinate_source_id,
                "coordinate_accuracy_meters": stmt.excluded.coordinate_accuracy_meters,
                "coordinate_verified_at": stmt.excluded.coordinate_verified_at,
                "source_latitude": stmt.excluded.source_latitude,
                "source_longitude": stmt.excluded.source_longitude,
                "source_coordinate_system": stmt.excluded.source_coordinate_system,
                "building_params": stmt.excluded.building_params,
                "core_function": stmt.excluded.core_function,
                "cultural_connotation": stmt.excluded.cultural_connotation,
                "detailed_intro": stmt.excluded.detailed_intro,
                "highlights": stmt.excluded.highlights,
                "performance_info": stmt.excluded.performance_info,
                "photos": stmt.excluded.photos,
                "tags": stmt.excluded.tags,
                "route_order": stmt.excluded.route_order,
                "best_visit_time": stmt.excluded.best_visit_time,
                "qr_code": stmt.excluded.qr_code,
                "lang": stmt.excluded.lang,
                "is_active": stmt.excluded.is_active,
            }
        )

        await session.execute(stmt)

        if existing:
            updated += 1
        else:
            inserted += 1

    await session.flush()

    return {"inserted": inserted, "updated": updated}


# 路线 ID 到 UUID 的映射缓存（确保同一字符串 ID 始终映射到同一个 UUID）
_route_id_map: dict[str, uuid.UUID] = {}


def get_route_uuid(route_id_str: str) -> uuid.UUID:
    """将字符串路线 ID 转换为固定的 UUID。"""
    if route_id_str not in _route_id_map:
        # 使用 UUID5 基于命名空间 DNS 和路线 ID 字符串生成确定性 UUID
        _route_id_map[route_id_str] = uuid.uuid5(uuid.NAMESPACE_DNS, f"lingjing.route.{route_id_str}")
    return _route_id_map[route_id_str]


async def init_routes(session: AsyncSession, routes_data: list[dict]) -> dict[str, int]:
    """
    初始化路线数据。

    路线采用 "先删除再插入" 的策略实现幂等：
    - 根据 route.id 判断，显式删除旧路线节点后再删除路线并重新插入
    - 确保节点数据与 JSON 完全一致
    - 路线 ID 从 JSON 字符串映射为 UUID（模型要求）

    返回统计信息
    """
    routes_processed = 0
    nodes_inserted = 0

    for route in routes_data:
        route_id_str = route["id"]
        route_id = get_route_uuid(route_id_str)

        # 1. 查询是否已存在该路线
        result = await session.execute(
            select(Route).where(Route.id == route_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # 数据库外键未配置 ON DELETE CASCADE，需先显式删除路线节点。
            await session.execute(
                delete(RouteNode).where(RouteNode.route_id == route_id)
            )
            await session.execute(
                delete(Route).where(Route.id == route_id)
            )
            await session.flush()

        # 2. 插入新路线
        # 处理 total_time 和 total_distance：统一入库为分钟/米。
        total_time_str = route.get("total_time", "")
        total_distance_str = route.get("total_distance", "")

        def parse_duration_minutes(s: str) -> int | None:
            """将“6小时/90分钟”等时长文本转成分钟。"""
            if not s:
                return None
            match = re.search(r"\d+(?:\.\d+)?", s)
            if not match:
                return None
            value = float(match.group())
            return int(value * 60) if "小时" in s else int(value)

        def parse_distance_meters(s: str) -> int | None:
            """将“约3.5公里/800米”等距离文本转成米。"""
            if not s:
                return None
            match = re.search(r"\d+(?:\.\d+)?", s)
            if not match:
                return None
            value = float(match.group())
            return int(value * 1000) if "公里" in s or "千米" in s else int(value)

        total_time = parse_duration_minutes(total_time_str)
        total_distance = parse_distance_meters(total_distance_str)

        new_route = Route(
            id=route_id,
            name=route["name"],
            description=route.get("description"),
            tags=route.get("tags", []),
            total_time=total_time,
            total_distance=total_distance,
            difficulty=route.get("difficulty", "easy"),
            is_active=route.get("is_active", 1),
        )
        session.add(new_route)
        await session.flush()

        routes_processed += 1

        # 3. 插入路线节点
        nodes = route.get("nodes", [])
        for node in nodes:
            # 处理 stay_time：JSON 中是字符串如 "15分钟"，模型中是 Integer（分钟）
            stay_time_str = node.get("stay_time", "")
            stay_time = parse_duration_minutes(stay_time_str) or 30

            new_node = RouteNode(
                route_id=route_id,
                spot_id=node["spot_id"],
                order=node["order"],
                stay_time=stay_time,
                description=node.get("description"),
            )
            session.add(new_node)
            nodes_inserted += 1

        await session.flush()

    return {
        "routes_processed": routes_processed,
        "nodes_inserted": nodes_inserted,
    }


async def main():
    """主入口函数。"""
    print("=" * 60)
    print("灵境智游 - 景点与路线数据初始化")
    print("=" * 60)

    # 检查数据文件是否存在
    if not SPOTS_JSON.exists():
        print(f"错误：找不到景点数据文件 {SPOTS_JSON}")
        sys.exit(1)
    if not ROUTES_JSON.exists():
        print(f"错误：找不到路线数据文件 {ROUTES_JSON}")
        sys.exit(1)

    # 加载数据
    print(f"\n加载景点数据: {SPOTS_JSON}")
    spots_data = await load_json(SPOTS_JSON)
    print(f"  共 {len(spots_data)} 个景点")

    print(f"\n加载路线数据: {ROUTES_JSON}")
    routes_data = await load_json(ROUTES_JSON)
    print(f"  共 {len(routes_data)} 条路线")

    # 创建数据库引擎和会话
    print(f"\n连接数据库: {DATABASE_URL.replace('://', '://***:***@')}")
    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        try:
            # 初始化景点
            print("\n[1/2] 初始化景点数据...")
            spot_stats = await init_spots(session, spots_data)
            print(f"  新增景点: {spot_stats['inserted']} 条")
            print(f"  更新景点: {spot_stats['updated']} 条")

            # 初始化路线
            print("\n[2/2] 初始化路线数据...")
            route_stats = await init_routes(session, routes_data)
            print(f"  路线数据: 处理 {route_stats['routes_processed']} 条路线")
            print(f"  路线节点: 插入 {route_stats['nodes_inserted']} 个节点")

            # 提交事务
            await session.commit()
            print("\n" + "=" * 60)
            print("数据初始化完成！")
            print("=" * 60)

        except Exception as e:
            await session.rollback()
            print(f"\n错误：数据初始化失败 - {e}")
            raise

    await engine.dispose()
    print("\n数据库连接已关闭。")


if __name__ == "__main__":
    asyncio.run(main())
