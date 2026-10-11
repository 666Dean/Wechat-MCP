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
  微信自身“版本更新”检查返回“已经是最新版本”，未安装更新或替换客户端。

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
