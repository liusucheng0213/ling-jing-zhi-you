#!/usr/bin/env python3
"""幂等写入文创社区展示内容，供本地演示使用。"""

import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.creative import CreativeContent


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/lingjing",
)

POSTS = [
    {
        "title": "清晨的大佛很安静",
        "content": "赶在第一批游客进园时走到登云道，晨光落在大佛肩头。风不大，广场也很安静，适合慢慢走、慢慢看。",
        "nickname": "山岚",
        "bio": "喜欢记录清晨与古建筑。",
        "spots": ["灵山大佛", "登云道"],
        "likes": 28,
        "comments": [("阿禾", "请问早上几点到光线最好？"), ("慢游记", "登云道慢慢走很舒服，长辈也可以中途休息。")],
    },
    {
        "title": "梵宫穹顶值得抬头看",
        "content": "梵宫内部的信息量很大，建议别急着往前走。穹顶、壁画和廊柱各有细节，跟着讲解看会更容易理解。",
        "nickname": "一页行程",
        "bio": "周末城市漫游者。",
        "spots": ["灵山梵宫"],
        "likes": 41,
        "comments": [("湖畔听风", "下午去人会不会很多？"), ("小满", "穹顶灯光亮起的那一刻确实很震撼。")],
    },
    {
        "title": "带父母走了一条轻松路线",
        "content": "这次没有追求打卡数量，重点看了九龙灌浴和梵宫。每段路都预留了休息时间，一天下来不赶也不累。",
        "nickname": "江南慢游",
        "bio": "关注适老路线和公共服务。",
        "spots": ["九龙灌浴", "灵山梵宫"],
        "likes": 35,
        "comments": [("青团", "这个安排很适合带老人，收藏了。"), ("云水间", "梵宫附近休息点多吗？")],
    },
]


async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        for index, item in enumerate(POSTS):
            post_id = uuid.uuid5(uuid.NAMESPACE_URL, f"lingjing-showcase:{item['title']}")
            existing = await session.scalar(select(CreativeContent).where(CreativeContent.id == post_id))
            comments = [
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{post_id}:{comment_index}")),
                    "nickname": nickname,
                    "avatar_url": "",
                    "content": content,
                    "created_at": datetime.utcnow().isoformat(),
                }
                for comment_index, (nickname, content) in enumerate(item["comments"])
            ]
            metadata = {
                "nickname": item["nickname"],
                "avatar_url": "",
                "bio": item["bio"],
                "spots": item["spots"],
                "image_names": [],
                "like_count": item["likes"],
                "comment_count": len(comments),
                "favorite_count": 8 + index,
                "visibility": "public",
                "is_hidden": False,
                "comments": comments,
                "demo_seed": True,
            }
            if existing:
                existing.title = item["title"]
                existing.content = item["content"]
                existing.meta_info = metadata
                existing.is_shared = True
            else:
                session.add(
                    CreativeContent(
                        id=post_id,
                        user_id=uuid.uuid5(uuid.NAMESPACE_URL, f"lingjing-author:{item['nickname']}"),
                        content_type="community_post",
                        title=item["title"],
                        content=item["content"],
                        meta_info=metadata,
                        is_shared=True,
                        shared_at=datetime.utcnow(),
                    )
                )
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
