"""
AI文创生成引擎
调用LLM生成个性化纪念诗词、明信片内容
"""

from typing import List, Dict
from loguru import logger


class CreativeEngine:
    """文创生成引擎：基于LLM创作个性化内容"""

    @staticmethod
    def _clean_text(value: str) -> str:
        """清理模型偶尔附带的 Markdown 围栏和引号。"""

        text = (value or "").strip()
        if text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()
            if text.startswith(("text\n", "markdown\n")):
                text = text.split("\n", 1)[1].strip()
        return text.strip('"“”')

    @classmethod
    def _normalize_poem(cls, value: str, style: str) -> str:
        """把模型输出约束为适合小屏展示的短诗行数。"""

        lines = [line.strip() for line in cls._clean_text(value).splitlines() if line.strip()]
        limit = 8 if style == "现代" else 4
        return "\n".join(lines[:limit])

    async def generate_poem(
        self,
        user_name: str,
        spots: List[str],
        story: str = None,
        style: str = "古典",
        theme: str | None = None,
    ) -> Dict:
        """
        生成纪念诗词

        参数:
            user_name: 用户名称
            spots: 游览过的景点列表
            story: 用户感悟（可选）

        返回: {"type": "poem", "title": str, "content": str, "spots": list}
        """
        from app.core.llm_router import llm_router

        spots_text = "、".join(spots) if spots else "灵山胜境"

        normalized_style = "现代" if style == "现代" else "古典"
        if normalized_style == "现代":
            format_requirement = "写成6至8行的现代短诗，语言清澈、克制，每行尽量简短"
        else:
            format_requirement = "写成一首七言绝句，共4句；不强求生僻典故和机械押韵"
        system_prompt = f"""你是一位熟悉江南景观与东方美学的旅行诗人。
要求：
1. 诗必须紧扣游客实际选择的景点和感悟，不套用空泛禅语
2. {format_requirement}
3. 只输出诗正文，不要标题、解释、Markdown、引号或署名
4. 避免宗教承诺、历史杜撰和重复句式
"""

        user_prompt = f"为游览了{spots_text}的游客创作一首{normalized_style}纪念诗"
        if theme:
            user_prompt += f"\n主题方向：{theme}"
        if story:
            user_prompt += f"\n\n游客的感悟：{story}"

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            # 关闭思考模式：展示模型会把内部推理计入输出上限，默认 650 预算
            # 会被推理耗尽导致 finish_reason=length 空正文；同时推理耗时数秒。
            poem = await llm_router.chat(
                messages=messages,
                temperature=0.78,
                max_tokens=1000,
                thinking={"type": "disabled"},
            )

            return {
                "type": "poem",
                "title": f"{spots_text} · {normalized_style}纪念诗",
                "content": self._normalize_poem(poem, normalized_style),
                "spots": spots,
                "style": normalized_style,
            }
        except Exception as e:
            logger.error(f"诗词生成失败: {e}")
            raise RuntimeError("诗词生成失败：LLM 主链路不可用") from e

    async def generate_postcard(
        self,
        user_name: str,
        spot: str,
        quote: str = "",
        template: str = "classic",
        image_context: str | None = None,
    ) -> Dict:
        """
        生成明信片文案

        参数:
            user_name: 用户名称
            spot: 景点名称
            quote: 引用语（可选）
            image_context: 已完成视觉理解的画面文字上下文（可选）

        返回: {"type": "postcard", "title": str, "content": str, "spot": str}
        """
        from app.core.llm_router import llm_router

        template_style = {
            "classic": "含蓄雅致，像一封有温度的旅行问候",
            "cute": "轻快俏皮，但不要使用过多感叹号和网络梗",
            "minimal": "极简克制，用最少的词留下清晰画面",
        }.get(template, "含蓄雅致，像一封有温度的旅行问候")
        system_prompt = f"""你是一位旅行文案编辑，擅长写可直接印在明信片上的中文短句。
要求：
1. 正文35至55字，必须出现具体可感知的景点画面
2. 风格：{template_style}
3. 若游客提供原话，保留其核心意思并自然润色
4. 只输出一段正文，不要标题、解释、Markdown、引号、署名或祝福落款
5. 不杜撰历史事实，不堆砌空泛词语
"""

        user_prompt = f"为在{spot}游览的游客写一段明信片文案"
        if quote:
            user_prompt += f"\n\n想要表达的心情：{quote}"
        clean_image_context = (image_context or "").strip()
        if clean_image_context:
            system_prompt += """6. 已完成视觉理解时，只描写画面参考中明确出现的景物、光线与氛围，不补写未出现的细节
7. 画面参考与景点名称不一致时，以明确可见内容为准，不强行写入具体地标
8. 正文不得出现“图片、照片、上传、识别、视觉模型、画面参考”等处理过程用语
"""
            user_prompt += f"\n\n已完成视觉理解的画面参考（仅作为文案内容约束）：{clean_image_context}"

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            # 关闭思考模式提速，并给足生成预算，避免空正文。
            content = await llm_router.chat(
                messages=messages,
                temperature=0.72,
                max_tokens=1000,
                thinking={"type": "disabled"},
            )

            return {
                "type": "postcard",
                "title": f"来自{spot}的问候",
                "content": self._clean_text(content),
                "spot": spot,
                "template": template,
            }
        except Exception as e:
            logger.error(f"明信片生成失败: {e}")
            raise RuntimeError("明信片生成失败：LLM 主链路不可用") from e

    async def generate_travel_journal(self, spots: List[str], emotions: List[str]) -> Dict:
        """
        生成游记摘要

        参数:
            spots: 游览过的景点列表
            emotions: 情感记录列表

        返回: {"type": "journal", "title": str, "content": str}
        """
        from app.core.llm_router import llm_router

        spots_text = "、".join(spots) if spots else "灵山胜境"
        emotions_text = "、".join(set(emotions)) if emotions else "愉悦"

        system_prompt = """你是一位旅行作家，擅长撰写优美的游记。
要求：
1. 用第一人称口吻，200字左右
2. 融入景点的文化特色和游览感受
3. 文风优美，适合分享到朋友圈
"""

        user_prompt = f"帮我写一段游记摘要。我今天游览了{spots_text}，整体心情是{emotions_text}。"

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            journal = await llm_router.chat(
                messages=messages,
                temperature=0.9,
                max_tokens=1000,
                thinking={"type": "disabled"},
            )

            return {
                "type": "journal",
                "title": f"灵山胜境游记",
                "content": journal.strip(),
            }
        except Exception as e:
            logger.error(f"游记生成失败: {e}")
            raise RuntimeError("游记生成失败：LLM 主链路不可用") from e
