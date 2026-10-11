# AXR Gen1 集成与验收

本轮将应用无关 SDK 放在根目录 `AXR/`，微信业务由本项目提供。
原有 legacy 模式继续保留其权限与存储边界，**没有因新增 AXR 自动变安全**。
使用 `server.py --axr-state STATE` 才进入 AET 路径；该模式禁止混用 legacy 管理开关。

## 本地安装和授权

1. Python 3.12，安装原生构建依赖与 `requirements.axr.txt`；Windows 的 wxauto4 只用于 legacy。
Legacy 安装仍使用 `requirements.txt` / `setup.ps1`；AXR opt-in 使用 `requirements.axr.txt` / `setup.ps1 -AXR`，后者须先安装 C++ 构建依赖。

2. 开发构建 `python scripts/build_axr.py --openssl /path/to/openssl3`，生成 Swift / C++ helper
   和 C++20 绑定。pip 安装 AXR 本身也会构建绑定，但不会构建微信 UIA；UIA 要构建根 CMake。
3. 把 `examples/axr.policy.example.json` 或 `axr.database.example.json` 复制到 Git 外的私有目录，
   只绑定主人确认的账号、会话和路径，填写精确 `agent_destination`，三个监听开关默认关闭。
4. 在主人本地终端执行：

```sh
axr-owner --state STATE --helper HELPER init --policy PRIVATE_POLICY
axr-owner --state STATE --helper HELPER grant --principal PRINCIPAL --platform wechat --account ACCOUNT --conversation CONVERSATION --purpose wechat-assistant --operation messages.read --operation messages.search --operation reply.prepare --class personal --ttl 3600 --uses 100
python server.py --axr-state STATE --doctor
python server.py --axr-state STATE --listener
```

WCDB 密钥：`axr-owner ... secret wcdb.test-account`，本地隐藏输入 32 字节 hex。
可读数据库导出亦须授权来源；读取程序不导出全部聊天、不关闭 SIP。
[独立 WCDB 所有者工具](WCDB_OWNER.md) 提供隐藏导入、首个页 HMAC 验证、缓存复核和私聊身份绑定。
Mac 可明确选择临时副本内的 C++20 KDF interposition；保持已安装客户端与 SIP，密钥仅进 OS 凭据库。
该路径已在授权本机取得所需数据库 key；不承诺其他版本、Windows 自动初始化或无主人参与。

本地配置面板：在主人终端运行 `python -m axr_integration.owner_panel --state STATE --helper HELPER`，提供 policy JSON、三个开关、精确审批/拒绝和实际 telemetry。Python 需有 Tk；所有写入仍需系统认证，按钮本身不授予权限。界面尚未实机验证。

所有者 `configure` 会使旧能力失效，并要求重启 broker，防止热改账号/数据源产生身份混用。
监听授权的 workflow 必须与 grant 一致；个人会话读取需 `--class personal`，workspace-normal 不覆盖个人分类。
所有 listener/runner 开关必须为 JSON 布尔值，字符串 false 不代表关闭，会被拒绝。`approve JOB --principal PRINCIPAL` 必须针对当前
密封意图完成系统认证；MCP 返回 AwaitingApproval 只代表待办，绝不是审批。

## 工具与数据流

| 功能 | 接口及约束 |
|---|---|
| 状态/会话元数据 | `wechat_status` / `wechat_find_conversations`，只列明确绑定范围 |
| 检索/聚焦 | `wechat_read_context`，时间、sender、关键词、cursor、limit；返回 context handle，不外传正文 |
| 内容披露 | `wechat_disclose_context` 提议精确 AET，主人另授模型目的地披露能力后 `axr_execute` 返回正文 |
| 回复草稿 | `wechat_prepare_reply`，默认 `【自动回复 · AI 助理】`；主人签名策略可关闭展示，实际 agent 来源仍保留；来源从加密上下文及已披露的加密 scope 元数据派生，不能用空列表或正文 TTL 清洗来源 |
| 发送 | `wechat_propose_send` → 本地批准 → `axr_execute`；稳定账号及会话证据缺失即拒绝，WCDB 不直接发送 |
| 事务管理 | `axr_job_status` / `axr_cancel` / `axr_execute(dry_run=true)`；Unknown 永不自动重发 |
| 工作区 | `axr_workspace_write` 提议受限文本写入，需 workspace authority |
| 回放 | `axr_policy_simulate`，本地过滤规则，模型调用为 0，回放不入队/发消息 |
| 监听与 runner | `--listener` 运行真实轮询线程；listen / wake_agent / auto_execute 独立默认关闭 |
| Runner 继续 | `axr_run_approved_batch` 对已批准的披露运行 owner-pinned 本地沙箱 worker，预算先预留，再生成草稿 |
| 兼容名称 | AXR 模式的 `poll_messages` / `reply_to_message` 全部经过 AET；旧整数 message_id 语义属于 legacy |

MCP 本身不保证唤醒模型。监听先建立历史基线、去重、过滤方向/时效/发送者/关键词，再聚合。
UI 缺少稳定账号/会话 witness 时拒绝正文读取；来源无可验证时间/方向时，不进入主动唤醒。SQLCipher 支持明确的加密 profile 和 WCDB
表型；未知 schema/压缩/群发送者拒绝，不能把读取失败当空消息。

Runner contract：owner-pinned command 从 stdin 读取 `{version, context, instruction}`，stdout
仅返回 `{text}` JSON。Mac 运行时根目录白名单，默认无文件写/网络；模型联网需要额外设计
经过授权的 provider broker，目前没有隐式放开网络。Win 须将独立 runtime 放入专用 staged root，
配置 `windows_launcher`、`windows_runtime_root`；原生 AppContainer 拒绝 root 外执行及 reparse paths。
不得把整个用户目录、策略目录、Keychain/credential store 放入 runtime roots。
`auto_execute` 允许已批准事务继续执行，绝不创造发送 authority；Gen1 runner 当前只输出草稿，
需要单独发送提议和精确批准，不提供 blanket 自动发送。
监听 pending 最多 50 个事件、每条正文 4000 字符，模型 batch 总正文最多 24000 字符；
截断保留来源及标记，预算拒绝负数、非整数和无效窗口，失败调用仍保留已预留的成本。

## 模式与真实范围

| 项目 | WCDB | Accessibility / UIA |
|---|---|---|
| 后台读取 | 原生只读 pager，已提交 WAL 可见；依赖目录权限、正确密钥/profile | 依赖微信版本实际暴露的节点；不承诺锁屏/最小化 |
| 历史范围 | 明确绑定的会话表与 shards，分页游标绑定范围/filters/TTL | 当前可见选定会话；无全历史/时间/sender 承诺 |
| 凭据 | Keychain / Windows Credential Manager，本地录入 | OS Accessibility / UI Automation 权限 |
| 发送 | 不提供 | 仅 owner-qualified 稳定 ID witness + input/header/account 检查 + AXPress/InvokePattern |
| 结果证据 | 读取成功与范围元数据 | 新客户端 bubble + 空 draft；不等同收件人已收到 |

Mac layout 复用 MIT 开源 wechat-mcp 的标识与标题规则，保留完整许可证；没有复用全局 Return
事件发送或仅调用即成功的确认逻辑。SDK 内不包含微信 bundle、数据库 schema 或联系人。

## 本轮证据与未关闭验收

* 原项目 91 个回归测试：通过，1 个原有平台跳过；已迁移 MCP 2.3.0 snake_case API。
* 新增安全/事务/worker/集成测试：本轮本机合计 150 项通过（2 项平台跳过）；上一代码轮双平台 CI 141 项通过。包含真实 SQLCipher 加密合成库、WAL、拒写/错钥，
  原生 helper 提交前撤权/过期/摘要及来源额度检查，以及监听正文/模型输入预算。
  每次提案的 execution_id 纳入 intent seal，取消后旧审批不能授权相同内容的新提案；持久 claim 拒绝同一 execution_id 重放。
* C++20 Core / Swift helper：本机编译及 CTest 通过；SDK 独立安装、外部 CMake consumer 构建通过。
* Mac 沙箱：允许指定 worker/只读 runtime，拒绝白名单外文件；监听中的 loopback socket 在沙箱外可连接、沙箱内拒绝。
* Mac 微信 4.1.15：解锁与 Full Disk Access 后定位 v4 账户目录。临时副本启动观察取得 21 个
  首个页 HMAC 校验 key 并进入 Keychain，覆盖 contact/session 与三个消息分库；24 个候选并未全部覆盖。
  重新校验会排除 salt 已变化的缓存，本轮一次复核保留 20 条。原版 Tencent 安装签名验证通过并恢复运行。
* v4 目录候选与 contact 表唯一匹配账户；指定私聊与本人各绑定唯一 username，排除同名群聊。
  指定私聊近 14 天首个限额页扫描 6 条、解码 2 条文本，方向明确；本人同时间窗口为空。
  在客户端失焦、foreground=false 时重复读取成功，查询结束无保留连接。
* 主人完成 LocalAuthentication 后，短时精确本地只读授权的两个 AET 均 Completed；真实 MCP stdio
  的两个读取也 Completed，审计链有效，返回不含正文，测试访问权限随后撤销。
  无模型披露/发送授权。该证据不代表发送审批或配置面板已完成设备验收。
* 聊天 AX 树仍未暴露；Computer Use 捕获白屏，而主人可见正常聊天列表。
  单微信窗口 ScreenCaptureKit app-to-window 探测也未取得 frame。稳定 UI 身份、输入/提交/送达见证
  不足时拒绝发送；没有盲坐标或全局 Return 兜底，**实际发送未通过**。
  私有账号、联系人、正文、密钥、截图、实际数据库路径不进入仓库或 CI。
* Windows：C++ UIA/Hello（HWND desktop interop，Windows 11 Build 22000+）/AppContainer + 自动化构建路径；本轮按主人要求 **不做微信实机测试**。
  macOS / Windows CI 均完成原生编译、CTest 和 141 项回归（各跳过 2 项平台测试）。
  AppContainer 的合成进程 witness 验证 staged 文件读取、私有文件及 loopback 隔离；
  Hello 所有者认证全过程和微信 UIA/后台行为尚无设备资格证明。
* 所有者 OS 认证与真实读取已验证；发送/披露审批全过程、任意外部模型 runner、多日稳定监听尚未端到端验证。
* 原生只读适配器已完成 1800 秒、714 次后台查询，零错误/保留连接；经历原版退出和恢复登录。
  P95 27.91 ms，RSS 高水位 42.73 → 54.09 MiB，不能外推多日稳定/恒定内存或长期 AET 监听。
  [匿名实机记录](AXR_MAC_ACCEPTANCE.md) 区分私有 bootstrap 成功与正式 CLI 组合流程认证未完成。
* 本轮代码 b4c9cca 的 macOS / Windows CI 均通过；各发现 150 项，分别跳过 2 / 4 项。
* 未提供成熟安装包签名、经过验收的跨平台原生配置 GUI、硬件反回滚、通用跨平台自动取得 WCDB 密钥，
  也未把全部复杂微信版本 schema 或媒体解析声明为支持。

这些限制意味着这是可评审的 Gen1 开发 PR，不能标为完整方案端到端交付。
完整架构的发布门槛仍包括真实账号绑定、指定会话读写、锁屏/重启/切换/并发人工输入、
撤权与审批抢占、成本统计和 Windows 平台验收。
