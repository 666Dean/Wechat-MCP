# Mac 微信聊天控件排障与安全边界

2026-10-11；本次设备为 macOS 27.0.1、微信 4.1.15。仅公开控件计数和错误码，
不公开身份、正文、截图、机器路径或密钥。下列来源的描述不等于本机通过。

## 固定源码与结论

| 来源 | 审查版本 | 本轮结论 |
| --- | --- | --- |
| [wechat-fastbridge](https://github.com/huj28-creator/wechat-fastbridge) | `421330c1998c7798432ade46c43504bb7fa68a3e`，MIT | 原生 AX 路线；其 [issue #1](https://github.com/huj28-creator/wechat-fastbridge/issues/1) 报告 4.1.x 主聊天树缺失，不能提供已验证的修复 |
| [wechat-mcp](https://github.com/dustin573/wechat-mcp) | `c6c600ae068c113224f984656db40f8cec4d0164`，MIT | 本项目已复用 selector 标识与标题规则；这些标识必须实际出现在树中，不能凭配置补出节点 |
| [本地 Swift 工具](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f) | `c98dbb10cf23c30e83d5d744905101b0880887a0`，MIT | 静态审查 ScreenCaptureKit 先应用、后窗口过滤的序列；本机此前同序列未取得 frame。其校准坐标/OCR 标题发送不能证明唯一私聊 ID，不直接接入发送 |

新下载的 Swift 工具只作源码阅读，没有执行其读取/发送或集成其代码。
依赖截图交给云端模型、固定坐标点击或显示名事后数据库核验的方案，均不能补齐本项目的发前稳定身份检查。

## 本机实验

- Apple Accessibility Inspector 已选中原版微信进程，聊天/输入树仍未出现。
- 原版严格 Tencent 签名验证后，一次以
  [`--force-renderer-accessibility=complete`](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md#command-line-options)
  参数启动并进入原有账号。该参数是 Chromium 文档能力；未观察到微信将它传递给渲染进程，
  12 个厂商进程的角色探测累计 888 节点、0 编辑节点，不能称为微信支持该参数。
  实验后恢复无该参数、无注入环境的原版并进入账号，原版严格签名仍有效。
- 恢复后的全应用角色探测有 199 节点、0 编辑节点；最终 SDK 将诊断限定为应用窗口，
  排除菜单中的搜索框，返回 1 个窗口、5 节点、0 编辑节点、0 静态文本节点；
  `AXError -25212` 共 2 次，遍历未截断。这是观测结果，不据此推断客户端故障原因。
- 微信设置窗口可正常截图，主聊天窗口仍白屏。主人未找到类似“演示屏幕时隐藏主窗口”的选项；
  不能推定它已关闭，也没有修改隐私设置或尝试绕过屏幕保护。
- 只读取 CoreGraphics 窗口元数据：当前单显示器、唯一可见的主聊天窗口
  `kCGWindowSharingState=0`（`kCGWindowSharingNone`）。这与白屏同时出现，但不是已证明的全部原因；
  不通过注入或过滤器漏洞改变/规避客户端共享属性。
- 只角色的备用子项数组及 AX 命中探测没有找到聊天/编辑节点，未产生点击或输入事件。
  当时微信自身“版本更新”检查返回“已经是最新版本”；后续标准厂商升级结果单独记录如下。

## 代码与隐私修正

Mac 通用 helper 的 `capabilities` 操作仅通过 AXWindows 枚举窗口、请求 AXRole / AXChildren，不请求名字、标识或正文值。
输出计数、有界遍历是否截断与错误码；UIAdapter 以 `expected_pid` 绑定 status 和能力探测，
进程更换时拒绝。`no_editable_controls` 是明确的健康状态，发现输入节点也只报告
`candidate_controls_unqualified`，`send_available` 仍为 false。

Mac / Windows 的 `structure` 不再先获取 Value/Name 再隐藏文字，不提供 `authorized_label`。
结构只保留路径、角色、技术标识和子项数；业务身份与正文值仍由带 commit proof 的 read/send 检查。

本机隔离 Cocoa 合成控件对 `accessibilityValue` getter 计数：旧 structure 调用 1 次，
修正后 structure 与 capabilities 均 0 次，且诊断确实发现该合成编辑控件。
这关闭了 Mac 结构探测提前取值的问题，不代表真实微信输入/发送已经通过；
Windows 同类修正已通过 CI 原生编译与回归，未做微信硬件验证。

另一次新的 OS 认证下，两目标各一个实际 AET 只读事务 Completed。
最小化状态首次确认后，下一轮检查观察到状态变化，测试立即停止并撤权、恢复开关关闭；
审计有效，测试 context 已逻辑清理为 0。此失败观察不算持续最小化/后台 UI 验收通过。

要进入真实发送验收，仍须在 UI 中取得账号、唯一会话 ID、空输入框、提交控件和新消息见证。
数据库绑定不会自动证明屏幕上当前选中的同名聊天。缺少这些证据时停止，不做全局回车或坐标发送。

[bf25e9c 双平台 CI](https://github.com/Aethra2007/wechat-codex-mcp/actions/runs/38121786431)
均通过原生构建与 CTest；160 项回归，Mac 执行 158 项/跳过 2 项，Win 执行 154 项/跳过 6 项。
这证明本次代码回归，不改变上述设备验收限制。

## 本轮补充的固定开源审查与实现

- [WeChatAutoReply](https://github.com/JunxiBao/WeChatAutoReply/tree/e3b0b96284a6cf863c8243249c7bcd7593956229)，MIT：源码使用 AX 输入、CGEvent.postToPid。没有采用其清空草稿、猜测 sender、云端模型、随机延迟或无读回即成功的逻辑；本项目自行实现资格焦点/精确意图与气泡见证。
- [WeChatBridge](https://github.com/freestylefly/WeChatBridge/tree/0b00e3f89ace0e8f5d9c17478b2c966d0e2b890e)，MIT：官方 Share Extension 合并转发可作为主人主动导出的读取候选；需要手动选择，标题不能证明内部 ID，不解决回复输入。没有安装或运行其应用/转发器，也未接入自动 AI/剪贴板转发。
- [wechat-controller](https://github.com/dragonking-T/wechat-controller)：其坐标、Vision/provider 路线不能自动取得本项目所需稳定身份和草稿证据；未运行其云端/坐标发送器。

已接入的本地 OCR 与 PID 输入及真实/合成证据见 [MAC_REPLY.md](MAC_REPLY.md)。本轮新源码审查结论不等于第三方版本的兼容承诺；官方独立聊天窗口实测白屏且无输入节点，真实发送未执行。

## 旧共享标志与标准升级复查

Apple 对 [NSWindow.SharingType.none](https://developer.apple.com/documentation/appkit/nswindow/sharingtype-swift.enum/none) 的当前说明是旧常量；不能把 CoreGraphics 数值 0 单独解释成现代捕获保护，也不能由此判断微信有意拦截自动化。
SDK 将相关健康状态改为捕获策略尚未资格验证，保留自动捕获的保守拒绝检查，不修改共享属性或通过过滤器切换规避排除。

主人在 Apple SCContentSharingPicker 选择单个微信主窗口，探针核对原 PID/bundle、单窗口 filter 成功；只返回元数据，没有 stream、截图、OCR 或消息操作。该主窗口不是指定私聊的稳定绑定证据。

随后主人正常退出旧客户端；腾讯官方 DMG 的 SHA256、Developer ID/Team 和 Gatekeeper 评估均通过，标准替换至 4.1.15.54 / 270134，并保留原签名应用副本。没有重签名或注入新版，也没有手动改动账号数据。
新版正常进入既有账号后，AX 仍只有窗口与系统按钮、工具截图仍白屏。登录页的按钮可通过 AX 操作，不能外推聊天页控件可用。
新渠道和开源版本适配审查见 [MAC_TRANSPORTS.md](MAC_TRANSPORTS.md)。

## 所有者单帧与合成对照补充

本轮显式本地所有者入口经新的 OS 认证、精确单次授权及主人选择后，用原始 Apple 单窗口 filter 实际调用截图和本地 Vision。
两个已指定独立私聊均返回 598×640 帧，OCR 0 行、0 个不透明采样；当前空帧判为 FailedSafe，不能称为读取通过。
同一路径纯合成窗口失焦时成功：1280×1024、4 行/67 字节、4072 个不透明采样，审计有效。
这验证实现可捕获合成内容，但不确定微信内部的限制原因，不修改或绕过隐私保护。
无图片落盘、模型正文披露或真实发送；操作结束撤权及逻辑清理。窗口选择不证明内部 ID、草稿或发送资格。
合成前两次等待超时不算成功；历史元数据或旧捕获事务 Completed 不等于可用内容验收。
微信失焦下空帧不算后台读取通过，发送/发送后读回/后台写入/多日运行仍未通过。
请求格式、安全边界及复现见 [MAC_REPLY.md](MAC_REPLY.md)。
