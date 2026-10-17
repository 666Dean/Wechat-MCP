# Windows 独立服务 MCP 接口

当前六工具是新独立服务的基础接口；Windows 目标还包含与 Mac 一致的完整自动回复、对话绑定与忙闲调度。自动回复适配及新原生桥的单独证据见 [功能对齐清单](WINDOWS_AUTOMATIC_REPLY.md)，不能把本页人工草稿接口当作完整目标已实现。

本轮接线把 MCP 前端接到独立 authority 的 v2 认证管道，不再调用旧 bearer Broker 或在前端打开所有者数据库、凭据和业务适配器。入口为 `server.py --authority-profile <所有者提供的本机配置>`，配置示例见 [Codex MCP 模板](../codex-authority.example.toml)。此模板不安装服务、不登记进程、不签发权限，也不修改 Codex 全局设置。

## 六个工具

| 工具 | 行为 |
| --- | --- |
| `wechat_status` | 返回连接状态、人工审批开关与能力元数据，不返回正文 |
| `wechat_read_context` | 单次最多 6 条、24KB 的授权范围读取，返回加密上下文和分页句柄 |
| `wechat_disclose_context` | 对独立披露权限进行核验；人工审批开启时创建精确内容待批准任务，关闭时在原任务授权范围内自动继续 |
| `axr_execute` | 执行已批准的披露任务；重复调用只返回元数据，不重新披露正文 |
| `wechat_prepare_reply` | 保存来源绑定的加密草稿，交由人提交，不调用微信发送 |
| `axr_receipt` | 查询本任务自己的执行回执；旧 epoch 可查询历史回执，不能重新执行 |

前端不接受模型传入的身份、权限、目的地、SQL、密钥或可执行文件。配置中的管道只负责定位服务，连接仍逐次比对真实 OS 服务进程的完整身份。配置里的签名任务凭证不是 owner 权限：它绑定已登记客户端，不能转给另一身份使用。

每个工具请求使用独立认证连接，给 Windows 的独立 owner 通道保留操作间隙。传输失败后不重连重放原请求；结果不确定时保留不可重试状态，重新启动前端也不会恢复已消耗的任务权限。

## 人工审批独立开关

所有者配置中的 `application.manual_approval_required` 为严格布尔值，默认 `true`。它独立于授权联系人、任务操作范围、有效期、次数及发送能力。

- 开启：披露返回 `AwaitingApproval`，由独立 owner 通道核对精确内容并签名，再通过 `axr_execute` 执行。
- 关闭：已在所有者签名任务内的披露可自动继续；authority 仍为精确操作签发短时、单次 Guard 权限，执行前后重新核验，不使用宽泛披露授权。
- 切换：只允许已登记 owner 通过 `review-approval-setting` / `approve-approval-setting` 完成新鲜挑战签名并密封保存。版本号防止旧审批在多次切换后重放。模型没有修改开关的 MCP 工具。

该开关不改变 Codex 客户端自身的工具确认设置。已新增 Windows 受保护 owner 宿主的固定 `--owner-control` 入口；独立 owner GUI 与 Windows 安装登记流程仍待接通，不能宣称按钮已在桌面上可用。

## Windows 所有者控制入口

`axr-owner.exe --owner-control` 只接受“设置是否需要人工审批”，不接受配置路径、服务地址、脚本或任意待签名正文。原生宿主先检查受保护安装，再读取固定 `runtime/owner-connection.json`。该文件只有 `version: 2`、本地 `endpoint` 和完整 `server` OS 身份固定，不包含客户端任务凭证；由可信部署流程生成，服务重启后需刷新进程固定。配置不能单独授予 owner 角色，服务仍检查登记身份。

本地控制协议使用有界单行 JSON：首先输入 `{"operation":"set-manual-approval","manual_approval_required":false}`；入口向本地界面输出待核对值、版本、期限及 `challenge_id`，收到精确 `{"confirm":"<challenge_id>"}` 才请求本人在场签名。取消、过期、服务 epoch 不符或硬件签名不可用均不改变设置，不重试不确定结果。此输入输出面向可信本地所有者界面，不是 MCP 工具，也不把配置写进 Codex 全局设置。

**当前硬件阻断**：Windows SDK 的 `HardwareSigningKey(user_presence=True)` 仍明确报告 `windows_owner_presence_key_requires_enrolled_hello_provider`；TPM 后台签名不能代替本人在场签名。本轮验证的是真实命名管道加合成所有者签名的控制协议，尚未用真人 Hello 签名修改设置，也未创建或更换机器密钥。

## 当前证据与未完成项

本机已通过真实 MCP stdio 与 Windows named pipe 完成工具发现、句柄读取、自动审批模式的单独披露、敏感值遮盖、人工草稿和回执；改变服务进程 birth 身份后拒绝数据调用。数据、签名者、权限与注册均为显式合成 fixture，使用实际原生 Guard/IPC，没有进行微信真实正文披露或发送。

默认人工审批、owner 签名切换、未授权操作拒绝、撤权、过期、跨来源草稿限制和旧 epoch 回执已有针对性回归。owner 控制覆盖本地取消、过期、错误 epoch、无签名提供方及真实认证管道；Windows 管道停止覆盖等待连接、未完成握手和空闲会话，避免跨线程关闭同步 I/O 时卡住。正式原生 SDK/消费者另验证无测试密钥构造器、普通 Python 不能打开 authority 凭据；这些局部结果不替代安装和完整设备验收。

最新完整回归 502 项发现、470 执行通过、32 平台/链接权限跳过（65.567 秒）；owner 宿主编译通过，缺少已安装运行时及额外启动参数分别明确拒绝。没有创建硬件密钥或重复原库读取。

Windows 原生服务部署、真实所有者与客户端登记、Hello/硬件、原生旧凭据迁移、新入站调度和新独立服务的真实 MCP 闭环尚未完成。应用整体准入保持关闭，没有恢复旧自动回复。Mac 的设备记录与本轮 Windows 接线分别维护，见 [平台状态](../README.md#一眼看清当前状态)。
