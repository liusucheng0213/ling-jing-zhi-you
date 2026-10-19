"""
对话编排引擎
管理对话状态机、意图识别、情感适配、提示词组装
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from loguru import logger

from app.config import settings


# ============================================================================
# 数据模型
# ============================================================================

class DialogueState(str, Enum):
    """对话状态枚举"""

    IDLE = "idle"                   # 空闲
    WELCOME = "welcome"             # 欢迎
    EXPLAINING = "explaining"       # 讲解中
    RECOMMENDING = "recommending"   # 推荐中
    STORYTELLING = "storytelling"   # 讲故事
    RPG = "rpg"                     # RPG互动
    CREATIVE = "creative"           # 文创生成
    GOODBYE = "goodbye"             # 告别


class UserIntent(str, Enum):
    """用户意图枚举"""

    GREETING = "greeting"           # 问候
    ASK_INFO = "ask_info"           # 询问信息
    ASK_STORY = "ask_story"         # 请求故事
    ASK_ROUTE = "ask_route"         # 询问路线
    ASK_RECOMMEND = "ask_recommend" # 请求推荐
    ASK_CREATIVE = "ask_creative"   # 请求文创
    CONFIRM = "confirm"             # 确认
    DENY = "deny"                   # 否认
    THANKS = "thanks"               # 感谢
    GOODBYE = "goodbye"             # 告别
    UNKNOWN = "unknown"             # 未知


@dataclass
class DialogueContext:
    """对话上下文"""

    session_id: str
    user_id: Optional[str] = None
    current_state: DialogueState = DialogueState.WELCOME
    current_spot_id: Optional[str] = None
    current_avatar: str = "舒窈"
    turn_count: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    user_emotion: str = "neutral"
    user_intent: UserIntent = UserIntent.UNKNOWN
    retrieved_docs: List[Dict[str, Any]] = field(default_factory=list)
    recent_suggestions: List[List[str]] = field(default_factory=list)
    story_progress: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """添加消息到历史记录"""
        self.history.append({
            "role": role,
            "content": content,
            **kwargs,
        })
        # 限制历史长度（保留最近20轮）
        if len(self.history) > 40:
            self.history = self.history[-40:]

    def get_recent_history(self, n: int = 10) -> List[Dict[str, Any]]:
        """获取最近n轮对话历史"""
        return self.history[-n * 2:]


# ============================================================================
# 对话引擎
# ============================================================================

class DialogueEngine:
    """
    对话编排引擎

    职责：
    1. 状态机管理：维护对话状态流转
    2. 意图识别：识别用户输入意图
    3. 情感适配：根据用户情感调整回复风格
    4. 多模态输出组装：整合文本、语音、视频、图片输出
    """

    # 状态转移规则：当前状态 -> {意图: 目标状态}
    STATE_TRANSITIONS = {
        DialogueState.IDLE: {
            UserIntent.GREETING: DialogueState.WELCOME,
            UserIntent.ASK_INFO: DialogueState.EXPLAINING,
            UserIntent.ASK_STORY: DialogueState.STORYTELLING,
            UserIntent.ASK_ROUTE: DialogueState.RECOMMENDING,
            UserIntent.ASK_CREATIVE: DialogueState.CREATIVE,
        },
        DialogueState.WELCOME: {
            UserIntent.ASK_INFO: DialogueState.EXPLAINING,
            UserIntent.ASK_STORY: DialogueState.STORYTELLING,
            UserIntent.ASK_ROUTE: DialogueState.RECOMMENDING,
            UserIntent.ASK_CREATIVE: DialogueState.CREATIVE,
            UserIntent.GOODBYE: DialogueState.GOODBYE,
        },
        DialogueState.EXPLAINING: {
            UserIntent.ASK_INFO: DialogueState.EXPLAINING,
            UserIntent.ASK_STORY: DialogueState.STORYTELLING,
            UserIntent.CONFIRM: DialogueState.EXPLAINING,
            UserIntent.DENY: DialogueState.RECOMMENDING,
            UserIntent.GOODBYE: DialogueState.GOODBYE,
        },
        DialogueState.STORYTELLING: {
            UserIntent.CONFIRM: DialogueState.STORYTELLING,
            UserIntent.DENY: DialogueState.EXPLAINING,
            UserIntent.ASK_INFO: DialogueState.EXPLAINING,
            UserIntent.GOODBYE: DialogueState.GOODBYE,
        },
        DialogueState.RECOMMENDING: {
            UserIntent.CONFIRM: DialogueState.EXPLAINING,
            UserIntent.DENY: DialogueState.RECOMMENDING,
            UserIntent.ASK_INFO: DialogueState.EXPLAINING,
            UserIntent.GOODBYE: DialogueState.GOODBYE,
        },
        DialogueState.CREATIVE: {
            UserIntent.CONFIRM: DialogueState.CREATIVE,
            UserIntent.DENY: DialogueState.EXPLAINING,
            UserIntent.THANKS: DialogueState.WELCOME,
            UserIntent.GOODBYE: DialogueState.GOODBYE,
        },
        DialogueState.RPG: {
            UserIntent.CONFIRM: DialogueState.RPG,
            UserIntent.DENY: DialogueState.EXPLAINING,
            UserIntent.GOODBYE: DialogueState.GOODBYE,
        },
    }

    # 意图关键词映射（简单规则匹配）
    INTENT_KEYWORDS = {
        UserIntent.GREETING: ["你好", "您好", "嗨", "哈喽", "hello", "hi", "在吗"],
        UserIntent.ASK_STORY: ["故事", "传说", "神话", "典故", "历史", "由来", "起源"],
        UserIntent.ASK_ROUTE: ["路线", "怎么走", "导航", "推荐", "攻略", "行程", "规划"],
        UserIntent.ASK_RECOMMEND: ["推荐", "建议", "哪里好玩", "值得", "必去"],
        UserIntent.ASK_CREATIVE: ["诗", "文创", "明信片", "创作", "帮我写", "写一首", "生成图片", "画一幅"],
        UserIntent.CONFIRM: ["好", "是的", "没错", "对", "可以", "行", "要"],
        UserIntent.DENY: ["不", "不用", "算了", "不要", "否", "别"],
        UserIntent.THANKS: ["谢谢", "感谢", "多谢", "谢了"],
        UserIntent.GOODBYE: ["再见", "拜拜", "bye", "告辞", "走了", "离开"],
    }

    def __init__(self):
        self.contexts: Dict[str, DialogueContext] = {}  # session_id -> context

    def get_or_create_context(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> DialogueContext:
        """
        获取或创建对话上下文

        Args:
            session_id: 会话ID
            user_id: 用户ID

        Returns:
            对话上下文
        """
        if session_id not in self.contexts:
            self.contexts[session_id] = DialogueContext(
                session_id=session_id,
                user_id=user_id,
            )
            logger.info(f"创建新对话上下文: session_id={session_id}")
        return self.contexts[session_id]

    def recognize_intent(self, user_input: str) -> UserIntent:
        """
        识别用户意图

        使用简单关键词匹配 + LLM意图分类（可扩展）

        Args:
            user_input: 用户输入文本

        Returns:
            识别到的意图
        """
        user_input_lower = user_input.lower().strip()

        # “纪念的是谁/纪念馆”等是知识问答，不应被“纪念”误判为文创。
        if any(keyword in user_input_lower for keyword in ("纪念的是谁", "纪念谁", "纪念馆")):
            return UserIntent.ASK_INFO

        short_intents = {
            UserIntent.CONFIRM,
            UserIntent.DENY,
            UserIntent.THANKS,
            UserIntent.GOODBYE,
        }

        # 关键词匹配；确认/否定等短词只接受完整短句，避免“主要/需要”误命中“要”。
        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                matched = (
                    user_input_lower.strip("，。！？!? ") in keywords
                    if intent in short_intents
                    else keyword in user_input_lower
                )
                if matched:
                    logger.debug(f"意图识别: '{user_input[:30]}...' -> {intent.value}")
                    return intent

        # 默认：信息询问
        logger.debug(f"意图识别: '{user_input[:30]}...' -> {UserIntent.ASK_INFO.value} (默认)")
        return UserIntent.ASK_INFO

    def transition_state(
        self,
        context: DialogueContext,
        intent: UserIntent,
    ) -> DialogueState:
        """
        状态转移

        Args:
            context: 当前对话上下文
            intent: 用户意图

        Returns:
            新状态
        """
        current = context.current_state
        transitions = self.STATE_TRANSITIONS.get(current, {})

        new_state = transitions.get(intent, current)

        # 特殊处理：如果用户在非RPG状态下提到RPG关键词，进入RPG状态
        if intent == UserIntent.ASK_STORY and context.history and "角色" in context.history[-1].get("content", ""):
            new_state = DialogueState.RPG

        if new_state != current:
            logger.info(
                f"状态转移: {current.value} -> {new_state.value} "
                f"(意图: {intent.value})"
            )

        context.current_state = new_state
        return new_state

    def build_system_prompt(
        self,
        context: DialogueContext,
        avatar_personality: str = "",
    ) -> str:
        """
        构建系统提示词（情感适配）

        根据当前状态、用户情感、对话历史构建适配的prompt

        Args:
            context: 对话上下文
            avatar_personality: 数字人人设描述

        Returns:
            系统提示词
        """
        state = context.current_state
        emotion = context.user_emotion

        # 基础人设
        base_prompt = f"""你是灵山胜境景区AI数字人导览员，名叫{context.current_avatar}。
你的职责是为游客提供景区讲解、文化介绍、路线推荐和互动体验。
请用亲切、专业、富有文化底蕴的语气回答问题。
涉及景区历史、文化、景点特色、票务、开放时间、交通、表演等事实时，必须优先依据知识库参考信息回答；如果参考信息不足，请明确说明“我暂时没有查到准确资料”，不要编造具体数字、时间、价格或典故。
回答要兼顾准确和响应速度：常见事实问题直接给结论，再补充1-2句背景；复杂文化问题仅在游客要求时展开。
默认回复控制在80-140字、2-4句；每轮最多给2-3个可选方向，结尾至多提出1个明确追问。
除非游客明确说“详细讲讲”“展开”“完整路线”等，不要一次性列出全部路线、全部故事线或全部文创能力。
知识库是事实依据，不是固定话术。除名称、数字和专有术语外，请用自己的话组织，不要连续照抄参考资料中的整句。
如果最近对话已经介绍过同一景点，只回答本轮新增角度；不要重复开场、整段背景或固定结尾。事实数字必须保持一致，但表达方式可以自然变化。
"""

        if avatar_personality:
            base_prompt += f"\n你的人设：{avatar_personality}\n"

        # 状态适配
        state_prompts = {
            DialogueState.WELCOME: "你现在正在欢迎游客。请热情介绍自己和景区，询问游客的兴趣。",
            DialogueState.EXPLAINING: "你现在正在讲解景点。请提供详细、有趣的文化历史介绍，适当引用诗词典故。",
            DialogueState.STORYTELLING: "你现在正在讲述与景点相关的故事或传说。请用生动的叙事方式，营造沉浸感。",
            DialogueState.RECOMMENDING: "你现在正在推荐游览路线。请先询问游客偏好，可围绕游览时间、兴趣主题、体力强度三类选择引导，不要直接输出所有路线。",
            DialogueState.CREATIVE: "你现在正在帮助游客创作文创内容。请先询问游客想发游记、做明信片还是找拍照点，不要一次铺开所有功能。",
            DialogueState.RPG: "你现在正在进行角色扮演互动。请先询问游客想跟随哪个角色或文化主题，不要直接展开长剧情。",
            DialogueState.GOODBYE: "你现在正在与游客告别。请送上祝福，邀请再次光临。",
        }

        if state in state_prompts:
            base_prompt += f"\n当前状态：{state_prompts[state]}\n"

        # 情感适配
        emotion_adaptations = {
            "happy": "游客心情愉快，请用轻松欢快的语气回应，可以适当幽默。",
            "curious": "游客充满好奇心，请用探索式的语气引导，多提出有趣的问题。",
            "frustrated": "游客可能有些疲惫或不耐烦，请用温和体贴的语气，回答简洁明了。",
            "excited": "游客非常兴奋，请用热情洋溢的语气回应，分享更多精彩的内容。",
            "calm": "游客心情平静，请用舒缓优雅的语气，娓娓道来。",
            "surprised": "游客感到惊讶，请肯定他们的感受，并解释背后的原因。",
            "neutral": "游客情绪平稳，请保持专业友好的服务态度。",
        }

        if emotion in emotion_adaptations:
            base_prompt += f"\n情感适配：{emotion_adaptations[emotion]}\n"

        # 上下文信息
        if context.current_spot_id:
            base_prompt += f"\n当前景点：{context.current_spot_id}\n"

        # 历史对话摘要（最近3轮）
        recent = context.get_recent_history(3)
        if recent:
            base_prompt += "\n最近对话：\n"
            for msg in recent:
                role = "游客" if msg["role"] == "user" else "你"
                base_prompt += f"{role}: {msg['content'][:100]}\n"

        return base_prompt

    def build_user_prompt(
        self,
        user_input: str,
        context: DialogueContext,
        retrieved_context: str = "",
    ) -> str:
        """
        构建用户提示词

        Args:
            user_input: 用户输入
            context: 对话上下文
            retrieved_context: RAG检索到的上下文

        Returns:
            用户提示词
        """
        prompt = f"游客说：{user_input}\n\n"

        if retrieved_context:
            prompt += f"参考信息：\n{retrieved_context}\n\n"

        if retrieved_context:
            prompt += (
                "请把参考信息作为事实证据，先给确定结论，再用自己的话做简洁讲解。"
                "不得根据常识推测、补写参考信息中没有的数字、人物关系、典故、设施或服务承诺；"
                "证据不足时直接说明未查到准确资料。除不可改写的名称、数字和术语外，不要复制参考信息的完整句子。"
            )
        else:
            prompt += "请给游客一个自然、有文化内涵的回复；如果涉及你不确定的景区事实，请说明需要以景区现场公告或官方资料为准。"

        detail_terms = ("详细", "展开", "完整", "深入", "全面", "来龙去脉", "多介绍")
        brief_terms = ("简要", "简单", "一句话", "概括", "简短", "只说", "直接说")
        if any(term in user_input for term in detail_terms):
            length_instruction = "游客要求展开，可分段回答，建议180-300字"
        elif any(term in user_input for term in brief_terms):
            length_instruction = "游客要求简答，用1-2句、40-80字直接回答"
        else:
            length_instruction = "默认用2-4句、80-140字回答"

        prompt += (
            f"\n\n输出要求：{length_instruction}；每轮最多给2-3个选项；"
            "如适合继续交流，可在结尾用1个简短且贴合本轮内容的问题引导游客，不要反复使用同一句邀请话术。"
            "若最近对话已经讲过同一景点，只补充本轮新角度，不复述此前介绍。"
            "除非游客明确要求详细展开，不要一次性列出全部路线、故事或文创能力。"
        )

        return prompt

    def _generate_suggestions(
        self,
        context: DialogueContext,
        intent: UserIntent,
        current_spot_name: Optional[str] = None,
        next_spot_name: Optional[str] = None,
        recognized_spots: Optional[List[str]] = None,
    ) -> List[str]:
        """
        生成建议按钮文本

        Args:
            context: 对话上下文
            intent: 用户意图

        Returns:
            建议文本列表
        """
        suggestions_map = {
            DialogueState.WELCOME: ["灵山胜境有哪些必看？", "帮我安排轻松路线", "这里有什么文化故事？", "推荐一个拍照点"],
            DialogueState.EXPLAINING: ["换个角度再讲讲", "它背后有什么故事？", "这里最值得看什么？", "接下来去哪里？"],
            DialogueState.STORYTELLING: ["这个故事后来怎样？", "它和景点有什么联系？", "还有不同版本吗？", "去哪里能看到相关细节？"],
            DialogueState.RECOMMENDING: ["只剩30分钟怎么走？", "给我一条轻松路线", "沿途哪里适合拍照？", "路线适合长者吗？"],
            DialogueState.CREATIVE: ["把它写成短游记", "生成照片明信片", "给我三个拍照建议", "让数字人简要讲解"],
            DialogueState.RPG: ["继续寻找下一条线索", "这段剧情对应哪个景点？", "换一条人物故事线"],
            DialogueState.GOODBYE: ["帮我总结今天的行程", "下次先去哪里？"],
        }

        candidates: List[str] = []
        contextual_secondary: List[str] = []
        image_spot = next((name.strip() for name in recognized_spots or [] if name and name.strip()), None)
        if image_spot:
            candidates.append(f"再讲讲{image_spot}的故事")
            contextual_secondary.append(f"{image_spot}怎么拍更出片？")
        if current_spot_name:
            candidates.append(f"{current_spot_name}最值得看什么？")
            contextual_secondary.append(f"在{current_spot_name}怎么拍照？")
        if next_spot_name and next_spot_name != current_spot_name:
            candidates.append(f"下一站{next_spot_name}看什么？")
            contextual_secondary.append(f"去{next_spot_name}要多久？")
        candidates.extend(contextual_secondary)
        candidates.extend(suggestions_map.get(context.current_state, ["继续讲一个新角度", "推荐下一站", "帮我简要总结"]))

        # 最近两轮已经出现过的按钮不再重复；保留候选顺序即可让景点、行程和图片上下文优先。
        recent = {item for group in context.recent_suggestions[-2:] for item in group}
        unique_candidates = list(dict.fromkeys(item for item in candidates if item and item not in recent))
        if len(unique_candidates) < 3:
            rotation = [
                "换个角度简要介绍",
                "推荐附近的下一个看点",
                "告诉我一个容易错过的细节",
                "按当前体力调整路线",
                "给我一个现场互动问题",
                "帮我总结成一句话",
            ]
            offset = context.turn_count % len(rotation)
            for index in range(len(rotation)):
                item = rotation[(offset + index) % len(rotation)]
                if item not in recent and item not in unique_candidates:
                    unique_candidates.append(item)
                if len(unique_candidates) >= 3:
                    break

        selected = unique_candidates[:3]
        context.recent_suggestions = [*context.recent_suggestions[-1:], selected]
        return selected
