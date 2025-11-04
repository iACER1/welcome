from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


@dataclass
class WelcomeConfig:
    enable: bool = True
    use_llm: bool = False
    provider_id: Optional[str] = None
    persona_id: Optional[str] = None
    system_prompt_prefix: str = ""
    static_template: str = "欢迎 {nickname} 加入 {group_name}！请先阅读群公告。"
    fallback_template: str = "欢迎 {nickname} 加入，祝你玩得开心！"
    max_length: int = 80

    @classmethod
    def from_raw(cls, raw: Optional[dict]) -> "WelcomeConfig":
        if not isinstance(raw, dict):
            raw = {}
        max_length = raw.get("max_length")
        try:
            max_length = int(max_length)
        except (TypeError, ValueError):
            max_length = 80
        max_length = max(10, min(max_length, 200))
        return cls(
            enable=bool(raw.get("enable", True)),
            use_llm=bool(raw.get("use_llm", False)),
            provider_id=_normalize_optional_str(raw.get("provider_id")),
            persona_id=_normalize_optional_str(raw.get("persona_id")),
            system_prompt_prefix=(raw.get("system_prompt_prefix") or "").strip(),
            static_template=raw.get("static_template")
            or "欢迎 {nickname} 加入 {group_name}！请先阅读群公告。",
            fallback_template=raw.get("fallback_template")
            or "欢迎 {nickname} 加入，祝你玩得开心！",
            max_length=max_length,
        )


@dataclass
class GroupIncreaseNotice:
    group_id: str
    user_id: str
    operator_id: Optional[str]
    group_name: str
    raw: Any


def _safe_get(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _ensure_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_optional_str(value: Any) -> Optional[str]:
    text = _ensure_str(value)
    return text or None


def _get_self_id(event: AstrMessageEvent) -> str:
    try:
        return _ensure_str(event.get_self_id())
    except Exception:  # noqa: BLE001
        return ""


@register(
    "welcome_clean",
    "Apex",
    "模块化的新成员欢迎插件：保持 @ 成员能力并支持可选 LLM 欢迎辞。",
    "3.0.0",
)
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.settings = WelcomeConfig.from_raw(config)
        self._tag = "[welcome_clean]"

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_group_event(self, event: AstrMessageEvent):
        if not self.settings.enable:
            return

        notice = self._extract_group_increase(event)
        if not notice:
            return

        self_id = _get_self_id(event)
        if self_id and notice.user_id == self_id:
            logger.debug(
                f"{self._tag} 检测到机器人自身加入事件，忽略欢迎。self_id={self_id}"
            )
            return

        nickname = await self._resolve_joiner_nickname(event, notice)
        group_name = notice.group_name or self._infer_group_name(event)
        message = await self._build_welcome_message(event, notice, nickname, group_name)

        if not message:
            logger.warning(
                f"{self._tag} 构建欢迎语失败，跳过发送。group={notice.group_id} user={notice.user_id}"
            )
            return

        limited = self._limit_length(message)
        chain = [
            Comp.At(qq=notice.user_id),
            Comp.Plain(limited),
        ]
        logger.debug(
            f"{self._tag} 发送欢迎消息 | group={notice.group_id} user={notice.user_id} nickname={nickname}"
        )
        yield event.chain_result(chain)

    def _extract_group_increase(
        self, event: AstrMessageEvent
    ) -> Optional[GroupIncreaseNotice]:
        raw = getattr(event.message_obj, "raw_message", None)
        if raw is None:
            return None

        if _safe_get(raw, "post_type") != "notice":
            return None
        if _safe_get(raw, "notice_type") != "group_increase":
            return None

        group_id = _ensure_str(
            _safe_get(raw, "group_id", event.get_group_id() or "")
        )
        user_id = _ensure_str(_safe_get(raw, "user_id"))
        operator_id = _normalize_optional_str(_safe_get(raw, "operator_id"))
        group_name = _ensure_str(
            _safe_get(raw, "group_name", self._infer_group_name(event))
        )

        if not group_id or not user_id:
            logger.debug(
                f"{self._tag} group_increase 事件缺少必要字段，忽略。raw={raw}"
            )
            return None

        return GroupIncreaseNotice(
            group_id=group_id,
            user_id=user_id,
            operator_id=operator_id,
            group_name=group_name,
            raw=raw,
        )

    async def _resolve_joiner_nickname(
        self, event: AstrMessageEvent, notice: GroupIncreaseNotice
    ) -> str:
        nickname = notice.user_id
        if event.get_platform_name() != "aiocqhttp":
            return nickname

        bot = getattr(event, "bot", None)
        if bot is None:
            return nickname

        try:
            group_id_int = int(notice.group_id)
            user_id_int = int(notice.user_id)
        except ValueError:
            logger.debug(
                f"{self._tag} 无法将 group_id/user_id 转为 int，使用原始 ID 作为昵称。group_id={notice.group_id} user_id={notice.user_id}"
            )
            return nickname

        try:
            info = await bot.call_action(
                action="get_group_member_info",
                group_id=group_id_int,
                user_id=user_id_int,
                no_cache=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"{self._tag} 获取成员信息失败：{exc} group_id={notice.group_id} user_id={notice.user_id}"
            )
            return nickname

        resolved = (
            _ensure_str(info.get("card"))
            or _ensure_str(info.get("nickname"))
            or nickname
        )
        return resolved

    def _infer_group_name(self, event: AstrMessageEvent) -> str:
        group = getattr(event.message_obj, "group", None)
        if group:
            name = _safe_get(group, "group_name", "")
            if name:
                return _ensure_str(name)
        return ""

    async def _build_welcome_message(
        self,
        event: AstrMessageEvent,
        notice: GroupIncreaseNotice,
        nickname: str,
        group_name: str,
    ) -> str:
        if self.settings.use_llm:
            llm_text = await self._render_llm_message(event, nickname, group_name)
            if llm_text:
                return llm_text

        rendered = self._render_template(
            self.settings.static_template, nickname, group_name
        )
        if rendered:
            return rendered

        return self._render_template(
            self.settings.fallback_template, nickname, group_name
        )

    async def _render_llm_message(
        self, event: AstrMessageEvent, nickname: str, group_name: str
    ) -> Optional[str]:
        provider = self._resolve_provider(event)
        if provider is None:
            logger.debug(f"{self._tag} 未解析到 LLM 提供商，回退到模板欢迎语。")
            return None

        persona_prompt = await self._resolve_persona_prompt(event)
        system_prompt = self._compose_system_prompt(persona_prompt)

        prompt = (
            "你是群管理助手，请生成一段友好的群欢迎辞。\n"
            f"新成员昵称：{nickname or '新成员'}。\n"
            f"群名称：{group_name or '本群'}。\n"
            f"请使用不超过 {self.settings.max_length} 个汉字或字符的正文，"
            "且不要包含任何 '@' 字符或标记。\n"
            "直接输出欢迎语句本身，不要加引号或额外说明。"
        )

        try:
            response = await provider.text_chat(
                prompt=prompt,
                context=[],
                system_prompt=system_prompt or None,
                model=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"{self._tag} 调用 LLM 生成欢迎语失败：{exc}")
            return None

        if response is None:
            return None

        text = _ensure_str(getattr(response, "completion_text", "")).strip()
        if not text:
            chain = getattr(response, "result_chain", None)
            if chain:
                try:
                    text = chain.get_plain_text().strip()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    text = ""
        return text or None

    def _resolve_provider(self, event: AstrMessageEvent):
        provider = None
        if self.settings.provider_id:
            try:
                provider = self.context.get_provider_by_id(self.settings.provider_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"{self._tag} 指定的 provider_id 加载失败：{exc} provider_id={self.settings.provider_id}"
                )
        if provider:
            return provider
        try:
            return self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"{self._tag} 获取会话默认提供商失败：{exc}")
            return None

    async def _resolve_persona_prompt(self, event: AstrMessageEvent) -> str:
        manager = getattr(self.context, "persona_manager", None)
        if manager is None:
            return ""

        if self.settings.persona_id:
            try:
                persona = await manager.get_persona(self.settings.persona_id)
                prompt = getattr(persona, "system_prompt", "") or ""
                if prompt:
                    return _ensure_str(prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"{self._tag} 指定的人格加载失败：{exc} persona_id={self.settings.persona_id}"
                )

        try:
            default_v3 = await manager.get_default_persona_v3(
                umo=event.unified_msg_origin
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"{self._tag} 获取默认人格失败：{exc}")
            return ""

        if isinstance(default_v3, dict):
            return _ensure_str(default_v3.get("prompt"))
        return _ensure_str(getattr(default_v3, "prompt", ""))

    def _compose_system_prompt(self, persona_prompt: str) -> str:
        persona_prompt = persona_prompt.strip()
        prefix = self.settings.system_prompt_prefix.strip()
        if persona_prompt and prefix:
            return f"{persona_prompt.rstrip()}\n{prefix}"
        if persona_prompt:
            return persona_prompt
        return prefix

    def _render_template(
        self, template: str, nickname: str, group_name: str
    ) -> str:
        try:
            rendered = template.format(
                nickname=nickname or "新成员",
                group_name=group_name or "本群",
            )
        except KeyError as exc:
            logger.error(
                f"{self._tag} 模板渲染失败，缺少字段 {exc}. template={template}"
            )
            return ""
        return rendered.strip()

    def _limit_length(self, text: str) -> str:
        if len(text) <= self.settings.max_length:
            return text
        truncated = text[: self.settings.max_length].rstrip()
        return f"{truncated}…"
