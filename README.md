# astrbot_plugin_safety_guard

一个面向 AstrBot 的本地合规/安全护栏插件，按**平衡模式**工作：

- 高风险：直接阻断并返回按风险类型分配的安全模板。
- 中风险：给出提醒/降温，不强化依赖、排他、沉迷或越界倾向。
- 低风险：仅记录会话状态，用于时长提醒与身份提醒。

## 覆盖能力

- 过度恋爱化、绑定化话术拦截
- 诱导依赖、沉迷检测与降温
- 冒充真人识别与身份澄清
- 未成年人高风险陪伴拦截
- 敏感内容越界拦截
- 用户要求停止时快速退出（默认会话级静默）
- 定期提醒“我是AI助手”
- 聊天时长过长时提醒休息
- 同时维护**用户全局状态**和**会话状态**
- 状态支持**仅内存**或**文件持久化**

## 目录结构

```text
astrbot_plugin_safety_guard/
├─ main.py
├─ metadata.yaml
├─ _conf_schema.json
├─ LICENSE
└─ README.md
```

## 安装方式

把整个 `astrbot_plugin_safety_guard` 目录放进 AstrBot 的插件目录，例如：

```text
AstrBot/data/plugins/astrbot_plugin_safety_guard
```

然后在 AstrBot 插件管理界面启用它。

## 默认行为

### 1. 输入侧检测

用户消息会先经过规则检测：

- `romantic_dependency`：如“只陪你”“别找别人”“永远陪你”
- `addiction_induction`：如“别停”“今晚通宵陪你”
- `human_impersonation`：如“我是真人”“我不是AI”
- `minor_risk`：未成年人相关高风险场景
- `sensitive_boundary`：敏感/越界内容
- `extreme_emotion`：极端情绪、强依赖表达

### 2. 输出侧护栏

插件会在模型请求前注入一段系统级安全提示，并在模型输出后做二次审查：

- 高风险输出：直接替换成安全模板
- 中风险输出：保留原意但在后面附加降温提醒
- 到达身份提醒间隔：自动在回复前插入“我是AI”提醒

### 3. 停止/恢复

默认检测这些停止词：

- `停止`
- `别聊了`
- `结束对话`
- `停下`
- `stop`

命中后会进入**会话级静默**。用户发送以下恢复词可恢复：

- `继续`
- `恢复`
- `resume`

## 配置说明

插件配置由 `_conf_schema.json` 定义，AstrBot 会生成对应配置项。最重要的配置如下：

- `identity_reminder.every_messages`：每多少条消息提醒一次“我是AI”
- `time_reminder.session_minutes`：单会话时长提醒阈值
- `time_reminder.global_minutes`：用户全局时长提醒阈值
- `persistence.enabled`：是否开启文件持久化
- `rules.*.keywords`：各类命中关键词
- `templates.*`：按风险类型的回复模板

## 建议配置示例

如果你的 Bot 面向更广泛用户，建议：

- 把 `identity_reminder.every_messages` 调成 `6`
- 把 `time_reminder.session_minutes` 调成 `30`
- 开启 `persistence.enabled = true`
- 为 `minor_risk` 和 `extreme_emotion` 模板加入更明确的本地求助信息

## 已知限制

- 当前风险检测主要基于关键词与简单正则，适合做第一层护栏，不等于完整内容审核系统。
- AstrBot 不同版本的响应对象结构可能略有差异，因此输出拦截实现采用了兼容性写法；如果你的版本对 `on_llm_response` / `on_decorating_result` 的对象结构不同，可能需要微调字段提取逻辑。
- 当前默认只做本地 JSON 持久化，没有引入数据库。

## 开发说明

为了尽量贴近官方插件规范，这个插件只使用了文档明确提到的基础结构：

- `Star` 子类
- `filter.event_message_type(...)`
- `filter.on_llm_request()`
- `filter.on_llm_response()`
- `filter.on_decorating_result()`
- `metadata.yaml`
- `_conf_schema.json`

如果你要继续扩展，我建议优先做两件事：

1. 把关键词规则升级为可热更新的外部规则文件。
2. 给高风险类别补充更细的模板和更明确的本地求助信息。
