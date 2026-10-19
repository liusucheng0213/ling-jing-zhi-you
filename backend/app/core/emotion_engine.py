"""
情感分析引擎
多模态融合：文本情感 + 语音情感 + 情感记忆
"""

from typing import Dict, Optional
from loguru import logger


class EmotionEngine:
    """情感分析引擎"""

    # 情感标签映射
    EMOTION_TYPES = {
        "happy": "愉悦",
        "curious": "好奇",
        "frustrated": "沮丧",
        "anxious": "焦虑",
        "tired": "疲惫",
        "excited": "兴奋",
        "neutral": "平静",
    }

    async def analyze_text(self, text: str) -> Dict:
        """
        分析文本情感

        返回: {"type": str, "confidence": float, "intensity": int}
        """
        text = text.lower()

        # 关键词规则匹配（简化实现）
        # 实际项目可调用讯飞情感分析API或使用大模型分析
        emotion_scores = {
            "happy": 0,
            "curious": 0,
            "frustrated": 0,
            "anxious": 0,
            "tired": 0,
            "excited": 0,
            "neutral": 1,
        }

        # 正向情感词
        positive_words = ["好", "棒", "喜欢", "开心", "赞", "不错", "漂亮", "美", "good", "great", "nice"]
        for word in positive_words:
            if word in text:
                emotion_scores["happy"] += 1
                emotion_scores["neutral"] -= 0.5

        # 好奇词
        curious_words = ["为什么", "怎么", "什么", "吗", "？", "?", "如何", "怎样", "呢"]
        for word in curious_words:
            if word in text:
                emotion_scores["curious"] += 1
                emotion_scores["neutral"] -= 0.5

        # 沮丧词
        frustrated_words = ["不好", "差", "失望", "讨厌", "烦", "累", "难", "找不到", "迷路", "bad", "disappointed"]
        for word in frustrated_words:
            if word in text:
                emotion_scores["frustrated"] += 2
                emotion_scores["neutral"] -= 1

        # 焦虑词
        anxious_words = ["急", "担心", "怕", "hurry", "快点", "来不及", "紧张"]
        for word in anxious_words:
            if word in text:
                emotion_scores["anxious"] += 2
                emotion_scores["neutral"] -= 1

        # 疲惫词
        tired_words = ["累", "困", "走不动", "休息", "坐", "tired", "sleepy", "exhausted"]
        for word in tired_words:
            if word in text:
                emotion_scores["tired"] += 2
                emotion_scores["neutral"] -= 1

        # 兴奋词
        excited_words = ["哇", "太棒了", "amazing", "激动", "兴奋", "cool", "awesome", "太美"]
        for word in excited_words:
            if word in text:
                emotion_scores["excited"] += 2
                emotion_scores["neutral"] -= 1

        # 选择得分最高的情感
        dominant_emotion = max(emotion_scores, key=emotion_scores.get)
        score = emotion_scores[dominant_emotion]

        # 归一化置信度
        total = sum(abs(v) for v in emotion_scores.values())
        confidence = min(1.0, score / max(total, 1))

        # 强度：1-5
        intensity = min(5, max(1, int(score)))

        return {
            "type": dominant_emotion,
            "confidence": round(confidence, 2),
            "intensity": intensity,
        }

    async def analyze_multimodal(
        self,
        text: str,
        voice_emotion_hint: Optional[str] = None,
        voice_emotion_confidence: Optional[float] = None,
        voice_emotion_reason: Optional[str] = None,
    ) -> Dict:
        """
        多模态情感融合分析

        参数:
            text: 文本内容
            voice_emotion_hint: PCM声学分析得到的语音情感
            voice_emotion_confidence: PCM声学分析得到的真实置信度
            voice_emotion_reason: PCM声学判定依据

        返回: {"type": str, "confidence": float, "intensity": int, "sources": list}
        """
        # 1. 文本情感
        text_emotion = await self.analyze_text(text)

        # 2. 语音情感仅采用服务端PCM声学分析证据，不为缺失置信度补固定值。
        supported_voice_types = {"excited", "tired", "frustrated", "anxious", "neutral"}
        voice_type = voice_emotion_hint if voice_emotion_hint in supported_voice_types else "neutral"
        voice_confidence = self._normalize_confidence(voice_emotion_confidence)
        voice_emotion = {
            "type": voice_type,
            "confidence": voice_confidence,
            "reason": voice_emotion_reason,
            "available": voice_confidence is not None,
        }

        # 3. 可解释仲裁。高置信非中性声学信号可覆盖弱文本信号，避免声音疲惫/兴奋
        # 只被记录却不参与回复策略；明确且高置信的文本信号仍可保留主导权。
        text_type = str(text_emotion["type"])
        text_confidence = float(text_emotion["confidence"])
        conflict = bool(
            voice_confidence is not None
            and voice_type != "neutral"
            and text_type != "neutral"
            and text_type != voice_type
        )
        selected_source = "text"
        decision = "text_only"
        explanation = "未获得可用声学置信度，采用文本情感。"
        final_type = text_type
        final_confidence = text_confidence
        final_intensity = int(text_emotion["intensity"])

        if voice_confidence is not None:
            if text_type == voice_type:
                selected_source = "text+voice"
                decision = "modalities_agree"
                explanation = "文本与声学情感一致，联合提高置信度。"
                final_confidence = min(
                    1.0,
                    text_confidence * 0.55 + voice_confidence * 0.45 + 0.1,
                )
            elif voice_type == "neutral":
                decision = "text_over_neutral_voice"
                explanation = "声学信号为中性，保留文本中更具体的情感。"
            elif text_type == "neutral" and voice_confidence >= 0.55:
                selected_source = "voice_acoustic"
                decision = "voice_over_neutral_text"
                explanation = "文本未表达明确情感，采用可信声学情感。"
                final_type = voice_type
                final_confidence = voice_confidence
                final_intensity = self._voice_intensity(voice_type, voice_confidence)
            elif voice_confidence >= 0.60 and text_confidence < 0.75:
                selected_source = "voice_acoustic"
                decision = "high_confidence_voice_over_text"
                explanation = "声学情感达到高置信阈值，文本证据不足以否定声音状态。"
                final_type = voice_type
                final_confidence = voice_confidence
                final_intensity = self._voice_intensity(voice_type, voice_confidence)
            elif text_confidence >= 0.75:
                decision = "high_confidence_text_over_voice"
                explanation = "文本情感非常明确，优先采用高置信文本证据。"
            elif voice_confidence > text_confidence:
                selected_source = "voice_acoustic"
                decision = "stronger_voice_evidence"
                explanation = "两种模态冲突，声学证据置信度更高。"
                final_type = voice_type
                final_confidence = voice_confidence
                final_intensity = self._voice_intensity(voice_type, voice_confidence)
            else:
                decision = "stronger_text_evidence"
                explanation = "两种模态冲突，文本证据置信度不低于声学证据。"

        return {
            "type": final_type,
            "confidence": round(final_confidence, 2),
            "intensity": final_intensity,
            "sources": ["text", "voice_acoustic"] if voice_confidence is not None else ["text"],
            "details": {
                "text": text_emotion,
                "voice": voice_emotion,
                "arbitration": {
                    "conflict": conflict,
                    "decision": decision,
                    "selected_source": selected_source,
                    "explanation": explanation,
                    "high_confidence_voice_threshold": 0.60,
                    "high_confidence_text_threshold": 0.75,
                },
            },
        }

    @staticmethod
    def _normalize_confidence(value: Optional[float]) -> Optional[float]:
        """校验外部置信度，未知或非数值时保持为空。"""

        if value is None or isinstance(value, bool):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not 0 <= numeric <= 1:
            return None
        return round(numeric, 3)

    @staticmethod
    def _voice_intensity(emotion_type: str, confidence: float) -> int:
        """把声学情感置信度转换为下游可用的1-5级强度。"""

        if emotion_type == "neutral":
            return 1
        if confidence >= 0.8:
            return 4
        if confidence >= 0.7:
            return 3
        return 2

    def get_response_strategy(self, emotion_type: str) -> Dict:
        """
        根据情感类型获取响应策略

        返回: {"dialogue_style": str, "recommendation": str, "content_depth": str, "tts_emotion": str}
        """
        strategies = {
            "tired": {
                "dialogue_style": "简短、温暖、鼓励",
                "recommendation": "推荐休息点、咖啡馆、短路线",
                "content_depth": "浅显",
                "tts_emotion": "gentle",
            },
            "excited": {
                "dialogue_style": "热情、深入、互动",
                "recommendation": "推荐隐藏景点、深度讲解",
                "content_depth": "深入",
                "tts_emotion": "cheerful",
            },
            "frustrated": {
                "dialogue_style": "安抚、共情、解决",
                "recommendation": "主动询问问题、提供人工帮助入口",
                "content_depth": "简化",
                "tts_emotion": "gentle",
            },
            "curious": {
                "dialogue_style": "启发式、引导探索",
                "recommendation": "推荐RPG故事线、隐藏剧情",
                "content_depth": "深入+拓展",
                "tts_emotion": "cheerful",
            },
            "happy": {
                "dialogue_style": "活泼、分享、延伸",
                "recommendation": "推荐拍照点位、文创体验",
                "content_depth": "适中",
                "tts_emotion": "cheerful",
            },
            "neutral": {
                "dialogue_style": "标准、清晰、友好",
                "recommendation": "常规路线推荐",
                "content_depth": "适中",
                "tts_emotion": "neutral",
            },
        }
        return strategies.get(emotion_type, strategies["neutral"])
