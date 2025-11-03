from typing import Any, Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp


@register("welcome_llm", "YourName", "新成员入群欢迎插件：通过LLM生成欢迎词并@新成员，兼容人格设定", "2.0.0")
class WelcomeLLMPlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        """
        当目录下存在 _conf_schema.json 时，AstrBot 会将解析后的配置在实例化时注入到 config 参数。
        """
        super().__init__(context)
        self.config = config or {}

    @staticmethod
    def _raw_get(source: Any, key: str, default: Any = None) -> Any:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    @staticmethod
    def _ensure_str(value: Any, default: str = "") -> str:
        if value is None:
            return default
        return str(value)

    async def initialize(self):
        """插件初始化（可选）。"""
        pass

    def _get_provider(self, event: AstrMessageEvent):
        """根据配置或当前会话获取 LLM 提供商"""
        prov_id = self.config.get("provider_id", "")
        try:
            if prov_id:
                prov = self.context.get_provider_by_id(provider_id=prov_id)
                if prov:
                    return prov
                logger.warning(
                    "[welcome_llm] 指定的 provider_id=%s 未找到，回退到当前会话提供商",
                    prov_id,
                )
            return self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception as e:
            logger.error(f"[welcome_llm] 获取LLM提供商失败: {e}")
            return None

    async def _get_persona_prompt(self, event: AstrMessageEvent) -> str:
        """获取人格设定的提示词"""
        persona_id = self.config.get("persona_id", "")
        try:
            pm = self.context.persona_manager
            # 优先使用指定人格
            if persona_id:
                persona = await pm.get_persona(persona_id)
                if persona and getattr(persona, "system_prompt", None):
                    prompt = persona.system_prompt or ""
                    logger.debug(
                        "[welcome_llm] 使用配置人格(id=%s)，prompt长度=%d",
                        persona_id,
                        len(prompt),
                    )
                    return prompt
                logger.warning(
                    "[welcome_llm] 指定的人格 id=%s 未找到 system_prompt，回退默认人格",
                    persona_id,
                )
            # 回退默认人格（v3 兼容）
            v3 = await pm.get_default_persona_v3(umo=event.unified_msg_origin)
            if v3:
                # v3 可能是 TypedDict 或对象
                if isinstance(v3, dict):
                    prompt = v3.get("prompt", "") or ""
                elif hasattr(v3, "prompt"):
                    prompt = v3.prompt or ""
                else:
                    prompt = ""
                logger.debug(
                    "[welcome_llm] 使用默认人格 prompt，长度=%d", len(prompt)
                )
                return prompt
        except Exception as e:
            logger.warning(f"[welcome_llm] 获取人格失败: {e}")
        return ""

    def _compose_system_prompt(self, persona_prompt: str) -> Optional[str]:
        prefix = (self.config.get("system_prompt_prefix") or "").strip()
        prompt = persona_prompt.strip() if persona_prompt else ""
        combined = None
        if prompt and prefix:
            combined = f"{prompt.rstrip()}\n{prefix}"
        elif prompt:
            combined = prompt
        elif prefix:
            combined = prefix
        if combined is not None:
            logger.debug(
                "[welcome_llm] 组合后的 system_prompt 长度=%d (前缀长度=%d)",
                len(combined),
                len(prefix),
            )
        else:
            logger.debug("[welcome_llm] 未找到人格 prompt 或前缀，system_prompt 为空")
        return combined

    async def _gen_welcome_text(self, event: AstrMessageEvent, group_name: str, new_member_nickname: str) -> str:
        """
        调用 LLM 生成欢迎文本；失败时回退到本地模板。
        要求 LLM 仅输出正文，不包含 @ 符号，本插件负责真正的 @。
        """
        default_tmpl = (
            "当有新成员加入QQ群，请用友好的语气欢迎他。"
            "输出不超过80字。不要包含@标记。"
            "新成员昵称：{new_member_nickname}，群名：{group_name}。只输出欢迎内容。"
        )
        tmpl = self.config.get("welcome_prompt_template", default_tmpl)
        prompt = tmpl.format(
            new_member_nickname=new_member_nickname,
            group_name=group_name or "",
        )

        provider = self._get_provider(event)
        persona_prompt = self._compose_system_prompt(await self._get_persona_prompt(event))
        logger.debug(
            "[welcome_llm] LLM 请求参数: provider=%s, model=%s, system_prompt_len=%d",
            getattr(provider, "provider_config", {}).get("id") if provider else None,
            self.config.get("model")
            or getattr(provider, "provider_config", {}).get("model"),
            len(persona_prompt) if persona_prompt else 0,
        )
        logger.debug(
            "[welcome_llm] 调用 LLM 前的设置: provider=%s, model=%s, system_prompt_len=%d",
            getattr(provider, "provider_config", {}).get("id") if provider else None,
            self.config.get("model") or getattr(provider, "provider_config", {}).get("model"),
            len(persona_prompt) if persona_prompt else 0,
        )

        try:
            if provider:
                model = self.config.get("model") or None
                resp = await provider.text_chat(
                    prompt=prompt,
                    context=[],
                    system_prompt=persona_prompt,
                    model=model,
                )
                if resp and resp.completion_text:
                    return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"[welcome_llm] 请求LLM失败: {e}")

        # 本地回退
        return f"欢迎 {new_member_nickname} 加入，本群欢迎新人～请先阅读群公告，祝你玩得开心！"

    async def _resolve_member_nickname(
        self, event: AstrMessageEvent, group_id: str, new_user_id: str
    ) -> str:
        nickname = new_user_id
        if event.get_platform_name() != "aiocqhttp":
            return nickname
        bot = getattr(event, "bot", None)
        if bot is None:
            return nickname
        try:
            info = await bot.call_action(
                action="get_group_member_info",
                group_id=int(group_id),
                user_id=int(new_user_id),
                no_cache=False,
            )
            if info:
                return info.get("card") or info.get("nickname") or nickname
        except Exception as e:
            logger.warning(f"[welcome_llm] 获取新成员昵称失败: {e}")
        return nickname

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_group_notice_increase(
        self, event: AstrMessageEvent, *extra_args, **extra_kwargs
    ):
        """
        监听 OneBot notice 中的 group_increase（新成员入群），并@新成员 + LLM欢迎
        """
        if extra_args or extra_kwargs:
            logger.debug(
                "[welcome_llm] handle_group_notice_increase 收到额外参数: args=%s kwargs=%s",
                extra_args,
                extra_kwargs,
            )
        raw = getattr(event.message_obj, "raw_message", None)
        if raw is None:
            logger.debug("[welcome_llm] 收到无 raw_message 的事件，忽略。")
            return

        post_type = self._raw_get(raw, "post_type")
        if post_type != "notice":
            return

        notice_type = self._raw_get(raw, "notice_type")
        if notice_type != "group_increase":
            return

        if not self.config.get("enable", True):
            logger.debug("[welcome_llm] 插件已在配置中禁用。")
            return

        group_id = event.get_group_id()
        new_user_id = self._ensure_str(self._raw_get(raw, "user_id"))
        if not group_id or not new_user_id:
            logger.debug(
                "[welcome_llm] 缺少 group_id 或 user_id，post_type=%s raw=%s",
                post_type,
                raw,
            )
            return

        nickname = await self._resolve_member_nickname(
            event, group_id=group_id, new_user_id=new_user_id
        )

        group_name = ""
        try:
            group_obj = getattr(event.message_obj, "group", None)
            if group_obj and getattr(group_obj, "group_name", None):
                group_name = group_obj.group_name or ""
            else:
                group_name = self._raw_get(raw, "group_name", "")
        except Exception:
            group_name = ""
        text = await self._gen_welcome_text(
            event, group_name=group_name, new_member_nickname=nickname
        )
        chain = [Comp.At(qq=new_user_id), Comp.Plain(text)]
        yield event.chain_result(chain)

    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        """测试指令：/helloworld"""
        user_name = event.get_sender_name()
        yield event.plain_result(f"Hello, {user_name}!")

    async def terminate(self):
        """插件销毁（可选）。"""
        pass
