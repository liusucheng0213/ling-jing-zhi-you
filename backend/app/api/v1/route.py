"""
路线相关API模块
提供推荐路线查询、路线详情和基于兴趣的路线推荐功能
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import BehaviorLog, Route, RouteNode, Spot
from app.schemas.route import (
    DynamicRoutePlan,
    DynamicRoutePlanNode,
    RouteBranchNode,
    RouteInterestProfileRequest,
    RouteInterestProfileResponse,
    RouteJourneyEventRequest,
    RouteJourneyEventResponse,
    RoutePlanRequest,
    RouteDetailResponse,
    RouteListItem,
    RouteNodeInfo,
    RouteRecommendRequest,
)

router = APIRouter(tags=["路线"])

ROUTE_TRANSITION_MINUTES = 10
CONSTRAINED_MAX_NODES = 3


INTEREST_LABELS = {
    "历史": "历史文化",
    "文化": "历史文化",
    "佛教": "佛教文化",
    "自然": "自然风光",
    "风光": "自然风光",
    "摄影": "摄影打卡",
    "亲子": "亲子游玩",
    "轻松": "轻松游览",
    "禅修": "禅修体验",
    "深度": "深度讲解",
    "美食": "美食探索",
}


def _normalized_route_metrics(route: Route) -> tuple[Optional[int], Optional[int]]:
    """兼容历史种子数据，将小时/公里误入库的小数值归一为分钟/米。"""

    total_time = route.total_time
    total_distance = route.total_distance
    if total_time is not None and 0 < total_time <= 12:
        total_time = total_time * 60
    if total_distance is not None and 0 < total_distance < 100:
        total_distance = total_distance * 1000
    return total_time, total_distance


def _route_personalization(
    route: Route,
    interests: list[str],
    score: int,
    recommend_mode: str,
    profile: dict | None = None,
) -> tuple[list[str], str, list[str], list[str], list[str]]:
    """生成路线推荐理由和讲解重点。"""

    route_tags = set(route.tags or [])
    matched = sorted(route_tags & set(interests))
    readable = [INTEREST_LABELS.get(item, item) for item in matched]
    if readable:
        reason = f"匹配您的{ '、'.join(readable[:3]) }偏好，适合按兴趣深度游览。"
    elif recommend_mode == "location":
        reason = "包含您当前所在景点，方便从当前位置开始游览。"
    elif recommend_mode == "default_hot":
        reason = "这条路线覆盖核心景点，适合第一次来灵山胜境轻松体验。"
    else:
        reason = "作为通用推荐路线，覆盖景区核心景点，适合首次游览。"

    focus = []
    for item in matched:
        if item in {"历史", "文化", "佛教", "深度"}:
            focus.append("历史典故与佛教文化")
        elif item in {"自然", "风光", "摄影"}:
            focus.append("自然风光与拍照点位")
        elif item in {"亲子", "轻松"}:
            focus.append("轻松节奏与亲子互动")
        elif item in {"美食"}:
            focus.append("餐饮补给与休息安排")
        elif item in {"禅修"}:
            focus.append("禅修体验与静心空间")
    if not focus:
        focus = ["核心景点讲解", "游览动线提醒"]
    match_reasons = []
    avoid_reasons = []
    if readable:
        match_reasons.append(f"兴趣匹配：{'、'.join(readable[:3])}")
    if recommend_mode == "location":
        match_reasons.append("包含当前所在景点")
    total_time, _ = _normalized_route_metrics(route)
    if total_time:
        match_reasons.append(f"预计{total_time}分钟，便于控制游览节奏")
    if profile:
        if profile.get("accessibility_required"):
            if route.difficulty == "easy":
                match_reasons.append("低难度路线更适合无障碍/适老需求")
            else:
                avoid_reasons.append("路线难度较高，无障碍游客需现场确认")
        if profile.get("mobility") == "low" and route.difficulty != "easy":
            avoid_reasons.append("体力要求偏高，建议减少支线停留")
        if profile.get("companion_type") == "family":
            match_reasons.append("可结合亲子讲解和拍照点位")
    return matched, reason, list(dict.fromkeys(focus)), match_reasons, avoid_reasons


async def _load_session_interests(db: AsyncSession, session_id) -> list[str]:
    """读取最近一次对话识别出的兴趣画像。"""

    if not session_id:
        return []
    result = await db.execute(
        select(BehaviorLog)
        .where(BehaviorLog.session_id == session_id)
        .where(BehaviorLog.event_type == "interest_profile")
        .order_by(BehaviorLog.created_at.desc())
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if not log or not isinstance(log.event_data, dict):
        return []
    return list(log.event_data.get("interests") or [])


def _normalize_match_score(
    raw_score: int,
    matched_count: int,
    recommend_mode: str,
    has_interest: bool,
) -> int | None:
    """将内部推荐分转换为面向游客展示的匹配分。"""

    if recommend_mode == "default_hot" and not has_interest:
        return None

    if recommend_mode == "location":
        base = 82
    else:
        base = 78

    interest_bonus = min(matched_count, 4) * 4
    raw_bonus = min(max(raw_score, 0) // 10, 8)
    return min(96, max(base, base + interest_bonus + raw_bonus))


def _build_route_detail_guidance(
    route: Route,
    nodes: list[RouteNodeInfo],
) -> tuple[list[RouteBranchNode], list[str], list[str]]:
    """根据路线标签和节点生成可选支线、休息提示和游览提醒。"""

    tags = set(route.tags or [])
    spot_names = [node.spot_name for node in nodes if node.spot_name]
    first_spot = spot_names[0] if spot_names else None
    middle_spot = spot_names[len(spot_names) // 2] if spot_names else first_spot
    last_spot = spot_names[-1] if spot_names else first_spot

    branch_nodes: list[RouteBranchNode] = []
    if tags & {"摄影", "风光", "自然"}:
        branch_nodes.append(
            RouteBranchNode(
                title="留一段拍照支线",
                type="photo",
                description="光线合适时可在主线附近多停留一会儿，适合拍全景、合影和建筑细节。",
                near_spot=middle_spot,
                extra_time=15,
            )
        )
    if tags & {"历史", "文化", "佛教", "深度", "禅修"}:
        branch_nodes.append(
            RouteBranchNode(
                title="加一段文化细看",
                type="culture",
                description="如果时间充裕，建议跟随讲解多听一段典故，把主线从打卡变成深度理解。",
                near_spot=middle_spot or first_spot,
                extra_time=20,
            )
        )
    if tags & {"亲子", "轻松", "美食"} or route.difficulty == "easy":
        branch_nodes.append(
            RouteBranchNode(
                title="安排一次轻松休整",
                type="rest",
                description="可在中段减少连续步行，补水、如厕或让同行长者和孩子稍作休息。",
                near_spot=middle_spot,
                extra_time=10,
            )
        )
    if route.difficulty == "hard":
        branch_nodes.append(
            RouteBranchNode(
                title="体力不足时走短线",
                type="shortcut",
                description="若现场人流较多或体力下降，可跳过末段支线，优先完成主线核心景点。",
                near_spot=last_spot,
                extra_time=0,
            )
        )
    if not branch_nodes:
        branch_nodes.append(
            RouteBranchNode(
                title="中段弹性停留",
                type="rest",
                description="按现场体力决定是否在中段多停留，路线不需要把每个点都走满。",
                near_spot=middle_spot,
                extra_time=10,
            )
        )

    total_time, total_distance = _normalized_route_metrics(route)
    rest_tips = ["建议随身带水，主线中段预留一次休息。"]
    if total_time and total_time >= 180:
        rest_tips.append("路线时间较长，可把可选支线放到体力充足时再走。")
    if route.difficulty != "easy":
        rest_tips.append("部分路段步行强度较高，长者或儿童同行时建议放慢节奏。")
    if tags & {"美食"}:
        rest_tips.append("可把餐饮补给安排在中后段，避免刚入园就打断游览节奏。")

    route_notes = ["主线按顺序游览，可选支线按时间和体力取舍。"]
    if total_distance:
        route_notes.append(f"全程约{total_distance}米，现场以景区导视和人流管控为准。")
    route_notes.append("返程或折返点可在最后一个主线景点附近决定，不必强行走完整支线。")

    return branch_nodes[:3], list(dict.fromkeys(rest_tips)), list(dict.fromkeys(route_notes))


def _build_dynamic_route_plan(
    nodes: list[RouteNodeInfo],
    *,
    current_spot_id: str | None,
    visited_spots: list[str],
    skipped_spots: list[str] | None = None,
    duration: int | None,
    mobility: str | None,
    accessibility_required: bool,
) -> DynamicRoutePlan:
    """仅使用已核验路线节点，按游客约束生成本次游览计划。"""

    ordered_nodes = sorted(
        (node for node in nodes if node.spot_id and node.spot_name),
        key=lambda item: item.order,
    )
    visited = {item for item in visited_spots if item}
    skipped = {item for item in (skipped_spots or []) if item}
    excluded = visited | skipped
    reasons: list[str] = []

    removed_visited = sum(1 for node in ordered_nodes if node.spot_id in visited)
    removed_skipped = sum(1 for node in ordered_nodes if node.spot_id in skipped and node.spot_id not in visited)
    if removed_visited:
        reasons.append(f"已排除{removed_visited}个已游览景点。")
    if removed_skipped:
        reasons.append(f"已排除{removed_skipped}个主动跳过景点。")

    route_start_index = 0
    if current_spot_id:
        current_order_index = next(
            (index for index, node in enumerate(ordered_nodes) if node.spot_id == current_spot_id),
            None,
        )
        if current_order_index is not None:
            route_start_index = current_order_index + (1 if current_spot_id in excluded else 0)
            if current_spot_id in excluded:
                reasons.append("从当前已完成或已跳过景点之后继续，避免折返。")
            else:
                reasons.append(
                    f"从当前景点{ordered_nodes[current_order_index].spot_name}开始，并沿原路线后续顺序游览。"
                )
            if current_order_index > 0:
                reasons.append(f"为避免折返，省略当前景点之前的{current_order_index}个节点。")
        else:
            reasons.append("当前景点不在该路线的已核验节点中，未强行添加其他景点。")

    corridor_nodes = ordered_nodes[route_start_index:]
    candidate_nodes = [node for node in corridor_nodes if node.spot_id not in excluded]

    constrained = mobility == "low" or accessibility_required
    if constrained and len(candidate_nodes) > CONSTRAINED_MAX_NODES:
        candidate_nodes = candidate_nodes[:CONSTRAINED_MAX_NODES]
        constraint_text = "低体力和无障碍" if mobility == "low" and accessibility_required else (
            "低体力" if mobility == "low" else "无障碍"
        )
        reasons.append(
            f"根据{constraint_text}需求，将计划控制在{CONSTRAINED_MAX_NODES}个节点以内。"
        )

    requested_duration = duration if duration is not None and duration > 0 else None
    selected_nodes: list[DynamicRoutePlanNode] = []
    estimated_duration = 0
    duration_trimmed = False

    for node in candidate_nodes:
        transition_time = ROUTE_TRANSITION_MINUTES if selected_nodes else 0
        original_stay_time = max(1, int(node.stay_time or 30))
        planned_stay_time = original_stay_time

        if requested_duration is not None:
            remaining = requested_duration - estimated_duration - transition_time
            if remaining <= 0:
                duration_trimmed = True
                break
            planned_stay_time = min(original_stay_time, remaining)
            if planned_stay_time < original_stay_time:
                duration_trimmed = True

        selected_nodes.append(
            DynamicRoutePlanNode(
                id=node.id,
                spot_id=node.spot_id,
                spot_name=node.spot_name,
                original_order=node.order,
                planned_order=len(selected_nodes) + 1,
                stay_time=planned_stay_time,
                description=node.description,
                is_current=node.spot_id == current_spot_id,
            )
        )
        estimated_duration += transition_time + planned_stay_time
        if duration_trimmed:
            break

    if requested_duration is not None and len(selected_nodes) < len(candidate_nodes):
        duration_trimmed = True
    if duration_trimmed:
        reasons.append(f"按可用时长{requested_duration}分钟裁剪节点和停留时间。")
    if not selected_nodes:
        if ordered_nodes and not candidate_nodes and route_start_index > 0:
            reasons.append("当前位置之后已没有待游览节点，本次不再安排折返。")
        elif ordered_nodes and not candidate_nodes and excluded.issuperset(
            node.spot_id for node in ordered_nodes
        ):
            reasons.append("该路线节点均已游览或跳过，本次不再重复安排。")
        elif not ordered_nodes:
            reasons.append("该路线暂无可用的已核验景点节点。")
    elif len(selected_nodes) == len(ordered_nodes) and not reasons:
        reasons.append("沿用数据库中已核验的路线节点与游览顺序。")

    is_trimmed = len(selected_nodes) < len(ordered_nodes) or any(
        node.stay_time < next(
            max(1, int(original.stay_time or 30))
            for original in ordered_nodes
            if original.id == node.id
        )
        for node in selected_nodes
    )
    return DynamicRoutePlan(
        nodes=selected_nodes,
        estimated_duration=estimated_duration,
        requested_duration=requested_duration,
        is_trimmed=is_trimmed,
        reasons=list(dict.fromkeys(reasons)),
    )


@router.get("/routes", response_model=List[RouteListItem], summary="获取推荐路线列表")
async def get_routes(
    scenic_area: Optional[str] = Query(None, description="景区名称筛选"),
    difficulty: Optional[str] = Query(None, description="难度筛选: easy/medium/hard"),
    tag: Optional[str] = Query(None, description="标签筛选"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    获取推荐路线列表

    支持按景区、难度、标签等条件筛选。
    """
    # 构建查询
    query = select(Route).where(Route.is_active == 1)

    if difficulty:
        query = query.where(Route.difficulty == difficulty)

    if tag:
        query = query.where(Route.tags.contains([tag]))

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    routes = result.scalars().all()

    # 获取每个路线的节点数量
    route_items = []
    for route in routes:
        node_count_result = await db.execute(
            select(func.count(RouteNode.id)).where(RouteNode.route_id == route.id)
        )
        node_count = node_count_result.scalar() or 0

        total_time, total_distance = _normalized_route_metrics(route)
        route_items.append(
            RouteListItem(
                id=route.id,
                name=route.name,
                description=route.description,
                tags=route.tags or [],
                total_time=total_time,
                total_distance=total_distance,
                difficulty=route.difficulty,
                node_count=node_count,
                match_score=None,
                matched_interests=[],
                recommend_reason=None,
                explanation_focus=[],
                recommend_mode=None,
                match_reasons=[],
                avoid_reasons=[],
                next_best_spots=[],
                profile_snapshot={},
            )
        )

    return route_items


@router.get("/routes/{route_id}", response_model=RouteDetailResponse, summary="获取路线详情")
async def get_route_detail(
    route_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定路线的详细信息，包含所有节点

    参数:
        route_id: 路线ID
    """
    # 查询路线
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()

    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="路线不存在",
        )

    # 查询路线节点
    result = await db.execute(
        select(RouteNode, Spot)
        .outerjoin(Spot, RouteNode.spot_id == Spot.id)
        .where(RouteNode.route_id == route_id)
        .order_by(RouteNode.order)
    )
    node_rows = result.all()

    nodes = []
    for route_node, spot in node_rows:
        nodes.append(
            RouteNodeInfo(
                id=route_node.id,
                spot_id=route_node.spot_id,
                spot_name=spot.name if spot else None,
                order=route_node.order,
                stay_time=route_node.stay_time,
                description=route_node.description,
            )
        )

    total_time, total_distance = _normalized_route_metrics(route)
    branch_nodes, rest_tips, route_notes = _build_route_detail_guidance(route, nodes)
    return RouteDetailResponse(
        id=route.id,
        name=route.name,
        description=route.description,
        tags=route.tags or [],
        total_time=total_time,
        total_distance=total_distance,
        difficulty=route.difficulty,
        nodes=nodes,
        branch_nodes=branch_nodes,
        rest_tips=rest_tips,
        route_notes=route_notes,
        created_at=route.created_at,
    )


@router.post("/routes/recommend", response_model=List[RouteListItem], summary="基于兴趣推荐路线")
async def recommend_routes(
    request: RouteRecommendRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    基于用户兴趣标签推荐路线

    根据用户提供的兴趣标签、可用时长、难度偏好等条件智能推荐路线。
    """
    session_interests = await _load_session_interests(db, request.session_id)
    combined_interests = list(dict.fromkeys([*(request.interests or []), *session_interests]))
    has_interest = bool(combined_interests)
    profile_snapshot = {
        "interests": combined_interests,
        "duration": request.duration,
        "difficulty": request.difficulty,
        "spot_id": request.spot_id,
        "companion_type": request.companion_type,
        "mobility": request.mobility,
        "accessibility_required": request.accessibility_required,
        "preferred_style": request.preferred_style,
        "visited_spots": request.visited_spots,
        "skipped_spots": request.skipped_spots,
    }

    # 构建推荐查询
    query = select(Route).where(Route.is_active == 1)

    # 难度筛选
    if request.difficulty:
        query = query.where(Route.difficulty == request.difficulty)

    result = await db.execute(query)
    routes = result.scalars().all()

    verified_nodes_by_route: dict[UUID, list[RouteNodeInfo]] = {route.id: [] for route in routes}
    if routes:
        node_result = await db.execute(
            select(RouteNode, Spot)
            .join(Spot, RouteNode.spot_id == Spot.id)
            .where(RouteNode.route_id.in_([route.id for route in routes]))
            .where(Spot.is_active.is_(True))
            .order_by(RouteNode.route_id, RouteNode.order)
        )
        for route_node, spot in node_result.all():
            verified_nodes_by_route[route_node.route_id].append(
                RouteNodeInfo(
                    id=route_node.id,
                    spot_id=route_node.spot_id,
                    spot_name=spot.name,
                    order=route_node.order,
                    stay_time=max(1, int(route_node.stay_time or 30)),
                    description=route_node.description,
                )
            )

    # 基于兴趣标签计算匹配度并排序
    route_scores = []
    for route in routes:
        total_time, _ = _normalized_route_metrics(route)
        verified_nodes = verified_nodes_by_route.get(route.id, [])
        score = 0
        route_tags = set(route.tags or [])
        user_interests = set(combined_interests)

        # 标签匹配得分
        recommend_mode = "personalized" if has_interest else "default_hot"
        if route_tags and user_interests:
            match_count = len(route_tags & user_interests)
            score += match_count * 20
        elif not has_interest:
            if route.difficulty == "easy":
                score += 10
            if total_time and total_time <= 180:
                score += 8

        # 总时长只影响排序，超出预算的路线交由动态计划裁剪，不再直接丢弃。
        if request.duration and total_time:
            if total_time <= request.duration:
                score += 6
            else:
                score -= min(12, max(2, (total_time - request.duration) // 30 * 2))

        # 当前景点关联加分
        if request.spot_id:
            if any(node.spot_id == request.spot_id for node in verified_nodes):
                score += 20
                recommend_mode = "location" if not has_interest else "personalized"
        if request.accessibility_required and route.difficulty == "easy":
            score += 12
        if request.mobility == "low" and total_time and total_time <= 150:
            score += 10
        if request.companion_type == "family" and route_tags & {"亲子", "轻松", "摄影"}:
            score += 8
        if request.visited_spots:
            visited_count = sum(
                1 for node in verified_nodes if node.spot_id in set(request.visited_spots)
            )
            score -= visited_count * 6
        if request.skipped_spots:
            skipped_count = sum(
                1 for node in verified_nodes if node.spot_id in set(request.skipped_spots)
            )
            score -= skipped_count * 4

        route_scores.append((route, score, recommend_mode))

    # 按得分降序排列
    route_scores.sort(key=lambda x: x[1], reverse=True)

    # 构建响应
    route_items = []
    for route, score, recommend_mode in route_scores[:10]:  # 最多返回10条
        verified_nodes = verified_nodes_by_route.get(route.id, [])
        dynamic_plan = _build_dynamic_route_plan(
            verified_nodes,
            current_spot_id=request.spot_id,
            visited_spots=request.visited_spots,
            skipped_spots=request.skipped_spots,
            duration=request.duration,
            mobility=request.mobility,
            accessibility_required=request.accessibility_required,
        )
        node_count = len(verified_nodes)

        matched, reason, focus, match_reasons, avoid_reasons = _route_personalization(
            route,
            combined_interests,
            score,
            recommend_mode,
            profile_snapshot,
        )
        display_score = _normalize_match_score(
            raw_score=score,
            matched_count=len(matched),
            recommend_mode=recommend_mode,
            has_interest=has_interest,
        )
        next_best_spots = [node.spot_name for node in dynamic_plan.nodes[:3]]
        total_time, total_distance = _normalized_route_metrics(route)
        route_items.append(
            RouteListItem(
                id=route.id,
                name=route.name,
                description=route.description,
                tags=route.tags or [],
                total_time=total_time,
                total_distance=total_distance,
                difficulty=route.difficulty,
                node_count=node_count,
                match_score=display_score,
                matched_interests=matched,
                recommend_reason=reason,
                explanation_focus=focus,
                recommend_mode=recommend_mode,
                match_reasons=match_reasons,
                avoid_reasons=avoid_reasons,
                next_best_spots=next_best_spots,
                profile_snapshot=profile_snapshot,
                dynamic_plan=dynamic_plan,
            )
        )

    return route_items


@router.post(
    "/routes/{route_id}/plan",
    response_model=DynamicRoutePlan,
    summary="生成指定路线的实时行程计划",
)
async def build_route_plan(
    route_id: UUID,
    request: RoutePlanRequest,
    db: AsyncSession = Depends(get_db),
):
    """按当前点位、已游节点、剩余时间和体力重新编排行程。"""

    route = await db.scalar(
        select(Route).where(Route.id == route_id).where(Route.is_active == 1)
    )
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="路线不存在或已停用")

    node_result = await db.execute(
        select(RouteNode, Spot)
        .join(Spot, RouteNode.spot_id == Spot.id)
        .where(RouteNode.route_id == route_id)
        .where(Spot.is_active.is_(True))
        .order_by(RouteNode.order)
    )
    nodes = [
        RouteNodeInfo(
            id=route_node.id,
            spot_id=route_node.spot_id,
            spot_name=spot.name,
            order=route_node.order,
            stay_time=max(1, int(route_node.stay_time or 30)),
            description=route_node.description,
        )
        for route_node, spot in node_result.all()
    ]
    return _build_dynamic_route_plan(
        nodes,
        current_spot_id=request.spot_id,
        visited_spots=request.visited_spots,
        skipped_spots=request.skipped_spots,
        duration=request.duration,
        mobility=request.mobility,
        accessibility_required=request.accessibility_required,
    )


@router.post(
    "/routes/journey-events",
    response_model=RouteJourneyEventResponse,
    summary="记录实时行程事件",
)
async def record_route_journey_event(
    request: RouteJourneyEventRequest,
    db: AsyncSession = Depends(get_db),
):
    """记录开始、到站、完成、跳过、重规划和结束等行程节点。"""

    route = await db.scalar(select(Route).where(Route.id == request.route_id))
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="路线不存在")

    event = BehaviorLog(
        session_id=request.session_id,
        event_type=f"route_journey_{request.event_type}",
        event_data={
            "journey_id": request.journey_id,
            "route_id": str(request.route_id),
            "route_name": route.name,
            "progress_percent": request.progress_percent,
            "visited_spots": request.visited_spots,
            "skipped_spots": request.skipped_spots,
            "estimated_remaining_minutes": request.estimated_remaining_minutes,
            "details": request.details,
        },
        spot_id=request.spot_id,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return RouteJourneyEventResponse(
        recorded=True,
        event_id=event.id,
        created_at=event.created_at,
    )


@router.post("/routes/interests", response_model=RouteInterestProfileResponse, summary="保存游客兴趣画像")
async def save_route_interests(
    request: RouteInterestProfileRequest,
    db: AsyncSession = Depends(get_db),
):
    """保存游客显式填写的兴趣画像，用于后续路线推荐和路线讲解。"""

    interests = list(dict.fromkeys([item for item in request.interests if item]))
    if request.session_id:
        db.add(
            BehaviorLog(
                session_id=request.session_id,
                event_type="interest_profile",
                event_data={
                "interests": interests,
                "source": request.source or "profile",
                "evidence_text": "游客在路线偏好引导中显式选择",
                "companion_type": request.companion_type,
                "duration": request.duration,
                "mobility": request.mobility,
                "accessibility_required": request.accessibility_required,
                "preferred_style": request.preferred_style,
                "visited_spots": request.visited_spots,
            },
            )
        )
        await db.commit()
    return RouteInterestProfileResponse(
        session_id=request.session_id,
        interests=interests,
        source=request.source or "profile",
        updated=True,
    )
