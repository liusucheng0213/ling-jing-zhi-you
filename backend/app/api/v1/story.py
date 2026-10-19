"""
RPG故事线API模块
提供故事线开始、推进、列表查询和用户进度查询功能
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.avatar_orchestrator import get_avatar_orchestrator, resolve_avatar_profile
from app.database import get_db
from app.models import StoryLine, UserStoryProgress
from app.schemas.story import (
    StoryLineItem,
    StoryProgressRequest,
    StoryProgressResponse,
    StoryStartRequest,
    UserStoryProgressItem,
)
from app.utils.jwt import get_current_user

router = APIRouter(tags=["故事线"])


# ==================== RPG故事引擎 ====================

AVATAR_NPC_NAMES = {
    "xuanzang": "风屿",
    "xiaowan": "雨桐",
    "lingxiaochan": "舒窈",
    "lingxiaoshan": "舒窈",
    "wuchanshi": "明朗",
    "zhaopuchu": "明泽",
}

AVATAR_CULTURE_NOTES = {
    "xuanzang": "风屿使用聆飞哲音色，把西行故事与祥符禅寺、灵山大佛的现场线索联系起来，并区分历史传说与可核实景观。",
    "xiaowan": "雨桐使用聆小玥音色，引导你观察建筑光影、取景层次和江南审美，把体验转化成可记录的旅行记忆。",
    "lingxiaochan": "舒窈使用聆小璇音色，以轻松方式解释佛教文化符号，适合亲子游客边看边问、边走边体验。",
    "lingxiaoshan": "舒窈使用聆小璇音色，以轻松方式解释佛教文化符号，适合亲子游客边看边问、边走边体验。",
    "wuchanshi": "明朗使用明哥音色，提示礼仪、停留节奏和现场观察重点，帮助游客稳重清晰地理解文化空间。",
    "zhaopuchu": "明泽使用明哥音色，从建筑、工艺与现代佛教文化交流角度串联灵山梵宫、坛城和博览空间。",
}

def _progress_percent(completed_nodes: list[str], total_nodes: int) -> int:
    """按已完成节点计算故事进度，当前节点未完成时不计入。"""

    if total_nodes <= 0:
        return 0
    return min(100, int((len(completed_nodes) / total_nodes) * 100))


def _append_completed_node(completed_nodes: list[str] | None, node_id: str) -> list[str]:
    """记录已完成节点并去重，保留原有顺序。"""

    completed = list(completed_nodes or [])
    if node_id not in completed:
        completed.append(node_id)
    return completed


def _build_story_display_fields(
    storyline: StoryLine,
    node: dict | None,
    is_completed: bool,
) -> dict:
    """根据故事线和当前节点生成详情页展示字段。"""

    choices = node.get("choices", []) if node else []
    avatar_name = AVATAR_NPC_NAMES.get(storyline.avatar_code, "数字人")
    node_title = node.get("title", "当前章节") if node else "当前章节"
    node_description = node.get("description", "") if node else ""

    if is_completed:
        task = f"故事已完成，可领取「{storyline.reward_badge or '灵山故事徽章'}」。"
        action_label = "返回故事列表"
    elif choices:
        labels = "、".join(str(choice.get("label", "继续")) for choice in choices[:3])
        task = f"请选择下一步行动：{labels}。"
        action_label = "选择下一步"
    else:
        task = "完成当前节点后继续推进剧情。"
        action_label = "继续剧情"

    culture_note = (
        node.get("culture_note") if node else None
    ) or AVATAR_CULTURE_NOTES.get(
        storyline.avatar_code,
        f"「{node_title}」关联景区文化线索，建议结合当前位置观察建筑、仪式和故事细节。",
    )
    narration = (node.get("narration") if node else None) or node_description or "请跟随线索继续探索。"

    return {
        "npc_line": f"{avatar_name}讲述：{narration}",
        "task": task,
        "culture_note": culture_note,
        "action_label": action_label,
        "narrator_name": avatar_name,
        "narration_text": f"{node_title}。{narration} {culture_note}",
    }


async def _story_progress_response(
    storyline: StoryLine,
    node: dict | None,
    current_node_id: str,
    completed_nodes: list[str],
    is_completed: bool,
    unlocked_hidden: bool,
    progress_percent: int,
    db: AsyncSession,
    choice_result: str | None = None,
) -> StoryProgressResponse:
    """统一组装故事进度响应，避免 start/progress 分支字段不一致。"""

    display_fields = _build_story_display_fields(storyline, node, is_completed)
    narration_text = display_fields["narration_text"]
    if choice_result:
        narration_text = f"{choice_result} {narration_text}"
        display_fields["narration_text"] = narration_text

    digital_human = None
    try:
        profile = resolve_avatar_profile(storyline.avatar_code)
        digital_human = await get_avatar_orchestrator().render_reply(
            text=narration_text,
            avatar_name=profile.code,
            emotion="friendly",
            session_id=f"story-{storyline.id}-{current_node_id}",
            audio_url="",
            intent="story_narration",
            prefer_video=True,
            db_session=db,
        )
    except Exception as exc:
        logger.error(f"故事节点数字人配置生成失败: storyline={storyline.id}, node={current_node_id}, error={exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="故事数字人主链路暂不可用，请检查讯飞 WebSDK 配置",
        ) from exc

    return StoryProgressResponse(
        storyline_id=storyline.id,
        title=storyline.title,
        avatar_code=storyline.avatar_code,
        reward_badge=storyline.reward_badge,
        current_node=current_node_id,
        current_node_title=node.get("title") if node else None,
        current_node_description=node.get("description") if node else None,
        current_node_spot_id=node.get("spot_id") if node else None,
        completed_nodes=completed_nodes,
        is_completed=is_completed,
        unlocked_hidden=unlocked_hidden,
        choices=node.get("choices", []) if node and not is_completed else [],
        progress_percent=progress_percent,
        choice_result=choice_result,
        digital_human=digital_human,
        **display_fields,
    )


async def _get_story_nodes(storyline: StoryLine) -> List[dict]:
    """从数据库故事线的 plot_points 字段读取完整节点定义。"""
    plot_points = storyline.plot_points or []
    nodes = []
    for i, point in enumerate(plot_points):
        if isinstance(point, dict):
            nodes.append({
                "node_id": point.get("node_id", f"node_{i}"),
                "spot_id": point.get("spot_id"),
                "title": point.get("title", f"节点{i+1}"),
                "description": point.get("description", ""),
                "choices": point.get("choices", []),
                "is_hidden": point.get("is_hidden", False),
                "narration": point.get("narration"),
                "culture_note": point.get("culture_note"),
            })
    return nodes


async def _get_next_node(
    storyline: StoryLine,
    current_node_id: str,
    choice: Optional[str] = None,
) -> Optional[dict]:
    """根据数据库故事图和游客选择获取下一个节点。"""
    nodes = await _get_story_nodes(storyline)
    node_map = {n["node_id"]: n for n in nodes}

    current = node_map.get(current_node_id)
    if not current:
        return None

    # 如果有选择，根据选择跳转
    if choice:
        choices = current.get("choices", [])
        for c in choices:
            if c.get("value") == choice:
                next_id = c.get("next_node")
                return node_map.get(next_id)

    # 默认顺序推进
    node_ids = list(node_map.keys())
    try:
        idx = node_ids.index(current_node_id)
        if idx + 1 < len(node_ids):
            return node_map[node_ids[idx + 1]]
    except ValueError:
        pass

    return None


# ==================== API端点 ====================

@router.post("/story/start", response_model=StoryProgressResponse, summary="开始故事线")
async def start_story(
    request: StoryStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    开始一条故事线

    为用户创建故事进度记录，返回第一个节点的内容。
    """
    # 查询故事线
    result = await db.execute(
        select(StoryLine).where(StoryLine.id == request.storyline_id)
    )
    storyline = result.scalar_one_or_none()

    if not storyline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故事线不存在",
        )

    if not storyline.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该故事线当前不可用",
        )

    # 确定用户ID
    user_id = request.user_id
    if current_user and not user_id:
        user_id = UUID(current_user["user_id"])

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="需要提供用户ID",
        )

    # 检查是否已有进度
    result = await db.execute(
        select(UserStoryProgress).where(
            UserStoryProgress.user_id == user_id,
            UserStoryProgress.storyline_id == request.storyline_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing and not existing.is_completed:
        # 继续已有进度
        nodes = await _get_story_nodes(storyline)
        node_map = {n["node_id"]: n for n in nodes}
        current = node_map.get(existing.current_node)
        if not current:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="故事进度引用了不存在的节点，请管理员修复故事数据",
            )

        total_nodes = len(nodes)
        progress_percent = _progress_percent(existing.completed_nodes or [], total_nodes)

        return await _story_progress_response(
            storyline=storyline,
            node=current,
            current_node_id=existing.current_node,
            completed_nodes=existing.completed_nodes or [],
            is_completed=existing.is_completed,
            unlocked_hidden=existing.unlocked_hidden,
            progress_percent=progress_percent,
            db=db,
        )

    # 创建新进度
    if existing and existing.is_completed:
        # 已完成的可以重新开始
        await db.delete(existing)
        await db.flush()

    nodes = await _get_story_nodes(storyline)
    if not nodes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="该故事线尚未配置可用节点",
        )
    first_node = nodes[0]

    progress = UserStoryProgress(
        user_id=user_id,
        storyline_id=request.storyline_id,
        current_node=first_node["node_id"],
        completed_nodes=[],
        is_completed=False,
        unlocked_hidden=False,
    )
    db.add(progress)
    await db.commit()

    return await _story_progress_response(
        storyline=storyline,
        node=first_node,
        current_node_id=first_node["node_id"],
        completed_nodes=[],
        is_completed=False,
        unlocked_hidden=False,
        progress_percent=0,
        db=db,
    )


@router.post("/story/progress", response_model=StoryProgressResponse, summary="推进故事")
async def progress_story(
    request: StoryProgressRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    推进故事线到下一个节点

    根据用户的选择或动作，推进故事进度。
    """
    # 确定用户ID
    user_id = request.user_id
    if current_user and not user_id:
        user_id = UUID(current_user["user_id"])

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="需要提供用户ID",
        )

    # 查询用户进度
    result = await db.execute(
        select(UserStoryProgress).where(
            UserStoryProgress.user_id == user_id,
            UserStoryProgress.storyline_id == request.storyline_id,
        )
    )
    progress = result.scalar_one_or_none()

    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到该故事线的进度记录，请先调用开始接口",
        )

    if progress.is_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该故事线已完成",
        )

    # 查询故事线
    result = await db.execute(
        select(StoryLine).where(StoryLine.id == request.storyline_id)
    )
    storyline = result.scalar_one_or_none()

    if not storyline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故事线不存在",
        )

    # 获取当前节点和下一个节点
    nodes = await _get_story_nodes(storyline)
    node_map = {n["node_id"]: n for n in nodes}

    current_node = node_map.get(progress.current_node)
    if not current_node:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="故事节点数据异常",
        )

    choices = current_node.get("choices", [])
    selected_choice = None
    if choices:
        if not request.choice:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="当前节点需要选择一个有效选项",
            )
        selected_choice = next(
            (item for item in choices if item.get("value") == request.choice),
            None,
        )
        if not selected_choice:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="所选故事选项不存在",
            )
        next_node_id = selected_choice.get("next_node")
        if next_node_id not in node_map:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="故事选项引用了不存在的下一节点",
            )
    elif request.choice:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="当前节点没有可选分支",
        )

    # 记录已完成节点
    completed = _append_completed_node(progress.completed_nodes, progress.current_node)

    # 推进到下一个节点
    next_node = await _get_next_node(storyline, progress.current_node, request.choice)

    if next_node:
        progress.current_node = next_node["node_id"]
        progress.completed_nodes = completed

        # 检查是否触发隐藏剧情
        if next_node.get("is_hidden") and not progress.unlocked_hidden:
            progress.unlocked_hidden = True

        await db.commit()

        total_nodes = len(nodes)
        progress_percent = _progress_percent(completed, total_nodes)

        choice_result = None
        if selected_choice:
            choice_result = selected_choice.get("feedback") or f"你选择了“{selected_choice.get('label', '继续探索')}”。"

        return await _story_progress_response(
            storyline=storyline,
            node=next_node,
            current_node_id=next_node["node_id"],
            completed_nodes=completed,
            is_completed=False,
            unlocked_hidden=progress.unlocked_hidden,
            progress_percent=progress_percent,
            db=db,
            choice_result=choice_result,
        )
    else:
        # 没有下一个节点，故事完成
        progress.is_completed = True
        progress.completed_nodes = completed
        progress.completed_at = datetime.now()
        await db.commit()

        return await _story_progress_response(
            storyline=storyline,
            node=current_node,
            current_node_id=progress.current_node,
            completed_nodes=completed,
            is_completed=True,
            unlocked_hidden=progress.unlocked_hidden,
            progress_percent=100,
            db=db,
            choice_result="本段探索已经完成。",
        )


@router.get("/story/list", response_model=List[StoryLineItem], summary="获取故事线列表")
async def get_story_list(
    avatar_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    获取可用的故事线列表

    可按数字人角色筛选。
    """
    query = select(StoryLine).where(StoryLine.is_active == True)

    if avatar_code:
        query = query.where(StoryLine.avatar_code == avatar_code)

    query = query.order_by(StoryLine.sort_order)

    result = await db.execute(query)
    storylines = result.scalars().all()

    return [
        StoryLineItem(
            id=s.id,
            avatar_code=s.avatar_code,
            title=s.title,
            description=s.description,
            reward_badge=s.reward_badge,
            reward_creative_type=s.reward_creative_type,
            is_active=s.is_active,
            sort_order=s.sort_order,
        )
        for s in storylines
    ]


@router.get("/story/progress/{user_id}", response_model=List[UserStoryProgressItem], summary="获取用户进度")
async def get_user_story_progress(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定用户的所有故事线进度

    参数:
        user_id: 用户ID
    """
    result = await db.execute(
        select(UserStoryProgress, StoryLine)
        .join(StoryLine, UserStoryProgress.storyline_id == StoryLine.id)
        .where(UserStoryProgress.user_id == user_id)
        .order_by(desc(UserStoryProgress.unlocked_at))
    )
    rows = result.all()

    items = []
    for progress, storyline in rows:
        nodes = storyline.plot_points or []
        total_nodes = len(nodes)
        # 已完成的故事按 100% 返回：可选隐藏节点未触发时不应拉低完成度
        progress_percent = (
            100
            if progress.is_completed
            else _progress_percent(progress.completed_nodes or [], total_nodes)
        )

        items.append(
            UserStoryProgressItem(
                storyline_id=storyline.id,
                title=storyline.title,
                avatar_code=storyline.avatar_code,
                current_node=progress.current_node,
                is_completed=progress.is_completed,
                progress_percent=progress_percent,
                unlocked_hidden=progress.unlocked_hidden,
                completed_at=progress.completed_at,
            )
        )

    return items
