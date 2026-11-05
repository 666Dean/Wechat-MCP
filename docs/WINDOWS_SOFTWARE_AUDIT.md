# Windows 软件阶段收尾审计

2026-11-05 后续纠正：独立分发回归发现旧 Windows 安装摘要缓存会在同大小/时间戳组合碰撞时复用旧内容摘要，已删除缓存并验证逐次全量 SHA-256。下方 `4372e20` 历史审计不能作为该条件的保证。新的原生遍历/SDK 修复和干净 `31d6a0a` 新候选分别通过完整 913/872/41、CTest 各 7/7、新包 14 项、正式 SDK 快速修改 32/32 拒绝及全部冻结/内容/隐私检查；见[分发证据](WINDOWS_DISTRIBUTION.md#内容重新校验)。当前客户端 provider/搜索条件、保护部署及真实设备材料仍未通过，软件记录不等于设备准入。

2026-11-04，按[完整代码清单](WINDOWS_CODE_COMPLETION.md)完成新独立 authority 的 Windows 代码、模块接线、构建、离线回归与冻结分发审计。实现基准为 `4372e20140d224c41a48951608e10102af911601`。本结论限本清单定义的软件阶段，不继承 Mac 实机结论，未运行真实微信、Hello/TPM、SCM 安装、凭据迁移或联网模型。

最终完整回归 898 项发现、857 通过、41 条件跳过（118.333 秒）；参考/正式根 CTest 各 5/5，125%/150% Qt 各 25 项。该干净提交的 186 文件服务包与 2,394 文件桌面候选通过实际正式运行时/隔离 EXE 启动、合成渲染、模块归档、冻结 QML/正式 SDK 一致性、全部文件哈希及隐私检查；新服务包另跑 13 项分发回归通过，1,360 个 Python 归档项无私密路径。交付目录的 `verification/summary.json` 记录聚合证据，不包含真实身份或聊天。

## 入口与调用者

| 范围 | 现有调用链与拒绝边界 | 离线证据入口 |
| --- | --- | --- |
| 正式启动及运行期准入 | 原生 `--service` → `authority_main` → `wechat.release_gate/create_authority` → `WindowsAdmissionKernel`；仅当前真实保护部署和可信设备材料可运行，失效撤权 | `test_windows_admission`、`test_windows_service` |
| 首次安装、初始化、恢复与组件更新 | 桌面固定 UAC → 安装器/SCM → setup/recover/refresh/reconfigure；硬件证明、配置/构建 pin、原生迁移和独立 owner 交互签名；不恢复授权 | `test_windows_distribution`、`test_windows_setup_desktop`、`test_windows_setup_recovery`、`test_windows_lifecycle`、`test_windows_owner_setup` |
| 六工具原生前端及八工具事务 | 固定前端 LPAC → 实际 OS 客户端登记 → 认证管道 → MCP/Windows dispatcher；正文读取与披露分开、精确待办审批 | `test_windows_frontend`、`test_authority_frontend`、`test_authority_mcp`、`test_windows_service` |
| 入站、分页、追赶、去重、合批 | Windows 继承最新共享 `WeChatService`；新入站按来源有限子任务，队列和游标持久化，重启不恢复待执行许可 | `test_wechat_service_v2`、`test_security_actor`、`test_windows_service` |
| 单来源推理与本人 Codex 任务 | 固定 AppContainer/独立 SID、受控临时登录副本、固定 CLI/CA、来源输出预算、无父历史/工具；owner bridge 单独处理本人任务 | `test_windows_source`、`test_wechat_service_v2`、`test_windows_service`、`test_owner_agent_bridge` |
| 联系人目录与授权申请 | 原生有界目录 → `windows_contacts` → owner 审查/拒绝/签名扩围；申请不发放权限，预算/期限不重置 | `test_windows_contacts`、`test_windows_service_desktop` |
| 导航配置 | `windows_navigation.prepare` → 桌面首次设置/受限导入 → System refresh → 固定 owner 完整审查；目录和 helper/端点再次核对 | `test_windows_navigation_configuration`、Qt 按钮回归 |
| 时机、草稿与完整回复 | Windows 活动事实 → 签名策略 → `ReplyExecutor` → 缓存/搜索见证 → 精确比较 → 永久单次认领 → 独立观察；Unknown 不重发 | `WeChatSendPolicy`、`test_windows_service`、`test_authority_reply`、`test_native_chat_state` |
| 可信材料与运行期失效 | 固定审查者 pin、未签署请求、受限导入 → 启动 gate 与双时钟 `RuntimeAdmission`；软件声明不能通过设备门槛 | `test_windows_admission` |
| 受约束设备验收的次序 | 桌面选择已签计划 → UAC → `--qualify-service` → `authority_qualify` → `wechat.qualify_once` → 单次 owner 审查和受限场景；不提供普通 MCP/调度、不产出设备通过结论 | `test_windows_qualification`、`test_windows_owner_setup`、Qt 确认回归 |
| 桌面、冻结与运行时 | 桌面 setup/恢复/范围/偏好/任务/目录/导航/准入/验收入口均有调用者；服务/桌面候选由固定脚本生成，执行隔离 runtime-check/合成渲染 | `test_desktop_ui`、`test_windows_service_desktop`、`package_authority_windows`、`package_desktop_windows` |

上述表是对已有项目模块和 Mac 共享调用链的收尾核对，不以一个通过的回归替代全项目实现。legacy Broker、旧参考 API 和 Mac 自己尚未接通的演示入口，不作为 Windows 新 authority 的可执行能力。

## 固定拒绝与疑似占位核对

- `WindowsWeChatService.background_qualified() == False` 是 Windows 后台发送拒绝边界；签名范围即使有限，也不开放后台试验，不是待改为 True 的占位。
- `windows_navigation.build_update`、`wechat.provider_build_update`、联系人存活检查的 False 是参数/进程/受限更新校验失败，不是缺少实现。
- `_WindowsNavigationProcess.wait()` 的空返回是原生通道 facade：`terminate/kill` 同步调用原生 `channel.close`，真实等待/清理在原生 `WindowsNavigation`/交互进程持有者内；不回退普通 System `Popen`。
- `empty_saved_draft` 的最终 False 拒绝把未知或非空缓存认作空；空来源 `infer` 的 None 表示无记录、不调用模型。
- 信任根普通更新不支持轮换、未知硬件/保护安装/凭据路径拒绝、缺少导航/owner 绑定时不能发送，均为明确安全边界；未通过设备条件不伪装成功。
- 新的验收入口有原生 SCM、固定 Python hook、桌面、UAC、owner 审查、Guard 与退出清理调用者；不以一个无调用者的 permit 类冒充完成链路。

## 仍须保留的设备与运行证据边界

真实跨会话 UIA、客户端控件路径与账号身份、Hello/TPM/AIK、保护 ACL 与 SCM、真实凭据迁移、联网隔离来源模型、真实新入站和发送及独立观察，仍须在软件阶段结束后由本人另行批准验证。源码/编译/合成程序/离屏 Qt/冻结 EXE 导入和启动不能代替这些记录。

既有 19 个 GC 退出警告没有在本轮修复；不据此宣称多日运行稳定。普通 Windows 发布准入仍关闭，没有真实可信设备材料，不发布生产 Release。
