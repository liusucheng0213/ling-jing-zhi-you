#!/usr/bin/env python3
"""
灵境智游 - 故事线数据初始化脚本

功能说明：
- 创建RPG故事线定义数据
- 每个故事线关联特定数字人角色和景点节点
- 支持幂等执行（已存在则更新）

使用方法：
    cd backend
    python -m scripts.init_storylines
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.storyline import StoryLine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/lingjing"
)

# 故事线定义数据
STORYLINES = [
    {
        "avatar_code": "xuanzang",
        "title": "风屿的西行研学",
        "description": "由数字人风屿带你沿灵山胜境的现场线索了解玄奘西行与佛法东传，在史实、传说和景观表达之间建立清晰联系。",
        "plot_points": [
            {
                "node_id": "xj_01",
                "spot_id": "LS-010",
                "title": "风屿开场",
                "description": "在祥符禅寺前，风屿从玄奘西行的求法愿望讲起，并提醒你区分沉浸式叙事、历史记载与现场景观表达。",
                "choices": [
                    {"label": "询问取经缘由", "value": "reason", "next_node": "xj_02"},
                    {"label": "请教佛法", "value": "buddhism", "next_node": "xj_03"},
                ],
            },
            {
                "node_id": "xj_02",
                "spot_id": "LS-010",
                "title": "取经缘由",
                "description": "风屿从求法、译经和文化交流三个角度解释西行的历史意义，并邀请你选择最想继续追问的线索。",
                "choices": [
                    {"label": "表示敬佩", "value": "admire", "next_node": "xj_04"},
                ],
            },
            {
                "node_id": "xj_03",
                "spot_id": "LS-010",
                "title": "佛法开示",
                "description": "风屿介绍《般若波罗蜜多心经》在汉传佛教文化中的影响，并提示经典义理应结合可靠注释理解。",
                "choices": [
                    {"label": "继续请教", "value": "continue", "next_node": "xj_04"},
                ],
            },
            {
                "node_id": "xj_04",
                "spot_id": "LS-010",
                "title": "祥符禅寺",
                "description": "你们从寺前进入祥符禅寺继续观察。风屿请你留意寺院建筑、古树和现场说明牌，并把可见事实与小灵山传说分开记录。",
                "choices": [
                    {"label": "参观古寺", "value": "temple", "next_node": "xj_05"},
                    {"label": "敲响禅钟", "value": "bell", "next_node": "xj_06"},
                ],
            },
            {
                "node_id": "xj_05",
                "spot_id": "LS-010",
                "title": "古寺探秘",
                "description": "在寺中，你找到与“小灵山”相关的文化线索。景区公开介绍记载祥符禅寺始建于唐贞观年间，但具体遗存年代仍应以现场展签为准。",
                "choices": [
                    {"label": "前往大佛", "value": "buddha", "next_node": "xj_07"},
                ],
            },
            {
                "node_id": "xj_06",
                "spot_id": "LS-010",
                "title": "钟声悠扬",
                "description": "你在允许的体验区域聆听钟声。浑厚声音在空间中回荡，风屿请你感受声音与寺院环境形成的节奏。",
                "choices": [
                    {"label": "前往大佛", "value": "buddha", "next_node": "xj_07"},
                ],
            },
            {
                "node_id": "xj_07",
                "spot_id": "LS-011",
                "title": "仰望大佛",
                "description": "你们沿登云道来到通高88米的灵山大佛前。风屿引导你辨认右手施无畏印与左手与愿印。",
                "choices": [
                    {"label": "登顶抱佛脚", "value": "climb", "next_node": "xj_08"},
                ],
            },
            {
                "node_id": "xj_08",
                "spot_id": "LS-011",
                "title": "佛脚祈福",
                "description": "你在灵山大佛前回顾一路线索，风屿为你总结史实、传说与景观之间的关系，并授予'西行研学徽章'。",
                "choices": [],
            },
        ],
        "hidden_triggers": ["长安", "佛法", "般若波罗蜜", "真经"],
        "reward_badge": "西行研学徽章",
        "reward_creative_type": "badge",
        "is_active": True,
        "sort_order": 1,
    },
    {
        "avatar_code": "xiaowan",
        "title": "雨桐的江南寻景",
        "description": "由数字人雨桐从梵宫到五印坛城带你观察光影、建筑层次与取景秩序，用镜头记录可核实的现场体验。",
        "plot_points": [
            {
                "node_id": "xw_01",
                "spot_id": "LS-001",
                "title": "雨桐开场",
                "description": "在灵山大照壁前，雨桐请你先观察现场光线、人流和建筑线条，再选择适合自己的取景方式。",
                "choices": [
                    {"label": "请教拍照技巧", "value": "photo", "next_node": "xw_02"},
                    {"label": "询问最美景点", "value": "scenic", "next_node": "xw_03"},
                ],
            },
            {
                "node_id": "xw_02",
                "spot_id": "LS-001",
                "title": "拍照秘籍",
                "description": "雨桐请你利用照壁的线条和人物比例构图，并根据当天光线选择顺光或侧光机位，避免固定承诺某一时刻的效果。",
                "choices": [
                    {"label": "前往梵宫", "value": "fangu", "next_node": "xw_04"},
                ],
            },
            {
                "node_id": "xw_03",
                "spot_id": "LS-001",
                "title": "最美景点",
                "description": "雨桐建议进入梵宫后放慢脚步，分别观察穹顶、廊柱与空间光线，再决定采用广角全景还是局部细节。",
                "choices": [
                    {"label": "前往梵宫", "value": "fangu", "next_node": "xw_04"},
                ],
            },
            {
                "node_id": "xw_04",
                "spot_id": "LS-013",
                "title": "梵宫秘境",
                "description": "走进梵宫，雨桐请你抬头观察穹顶、廊柱与光影关系，再从木雕、壁画和琉璃等工艺中选择一个细节记录。",
                "choices": [
                    {"label": "欣赏琉璃巨制", "value": "liuli", "next_node": "xw_05"},
                    {"label": "观看吉祥颂", "value": "show", "next_node": "xw_06"},
                ],
            },
            {
                "node_id": "xw_05",
                "spot_id": "LS-013",
                "title": "华藏世界",
                "description": "你们驻足观察琉璃艺术作品。雨桐请你比较颜色、透光与观看距离，并通过现场展签核对作品名称和工艺信息。",
                "choices": [
                    {"label": "前往五印坛城", "value": "wuyin", "next_node": "xw_07"},
                ],
            },
            {
                "node_id": "xw_06",
                "spot_id": "LS-013",
                "title": "灵山吉祥颂",
                "description": "若当天演出开放，你们按公告场次进入梵宫圣坛观看文化演出；若临时调整，则转为观察建筑与展陈，不虚构已经观看。",
                "choices": [
                    {"label": "前往五印坛城", "value": "wuyin", "next_node": "xw_07"},
                ],
            },
            {
                "node_id": "xw_07",
                "spot_id": "LS-014",
                "title": "坛城探秘",
                "description": "在五印坛城，雨桐引导你观察彩绘、壁饰、木雕和唐卡等装饰技艺；互动设施是否可触碰，以现场提示为准。",
                "choices": [
                    {"label": "登顶俯瞰", "value": "climb", "next_node": "xw_08"},
                ],
            },
            {
                "node_id": "xw_08",
                "spot_id": "LS-014",
                "title": "寻梦完成",
                "description": "在五印坛城完成最后一组观察后，雨桐与你回顾构图、光线和游览礼仪，并授予'灵韵徽章'。",
                "choices": [],
            },
        ],
        "hidden_triggers": ["拍照", "美景", "江南", "摄影"],
        "reward_badge": "灵韵徽章",
        "reward_creative_type": "badge",
        "is_active": True,
        "sort_order": 2,
    },
    {
        "avatar_code": "lingxiaochan",
        "title": "舒窈的亲子禅意之旅",
        "description": "由数字人舒窈用清楚、轻松的语言带亲子家庭观察佛足坛、九龙灌浴与弥勒造像中的文化符号。",
        "plot_points": [
            {
                "node_id": "lx_01",
                "spot_id": "LS-003",
                "title": "舒窈开场",
                "description": "在佛足坛前，舒窈用一个观察小游戏开启旅程：先找纹样、再听故事，最后说出你看到的文化符号。",
                "choices": [
                    {"label": "佛足是什么？", "value": "fozu", "next_node": "lx_02"},
                    {"label": "菩提树的故事", "value": "puti", "next_node": "lx_03"},
                ],
            },
            {
                "node_id": "lx_02",
                "spot_id": "LS-003",
                "title": "佛足的秘密",
                "description": "舒窈指向佛足坛。景区公开介绍称这里的佛足印以玄奘西行时临摹的图为原型，具体纹样可以在不触碰展陈的前提下观察。",
                "choices": [
                    {"label": "去菩提大道", "value": "road", "next_node": "lx_04"},
                ],
            },
            {
                "node_id": "lx_03",
                "spot_id": "LS-005",
                "title": "菩提树的故事",
                "description": "舒窈用菩提树解释“觉悟”的文化象征，并请你观察叶形与树影；树种来源以景区植物标牌为准。",
                "choices": [
                    {"label": "观察菩提叶形", "value": "leaf", "next_node": "lx_04"},
                ],
            },
            {
                "node_id": "lx_04",
                "spot_id": "LS-006",
                "title": "九龙灌浴",
                "description": "舒窈引导你观察九龙灌浴演出中的莲花、太子佛与水景表达；具体场次以景区当天公告为准。",
                "choices": [
                    {"label": "观察水幕变化", "value": "water", "next_node": "lx_05"},
                ],
            },
            {
                "node_id": "lx_05",
                "spot_id": "LS-006",
                "title": "圣水祈福",
                "description": "你在安全区域观察水幕和音乐配合。舒窈解释其祝福寓意，同时提醒景观水不可替代饮用水，取水规则以现场提示为准。",
                "choices": [
                    {"label": "去百子戏弥勒", "value": "mile", "next_node": "lx_06"},
                ],
            },
            {
                "node_id": "lx_06",
                "spot_id": "LS-009",
                "title": "百子戏弥勒",
                "description": "舒窈请你寻找弥勒造像周围不同姿态的童子形象，并从表情和动作中理解“笑口常开”的文化表达。",
                "choices": [
                    {"label": "寻找童子造型", "value": "touch", "next_node": "lx_07"},
                ],
            },
            {
                "node_id": "lx_07",
                "spot_id": "LS-009",
                "title": "福气满满",
                "description": "你完成了童子姿态观察任务。舒窈送上“笑口常开”的祝愿；是否允许触碰造像，始终遵从现场管理要求。",
                "choices": [
                    {"label": "完成旅程", "value": "finish", "next_node": "lx_08"},
                ],
            },
            {
                "node_id": "lx_08",
                "spot_id": "LS-009",
                "title": "禅心徽章",
                "description": "舒窈与你回顾一路发现的文化符号，并授予'禅心徽章'，鼓励孩子把观察和尊重带回日常生活。",
                "choices": [],
            },
        ],
        "hidden_triggers": ["禅意", "小朋友", "简单", "可爱"],
        "reward_badge": "禅心徽章",
        "reward_creative_type": "badge",
        "is_active": True,
        "sort_order": 3,
    },
]


STORYLINES.extend(
    [
        {
            "avatar_code": "wuchanshi",
            "title": "明朗的静心行旅",
            "description": "跟随数字人明朗沿景区中轴线放慢脚步，从大照壁、佛足坛到祥符禅寺，在现场观察、礼仪选择和文化问答中完成一段安静而清晰的行旅。",
            "plot_points": [
                {
                    "node_id": "mg_01",
                    "spot_id": "LS-001",
                    "title": "照壁前的第一问",
                    "description": "明朗请你先看大照壁的尺度、纹样和中轴关系，再思考入口建筑为什么要用庄重的空间感迎接游客。",
                    "choices": [
                        {"label": "观察照壁纹样", "value": "pattern", "next_node": "mg_02"},
                        {"label": "先了解游览礼仪", "value": "etiquette", "next_node": "mg_03"},
                    ],
                },
                {
                    "node_id": "mg_02",
                    "spot_id": "LS-001",
                    "title": "从入口读懂空间",
                    "description": "你沿照壁边缘寻找对称线和装饰细节。明朗提醒，景观信息应以现场标识为准，故事讲述则帮助理解空间氛围。",
                    "choices": [
                        {"label": "前往佛足坛", "value": "fozu", "next_node": "mg_04"},
                        {"label": "转入礼仪线索", "value": "ritual", "next_node": "mg_03"},
                    ],
                },
                {
                    "node_id": "mg_03",
                    "spot_id": "LS-003",
                    "title": "礼仪不是距离",
                    "description": "明朗用简洁方式说明参观文化空间时的基本礼仪：降低音量、尊重现场提示、不触碰未开放展陈，也不替他人定义信仰体验。",
                    "choices": [
                        {"label": "观察佛足印", "value": "observe", "next_node": "mg_04"},
                        {"label": "带孩子一起辨认", "value": "family", "next_node": "mg_04"},
                    ],
                },
                {
                    "node_id": "mg_04",
                    "spot_id": "LS-005",
                    "title": "菩提大道的慢行任务",
                    "description": "你把步速放慢，选择一处不妨碍通行的位置停留片刻。明朗请你听环境声、看树影，再记录一个最想继续追问的文化符号。",
                    "choices": [
                        {"label": "记录一个问题", "value": "question", "next_node": "mg_05"},
                        {"label": "做一分钟静观", "value": "pause", "next_node": "mg_05"},
                    ],
                },
                {
                    "node_id": "mg_05",
                    "spot_id": "LS-010",
                    "title": "祥符禅寺的时间线",
                    "description": "来到祥符禅寺，明朗把可见建筑、景区公开介绍与小灵山传说分层讲述，提醒你把传说当作文化记忆，而不是未经核验的年代证据。",
                    "choices": [
                        {"label": "寻找现场说明牌", "value": "sign", "next_node": "mg_06"},
                        {"label": "回顾一路的线索", "value": "review", "next_node": "mg_06"},
                    ],
                },
                {
                    "node_id": "mg_06",
                    "spot_id": "LS-010",
                    "title": "静心行旅完成",
                    "description": "明朗请你用一句话记录今天真正看到的景观，再用一句话写下自己的感受。事实和体验被分别保存，这段旅程也因此更可信、更属于你。",
                    "choices": [],
                },
            ],
            "hidden_triggers": ["礼仪", "静心", "现场标识", "慢行"],
            "reward_badge": "静观徽章",
            "reward_creative_type": "badge",
            "is_active": True,
            "sort_order": 4,
        },
        {
            "avatar_code": "zhaopuchu",
            "title": "明泽的艺术巡礼",
            "description": "由数字人明泽串联灵山梵宫、五印坛城与佛教文化博览空间，从建筑结构、传统工艺和展陈方式三个角度完成一场可观察、可选择的艺术巡礼。",
            "plot_points": [
                {
                    "node_id": "bs_01",
                    "spot_id": "LS-013",
                    "title": "梵宫建筑初读",
                    "description": "明泽请你先不急着拍照，从入口、廊柱、穹顶和空间轴线中选择一个观察对象，理解建筑如何组织人的视线与行走。",
                    "choices": [
                        {"label": "沿廊柱寻找节奏", "value": "columns", "next_node": "bs_02"},
                        {"label": "抬头观察穹顶", "value": "dome", "next_node": "bs_03"},
                    ],
                },
                {
                    "node_id": "bs_02",
                    "spot_id": "LS-013",
                    "title": "木雕与空间节奏",
                    "description": "你沿廊厅观察木雕与梁柱的连续关系。明泽提醒，比起背诵尺寸，更重要的是辨认材料、纹样、光线和观看距离如何共同形成体验。",
                    "choices": [
                        {"label": "寻找琉璃作品", "value": "glass", "next_node": "bs_04"},
                        {"label": "转向穹顶光影", "value": "light", "next_node": "bs_03"},
                    ],
                },
                {
                    "node_id": "bs_03",
                    "spot_id": "LS-013",
                    "title": "穹顶与光",
                    "description": "明泽引导你比较自然光、人工照明与装饰表面的反射。若现场正在举办活动或局部关闭，应优先遵从当天公告与工作人员指引。",
                    "choices": [
                        {"label": "继续看工艺细节", "value": "craft", "next_node": "bs_04"},
                        {"label": "前往坛城比较", "value": "compare", "next_node": "bs_05"},
                    ],
                },
                {
                    "node_id": "bs_04",
                    "spot_id": "LS-013",
                    "title": "多种工艺同场",
                    "description": "木雕、琉璃、壁画与金石工艺在同一建筑中并置。明泽请你选择两种材料，比较它们在颜色、肌理和叙事功能上的差异。",
                    "choices": [
                        {"label": "记录两种材料", "value": "materials", "next_node": "bs_05"},
                        {"label": "寻找展签核对", "value": "labels", "next_node": "bs_05"},
                    ],
                },
                {
                    "node_id": "bs_05",
                    "spot_id": "LS-014",
                    "title": "五印坛城的比较观察",
                    "description": "来到五印坛城，你把彩绘、壁饰、木雕和唐卡等装饰技艺与梵宫所见进行比较，理解不同文化艺术表达如何在景区中并置呈现。",
                    "choices": [
                        {"label": "完成工艺对照表", "value": "compare_table", "next_node": "bs_06"},
                        {"label": "选择最难忘的细节", "value": "favorite", "next_node": "bs_06"},
                    ],
                },
                {
                    "node_id": "bs_06",
                    "spot_id": "LS-014",
                    "title": "艺术巡礼完成",
                    "description": "明泽请你用“材料、空间、故事”三个词各写一条观察。你获得的不是标准答案，而是一套以后参观文化建筑时仍可复用的方法。",
                    "choices": [],
                },
            ],
            "hidden_triggers": ["木雕", "琉璃", "穹顶", "展签"],
            "reward_badge": "匠心徽章",
            "reward_creative_type": "badge",
            "is_active": True,
            "sort_order": 5,
        },
    ]
)


STORY_CULTURE_NOTES = {
    "xuanzang": "西行故事属于叙事线索；景点年代、开放状态与现场信息应以景区公开资料和当日公告为准。",
    "xiaowan": "拍摄时应避让通行、遵守室内摄影提示，并把建筑光影与现场体验作为主要观察对象。",
    "lingxiaochan": "亲子讲述以可观察现象和开放式提问为主，不把传说当作已经证实的历史事实。",
    "wuchanshi": "参观礼仪以尊重现场规则和其他游客为前提，不要求游客接受特定信仰表达。",
    "zhaopuchu": "建筑与工艺信息优先依据展签和景区公开资料，临时展陈与开放区域以当天安排为准。",
}


def _enrich_story_nodes() -> None:
    """补足朗读正文、选择反馈和可操作选项。"""

    option_labels = ["观察现场细节", "听一段文化补充", "记录旅行线索"]
    for storyline in STORYLINES:
        culture_note = STORY_CULTURE_NOTES.get(
            storyline["avatar_code"],
            "请结合现场标识和当天公告理解本节点内容。",
        )
        for index, node in enumerate(storyline["plot_points"], start=1):
            node.setdefault(
                "narration",
                f"{node['description']} 到达现场后，请先确认开放区域与通行安全，再按自己的节奏完成这一章。",
            )
            node.setdefault("culture_note", culture_note)
            choices = node.get("choices", [])
            for choice in choices:
                choice.setdefault(
                    "feedback",
                    f"你选择了“{choice.get('label', '继续探索')}”，讲述将沿这个观察角度继续。",
                )
            if not choices:
                continue
            destination = choices[0].get("next_node")
            while len(choices) < 3:
                option_index = len(choices)
                label = option_labels[option_index % len(option_labels)]
                choices.append(
                    {
                        "label": label,
                        "value": f"observe_{index}_{option_index}",
                        "next_node": destination,
                        "feedback": f"你选择了“{label}”，先完成一个简短观察，再继续主线。",
                    }
                )


_enrich_story_nodes()


async def init_storylines(session: AsyncSession):
    """初始化故事线数据"""
    inserted = 0
    updated = 0

    for story_data in STORYLINES:
        # 检查是否已存在
        result = await session.execute(
            select(StoryLine).where(
                (StoryLine.title == story_data["title"])
                | (StoryLine.sort_order == story_data["sort_order"])
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # 更新
            existing.title = story_data["title"]
            existing.avatar_code = story_data["avatar_code"]
            existing.description = story_data["description"]
            existing.plot_points = story_data["plot_points"]
            existing.hidden_triggers = story_data["hidden_triggers"]
            existing.reward_badge = story_data["reward_badge"]
            existing.reward_creative_type = story_data["reward_creative_type"]
            existing.is_active = story_data["is_active"]
            existing.sort_order = story_data["sort_order"]
            updated += 1
        else:
            # 插入
            story = StoryLine(
                id=uuid4(),
                avatar_code=story_data["avatar_code"],
                title=story_data["title"],
                description=story_data["description"],
                plot_points=story_data["plot_points"],
                hidden_triggers=story_data["hidden_triggers"],
                reward_badge=story_data["reward_badge"],
                reward_creative_type=story_data["reward_creative_type"],
                is_active=story_data["is_active"],
                sort_order=story_data["sort_order"],
            )
            session.add(story)
            inserted += 1

    await session.flush()
    return {"inserted": inserted, "updated": updated}


async def main():
    """主入口"""
    print("=" * 60)
    print("灵境智游 - 故事线数据初始化")
    print("=" * 60)

    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        try:
            print(f"\n连接数据库...")
            stats = await init_storylines(session)
            await session.commit()

            print(f"\n新增故事线: {stats['inserted']} 条")
            print(f"更新故事线: {stats['updated']} 条")
            print("\n故事线初始化完成！")

        except Exception as e:
            await session.rollback()
            print(f"\n错误: {e}")
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
