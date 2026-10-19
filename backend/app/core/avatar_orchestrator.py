"""
数字人编排器

统一管理数字人形象、表情映射、语音播放地址和云端数字人视频生成。
严格使用讯飞数字人 SDK 配置驱动数字人，不再用前端 2.5D 形象伪装真实链路。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import urlencode

from loguru import logger

from app.config import settings
from app.core.xunfei_avatar import XunfeiAvatarClient


@dataclass(frozen=True)
class AvatarProfile:
    """数字人角色配置"""

    code: str
    name: str
    avatar_id: str
    voice_id: str
    title: str
    gender: str
    action_presets: tuple[str, ...] = ()


DEFAULT_AVATAR_NAME = "舒窈"


AVATAR_PROFILES: dict[str, AvatarProfile] = {
    "舒窈": AvatarProfile(
        "lingxiaochan",
        "舒窈",
        settings.XFYUN_AVATAR_LINGXIAOCHAN_ID,
        settings.XFYUN_AVATAR_LINGXIAOCHAN_VCN,
        "轻松导览与亲子讲解",
        "female",
    ),
    "明朗": AvatarProfile(
        "wuchanshi",
        "明朗",
        settings.XFYUN_AVATAR_WUCHANSHI_ID,
        settings.XFYUN_AVATAR_WUCHANSHI_VCN,
        "稳重文化讲解",
        "male",
    ),
    "风屿": AvatarProfile(
        "xuanzang",
        "风屿",
        settings.XFYUN_AVATAR_XUANZANG_ID,
        settings.XFYUN_AVATAR_XUANZANG_VCN,
        "历史故事与研学讲述",
        "male",
    ),
    "明泽": AvatarProfile(
        "zhaopuchu",
        "明泽",
        settings.XFYUN_AVATAR_ZHAOPUCHU_ID,
        settings.XFYUN_AVATAR_ZHAOPUCHU_VCN,
        "佛教艺术与建筑导览",
        "male",
    ),
    "雨桐": AvatarProfile(
        "xiaowan",
        "雨桐",
        settings.XFYUN_AVATAR_XIAOWAN_ID,
        settings.XFYUN_AVATAR_XIAOWAN_VCN,
        "江南美学与旅拍向导",
        "female",
    ),
}


# 默认按景点分配讲述人；后台可编辑 trigger_spots 覆盖这些初始值。
DEFAULT_AVATAR_TRIGGER_SPOTS: dict[str, tuple[str, ...]] = {
    "lingxiaochan": ("灵山大照壁", "九龙灌浴", "百子戏弥勒"),
    "wuchanshi": ("五智门", "菩提大道"),
    "xuanzang": ("佛足坛", "降魔浮雕", "阿育王柱", "祥符禅寺"),
    "zhaopuchu": ("灵山大佛", "佛教文化博览馆", "灵山梵宫", "五印坛城"),
    "xiaowan": ("五明桥", "曼飞龙塔", "无尽意斋"),
}


# 后台展示与编辑使用的角色动作预设。实际回复仍由意图/情感动态选择动作，
# 这里用于声明每个形象已验收的常用动作集合，避免配置重置后丢失。
DEFAULT_AVATAR_ACTION_PRESETS: dict[str, tuple[str, ...]] = {
    "lingxiaochan": ("A_U_hello_O", "A_RLH_welcome_O", "A_RLH_Scratch_O", "A_RH_wave_C"),
    "wuchanshi": ("A_X_jingli_O", "A_LRH_emphasize2_O", "A_RLH_sit_talk_xhands_O"),
    "xuanzang": ("A_X_jingli_O", "A_LH_Show_left_up_O", "A_LRH_emphasize2_twice_O"),
    "zhaopuchu": ("A_X_jingli_O", "A_LRH_emphasize2_O"),
    "xiaowan": ("A_RLH_welcome_O", "A_LH_Show_forward_O", "A_RH_ok_O"),
}


# 兼容历史会话、旧版故事角色名和发音人名称；游客端展示形象资源名称。
AVATAR_NAME_ALIASES: dict[str, str] = {
    "灵小禅": "舒窈",
    "灵小山": "舒窈",
    "lingxiaoshan": "舒窈",
    "聆小璇": "舒窈",
    "悟禅师": "明朗",
    "明哥": "明朗",
    "玄奘法师": "风屿",
    "聆飞哲": "风屿",
    "林延": "风屿",
    "知夏": "风屿",
    "赵朴初先生": "明泽",
    "聆伯松": "明泽",
    "林靖": "明泽",
    "小宛": "雨桐",
    "聆小玥": "雨桐",
    "舒然": "雨桐",
}


def resolve_avatar_profile(value: str | None) -> AvatarProfile:
    """按官方名称、历史名称或角色编码解析数字人配置。"""

    normalized = AVATAR_NAME_ALIASES.get(value or "", value or DEFAULT_AVATAR_NAME)
    direct = AVATAR_PROFILES.get(normalized)
    if direct:
        return direct
    return next(
        (profile for profile in AVATAR_PROFILES.values() if profile.code == normalized),
        AVATAR_PROFILES[DEFAULT_AVATAR_NAME],
    )


EXPRESSION_MAP: dict[str, str] = {
    "happy": "smile",
    "excited": "delighted",
    "curious": "thinking",
    "frustrated": "concerned",
    "anxious": "soothing",
    "tired": "gentle",
    "calm": "calm",
    "neutral": "neutral",
    "friendly": "smile",
}


AVATAR_ACTIONS: dict[str, str] = {
    "emphasize_left": "A_LH_emphasize2_O",
    "show_forward_left": "A_LH_Show_forward_O",
    "show_left": "A_LH_Show_left_O",
    "show_left_up": "A_LH_Show_left_up_O",
    "wave_left": "A_LH_wave_C",
    "emphasize_both": "A_LRH_emphasize2_O",
    "emphasize_both_twice": "A_LRH_emphasize2_twice_O",
    "hello": "A_U_hello_O",
    "respect": "A_X_jingli_O",
    "welcome": "A_RLH_welcome_O",
    "talk_hands": "A_RLH_sit_talk_xhands_O",
    "emphasize_hands": "A_RLH_sit_emphasize_xhands_O",
    "thinking": "A_RLH_Scratch_O",
    "applaud": "A_RLH_applaud_C",
    "wave_right": "A_RH_wave_C",
    "thumbs_up": "A_RH_sit_good_O",
    "encourage": "A_RH_sit_encourage_O",
    "show_right": "A_RH_Show_right_O",
    "show_forward_right": "A_RH_Show_forward_O",
    "ok": "A_RH_ok_O",
    "right_then_both": "A_RH_emphasize_twice_RLH_O",
    "emphasize_right_twice": "A_RH_emphasize_twice_O",
    "emphasize_right": "A_RH_emphasize2_O",
}


class AvatarOrchestrator:
    """生成前后端一致的数字人多模态输出描述。"""

    def __init__(self) -> None:
        self.avatar_client = XunfeiAvatarClient()

    async def render_reply(
        self,
        *,
        text: str,
        avatar_name: str,
        emotion: str,
        session_id: str,
        audio_url: str,
        intent: str = "",
        prefer_video: bool = True,
        db_session: Any = None,
    ) -> dict[str, Any]:
        """生成数字人回复载荷。"""

        profile = await self._resolve_profile(avatar_name, db_session)
        expression = EXPRESSION_MAP.get(emotion, "neutral")
        action_sequence = self._select_action_sequence(
            text=text,
            emotion=emotion,
            intent=intent,
            allowed_action_ids=profile.action_presets,
        )
        sdk_config = self._build_xfyun_sdk_config(profile, emotion, action_sequence)
        if not sdk_config:
            missing = []
            if not settings.XFYUN_APP_ID:
                missing.append("XFYUN_APP_ID")
            if not settings.XFYUN_AVATAR_SCENE_ID:
                missing.append("XFYUN_AVATAR_SCENE_ID")
            if not profile.avatar_id:
                missing.append(f"{profile.name}.avatar_id")
            raise RuntimeError(f"讯飞数字人SDK配置不完整，缺少: {', '.join(missing) or '未知配置'}")

        return {
            "avatar_code": profile.code,
            "avatar_name": profile.name,
            "avatar_title": profile.title,
            "emotion": emotion,
            "expression": expression,
            "audio_url": audio_url,
            "video_url": None,
            "stream_url": None,
            "render_mode": "xunfei_sdk",
            "lip_sync_mode": "provider_phoneme",
            "viseme_sequence": [],
            "provider": "xunfei-avatar-sdk",
            "action_sequence": action_sequence,
            "sdk_config": sdk_config,
        }

    async def _resolve_profile(self, avatar_name: str, db_session: Any = None) -> AvatarProfile:
        """优先读取数据库数字人配置，不存在时回退到环境变量配置。"""

        if db_session is not None:
            try:
                from sqlalchemy import select
                from app.models import Avatar

                result = await db_session.execute(
                    select(Avatar)
                    .where(Avatar.is_active == True)  # noqa: E712
                    .where((Avatar.name == avatar_name) | (Avatar.code == avatar_name))
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    default_profile = resolve_avatar_profile(row.code or row.name)
                    try:
                        voice_params = json.loads(row.voice_params or "{}")
                    except Exception:
                        voice_params = {}
                    return AvatarProfile(
                        code=row.code,
                        name=row.name,
                        avatar_id=row.avatar_id or "",
                        voice_id=row.voice_id or settings.XFYUN_TTS_VCN,
                        title=row.role_description or "数字人导游",
                        gender=voice_params.get("gender") or (default_profile.gender if default_profile else "female"),
                        action_presets=tuple(
                            item
                            for item in (voice_params.get("action_presets") or [])
                            if isinstance(item, str) and item in AVATAR_ACTIONS.values()
                        ),
                    )
            except Exception as exc:
                logger.warning(f"读取数字人数据库配置失败，使用默认配置: {exc}")
        return resolve_avatar_profile(avatar_name)

    @staticmethod
    def build_tts_url(text: str, avatar_name: str, emotion: str, speed: float = 1.0) -> str:
        """构建同源 TTS 播放地址。"""

        query = urlencode(
            {
                "text": text,
                "avatar": avatar_name,
                "emotion": emotion,
                "speed": f"{speed:.2f}",
            }
        )
        return f"/api/v1/tts?{query}"

    @staticmethod
    def _resolve_avatar_vcn(profile: AvatarProfile) -> str:
        """解析数字人 SDK 发音人，独立于普通 TTS 播放接口。"""

        return profile.voice_id or settings.XFYUN_AVATAR_VCN or settings.XFYUN_TTS_VCN

    def _build_xfyun_sdk_config(
        self,
        profile: AvatarProfile,
        emotion: str,
        action_sequence: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        构建讯飞星火虚拟数字人 WebSDK payload。

        对话文本由 DeepSeek/RAG 生成，前端调用 writeText 时必须传 nlp=false，
        避免星火大模型接管对话。
        """

        if not (settings.XFYUN_APP_ID and settings.XFYUN_AVATAR_SCENE_ID and profile.avatar_id):
            return None

        server_url = settings.XFYUN_AVATAR_SERVER_URL
        avatar_vcn = self._resolve_avatar_vcn(profile)
        api_info: dict[str, Any] = {
            "serverUrl": server_url,
            "appId": settings.XFYUN_APP_ID,
            "sceneId": settings.XFYUN_AVATAR_SCENE_ID,
        }
        if settings.XFYUN_AVATAR_EXPOSE_SECRET_TO_FRONTEND:
            api_info.update(
                {
                    "apiKey": settings.XFYUN_API_KEY,
                    "apiSecret": settings.XFYUN_API_SECRET,
                }
            )
        else:
            signed_url = self.avatar_client.build_signed_url(server_url)
            if signed_url:
                api_info["signedUrl"] = signed_url

        global_params = {
            "stream": {
                "protocol": settings.XFYUN_AVATAR_STREAM_PROTOCOL,
                "fps": settings.XFYUN_AVATAR_FPS,
                "bitrate": settings.XFYUN_AVATAR_BITRATE,
                "alpha": 0,
            },
            "avatar": {
                "avatar_id": profile.avatar_id,
                "width": settings.XFYUN_AVATAR_WIDTH,
                "height": settings.XFYUN_AVATAR_HEIGHT,
                "audio_format": 1,
            },
            "tts": {
                "vcn": avatar_vcn,
                "speed": 50,
                "pitch": 50,
                "volume": 70,
                "audio": {"sample_rate": 16000},
            },
            "avatar_dispatch": {
                "interactive_mode": 1,
                "enable_action_status": 1,
                "content_analysis": 1,
            },
            "subtitle": {
                "subtitle": 1,
                "font_color": "#FFFFFF",
            },
            "air": {
                "air": 1,
                "add_nonsemantic": 1,
            },
        }
        background_payload = self._build_background_payload()
        start_options: dict[str, Any] = {}
        if background_payload:
            global_params["background"] = background_payload["global_params"]
            start_options.update(background_payload["start_options"])

        text_driver = {
            "nlp": False,
            "tts": {
                "vcn": avatar_vcn,
                "speed": 50,
                "pitch": 50,
                "volume": 70,
                "audio": {"sample_rate": 16000},
            },
            "avatar_dispatch": {
                "interactive_mode": 1,
                "enable_action_status": 1,
                "content_analysis": 1,
            },
            "avatar": [
                {
                    "type": "emotion",
                    "value": EXPRESSION_MAP.get(emotion, "neutral"),
                    "tb": 0,
                }
            ],
        }

        return {
            "sdk_version": "3.2.1-1016",
            "api_info": api_info,
            "global_params": global_params,
            "text_driver": text_driver,
            "action_sequence": action_sequence,
            "write_text_nlp": False,
            "uses_signed_url": "signedUrl" in api_info,
            "background_configured": bool(settings.XFYUN_AVATAR_BACKGROUND_RES_KEY),
            "background_fields": list((background_payload or {}).get("global_params", {}).keys()),
            "start_options": start_options,
            "requires_frontend_secret": False,
            "deepseek_reply_driver": "writeCmd(action) + writeText(text, { nlp: false })",
        }

    @staticmethod
    def _build_background_payload() -> dict[str, Any] | None:
        """构建兼容讯飞 WebSDK 的背景资源载荷，不向前端暴露任何密钥。"""

        value = settings.XFYUN_AVATAR_BACKGROUND_RES_KEY.strip()
        if not value:
            return None

        resource_type = (settings.XFYUN_AVATAR_BACKGROUND_TYPE or "background_data").strip()
        normalized = resource_type.lower()
        global_params: dict[str, Any] = {
            "data": value,
            "type": resource_type,
        }
        start_options: dict[str, Any] = {}

        if normalized in {"res_id", "resid", "resource_id"}:
            global_params.update({"res_id": value, "resId": value})
            start_options["res_id"] = value
        elif normalized in {"res_key", "reskey", "resource", "resource_key"}:
            global_params.update({"res_key": value, "resKey": value})
            start_options["res_key"] = value
        else:
            global_params["type"] = resource_type or "background_data"

        return {
            "global_params": global_params,
            "start_options": start_options,
        }

    @staticmethod
    def _select_action_sequence(
        text: str,
        emotion: str,
        intent: str,
        allowed_action_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        """按意图选择自然动作，并遵守后台为当前形象验收过的动作集合。"""

        content = text or ""
        intent_action_map = {
            "greeting": ("hello", "打招呼"),
            "thanks": ("respect", "抚胸礼"),
            "goodbye": ("wave_right", "右挥手"),
            "ask_route": ("show_forward_right", "右手前方展示"),
            "ask_recommend": ("show_forward_left", "左手向前展示"),
            "ask_story": ("show_left_up", "左手向左上展示"),
            "ask_creative": ("ok", "右手举起OK"),
        }
        emotion_action_map = {
            "curious": ("thinking", "托下巴思考"),
            "happy": ("welcome", "双手打开欢迎"),
            "excited": ("applaud", "鼓掌"),
            "frustrated": ("talk_hands", "双手交流后握手"),
            "tired": ("encourage", "右手加油"),
        }

        selected: list[tuple[str, str]] = []
        if intent in intent_action_map:
            selected.append(intent_action_map[intent])
        elif emotion in emotion_action_map:
            selected.append(emotion_action_map[emotion])
        elif any(word in content for word in ("首先", "第一", "重点", "核心", "建议")):
            selected.append(("emphasize_both", "双手强调"))
        elif any(word in content for word in ("左侧", "左边", "西侧")):
            selected.append(("show_left", "左手向左展示"))
        elif any(word in content for word in ("右侧", "右边", "东侧")):
            selected.append(("show_right", "右手向右展示"))
        else:
            selected.append(("emphasize_left", "左手掌强调"))

        if len(content) > 120 and selected[0][0] not in {"emphasize_both", "right_then_both"}:
            selected.append(("right_then_both", "右手2次强调双手强调"))

        allowed = set(allowed_action_ids)
        if allowed:
            selected = [item for item in selected if AVATAR_ACTIONS[item[0]] in allowed]
            if not selected:
                fallback_id = next((item for item in allowed_action_ids if item in AVATAR_ACTIONS.values()), None)
                if fallback_id:
                    fallback_key = next(key for key, value in AVATAR_ACTIONS.items() if value == fallback_id)
                    selected = [(fallback_key, "角色预设动作")]

        sequence: list[dict[str, Any]] = []
        for index, (key, label) in enumerate(selected[:2]):
            action_id = AVATAR_ACTIONS[key]
            sequence.append(
                {
                    "id": action_id,
                    "name": label,
                    "timing": "before_speech" if index == 0 else "during_speech",
                    "delay_ms": 0 if index == 0 else 1400,
                }
            )
        return sequence


_avatar_orchestrator: AvatarOrchestrator | None = None


def get_avatar_orchestrator() -> AvatarOrchestrator:
    """获取数字人编排器单例。"""

    global _avatar_orchestrator
    if _avatar_orchestrator is None:
        _avatar_orchestrator = AvatarOrchestrator()
    return _avatar_orchestrator
