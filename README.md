# 入群欢迎 LLM（welcome_llm）

新成员加入QQ群时，自动通过 LLM 生成欢迎词并 @ 新成员，支持人格设定与可编辑提示词模板。

- 入口类: [WelcomeLLMPlugin.register()](test plugins/welcome/main.py:9)
- 事件监听: [WelcomeLLMPlugin.on_group_notice_increase()](test plugins/welcome/main.py:78)
- LLM与人格: [WelcomeLLMPlugin._get_provider()](test plugins/welcome/main.py:28), [WelcomeLLMPlugin._build_system_prompt()](test plugins/welcome/main.py:40)
- 提示词生成: [WelcomeLLMPlugin._gen_welcome_text()](test plugins/welcome/main.py:58)
- 配置 Schema: [_conf_schema.json](test plugins/welcome/_conf_schema.json)

## 功能

- 监听 OneBot v11 notice: group_increase（新成员入群事件）
- 自动调用当前会话使用的 LLM（或你配置的 provider/model），生成一段欢迎文本
- 使用消息链发送: At(新成员) + 文本（不把 @ 交给 LLM生成，避免平台兼容性问题）
- 兼容人格设定（优先使用你在配置里指定的 persona_id，否则回退到默认人格）

## 安装

1) 将本插件目录放置于 AstrBot 项目内：
- 推荐路径: data/plugins/welcome_llm
- 临时测试也可直接放在 test plugins/welcome（本仓库已提供示例）

2) 打开 AstrBot，本体运行后在 WebUI -> 插件管理 中找到该插件：
- 点击 管理
- 点击 重载插件（如果你做了代码更新）
- 启用 插件

3) 确保你已配置至少一个 LLM Provider（WebUI -> 设置 -> 提供商）

## 配置

本插件在目录下提供 [_conf_schema.json](test plugins/welcome/_conf_schema.json)，AstrBot 将自动解析并注入到插件实例 config 参数中。

可配置项：
- enable(bool, default=true): 是否启用入群欢迎
- provider_id(string, _special="select_provider"): 指定使用的 LLM 提供商，不填则使用当前会话默认提供商
- model(string): 可选，强制指定模型名称
- persona_id(string, _special="select_persona"): 指定人格 ID，优先使用该人格作为 system prompt
- system_prompt_prefix(text): 在人格系统提示词之后追加的 system 前缀
- welcome_prompt_template(text): 欢迎词提示词模板，可用变量:
  - {bot_name}: 机器人名（当前实现固定为 AstrBot）
  - {new_member_nickname}: 新成员昵称（或QQ号兜底）
  - {group_name}: 群名（可获取时）

默认模板示例：
```
你是{bot_name}，当有新成员加入QQ群，请用友好的语气欢迎他，简要介绍群主题和规则（若已知），邀请其先阅读置顶公告。输出不超过80字。不要包含@标记。新成员昵称：{new_member_nickname}，群名：{group_name}。只输出欢迎内容。
```

注意：模板中不要包含 @，本插件会在发送阶段正确拼接 [Comp.At()](plugin.md:158) 与 [Comp.Plain()](plugin.md:153)。

## 工作原理

- AstrBot 的 aiocqhttp 平台适配器会把 OneBot 的 notice 事件转换为 AstrBotMessage，若包含 group_id 则类型标记为 GROUP_MESSAGE。
- 插件使用 [filter.event_message_type()](plugin.md:352) 监听 GROUP_MESSAGE，并在 Handler 内部检查 [event.message_obj.raw_message](plugin.md:171)：
  - post_type == "notice"
  - notice_type == "group_increase"
- 获取新成员的用户 ID/昵称：
  - 在 aiocqhttp 下，调用 `get_group_member_info` 获取 card/nickname 作为显示名
  - 获取失败时使用 QQ号作为兜底昵称
- 构造 system prompt：
  - 优先使用配置 persona_id 对应的人格
  - 否则回退到默认人格（v3 兼容）
  - 追加 system_prompt_prefix（如不为空）
- 调用 Provider.text_chat() 生成欢迎文本；失败时本地回退固定文案
- 以消息链发送: [Comp.At(qq)](plugin.md:158) + [Comp.Plain(text)](plugin.md:153)

## 人格兼容

- 指定 persona_id 时直接读取该人格的 system_prompt
- 未指定时使用 PersonaManager 的默认人格（v3 兼容对象）
- 你可以在 WebUI 的人格管理中创建/配置人格，并把其 ID 填到本插件配置

## 平台兼容性

- 主要针对 OneBot v11（如 go-cqhttp/Napcat/Lagrange 等）
- 其他平台若能将“新成员加入”的事件转化为 AstrBot 的通知并带上 group_id，同样可以触发；但昵称 API 不一定可用，可能显示为 ID

## 测试步骤

1) 在 WebUI 中启用插件，保存配置
2) 将机器人拉入测试群，或由他人邀请新成员加入测试群
3) 观察群内是否自动发送:
   - @新成员
   - 生成的欢迎文本（不含@）
4) 如果长时间无响应：
   - 检查 OneBot 连接是否正常
   - 检查 LLM Provider 是否可用
   - 查看 AstrBot 日志（插件会输出错误日志）

## 常见问题

- metadata.yaml 报 YAML schema 警告（如 VSCode 提示缺少 spec）：这通常是本地编辑器的 YAML 关联错误，不影响 AstrBot 读取插件元数据。模板格式参考 [metadata.yaml](test plugins/welcome/metadata.yaml:1)。
- LLM 没有回复文本：请确认 provider_id/model 配置正确，或移除它们使用当前会话默认提供商；查看日志定位错误。
- 没有正确 @ 新成员：请确认平台支持 At 组件；OneBot v11 的 At 由协议端负责解析。

## 变更日志

- v1.0.0
  - 新增: 监听群新成员加入，调用 LLM 生成欢迎文本并 @ 新成员
  - 新增: 可编辑提示词模板、人格兼容、provider/model 可选指定
