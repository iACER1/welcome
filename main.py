from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp


@register("welcome_llm", "YourName", "新成员入群欢迎插件：通过LLM生成欢迎词并@新成员，兼容人格设定", "1.0.0")
class WelcomeLLMPlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        """
        当目录下存在 _conf_schema.json 时，AstrBot 会将解析后的配置在实例化时注入到 config 参数。
        """
        super().__init__(context)
        self.config = config or {}

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
            return self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception as e:
            logger.error(f"[welcome_llm] 获取LLM提供商失败: {e}")
            return None

    def _get_persona_prompt(self, event: AstrMessageEvent) -> str:
        """获取人格设定的提示词"""
        persona_id = self.config.get("persona_id", "")
        try:
            pm = self.context.persona_manager
            # 优先使用指定人格
            if persona_id:
                persona = pm.get_persona(persona_id)
                if persona and hasattr(persona, "system_prompt"):
                    return persona.system_prompt or ""
            # 回退默认人格（v3 兼容）
            v3 = pm.get_default_persona_v3(umo=event.unified_msg_origin)
            if v3:
                # v3 可能是 TypedDict 或对象
                if isinstance(v3, dict):
                    return v3.get("prompt", "") or ""
                elif hasattr(v3, "prompt"):
                    return v3.prompt or ""
        except Exception as e:
            logger.warning(f"[welcome_llm] 获取人格失败: {e}")
        return ""

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
        persona_prompt = self._get_persona_prompt(event)

        try:
            if provider:
                model = self.config.get("model") or None
                resp = await provider.text_chat(
                    prompt=prompt,
                    context=[],
                    system_prompt=persona_prompt if persona_prompt else None,
                    model=model,
                )
                if resp and resp.completion_text:
                    return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"[welcome_llm] 请求LLM失败: {e}")

        # 本地回退
        return f"欢迎 {new_member_nickname} 加入，本群欢迎新人～请先阅读群公告，祝你玩得开心！"

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_notice_increase(self, event: AstrMessageEvent, *args, **kwargs):
        """
        监听 OneBot notice 中的 group_increase（新成员入群），并@新成员 + LLM欢迎
        注意：Notice 事件被转换后仍标记为 GROUP_MESSAGE 类型，这里需用 raw_message 识别。
        """
        raw = getattr(event.message_obj, "raw_message", {}) or {}
        if not isinstance(raw, dict) or raw.get("post_type") != "notice":
            return
        if raw.get("notice_type") != "group_increase":
            return

        if not self.config.get("enable", True):
            return

        group_id = event.get_group_id()
        new_user_id = str(raw.get("user_id") or "")
        if not group_id or not new_user_id:
            return

        # 获取新成员昵称
        nickname = new_user_id
        try:
            if event.get_platform_name() == "aiocqhttp":
                info = await event.bot.call_action(
                    action="get_group_member_info",
                    group_id=int(group_id),
                    user_id=int(new_user_id),
                    no_cache=False,
                )
                if info:
                    nickname = info.get("card") or info.get("nickname") or nickname
        except Exception as e:
            logger.warning(f"[welcome_llm] 获取新成员昵称失败: {e}")

        # 群名（若可用）
        group_name = ""
        try:
            group_name = event.message_obj.group.group_name or ""
        except Exception:
            pass

        # 生成欢迎文本并发送（链路：@ + 文本）
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
