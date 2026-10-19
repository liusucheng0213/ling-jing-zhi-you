#!/usr/bin/env python3
"""为演示环境写入可追踪、可重复的运营数据。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import os
import random
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import BehaviorLog, ChatMessage, CreativeContent, EmotionHistory, Session, User


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/lingjing",
)
SEED_VERSION = "dashboard-demo-v3"

QUESTIONS = [
    ("灵山大佛有哪些值得看的细节？", "景点"),
    ("九龙灌浴今天有哪些游览提醒？", "表演"),
    ("梵宫开放时间和参观顺序是什么？", "开放时间"),
    ("带老人怎样安排少走路的路线？", "无障碍"),
    ("五印坛城适合从哪些角度拍照？", "拍照点"),
    ("从市区到灵山胜境怎样走？", "交通"),
    ("景区里有哪些素食和休息点？", "餐饮"),
    ("祥符禅寺与小灵山传说有什么关系？", "历史文化"),
    ("亲子游客半天应该怎么安排？", "路线"),
    ("门票和当天活动在哪里核对？", "门票"),
]

ANSWERS = {
    "景点": "建议先观察大佛的手印、莲花座与中轴景观关系，具体开放区域以现场提示为准。",
    "表演": "九龙灌浴属于动态文化景观，场次可能调整，请先核对景区当天公告并提前到达安全观赏区。",
    "开放时间": "梵宫开放与活动安排存在季节性变化，应以景区当天公告为准；进入后可依次观察廊柱、穹顶与工艺展陈。",
    "无障碍": "可优先选择主轴短线、减少折返，并在游客中心核对轮椅、接驳和临时关闭信息。",
    "拍照点": "可利用建筑倒影、轴线和人物比例构图，室内摄影与三脚架规则以现场提示为准。",
    "交通": "出发前请通过官方渠道核对公交、停车与临时交通信息，节假日应预留排队和接驳时间。",
    "餐饮": "景区公开资料列有素食与轻食服务，营业状态和位置请结合当天导览确认。",
    "历史文化": "祥符禅寺始建信息可参考景区公开介绍；玄奘与小灵山故事属于重要文化传说，讲述时应与可核实史实区分。",
    "路线": "半天亲子线宜控制节点数量，围绕佛足坛、九龙灌浴和一处室内文化空间安排互动提问与休息。",
    "门票": "票价、优惠与活动变化较快，请以景区当前官方购票渠道或服务热线信息为准。",
}

SPOTS = ["LS-001", "LS-003", "LS-006", "LS-010", "LS-011", "LS-013", "LS-014"]
AVATARS = ["舒窈", "明朗", "风屿", "明泽", "雨桐"]
EMOTIONS = ["happy", "happy", "neutral", "neutral", "surprised", "calm"]


def stable_uuid(kind: str, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"lingjing/{SEED_VERSION}/{kind}/{index}")


async def seed_demo_data(db: AsyncSession) -> dict[str, int | bool]:
    marker_result = await db.execute(
        select(BehaviorLog.id).where(
            BehaviorLog.event_type == "demo_seed",
            BehaviorLog.event_data["version"].as_string() == SEED_VERSION,
        ).limit(1)
    )
    if marker_result.scalar_one_or_none():
        return {"skipped": True, "users": 0, "sessions": 0, "messages": 0}

    rng = random.Random(20260809)
    now = datetime.now()
    users: list[User] = []
    for index in range(36):
        user = User(
            id=stable_uuid("user", index),
            nickname=f"演示游客{index + 1:02d}",
            interests='["文化", "摄影", "轻松"]',
            age_group=rng.choice(["18-30", "31-45", "46-60", "60+"]),
            visit_count=rng.randint(1, 4),
            last_visit_at=now - timedelta(days=rng.randint(0, 12)),
            created_at=now - timedelta(days=rng.randint(20, 180)),
        )
        users.append(user)
        db.add(user)

    await db.flush()

    sessions: list[Session] = []
    messages: list[ChatMessage] = []
    for index in range(120):
        day_offset = index % 30
        if index < 4:
            started_at = now - timedelta(minutes=5 + index * 4)
        else:
            started_at = now - timedelta(days=day_offset, minutes=rng.randint(25, 1320))
        user = users[index % len(users)] if index % 4 != 0 else None
        session_id = stable_uuid("session", index)
        session = Session(
            id=session_id,
            user_id=user.id if user else None,
            status="active" if index < 4 else "closed",
            current_spot_id=SPOTS[index % len(SPOTS)],
            current_avatar=AVATARS[index % len(AVATARS)],
            dialogue_state="chatting",
            turn_count=2,
            started_at=started_at,
            ended_at=None if index < 4 else started_at + timedelta(minutes=rng.randint(8, 46)),
            satisfaction_score=rng.choices([1, 2, 3, 4, 5], weights=[2, 5, 15, 42, 36], k=1)[0],
            user_agent=f"Lingjing-Demo-Browser/{index % 36 + 1}",
        )
        sessions.append(session)
        db.add(session)
        await db.flush([session])

        question, category = QUESTIONS[index % len(QUESTIONS)]
        user_created = started_at + timedelta(seconds=20)
        assistant_created = user_created + timedelta(seconds=rng.randint(1, 4))
        user_message = ChatMessage(
            id=stable_uuid("user-message", index),
            session_id=session_id,
            role="user",
            content=question,
            content_type="text",
            emotion=EMOTIONS[index % len(EMOTIONS)],
            intent=category,
            spot_id=session.current_spot_id,
            created_at=user_created,
        )
        is_no_hit = index % 17 == 0
        is_low_confidence = not is_no_hit and index % 11 == 0
        source_score = round(rng.uniform(0.18, 0.32), 3) if is_low_confidence else round(rng.uniform(0.72, 0.94), 3)
        rag_ms = rng.randint(35, 160)
        latency_ms = rng.randint(3400, 5200) if index % 19 == 0 else rng.randint(480, 1680)
        sources = [] if is_no_hit else [
            {
                "title": f"{category}运营知识卡",
                "chunk_id": f"demo-{category}-{index % 6 + 1}",
                "score": source_score,
                "mode": "hybrid_rrf",
                "content": ANSWERS[category],
            },
            {
                "title": "灵山胜境公开资料",
                "chunk_id": f"demo-public-{index % 8 + 1}",
                "score": round(max(0.1, source_score - rng.uniform(0.05, 0.16)), 3),
                "mode": "vector",
                "content": "演示溯源片段，用于展示知识命中、分值和检索耗时，不代表实时景区公告。",
            },
        ]
        assistant_message = ChatMessage(
            id=stable_uuid("assistant-message", index),
            session_id=session_id,
            role="assistant",
            content=ANSWERS[category],
            content_type="text",
            emotion="friendly",
            intent=category,
            spot_id=session.current_spot_id,
            latency_ms=latency_ms,
            retrieved_docs=[
                {
                    "query_trace": {
                        "rag_success": not is_no_hit,
                        "confidence": 0.0 if is_no_hit else source_score,
                        "rag_ms": rag_ms,
                        "retrieved_docs_count": len(sources),
                        "fast_reply": bool(sources) and index % 5 == 0,
                        "rag": {"mode": "hybrid_rrf", "total_ms": rag_ms},
                    },
                    "sources": sources,
                }
            ],
            created_at=assistant_created,
        )
        messages.extend([user_message, assistant_message])
        db.add_all([user_message, assistant_message])

        db.add(
            EmotionHistory(
                id=stable_uuid("emotion", index),
                user_id=user.id if user else stable_uuid("anonymous", index),
                session_id=session_id,
                emotion_type=EMOTIONS[index % len(EMOTIONS)],
                intensity=rng.randint(55, 88),
                trigger_text=question,
                spot_id=session.current_spot_id,
                created_at=user_created,
            )
        )

        if index % 2 == 0:
            rating = session.satisfaction_score or 4
            feedback_pool = (
                [
                    "停车入口有点难找，希望补充更明确的交通说明。",
                    "排队提醒不够及时，建议把当天公告放在回答开头。",
                ]
                if rating <= 2
                else [
                    "路线说明清楚，老人走起来比较轻松。",
                    "梵宫讲解很有层次，希望增加更多展签图片。",
                    "回答很快，表演时间提醒很实用。",
                    "拍照建议具体，能够直接找到构图位置。",
                ]
            )
            db.add(
                BehaviorLog(
                    id=stable_uuid("feedback", index),
                    user_id=user.id if user else None,
                    session_id=session_id,
                    event_type="feedback",
                    event_data={
                        "rating": rating,
                        "feedback_text": rng.choice(feedback_pool),
                        "tags": [category],
                        "dimension_scores": {"内容准确": rating, "响应速度": min(5, rating + 1), "数字人体验": rating},
                        "demo_seed": SEED_VERSION,
                    },
                    spot_id=session.current_spot_id,
                    created_at=assistant_created + timedelta(minutes=1),
                )
            )

    for index, event_type in enumerate(["voice_quality", "tts_quality", "avatar_quality"] * 30):
        db.add(
            BehaviorLog(
                id=stable_uuid("quality", index),
                session_id=sessions[index % len(sessions)].id,
                event_type=event_type,
                event_data={"failed": index in {17, 41, 73}, "demo_seed": SEED_VERSION},
                created_at=now - timedelta(hours=index * 5),
            )
        )

    for index in range(30):
        db.add(
            BehaviorLog(
                id=stable_uuid("photo-review", index),
                user_id=users[index % len(users)].id,
                event_type="vision_photo_review",
                event_data={"status": "failed" if index in {7, 15, 26} else "success", "demo_seed": SEED_VERSION},
                created_at=now - timedelta(days=index % 30, hours=index % 12),
            )
        )

    community_comments = ["讲解把传说和史实分开了，很清楚。", "这个机位下午光线不错。", "带老人走这条线比较合适。", "建议补充当天演出公告入口。"]
    for index in range(24):
        db.add(
            CreativeContent(
                id=stable_uuid("community", index),
                user_id=users[index % len(users)].id,
                content_type="community_post",
                title=f"灵山游览记录 {index + 1}",
                content=community_comments[index % len(community_comments)],
                meta_info={
                    "comment_count": rng.randint(2, 14),
                    "favorite_count": rng.randint(5, 36),
                    "report_count": 1 if index in {8, 17} else 0,
                    "is_hidden": index in {8, 17},
                    "demo_seed": SEED_VERSION,
                },
                is_shared=index not in {8, 17},
                shared_at=now - timedelta(days=index % 30),
                created_at=now - timedelta(days=index % 30, minutes=index * 13),
            )
        )

    db.add(
        BehaviorLog(
            id=stable_uuid("marker", 0),
            event_type="demo_seed",
            event_data={
                "version": SEED_VERSION,
                "purpose": "管理端运营演示；不代表景区真实客流或经营数据",
                "generated_at": now.isoformat(),
            },
            created_at=now,
        )
    )
    await db.commit()
    return {"skipped": False, "users": len(users), "sessions": len(sessions), "messages": len(messages)}


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        result = await seed_demo_data(db)
        print(result)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
