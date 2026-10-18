# Windows 独立服务 MCP 接口

当前八工具接入新独立服务；新增精确发送计划及异步状态，读取、披露和人工草稿仍单独保留。Windows 整个项目的实现仍按[代码完成清单](WINDOWS_CODE_COMPLETION.md)推进，软件链路全部完成前不开展新的微信实机测试，不能把这里的合成闭环当作全部自动回复已实现。

本轮接线把 MCP 前端接到独立 authority 的 v2 认证管道，不再调用旧 bearer Broker 或在前端打开所有者数据库、凭据和业务适配器。入口为 `server.py --authority-profile <所有者提供的本机配置>`，配置示例见 [Codex MCP 模板](../codex-authority.example.toml)。此模板不安装服务、不登记进程、不签发权限，也不修改 Codex 全局设置。

## 八个工具

| 工具 | 行为 |
| --- | --- |
| `wechat_status` | 返回连接状态、人工审批开关与能力元数据，不返回正文 |
| `wechat_read_context` | 单次最多 6 条、24KB 的授权范围读取，返回加密上下文和分页句柄 |
| `wechat_disclose_context` | 对独立披露权限进行核验；人工审批开启时创建精确内容待批准任务，关闭时在原任务授权范围内自动继续 |
| `axr_execute` | 执行已批准的披露任务，或排入已批准的异步回复计划；重复调用不重新披露或发送 |
| `wechat_prepare_reply` | 保存来源绑定的加密草稿，交由人提交，不调用微信发送 |
| `wechat_submit_reply` | 将本任务已有草稿变成精确计划；默认等待独立 owner 审批，配置和签名任务不完整时拒绝 |
| `wechat_reply_status` | 读取本任务回复计划状态及独立数据库观察元数据，不返回正文，不允许重发 |
| `axr_receipt` | 查询本任务自己的执行回执；旧 epoch 可查询历史回执，不能重新执行 |

前端不接受模型传入的身份、权限、目的地、SQL、密钥或可执行文件。配置中的管道只负责定位服务，连接仍逐次比对真实 OS 服务进程的完整身份。配置里的签名任务凭证不是 owner 权限：它绑定已登记客户端，不能转给另一身份使用。

每个工具请求使用独立认证连接，Windows 服务也允许多个有界认证连接同时存在，以便 helper 在客户端连接期间回连。回复计划在受控后台执行，UI 等待不占用 authority 状态锁。传输失败后不重连重放原请求；结果不确定时保留不可重试状态，重新启动前端也不会恢复已消耗的任务权限。

回复控制器仅在受保护配置提供 `reply_navigation` 时登记：helper 路径/摘要、同一服务 endpoint、已登记私聊的显示标签和固定 UIA 选择器、署名前缀及可选严格布尔 `attribution_required`（默认开启）。helper 必须与部署的 `navigation_helper` 一致。模型不能传入这些参数。一次计划需要不同的停车私聊、完整的读取/元数据/导航/草稿/发送任务范围、来源和目的地；每个实际阶段的 Guard 权限仍精确、单次、短时。当前整体服务准入关闭，配置存在不等于真实发送已可用。

## 人工审批独立开关

所有者配置中的 `application.manual_approval_required` 为严格布尔值，默认 `true`。它独立于授权联系人、任务操作范围、有效期、次数及发送能力。

- 开启：披露和发送计划返回 `AwaitingApproval`，由独立 owner 通道核对精确内容并签名，再通过 `axr_execute` 执行。
- 关闭：已在完整所有者签名任务内的新披露/发送计划可自动继续；authority 仍为精确操作签发短时、单次 Guard 权限，执行前后重新核验，不使用宽泛授权。此前等待人工批准的计划不会自动转为已批准。
- 切换：只允许已登记 owner 通过 `review-approval-setting` / `approve-approval-setting` 完成新鲜挑战签名并密封保存。版本号防止旧审批在多次切换后重放。模型没有修改开关的 MCP 工具。

该开关不改变 Codex 客户端自身的工具确认设置。已新增 Windows 受保护 owner 宿主的固定 `--owner-control` 入口；独立 owner GUI 与 Windows 安装登记流程仍待接通，不能宣称按钮已在桌面上可用。

## Windows 所有者控制入口

`axr-owner.exe --owner-control` 只接受“设置是否需要人工审批”或“核对并批准精确任务”，不接受配置路径、服务地址、脚本或任意待签名正文。原生宿主先检查受保护安装，再读取固定 `runtime/owner-connection.json`。该文件只有 `version: 2`、本地 `endpoint` 和完整 `server` OS 身份固定，不包含客户端任务凭证；由可信部署流程生成，服务重启后需刷新进程固定。配置不能单独授予 owner 角色，服务仍检查登记身份。

本地控制协议使用有界单行 JSON：首先输入 `{"operation":"set-manual-approval","manual_approval_required":false}`；入口向本地界面输出待核对值、版本、期限及 `challenge_id`，收到精确 `{"confirm":"<challenge_id>"}` 才请求本人在场签名。取消、过期、服务 epoch 不符或硬件签名不可用均不改变设置，不重试不确定结果。此输入输出面向可信本地所有者界面，不是 MCP 工具，也不把配置写进 Codex 全局设置。

`{"operation":"approve-job","job_id":"<本任务句柄>"}` 读取服务保存的精确计划并核对 action seal、root、epoch、期限和句柄，向可信本地界面显示审查内容。本人确认挑战后才请求签名；正文只出现在本地所有者审查面，不进入日志或其他 MCP 返回。批准任务与实际执行分开，批准不会立即调用微信。

**Hello 签名代码与登记缺口**：固定 owner 控制入口现使用独立原生 `WindowsHelloOwnerKey`，只打开既有 `Stellaria.AXR.Owner.v2.owner-presence-v2` 凭据，逐次 `RequestSignAsync`，结果再次核对精确挑战签名。原生层在任何 WinRT 调用前检查固定 owner 程序、交互会话、安装及依赖目录的受保护 ACL 和重解析点；普通 Python、服务会话及可写安装不能调用。打开、签名均有时间预算，取消或失败无静默 TPM 回退。

受保护安装需提供单行 `runtime/owner-key.json`：仅含 `version: 2`、`provider: "WindowsHello/RSA2048"` 和已登记 `public_key` 的小写 DER 十六进制。它由后续可信部署/硬件登记流程生成，模型不能提供或修改，控制调用不生成此文件。打开的凭据必须精确匹配公钥固定；服务仍独立核对已登记 owner 身份和签名，文件本身不授权。该接口没有创建、替换、删除、密钥导出或软件密钥功能。

首次创建、硬件证明链验证、可信登记及交互安装启动尚未完成；本轮只编译原生路径并验证调用前拒绝、配置固定和合成签名控制，没有弹出 Hello 或创建密钥，不能宣称真实本人认证通过。旧 `HardwareSigningKey(user_presence=True)` 继续明确拒绝，避免将后台 TPM 签名当成 Hello。

所有者验签现与 authority 根签名分开：Windows 所有者挑战支持规范的 RSA-2048 SPKI 公钥、65537 指数及 PKCS#1 v1.5/SHA-256 签名，同时保留原 P-256 格式；任务凭证和原生执行证明的根验签仍仅支持 P-256。任务授权、执行审查、恢复、应用批准及审批设置均调用独立所有者验签。参考与正式原生构建已用临时合成密钥验证该格式和拒绝分支；签名格式验证不构成 Hello 本人在场或硬件证明，首次登记和硬件证明缺口仍在。格式依据见 [Microsoft Windows Hello](https://learn.microsoft.com/en-us/windows/apps/develop/security/windows-hello)。

## 当前证据与未完成项

本机已通过真实 MCP stdio 与 Windows named pipe 完成工具发现、句柄读取、自动审批模式的单独披露、敏感值遮盖、人工草稿和回执；改变服务进程 birth 身份后拒绝数据调用。数据、签名者、权限与注册均为显式合成 fixture，使用实际原生 Guard/IPC，没有进行微信真实正文披露或发送。

默认人工审批、owner 签名切换、未授权操作拒绝、撤权、过期、跨来源草稿限制和旧 epoch 回执已有针对性回归。owner 控制覆盖本地取消、过期、错误 epoch、无签名提供方及真实认证管道；Windows 管道停止覆盖等待连接、未完成握手和空闲会话，避免跨线程关闭同步 I/O 时卡住。正式原生 SDK/消费者另验证无测试密钥构造器、普通 Python 不能打开 authority 凭据；这些局部结果不替代安装和完整设备验收。

最新完整回归 540 项发现、508 执行通过、32 平台/可选条件跳过（76.769 秒）；参考及正式 UIA/隔离程序构建、参考 CTest 和正式安全检查通过。owner 宿主此前编译通过，缺少已安装运行时及额外启动参数分别明确拒绝。没有创建硬件密钥或重复原库读取。

Windows 原生服务部署、真实所有者与客户端登记、Hello/硬件、原生旧凭据迁移、新入站调度和新独立服务的真实 MCP 闭环尚未完成。应用整体准入保持关闭，没有恢复旧自动回复。Mac 的设备记录与本轮 Windows 接线分别维护，见 [平台状态](../README.md#一眼看清当前状态)。
