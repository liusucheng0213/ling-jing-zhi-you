"""
文创生成API模块
提供纪念诗词生成、明信片生成和用户文创列表查询功能
"""

import base64
import binascii
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import BehaviorLog, CreativeContent, Spot
from app.schemas.creative import (
    CommunityAuthorProfileResponse,
    CommunityComment,
    CommunityCommentCreateRequest,
    CommunityFeedResponse,
    CommunityPostCreateRequest,
    CommunityPostResponse,
    CommunityReportRequest,
    CreativeGenerateResponse,
    CreativeItem,
    CreativeListResponse,
    JournalGenerateRequest,
    JournalPolishRequest,
    JournalPolishResponse,
    PhotoTipsResponse,
    PoemGenerateRequest,
    PostcardGenerateRequest,
    VisionAnalyzeRequest,
    VisionAnalyzeResponse,
)
from app.utils.jwt import get_current_user

router = APIRouter(tags=["文创"])


# ==================== AI文创生成引擎 ====================

_creative_engine = None
DEFAULT_NICKNAME = "游客"

SHOWCASE_NOISE_TERMS = ("测试", "检查", "回归", "接口")
COMMUNITY_IMAGE_DIR = Path(__file__).resolve().parents[2] / "static" / "community-images"
COMMUNITY_IMAGE_TYPES = {
    "data:image/jpeg;base64": ("jpg", b"\xff\xd8\xff"),
    "data:image/png;base64": ("png", b"\x89PNG\r\n\x1a\n"),
    "data:image/webp;base64": ("webp", b"RIFF"),
}
MAX_COMMUNITY_IMAGE_BYTES = 3_000_000


def _is_showcase_noise(item: CreativeContent) -> bool:
    """过滤开发期产生的回归帖子，避免污染游客社区信息流。"""

    metadata = item.meta_info or {}
    demo_seed = metadata.get("demo_seed")
    if isinstance(demo_seed, str) and demo_seed.startswith("dashboard-demo"):
        return True
    text = " ".join(
        str(value or "")
        for value in (item.title, item.content, metadata.get("nickname"))
    )
    return any(term in text for term in SHOWCASE_NOISE_TERMS)
DEFAULT_AVATAR_URL = "/assets/avatars/default-user.webp"


def _save_community_images(data_urls: list[str]) -> list[str]:
    """校验并保存游客发布图片，拒绝伪造扩展名和超大载荷。"""

    decoded_images: list[tuple[str, bytes]] = []
    for value in data_urls[:3]:
        try:
            header, encoded = value.split(",", 1)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="社区图片格式无效") from exc
        image_type = COMMUNITY_IMAGE_TYPES.get(header.lower())
        if not image_type:
            raise HTTPException(status_code=422, detail="仅支持 JPEG、PNG 或 WebP 图片")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=422, detail="社区图片编码无效") from exc
        extension, signature = image_type
        if not image_bytes.startswith(signature):
            raise HTTPException(status_code=422, detail="社区图片内容与声明类型不一致")
        if extension == "webp" and image_bytes[8:12] != b"WEBP":
            raise HTTPException(status_code=422, detail="WebP 图片签名无效")
        if len(image_bytes) > MAX_COMMUNITY_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="单张社区图片不能超过 3MB")
        decoded_images.append((extension, image_bytes))

    COMMUNITY_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    urls: list[str] = []
    for extension, image_bytes in decoded_images:
        filename = f"{uuid.uuid4()}.{extension}"
        (COMMUNITY_IMAGE_DIR / filename).write_bytes(image_bytes)
        urls.append(f"/api/v1/community-images/{filename}")
    return urls


def _delete_community_images(image_urls: list[str]) -> None:
    """数据库写入失败时删除本次已保存文件，避免产生孤立附件。"""

    root = COMMUNITY_IMAGE_DIR.resolve()
    for url in image_urls:
        path = (root / Path(url).name).resolve()
        if path.parent == root and path.exists():
            path.unlink()


def _get_creative_engine():
    """获取文创引擎单例（延迟导入）"""
    global _creative_engine
    if _creative_engine is None:
        from app.core.creative_engine import CreativeEngine
        _creative_engine = CreativeEngine()
    return _creative_engine


def _current_user_id(current_user: Optional[dict]) -> UUID:
    """获取当前用户ID，游客模式使用临时ID写入文创内容。"""

    user_id = current_user.get("user_id") if current_user else None
    return UUID(user_id) if user_id else uuid.uuid4()


def _user_snapshot(
    current_user: Optional[dict],
    nickname: str | None = None,
    avatar_url: str | None = None,
    bio: str | None = None,
) -> dict:
    """生成社区展示用的用户快照。"""

    return {
        "nickname": nickname or (current_user or {}).get("username") or DEFAULT_NICKNAME,
        "avatar_url": avatar_url or DEFAULT_AVATAR_URL,
        "bio": (bio or "").strip()[:80],
    }


def _post_response(item: CreativeContent) -> CommunityPostResponse:
    """将文创内容转换为社区帖子响应。"""

    metadata = item.meta_info or {}
    comments = [
        CommunityComment(
            id=str(comment.get("id") or uuid.uuid4()),
            nickname=comment.get("nickname") or DEFAULT_NICKNAME,
            avatar_url=comment.get("avatar_url") or DEFAULT_AVATAR_URL,
            content=str(comment.get("content") or "")[:160],
            created_at=comment.get("created_at") or item.created_at,
        )
        for comment in list(metadata.get("comments") or [])[-30:]
        if comment.get("content")
    ]
    return CommunityPostResponse(
        id=item.id,
        title=item.title or "灵山游记",
        content=item.content,
        nickname=metadata.get("nickname") or DEFAULT_NICKNAME,
        avatar_url=metadata.get("avatar_url") or DEFAULT_AVATAR_URL,
        bio=metadata.get("bio") or "",
        image_names=list(metadata.get("image_names") or []),
        image_urls=list(metadata.get("image_urls") or []),
        like_count=int(metadata.get("like_count") or 0),
        comment_count=int(metadata.get("comment_count") or 0),
        favorite_count=int(metadata.get("favorite_count") or 0),
        is_liked=bool(metadata.get("is_liked") or False),
        is_favorited=bool(metadata.get("is_favorited") or False),
        is_followed=bool(metadata.get("is_followed") or False),
        is_hidden=bool(metadata.get("is_hidden") or False),
        visibility=metadata.get("visibility") or "public",
        report_count=int(metadata.get("report_count") or 0),
        follower_count=int(metadata.get("follower_count") or 0),
        comments=comments,
        created_at=item.created_at,
    )


async def _get_community_post(db: AsyncSession, post_id: UUID) -> CreativeContent:
    """读取社区帖子。"""

    result = await db.execute(
        select(CreativeContent).where(
            CreativeContent.id == post_id,
            CreativeContent.content_type == "community_post",
        )
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="社区游记不存在")
    return post


async def _polish_journal_text(title: str | None, content: str, spots: list[str]) -> JournalPolishResponse:
    """调用文本主链路润色游记；主链路不可用时明确报错。"""

    spots_text = "、".join(spots) if spots else "灵山胜境"
    clean_title = (title or "").strip() or f"{spots_text}游记"
    clean_content = content.strip()
    try:
        from app.core.llm_router import llm_router

        messages = [
            {
                "role": "system",
                "content": (
                    "你是景区社区游记编辑。请在保留游客真实感受的基础上润色文字，"
                    "不要编造未提到的经历，不要加入图片已上传等表述。返回JSON，"
                    "字段为title和content，content控制在180字以内。"
                ),
            },
            {
                "role": "user",
                "content": f"景点：{spots_text}\n标题：{clean_title}\n正文：{clean_content}",
            },
        ]
        polished = await llm_router.chat(
            messages=messages,
            temperature=0.65,
            thinking={"type": "disabled"},
        )
        import json

        parsed = json.loads(polished.strip())
        return JournalPolishResponse(
            title=(parsed.get("title") or clean_title).strip()[:80],
            content=(parsed.get("content") or clean_content).strip(),
        )
    except Exception as exc:
        raise RuntimeError("游记润色失败：LLM 主链路不可用") from exc


# ==================== API端点 ====================

@router.post("/creative/poem", response_model=CreativeGenerateResponse, summary="生成纪念诗词")
async def generate_poem(
    request: PoemGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    生成AI纪念诗词

    基于景点信息、主题和用户感悟，生成个性化的纪念诗词。
    支持古典和现代两种风格。
    """
    # 查询景点名称
    spot_name = None
    if request.spot_id:
        result = await db.execute(
            select(Spot).where(Spot.id == request.spot_id)
        )
        spot = result.scalar_one_or_none()
        if spot:
            spot_name = spot.name

    # 调用文创引擎生成诗词
    engine = _get_creative_engine()
    user_name = current_user.get("username") if current_user else "游客"
    spots = [spot_name] if spot_name else ["灵山胜境"]
    try:
        poem_data = await engine.generate_poem(
            user_name=user_name,
            spots=spots,
            story=request.user_input,
            style=request.style or "古典",
            theme=request.theme,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # 保存到数据库
    creative = CreativeContent(
        user_id=_current_user_id(current_user),
        content_type="poem",
        title=poem_data["title"],
        content=poem_data["content"],
        meta_info={
            "style": request.style or "古典",
            "spots": poem_data.get("spots") or spots,
            "theme": request.theme,
            "user_input": request.user_input,
        },
    )
    db.add(creative)
    await db.commit()
    await db.refresh(creative)

    return CreativeGenerateResponse(
        id=creative.id,
        content_type="poem",
        title=creative.title,
        content=creative.content,
        metadata=creative.meta_info or {},
    )


@router.post("/creative/postcard", response_model=CreativeGenerateResponse, summary="生成明信片")
async def generate_postcard(
    request: PostcardGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    生成AI明信片

    基于景点信息和用户留言，生成个性化明信片。
    支持多种模板风格。
    """
    # 查询景点名称
    spot_name = None
    if request.spot_id:
        result = await db.execute(
            select(Spot).where(Spot.id == request.spot_id)
        )
        spot = result.scalar_one_or_none()
        if spot:
            spot_name = spot.name

    # 调用文创引擎生成明信片
    engine = _get_creative_engine()
    user_name = current_user.get("username") if current_user else "游客"
    try:
        postcard_data = await engine.generate_postcard(
            user_name=user_name,
            spot=spot_name or "灵山胜境",
            quote=request.message,
            template=request.template or "classic",
            image_context=request.image_context,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # 保存到数据库
    metadata = {
        "template": request.template or "classic",
        "spot": spot_name,
        "include_photo": request.include_photo,
    }
    if request.image_context and request.image_context.strip():
        metadata["image_context"] = request.image_context.strip()

    creative = CreativeContent(
        user_id=_current_user_id(current_user),
        content_type="postcard",
        title=postcard_data["title"],
        content=postcard_data["content"],
        meta_info=metadata,
    )
    db.add(creative)
    await db.commit()
    await db.refresh(creative)

    return CreativeGenerateResponse(
        id=creative.id,
        content_type="postcard",
        title=creative.title,
        content=creative.content,
        metadata=creative.meta_info or {},
    )


@router.post("/creative/journal", response_model=CreativeGenerateResponse, summary="生成AI游记")
async def generate_journal(
    request: JournalGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """
    生成AI游记

    基于游览景点和情感记录，生成个性化的游记摘要。
    """
    engine = _get_creative_engine()
    try:
        journal_data = await engine.generate_travel_journal(
            spots=request.spots,
            emotions=request.emotions,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    # 保存到数据库
    creative = CreativeContent(
        user_id=_current_user_id(current_user),
        content_type="journal",
        title=journal_data["title"],
        content=journal_data["content"],
        meta_info={
            "spots": request.spots,
            "emotions": request.emotions,
            "user_input": request.user_input,
        },
    )
    db.add(creative)
    await db.commit()
    await db.refresh(creative)

    return CreativeGenerateResponse(
        id=creative.id,
        content_type="journal",
        title=creative.title,
        content=creative.content,
        metadata=creative.meta_info or {},
    )


@router.post("/creative/journal/polish", response_model=JournalPolishResponse, summary="AI润色社区游记")
async def polish_journal(
    request: JournalPolishRequest,
):
    """润色游客准备发布到社区的游记。"""

    try:
        return await _polish_journal_text(request.title, request.content, request.spots)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/creative/community/posts", response_model=CommunityPostResponse, summary="发布社区游记")
async def create_community_post(
    request: CommunityPostCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """发布社区游记，并持久化经过校验和压缩的图片。"""

    snapshot = _user_snapshot(current_user, request.nickname, request.avatar_url, request.bio)
    image_names = [name for name in request.image_names if name][:3]
    image_urls = _save_community_images(request.image_data_urls)
    if len(image_names) != len(image_urls):
        image_names = image_names[:len(image_urls)]
    post = CreativeContent(
        user_id=_current_user_id(current_user),
        content_type="community_post",
        title=request.title.strip(),
        content=request.content.strip(),
        meta_info={
            **snapshot,
            "spots": request.spots,
            "image_names": image_names,
            "image_urls": image_urls,
            "like_count": 0,
            "comment_count": 0,
            "favorite_count": 0,
            "is_liked": False,
            "visibility": request.visibility,
            "is_hidden": False,
            "report_count": 0,
            "image_upload_status": "stored",
        },
        is_shared=True,
        shared_at=datetime.utcnow(),
    )
    try:
        db.add(post)
        await db.commit()
        await db.refresh(post)
    except Exception:
        await db.rollback()
        _delete_community_images(image_urls)
        raise
    return _post_response(post)


@router.get("/creative/community/feed", response_model=CommunityFeedResponse, summary="获取社区信息流")
async def get_community_feed(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """按发布时间倒序获取社区游记。"""

    limit = min(max(limit, 1), 50)
    offset = max(offset, 0)
    query = (
        select(CreativeContent)
        .where(CreativeContent.content_type == "community_post")
        .where(CreativeContent.is_shared == True)
        .order_by(desc(CreativeContent.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    raw_items = result.scalars().all()
    items = [
        item for item in raw_items
        if not (item.meta_info or {}).get("is_hidden")
        and (item.meta_info or {}).get("visibility", "public") == "public"
        and not _is_showcase_noise(item)
    ]

    count_result = await db.execute(
        select(CreativeContent)
        .where(CreativeContent.content_type == "community_post")
        .where(CreativeContent.is_shared == True)
    )
    visible_total = [
        item for item in count_result.scalars().all()
        if not (item.meta_info or {}).get("is_hidden")
        and (item.meta_info or {}).get("visibility", "public") == "public"
        and not _is_showcase_noise(item)
    ]
    total = len(visible_total)
    return CommunityFeedResponse(items=[_post_response(item) for item in items], total=total)


@router.get(
    "/creative/community/authors/{nickname}",
    response_model=CommunityAuthorProfileResponse,
    summary="获取社区作者资料快照",
)
async def get_community_author_profile(
    nickname: str,
    db: AsyncSession = Depends(get_db),
):
    """基于公开社区帖子返回作者快照，不引入独立用户资料表。"""

    clean_nickname = nickname.strip()[:40] or DEFAULT_NICKNAME
    result = await db.execute(
        select(CreativeContent)
        .where(CreativeContent.content_type == "community_post")
        .where(CreativeContent.is_shared == True)
        .order_by(desc(CreativeContent.created_at))
    )
    author_items = []
    for item in result.scalars().all():
        metadata = item.meta_info or {}
        if metadata.get("nickname") != clean_nickname:
            continue
        if metadata.get("is_hidden"):
            continue
        if metadata.get("visibility", "public") != "public":
            continue
        author_items.append(item)

    latest = (author_items[0].meta_info or {}) if author_items else {}
    posts = [_post_response(item) for item in author_items[:20]]
    return CommunityAuthorProfileResponse(
        nickname=clean_nickname,
        avatar_url=latest.get("avatar_url") or DEFAULT_AVATAR_URL,
        bio=latest.get("bio") or "这位游客还没有留下自我介绍。",
        visibility=latest.get("visibility") or "public",
        is_followed=bool(latest.get("is_followed") or False),
        follower_count=max((int((item.meta_info or {}).get("follower_count") or 0) for item in author_items), default=0),
        post_count=len(author_items),
        posts=posts,
    )


@router.post("/creative/community/posts/{post_id}/like", response_model=CommunityPostResponse, summary="点赞社区游记")
async def like_community_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """点赞社区游记，第一版只做正向点赞。"""

    post = await _get_community_post(db, post_id)
    metadata = dict(post.meta_info or {})
    metadata["like_count"] = int(metadata.get("like_count") or 0) + 1
    metadata["is_liked"] = True
    post.meta_info = metadata
    await db.commit()
    await db.refresh(post)
    return _post_response(post)


@router.post("/creative/community/posts/{post_id}/comments", response_model=CommunityPostResponse, summary="评论社区游记")
async def comment_community_post(
    post_id: UUID,
    request: CommunityCommentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """发表评论，第一版保存在帖子 metadata 中。"""

    post = await _get_community_post(db, post_id)
    metadata = dict(post.meta_info or {})
    snapshot = _user_snapshot(current_user, request.nickname, request.avatar_url)
    comments = [item for item in list(metadata.get("comments") or []) if isinstance(item, dict)]
    comments.append(
        {
            "id": str(uuid.uuid4()),
            **snapshot,
            "content": request.content.strip()[:160],
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    comments = comments[-30:]
    metadata["comments"] = comments
    metadata["comment_count"] = len(comments)
    post.meta_info = metadata
    await db.commit()
    await db.refresh(post)
    return _post_response(post)


@router.post("/creative/community/posts/{post_id}/favorite", response_model=CommunityPostResponse, summary="收藏社区游记")
async def favorite_community_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """切换收藏状态，第一版保存在帖子 metadata 中。"""

    post = await _get_community_post(db, post_id)
    metadata = dict(post.meta_info or {})
    is_favorited = not bool(metadata.get("is_favorited") or False)
    favorite_count = int(metadata.get("favorite_count") or 0)
    metadata["is_favorited"] = is_favorited
    metadata["favorite_count"] = max(0, favorite_count + (1 if is_favorited else -1))
    post.meta_info = metadata
    await db.commit()
    await db.refresh(post)
    return _post_response(post)


@router.post("/creative/community/posts/{post_id}/follow", response_model=CommunityPostResponse, summary="关注社区作者")
async def follow_community_author(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """切换作者关注状态，第一版只做帖子作者快照级状态。"""

    post = await _get_community_post(db, post_id)
    metadata = dict(post.meta_info or {})
    is_followed = not bool(metadata.get("is_followed") or False)
    follower_count = int(metadata.get("follower_count") or 0)
    metadata["is_followed"] = is_followed
    metadata["follower_count"] = max(0, follower_count + (1 if is_followed else -1))
    post.meta_info = metadata
    await db.commit()
    await db.refresh(post)
    return _post_response(post)


@router.post("/creative/community/posts/{post_id}/report", response_model=CommunityPostResponse, summary="举报社区游记")
async def report_community_post(
    post_id: UUID,
    request: CommunityReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """举报社区帖子，第一版记录在帖子 metadata 中。"""

    post = await _get_community_post(db, post_id)
    metadata = dict(post.meta_info or {})
    reports = [item for item in list(metadata.get("reports") or []) if isinstance(item, dict)]
    reports.append(
        {
            "id": str(uuid.uuid4()),
            "reason": request.reason.strip()[:120],
            "nickname": request.nickname or (current_user or {}).get("username") or DEFAULT_NICKNAME,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    metadata["reports"] = reports[-50:]
    metadata["report_count"] = len(metadata["reports"])
    post.meta_info = metadata
    await db.commit()
    await db.refresh(post)
    return _post_response(post)


@router.post("/creative/vision/analyze", response_model=VisionAnalyzeResponse, summary="图片理解能力探针")
async def analyze_creative_image(
    request: VisionAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """进行照片点评；未启用或失败时不伪造图片识别结果。"""

    from app.core.vision_router import VisionAnalysisRequest, VisionRouter

    result = await VisionRouter().analyze_image(
        VisionAnalysisRequest(
            image_name=request.image_name,
            task=request.task,
            spot_name=request.spot_name,
            context=request.context,
            image_data_url=request.image_data_url,
        )
    )
    response = VisionAnalyzeResponse(
        enabled=result.enabled,
        provider=result.provider,
        status=result.status,
        message=result.message,
        task=result.task,
        image_name=result.image_name,
        spot_name=result.spot_name,
        scene_description=result.scene_description,
        spot_candidates=result.spot_candidates,
        visual_facts=result.visual_facts,
        confidence=result.confidence,
        suggestions=result.suggestions,
        safety_tips=result.safety_tips,
        publish_tip=result.publish_tip,
        evidence=result.evidence,
    )
    db.add(
        BehaviorLog(
            user_id=UUID(current_user["user_id"]) if current_user and current_user.get("user_id") else None,
            event_type="vision_photo_review",
            event_data={
                "status": result.status,
                "provider": result.provider,
                "model": result.evidence.get("model"),
                "latency_ms": result.evidence.get("latency_ms"),
                "image_name": request.image_name,
                "spot_name": request.spot_name,
            },
            spot_id=request.spot_name,
        )
    )
    await db.commit()
    return response


@router.get("/creative/photo-tips/{spot_id}", response_model=PhotoTipsResponse, summary="获取景点拍照推荐")
async def get_photo_tips(
    spot_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取景点拍照推荐

    返回景点的最佳拍照位置、角度、时间和技巧建议。
    """
    # 查询景点信息
    result = await db.execute(select(Spot).where(Spot.id == spot_id))
    spot = result.scalar_one_or_none()
    spot_name = spot.name if spot else "灵山胜境"

    # 拍照建议数据库（基于景点特征）
    tips_db = {
        "LS-011": [  # 灵山大佛
            {
                "location": "大佛广场正前方",
                "angle": "仰拍，人物在画面下方1/3处",
                "time": "开园后较早时段，光线通常更柔和",
                "tip": "手机可用0.5倍广角并略微降低机位，人物放在下方三分之一处",
                "description": "正面轴线适合同时交代人物、台阶与大佛主体，画面关系最清楚。",
                "safety": "只在开放广场内取景，不退入车行或游览通道；人多时先让行。",
                "image_key": "buddha",
                "marker_x": 48,
                "marker_y": 78,
                "frame_x": 28,
                "frame_y": 10,
                "frame_width": 44,
                "frame_height": 68,
            },
            {
                "location": "佛手广场",
                "angle": "与佛手掌心对齐，借位拍摄",
                "time": "白天光线充足时均可",
                "tip": "让同行者小幅前后移动，确认手掌轮廓没有与背景重叠后再拍",
                "description": "利用前后距离做借位构图，能得到轻松、有互动感的纪念照。",
                "safety": "不要攀爬、倚靠设施或跨越围栏，按现场排队方向快速完成拍摄。",
                "image_key": "buddha",
                "marker_x": 64,
                "marker_y": 70,
                "frame_x": 46,
                "frame_y": 26,
                "frame_width": 38,
                "frame_height": 48,
            },
            {
                "location": "莲花座基座",
                "angle": "平视角度，背景虚化",
                "time": "日落前约1小时，具体以当天光线为准",
                "tip": "点击天空附近降低曝光，人物侧身站立可获得更干净的轮廓",
                "description": "侧逆光更适合表现大佛轮廓和人物剪影，但阴雨天可改拍环境人像。",
                "safety": "留意台阶和人流，不要边后退边看手机取景。",
                "image_key": "buddha",
                "marker_x": 38,
                "marker_y": 82,
                "frame_x": 18,
                "frame_y": 20,
                "frame_width": 52,
                "frame_height": 58,
            },
        ],
        "LS-013": [  # 梵宫
            {
                "location": "梵宫正门前广场",
                "angle": "对称构图，正面全景",
                "time": "开园后较早或人流相对平缓时",
                "tip": "打开相机网格线，让建筑中轴垂直；有倒影时适当降低机位",
                "description": "正门方向适合对称构图，可完整表现梵宫的建筑层次和入口氛围。",
                "safety": "在开放停留区取景，不占用入口、疏散通道或团队集合点。",
                "image_key": "palace",
                "marker_x": 50,
                "marker_y": 76,
                "frame_x": 18,
                "frame_y": 16,
                "frame_width": 64,
                "frame_height": 58,
            },
            {
                "location": "梵宫穹顶内部",
                "angle": "仰拍，聚焦星空穹顶",
                "time": "以室内开放区域和当日参观安排为准",
                "tip": "先关闭闪光灯，再用1倍镜头向上取景；手机贴近身体可减少抖动",
                "description": "仰拍能突出穹顶纹样和纵深，曝光以保住高光细节为先。",
                "safety": "遵守室内拍摄标识；禁止拍摄或表演进行时请立即收起设备。",
                "image_key": "palace",
                "marker_x": 52,
                "marker_y": 66,
                "frame_x": 24,
                "frame_y": 10,
                "frame_width": 52,
                "frame_height": 52,
            },
        ],
        "LS-006": [  # 九龙灌浴
            {
                "location": "喷泉观景台",
                "angle": "正面中景，捕捉水花飞溅瞬间",
                "time": "以景区当日场次公告为准，建议提前约10分钟到观景区",
                "tip": "手机可开启连拍或实况照片，在水柱完全展开时连续拍摄",
                "description": "正面中景能同时保留九龙群雕、水幕与主要表演区域，方便从连拍中挑选瞬间。",
                "safety": "站在指定观景线外，注意湿滑地面，不使用三脚架阻挡通行。",
                "image_key": "scenic",
                "marker_x": 46,
                "marker_y": 74,
                "frame_x": 26,
                "frame_y": 18,
                "frame_width": 50,
                "frame_height": 50,
            },
            {
                "location": "池畔侧前方",
                "angle": "斜侧构图，保留水面倒影",
                "time": "侧光较柔和时；表演时段仍以现场公告为准",
                "tip": "人物放在画面一侧，给喷泉和水面留出三分之二空间",
                "description": "侧前方更容易形成水面、人物和群雕的层次，也便于避开正面密集人群。",
                "safety": "不要靠近池沿或跨越隔离带，地面有水时放慢脚步。",
                "image_key": "scenic",
                "marker_x": 68,
                "marker_y": 78,
                "frame_x": 32,
                "frame_y": 22,
                "frame_width": 46,
                "frame_height": 48,
            },
        ],
        "LS-014": [  # 五印坛城
            {
                "location": "坛城入口前平台",
                "angle": "低机位横向构图，保留建筑层次",
                "time": "开园后较早或日落前，具体以现场光线为准",
                "tip": "让人物站在台阶一侧，开启网格线校正建筑垂直线",
                "description": "入口方向适合表现坛城层层递进的体量，横向构图可保留更多建筑环境。",
                "safety": "示意图仅表达构图思路；请以现场开放平台和工作人员指引为准。",
                "image_key": "history",
                "marker_x": 42,
                "marker_y": 76,
                "frame_x": 18,
                "frame_y": 16,
                "frame_width": 58,
                "frame_height": 56,
            },
            {
                "location": "转经廊外侧",
                "angle": "顺着廊道斜线拍摄",
                "time": "光线从侧面进入廊道时",
                "tip": "用廊道边线引导视线，人物保持自然行走或看向建筑方向",
                "description": "斜线构图可以突出廊道纵深，适合安静、克制的旅行纪念照。",
                "safety": "不要在狭窄通道中长时间停留或反复倒退取景。",
                "image_key": "history",
                "marker_x": 58,
                "marker_y": 72,
                "frame_x": 28,
                "frame_y": 18,
                "frame_width": 52,
                "frame_height": 52,
            },
        ],
    }

    if not spot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="景点不存在")
    tips = tips_db.get(spot_id)
    if not tips:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="该景点尚无经过审核的拍照建议")

    return PhotoTipsResponse(
        spot_id=spot_id,
        spot_name=spot_name,
        tips=tips,
    )


@router.get("/creative/list/{user_id}", response_model=CreativeListResponse, summary="获取用户的文创列表")
async def get_user_creative_list(
    user_id: UUID,
    content_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定用户的文创内容列表

    参数:
        user_id: 用户ID
        content_type: 按类型筛选 (poem/postcard/badge/journal/painting)
        limit: 返回数量上限
        offset: 偏移量
    """
    query = select(CreativeContent).where(CreativeContent.user_id == user_id)

    if content_type:
        query = query.where(CreativeContent.content_type == content_type)

    query = query.order_by(desc(CreativeContent.created_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    items = result.scalars().all()

    # 查询总数
    count_result = await db.execute(
        select(CreativeContent).where(CreativeContent.user_id == user_id)
    )
    total = len(count_result.scalars().all())

    if content_type:
        count_result = await db.execute(
            select(CreativeContent).where(
                CreativeContent.user_id == user_id,
                CreativeContent.content_type == content_type,
            )
        )
        total = len(count_result.scalars().all())

    return CreativeListResponse(
        items=[
            CreativeItem(
                id=item.id,
                content_type=item.content_type,
                title=item.title,
                content=item.content,
                metadata=item.meta_info or {},
                is_shared=item.is_shared,
                shared_at=item.shared_at,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
    )
