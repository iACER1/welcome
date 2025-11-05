# Welcome Clean 插件

一个干净、可配置的 AstrBot 入群欢迎插件，保持 @ 新成员能力，提供静态模板与可选 LLM 文案生成，避免旧版本中的复杂副作用。

## 功能特性

- 监听 OneBot `group_increase` 事件，自动识别新入群成员 QQ 号。
- 调用 QQ 协议端 `get_group_member_info` 获取入群者群名片/昵称（若可用）。
- 静态模板渲染，支持 `{nickname}`、`{group_name}` 占位符。
- 可选启用 LLM 欢迎语，自动拼接人格提示词与附加 System Prompt。
- 系统化配置项（`_conf_schema.json`），可通过 WebUI 管理。
- 文本长度限制，避免 LLM 输出过长内容。
- 兜底模板确保在 LLM 调用失败时仍能发送欢迎语。

## 配置项

| 键名 | 类型 | 说明 |
| ---- | ---- | ---- |
| `enable` | bool | 总开关，默认启用。 |
| `use_llm` | bool | 是否启用 LLM 文案生成。 |
| `provider_id` | string | 指定的 LLM Provider ID，留空使用当前会话默认提供商。 |
| `persona_id` | string | 指定人格 ID，留空使用默认人格。 |
| `system_prompt_prefix` | text | 附加在人格 `system_prompt` 之后的额外提示。 |
| `static_template` | string | 静态欢迎模板。占位符：`{nickname}`、`{group_name}`。 |
| `fallback_template` | string | 模板渲染失败或其他异常时的兜底文案。 |
| `max_length` | int | 欢迎语最大长度（10~200）。 |

> **提示**  
> 若开启 LLM 模式，插件会：  
> 1. 根据 `persona_id` 读取 System Prompt；  
> 2. 拼接 `system_prompt_prefix`；  
> 3. 以新成员昵称和群名生成最终提示词；  
> 4. 调用 Provider `text_chat`，并对结果进行长度截断。

## 事件处理流程

1. `handle_group_event` 监听 `GROUP_MESSAGE`，筛选出 `notice` 中的 `group_increase`。
2. 提取新成员 QQ 号和群号，调用 `get_group_member_info` 获取昵称/群名片。
3. 构造欢迎语：优先调用 LLM；失败时使用静态模板；仍失败则使用兜底模板。
4. 构建消息链 `[At(new_member_id), Plain(welcome_text)]` 并发送。

## 开发说明

- 插件入口位于 [`main.py`]。
- 配置 Schema 定义在 [`_conf_schema.json`]，支持 WebUI 编辑。
- 元数据在 [`metadata.yaml`] 中维护。
- 若需扩展，可在 `WelcomeConfig` 增加新字段，并同步 Schema / README。

欢迎根据自身需求二次开发，保持异步调用与异常处理即可无缝集成到 AstrBot 中。
