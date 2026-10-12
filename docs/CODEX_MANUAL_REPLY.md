# Codex 读取、回信任务与人工提交

本轮交付流程：已绑定私聊 → WCDB 有界只读 → 加密任务收件箱 → 经所有者批准披露给 Codex → 完成回复草稿 → 人工核对目标并提交。微信正文始终是外部不可信数据，不能修改权限、执行任意命令或指定新的联系人。

使用根目录 `AXR/` SDK、Python MCP broker 和系统凭据库。本文的微信功能位于 SDK 外，许可证边界保持。Mac/Windows 使用同一 Python 编排和 C++ Guard；Windows 实机证据单独记录。

## 所有者设置

先完成 WCDB 本地初始化与私聊稳定 ID 绑定，详见 [AXR Gen1](AXR_GEN1.md)。在本地交互终端运行；不要经 MCP 或聊天提交密钥：

```sh
python -m axr_integration.owner_codex --state /private/axr-owner-state --helper /path/to/axr-helper setup --ttl 1800 --uses 300
```

CLI 要求系统身份认证，保留原来的账号/私聊绑定，使用 `model:codex` 作为披露目标。设置仅开启监听与回信任务准入，外部 runner 和自动执行关闭。默认仅对含 `AXR测试` 或 `@Codex` 的新入站文本建任务，已发送文本、过期消息、重复事件和历史基线不触发。读取与草稿操作受每目标限时额度约束。

若主人授权一次有时限的工作会话，可用本地所有者控制器：

```sh
python -m axr_integration.owner_codex --state /private/axr-owner-state --helper /path/to/axr-helper session --ttl 3600 --uses 400 --batches 12
```

本次 OS 认证授权控制器在最长一小时、每目标最多 400 额度、最多 12 批的范围内批准任务。每批必须属于既有账号/私聊、固定 principal/purpose/workflow、`model:codex`、配置的数据分类，且不超过 6 条/24KB；控制器验证已加密上下文和精确摘要。它仍签发原生 Guard 的单次、最长 300 秒精确披露批准，不创建微信发送或其他外部动作权限。停止/到期撤权，并在配置未被其他所有者修改时关闭监听/唤醒/自动执行；配置/策略变化立即停止。控制器只在本地交互终端启动，不注册 MCP，不接受聊天控制；达到批次数后停止签发，保留已批准任务至会话停止/到期。

若主人明确更换测试联系人，可在 `session` 后重复传入 `--contact EXACT_LABEL`（包括本人时传本人 ID）。本次 OS 认证先复核既有账号目录与联系人库、Keychain 缓存的 salt/HMAC，再核对每个精确标签唯一对应非群聊稳定 ID；全部通过后替换绑定并撤销旧权限。不重新取钥、启动临时副本或切换微信登录；同名/别名冲突则拒绝且保留原配置。只能从本地所有者 CLI 操作，MCP 不提供换联系人权限。

不用会话控制器时，可逐批批准 MCP 返回的 `disclosure_job`：

```sh
python -m axr_integration.owner_codex --state /private/axr-owner-state --helper /path/to/axr-helper approve --job JOB_ID
```

一次认证最多批准 8 个已快照的精确 intent；认证期间新来的任务不会被加入。只有披露到 Codex 的非 runner 上下文可用此入口。

## Codex MCP 接入与任务

按 [codex-axr.example.toml](../codex-axr.example.toml) 设置本机路径，加入 Codex 配置。启用的工具仅覆盖读取、任务与草稿，不暴露联系人管理、owner/issuer/key 或发送工具。客户端工具调用配置与 AXR 所有者授权是两层机制：允许调用 MCP 不会授予数据披露权限。配置用法依据 [官方 MCP 文档](https://developers.openai.com/codex/mcp/)。

同一 owner state 只启动一个 broker，避免多进程恢复/抢占日志。stdio listener 依附于当前 MCP 连接，Codex 关闭后退出；本地所有者面板/控制器可以并行使用独立 SQLite 连接。不要把 MCP 配置已保存当作当前 Codex 连接已刷新，需实际调用 `wechat_status`。此服务不是自动创建 Codex 桌面任务的调度器。

若需要一个在本轮持续等待回信的 Codex worker，可在另一个本地终端启动：

```sh
python scripts/run_codex_manual.py --state /private/axr-owner-state --duration 1800
```

使用现有 Codex 登录，最长一小时；`--model` 可选择用户已确定的模型，否则使用 CLI 默认。worker 仅连接上述 MCP 白名单，禁用 shell、其他 apps/plugins 和 web；只读环境、临时会话，不保存/打印原始 JSONL 或正文。终端只提示草稿已就绪和计数。消息到来后完成整理和草稿任务，继续等待；外部任务执行不属于此 worker。它和另一个 Codex 客户端不能同时占用同一 state。Windows 使用同一 Python 入口；Codex CLI 与微信实机分别验收。

1. `wechat_find_conversations` 只列所有者绑定；`wechat_request_task` 对指定会话最多读 6 条，返回上下文句柄、数量和披露 proposal。标记 `origin=explicit_read`，不会伪装成新回信。
2. 新回信准入后，listener 将任务加密持久化；没有外部 runner 也不会丢弃。`wechat_poll_tasks` / `wechat_wait_for_tasks` 只返回元数据；等待最长 45 秒，`after={task_id: state}` 等待新任务或状态变化，避免反复返回同一个待批准任务。
3. `wechat_get_task_context` 必须经过精确披露批准；无批准只返回 `AwaitingApproval`，不会输出正文。已完成读取仍重验当前策略/授权，过期或撤权后不能重取缓存。
4. Codex 按主人的任务范围处理内容，再调用 `wechat_prepare_reply`，保留来源 context；用已完成的 draft job 调用 `wechat_finish_task`。后者核对目标、来源、披露和草稿状态，返回 `DraftReadyForHuman`。这是草稿完成，不是微信送达。

任务容量 50，正文/任务有限 TTL、加密落盘。政策或权限版本变化、到期会清理任务访问；任务不因重启变成新的收到消息。聊天内容不拥有 shell、文件删除、账号切换或发送能力。接入 Agent 时应另外根据主人任务限制 Agent 自己的工作区与工具权限。

## 人工提交与读回

```sh
python -m axr_integration.owner_panel --state /private/axr-owner-state --helper /path/to/axr-helper
```

打开 **Manual replies**（F6），刷新后核对精确目标、稳定私聊 ID、正文及 AI 署名。复制按钮在用户点击时重新读取并验证密封草稿，再写入本机剪贴板；不自动粘贴、按回车或调用微信。用户到原版微信核对目标后提交。草稿过期/撤权时不允许复制，不留明文草稿文件。

`--manual-replies` 在 broker 执行前阻断所有 `messages.send`，即使该动作已有批准。主动发送原型仍随项目保留，未资格的 Mac 私有原生路径保持关闭。

人工提交后可调用 `wechat_observe_manual_reply(draft_job)`：独立只读 AET 按完整草稿、本人 sender、目标、创建时间和非零 server_id 查找唯一记录，只返回数量/观察状态。不披露原始正文，不把人工发送写成 Agent 发送，不承诺对方送达，也不自动重发。

## 验证边界

回归覆盖加密持久化、去重/旧消息/出站过滤、无批准不披露、撤权/TTL、跨目标/来源绑定、人工模式禁止已批准发送、精确人工记录观察以及会话控制器拒绝其他目标/预算。合成协议测试、真实 WCDB、真正 Codex 工具调用和人工微信提交分别记录，不能互相替代。
