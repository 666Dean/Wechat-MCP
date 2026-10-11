# 更新日志

格式参考 Keep a Changelog。日期按 Asia/Shanghai 记录；版本号仅表示本项目，
不表示微信客户端兼容性已经得到验证。

## Unreleased

后续每次完成更新，都在这里说明新增、修复、测试及仍未解决的限制；发布版本时归档。

### 2026-10-11 — 157 项双平台 CI 验收记录

- 代码 30a2797 的 macOS/Windows CI 原生构建、CTest、157 项回归全部通过，分别执行 155/151 项、跳过 2/6 项。记录最终代码检查结果，实机 AET 持续测试仍归属实际启动的 1a16221，不声称 GUI、真实发送或多日资格。

### 2026-10-11 — 关闭监听时的 TTL 维护与证据整理

- 1898980 双平台 CI 构建/CTest 及 156 项回归均通过（Mac/Win 分别跳过 2/6 项），外部 SDK consumer 构建运行通过。更新 Gen1 说明中已被后续实测关闭的正式 CLI 认证限制，保持每项证据所属版本。
- 运行监听维护线程时，即使 listen/wake/auto_execute 全部关闭，也清理过期 context/result 和待审批正文；不访问适配器，不删除正在提交的 payload。新增无适配器访问的过期审批与审计回归，本机 157 项通过（2 项跳过）。这是逻辑 TTL 清理，不声称磁盘物理擦除。
- 1a16221 启动的实际 AET 监听线程完成 1800.01 秒/714 个新增 Completed 读取，零失败/保留连接/活动正文 context；审计有效，线程停止、权限撤销与两目标拒绝复核、开关恢复关闭。RSS 高水位 39.95→60.58 MiB，不外推恒定内存或多日资格。锁屏提示后又完成 286 个事务，未连续监测锁屏状态。

### 2026-10-11 — 临时副本厂商签名与缓存格式预检

- 私有副本在 ad-hoc 签名前先执行 Tencent 严格签名验证，并要求 Identifier / TeamIdentifier / CDHash 与复制前原版一致；不同 Executable 路径不影响比较。副本不完整或发生变化时拒绝重签名/启动，清理并恢复原版。
- 私有缓存索引的版本、容器、条目数与 salt/key-reference 类型有界校验，异常结构返回固定 AXR 错误，不能进入凭据获取或产生意外 traceback。
- 本机复制原版后独立验证厂商签名与 CDHash 一致，原安装前后签名一致；该验证副本未重签名或启动并已清理。新增副本变化/缺失或重复签名身份及缓存异常结构回归，本机 156 项通过（2 项平台跳过）。
- 正式取钥完整流程的已通过实机版本为 1a16221；这次新增复制资格环节单独验证，不外推新的全流程、发送、GUI 或多日资格。

### 2026-10-11 — 读取分类、来源访问与单次额度检查

- 明确读取、监听与 policy simulation 的密封意图始终带入所有者绑定的数据分类，个人会话不能借 workspace-normal 授权取得正文；派生草稿/披露的来源访问能力也须覆盖实际来源分类。
- 原生 Guard 将同资源读取的分类查询交给主授权校验，避免把已预留的最后一页当作额度耗尽，也允许精确批准的一次敏感读取完成；其他来源仍复核独立访问/披露权限与额度。
- 集成 broker 与本地配置面板校验监听及 runner 开关必须为 JSON 布尔值，字符串 false、数字或异常容器在接触适配器前拒绝，不能意外开启后台能力。
- 本机 155 项回归通过（2 项平台跳过），含实际 stdio 披露/拒绝与新分类、单次敏感读取、最后一页/原生提交 proof、回放和无数据访问的控制校验。原生 CTest 与 C++ Core 的 ASan/UBSan CTest 通过；sanitizer 仅限定 Core 测试目标，不声称 Swift helper 的 sanitizer 构建资格。
- 当前 30 分钟 AET 监听测试使用启动时的 1a16221 版本，不能归为这次修改的长期实机证据；真实发送、GUI 设备资格与多日运行仍未通过。

### 2026-10-11 — 正式取钥/绑定 CLI 实测及失败恢复修正

- Mac 启动观察在原版签名有效且已正常退出后，即使复制、签名、临时启动或中断发生于创建子进程之前，也清理并恢复原版；检测用户已重新打开原版时不重复启动，签名发生变化时拒绝启动。临时写进程退出后才关闭 FIFO，多个账户共用客户端捕获锁。
- 正式 observe-mac 本次 OS 认证成功，完整取得 21 个 HMAC 校验 key；临时目录与进程最终清理为 0，原版 Tencent 签名有效并恢复登录。正式 qualify 再次独立 OS 认证成功，两个私聊 ID 与先前绑定一致，三个消息分库只读验证；只生成本地配置片段，未开通发送/披露或模型。
- 本机 151 项回归通过（2 项平台跳过）。新增复制/签名/启动/中断失败、用户自行重启及原版签名变化的恢复回归；其故障注入证据不替代微信长期设备测试。
- 真实 UI 发送仍无稳定见证，本人近 14 天无正文，配置 GUI 与多日/锁屏运行资格仍未完成；Windows 本轮无微信实机验收。

### 2026-10-11 — WCDB 所有者初始化与 Mac 实机只读验证

- 微信集成增加独立所有者 CLI：隐藏 key 导入、有限首个页 HMAC 校验、Keychain/Windows Credential Manager 存储、缓存 salt/引用复核、目录候选与 contact 唯一账户绑定、排除群聊/公众号/删除项/重复私聊身份。仅生成私有配置片段，不自动启用 policy、模型或发送。
- Mac 可选 C++20 启动 observer：主人认证并明确选择私有临时副本，原 KDF 参数与结果保持不变，0600 FIFO/128 记录/120 秒封顶，只存 HMAC 校验 key；清理自有副本进程并验证、恢复原安装。应用专属代码在 SDK 外，Windows 仅支持已有 key 本地导入。
- 实机发现新版 WCDB 压缩标记 4/5，修复为普通 Zstd；2/3 字典模式明确拒绝。完整单 frame、编码/解码/窗口限额阻止截断、尾随内容和解压扩张。
- Mac 实机初次取得 21/24 个候选 key（必要 contact/session/三个消息分库均覆盖）；复核会排除 salt 变化项。两个私聊稳定 ID 绑定通过，指定私聊有真实文本读回，本人近 14 天为空；后台失焦重复读取成功，连接及时释放。所有者 OS 认证及实际 AET/MCP stdio 两会话读取 Completed，审计有效、代理回执无正文；短时读取授权已撤销。
- 本机 150 项 unittest 通过（2 项平台跳过），原生构建/CTest 通过。新增错误 key/首个页篡改/代际变化/路径与预算/索引换 key 或路径/私聊与账户歧义/完整 Zstd/observer 等价及 FIFO 权限回归；Mac CI 执行 observer 合成 fixture，Win 平台跳过。
- 保留限制：本机 AX 聊天树与捕获画面缺失，真实发送仍未通过；本人正文为空不视为读写读回成功；多日/锁屏/客户端切换与发送审批、模型 runner、配置 GUI 尚未资格验证。Windows 按本轮要求无微信实机测试。实机数据、私钥、账号路径与副本二进制不进入公开提交。
- 后续验收记录：代码 b4c9cca 的 macOS/Windows CI 均通过原生构建、CTest 与 150 项回归（分别跳过 2/4 项）。原生只读适配器完成 1800 秒、714 次查询，零错误/保留连接，P95 27.91 ms；包含原版正常退出与恢复登录，RSS 高水位 42.73→54.09 MiB。新增匿名实机记录，明确不外推长期 AET 监听、恒定内存或多日资格。正式 observe-mac 再次实测未完成 OS 认证，没有进入 capture；与已成功的私有 bootstrap、资格函数及 OS 认证读取分开记录。

### 2026-10-11 — Stellaria AXR Gen1 开发与安全边界

#### 新增

- 根目录 AXR/ 应用无关 SDK：C++20 Guard、AET intent seal、OpenSSL AES-GCM/HMAC、持久链、进程 API、Python 薄绑定；Swift 通用 AX helper；Win C++ Hello 与 AppContainer。
- 从主人 GitHub 的 BasicX-Hub/BasicX/Connector 实际抽取固定提交的预算、append-only triggers、耐久日志、进程管理与沙箱原语；REUSE.json 记录源文件 SHA-256/符号。没有导出计算 DAG、SOF/SPX、渲染、模型 Provider 或 DCC 源码。
- SDK AGPL v3 only，项目其他源码保留 MIT，README/LICENSE/LICENSES/NOTICE 明确边界与第三方义务。
- 独立 owner CLI / 本地 Tk policy/审批/telemetry 面板 + Keychain/Windows Credential Manager；代理不能发放 capability；principal/account/conversation/purpose/workflow/TTL/quota 全部绑定，外部发送与披露逐动作确认。
- AXR MCP、AET 执行与取消、加密 context/result TTL、会话来源传播、dry-run/模拟、metadata-only 审计和计数；legacy 兼容名称在 AXR 模式走 AET。
- 原生 SQLCipher 只读 WCDB DB+WAL、明确会话/分库、过滤与 keyset 游标、Name2Id 稳定发送者解析、bounded zstd。复用 MIT chatlog-keeper 的选定解析规则与 wechat-mcp 的 AX 标识/标题工具，保留完整许可。
- Swift AX / C++ STA UIA 有界读取及发前身份检查；稳定账号/会话 witness 不足时拒绝发送，没有坐标/全局 Return 兜底。
- 常驻监听实际线程，listen/wake/auto_execute 默认独立关闭，历史 baseline、聚合/TTL/去重、调用/成本预算；owner-pinned 本地 runner 同样进入精确披露 AET，仅生成草稿。
- 受限 workspace 文本原子写入/加密版本备份；Mac deny-default worker sandbox，Win AppContainer/JobObject；跨平台 CMake、独立 SDK 安装导出、Python 原生构建与 CI。

#### 修复与验证

- MCP 迁移至官方 Python SDK 2.3.0 / MCPServer，更新 snake_case 测试 API；保留旧模式行为。
- 修复事务插入列数、Swift throwing predicate、worker runtime ancestor stat 权限等开发期问题；发送不明/旧 epoch/崩溃恢复均拒绝重复执行。
- 本机 141 项 unittest 通过（2 项平台跳过）：原有 91 项 + 50 项安全、合成数据库、原生沙箱与实际 stdio AET 测试。
- 真实 SQLCipher 库对合成加密 DB/WAL 验证 committed WAL 可见、原始密钥拒错、只读拒写；这不等同本机微信正文验证。
- C++ Core/Swift 编译与 CTest、SDK 安装、独立 CMake consumer 通过；Mac 实际 sandbox 拒绝范围外文件与 loopback 连接。
- Win CI 加入 AppContainer 真实进程合成 witness：staged 文件读取、私有文件拒绝与 loopback 拒绝；这是 CI 验证，不是微信实机测试。
- Win CI 随 PR 运行；本轮按主人要求不做 Windows 微信实机测试。

- PR 后续修正：可信 Swift/UIA helper 在实际读取/平台提交之前复核 broker 的 grant 摘要、策略版本、墙钟 TTL 和来源额度；私有管道不传 issuer key，不把 metadata proof 声称为公开认证协议。增加原生/Python 撤权、过期、改摘要和来源额度测试。
- Windows CI 实际发现 Hello interop 的 get_abi 返回 void* / HSTRING 类型错误，按官方 ABI 显式转换；dependency cache 在依赖构建后保存，编译失败不再丢失已构建依赖。
- PR 后续修正：监听每条 4000 字符、pending 50 条，runner 总正文 24000 字符；预算拒绝负数/非整数/无效窗口；owner grant 可明确授权 personal 本地草稿分类。独立 SDK 安装包含 AGPL/NOTICE/源复用和第三方许可。
- PR 后续修正：TTL 清理将过期的待审批/Ready 任务置为终态并去除正文，保留正在提交事务直至核验/恢复；Swift/UIA 原生回复生成前限制单节点与总正文，保留截断标记。新增 TTL/崩溃恢复测试。
- PR 后续修正：SDK wheel 和独立安装补齐 pybind11 编译头的 BSD 全文；独立 Windows helper 安装也保留实际链接 DLL 的依赖 copyright。
- PR 后续修正：Mac draft 核验只读取真实 AXValue，空值不会被标题/描述替代；无法读取 draft value 时拒绝提交。C++ Core 新提交前复核路径通过本机 ASan/UBSan；独立 wheel 在全新 venv 验证 crypto/Guard/Swift helper 与许可文件。
- 验证入口强化：显式指定的 SQLCipher 库不存在时测试失败，不能通过平台跳过掩盖 CI 配置错误。
- Windows SDK 已完成 MSVC 编译；CI 暴露 install 阶段对系统 DLL 路径分隔符匹配错误，现按 CMake CMP0207 归一化并兼容两种分隔符，避免递归打包 Windows 系统依赖。
- Windows wheel/install、UIA/Hello/AppContainer 编译及 CTest 均已运行通过；真实 CI 回归暴露 pywin32 JobObject 不接受 None name，改为每次随机唯一名称，并使用 PyHANDLE.Close 正确释放、对配置失败清理句柄与进程。
- 隐私修正：已经披露的来源保留加密的 coarse scope/class 元数据，正文 TTL 或 broker 重启不会清洗后续输出的 provenance；不保留聊天正文历史。新增到期/重启及空 context_ids 草稿测试。
- Windows native AppContainer 的 staged 文件读取在 CI 直接 probe 已运行成功；移除重复 JobObject 后 supervised bootstrap 仍失败，正在核查启动环境。仍由原生启动器在恢复线程前强制配置 JobObject，并由 parent 退出关闭 handle 终止子进程。
- 审批修正：每个 Action 的唯一 execution_id 纳入原生 intent seal；Journal 原子登记持久 execution claim，取消/正文 TTL/重启后也不能重提同一 ID。旧审批无法迁移到内容相同的新任务；新增取消后的审批复用与持久重放测试。开发期旧意图缺字段时拒绝执行，须重新提案与审批。
- Windows Supervisor 保留系统用户 profile 路径环境供 AppContainer 初始化，不传密钥或服务配置；原生失败仅输出白名单 stage 与整数错误码，继续拒绝沙箱降级。
- Windows worker/JobObject 超时及输出上限回归已通过；CI 使用与 wheel 一致的 Release helper/probe，避免依赖不可分发的 Debug CRT；沙箱保持拒绝降级，新增纯元数据 stage/exit 诊断。
- Windows CI 已验证 profile 环境修复后的 AppContainer 受管启动、staged 文件读取与私有文件拒绝。loopback 探针的阻塞 connect 在 WFP 丢包时超时，改为非阻塞 select + SO_ERROR，最多 1.5 秒；仍要求同一端口的沙箱外控制连接成功，不能用 worker 超时当作网络隔离通过。
- CI run 38080631671（cf7d64a）：macOS / Windows 原生 SDK、UIA/Hello/AppContainer 编译、CTest、141 项回归均通过（各 2 项平台跳过）。Windows AppContainer 实际合成进程验证受管启动、staged 文件读取、私有文件及 loopback 隔离；Hello 人类认证和微信 UIA 仍待设备验收。更新 README/STATUS/SDK 文档与 PR 证据，保留 Draft。
- PR 后续修正：监听分页同样进入 AET/账号租约/额度与提交前复核；本地基线 context 在处理后删除，仅 admitted batch 留待精确披露审阅。保留末页高水位便于增量读取，非文本媒体正文不取出 SQLite。
- 新建纯 legacy venv 安装 requirements.txt 后 93 项发现结果通过（3 项跳过，含 2 个可选 AXR 测试模块），证明 opt-in 路径无原生编译依赖。
- PR 后续修正：数据库 interrupt/close 生命周期加锁；所有者可显式关闭展示前缀，但密封意图中的 agent 来源仍保留。Win dependency binary cache 加入 CI。
- PR 后续修正：每页完成后释放原生数据库连接，避免 Windows 持久句柄阻止微信分库轮换/替换；保留 generation/salt 变化检测与只读 pager。
- Windows CI 实际发现 UIA SetValue 的 BSTR 类型错误，改为 SysAllocStringLen / SysFreeString；原生 SDK 改成显式 opt-in requirements.axr.txt / setup.ps1 -AXR，保留只装 Python 的 legacy 安装路径，未安装 SDK 时仅跳过其可选测试，原生加载错误仍失败。
- PR 后续修正：Win 构建显式 UTF-8 / Windows API 版本；wheel/helper 安装收集运行时 DLL 并保留依赖 copyright，避免 Python 3.8+ DLL 搜索规则导致 native import 失败；Windows CI 同样加载 SQLCipher 做加密合成库验证。
- PR 后续修正：披露意图绑定 context digest，本地终端/面板显示实际待披露内容，不能只用 opaque handle 代替精确审阅。
- PR 后续修正：原生 Windows path/argv 按 UTF-8 转换，避免中文用户名/目录错误；SQLCipher 查询增加 5 秒 VM 进度上限，关闭服务时取消 runner；模型尝试与成功结果分开计数。
- PR 后续修正：按 Microsoft 桌面应用文档使用 HWND / IUserConsentVerifierInterop，替换依赖 UWP CoreWindow 的 Windows Hello 调用；保持设备无可用验证方式时拒绝。

#### 未关闭的验收

- Mac 微信 4.1.15 没有暴露聊天 AX 树；增强 AX 失败、调试 capability 被系统拒绝（未读内存），数据目录被 macOS 权限拒绝；后续 GUI 测试又遇到锁屏。
- 尚未取得/验证本机微信数据库密钥，指定会话读写与稳定身份映射、后台/锁屏/人工并发、OS 所有者审批、Windows 平台行为及长期 listener/runner 端到端均未通过。
- 没有成熟安装签名/经过验收的原生配置 GUI/硬件防回滚/自动密钥初始化；Gen1 不提供 blanket 自动发送。完整架构发布验收仍开放，提交为开发 PR。
- 本轮不发布账号标识、联系人、聊天内容、密钥、实际数据库路径、实机截图、私有仓库整树或第三方二进制。

### 2026-10-10 — 开源数据库读取路线评估

- 新增 docs/OPEN_SOURCE_READERS.md：固定提交核对 chatlog-keeper、wxq、wechat-cli-local 的许可证、页解密、WAL 和分页实现；首选评估 chatlog-keeper 的密钥模式判别与校验逻辑。
- 记录候选的逐页校验/提交边界差异、Windows 快照锁及整库重新解密开销；更新下一步验证顺序，不将开源 README 的兼容声明作为本机证据。
- 本项目 91 项回归测试通过。仅静态阅读候选源码，未安装或执行候选，未新增真实数据库读取、发送或可用后端；0.6.1 消息 -100 阻塞仍存在。

## 0.6.1 — 2026-10-10

### 新增与修复

- 在使用者明确授权下，将 EchoTrace 已保存的数据库密钥仅在本机转存为 DPAPI 凭据；私有配置只绑定一个选定私聊，发送关闭。一次性转存脚本未纳入仓库，没有新增自动提取密钥的产品接口。
- 添加 .local-private/ 排除规则；凭据、私有配置、账号/联系人标识、诊断原文和聊天正文不纳入提交。
- 修复原生清理异常覆盖初始打开/查询错误的问题；关闭句柄失败后仍尝试 shutdown 和 DLL 目录清理，不重试可能部分销毁的句柄，错误不携带原生私有细节。
- 单页验证及会话查询 CLI 保留首个查询错误，单独报告 cleanup_error；即使查询成功，清理失败也非零退出。

### 验证与限制

- Windows / Python 3.14.7 / mcp 1.30.0：`python -m unittest discover -q`，91 项通过（此前 86 项 + 新增 5 项），覆盖清理异常/状态码、打开错误保持和 CLI 查询/清理双重失败。
- 本项目真实加载现有 WCDB DLL，账号打开、会话查询及显示名查询成功，选定私聊唯一名称匹配；这只是配置目录绑定，不是原生账号认证。
- 同一绑定私聊 limit=20 与 limit=1 的消息查询均返回 -100，没有收到可验证正文；关闭原生连接又出现异常。内部原因未知，未将失败转成空消息或成功读取。
- DPAPI 密钥转存成功；未建立消息基线或回复队列，未发送微信消息、未启用近期窗口。原生异常只在独立验证进程观察，进程已退出；错误处理修复用合成回归验证，不代表第三方 DLL 故障已修好。
- 没有实测文本解码、方向、排序、实时增量延迟、Python 3.12 或远程 CI 证据。详细边界见 docs/DATABASE_READER.md。

## 0.6.0 — 2026-10-10

### 新增与修复

- 新增显式选择的近期窗口 scan_mode=recent，按固定 15 分钟资格边界裁剪历史扫描；保留重叠分页和两次稳定检查，观察到逆序、超限或持续变化时不推进状态。full 仍为默认，兼容省略字段的旧配置。
- 状态与轮询报告 scan_mode；近期窗口基线、已见身份与入队仍在同一事务提交，数据库来源始终强制预览。
- 新增 --probe-database-messages 和 --probe-limit：只读一个已绑定会话的一页，最多 50 条；仅输出统计，不输出正文/消息身份，不创建状态库、不入队。前后核对绑定，失败非零退出并清理句柄。
- 更新数据库配置模板、验证说明与功能状态，区分近期窗口、完整对账和未实现的分库游标。

### 验证与限制

- Windows / Python 3.14.7 / mcp 1.30.0：`python -m unittest discover -q`，86 项通过（此前 76 项 + 新增 10 项）。
- 合成 1 万条旧消息以 page_size=4 建立窗口基线只读两页；重启后新增一条近期消息只读四页，预览保存与去重通过。验证逆序、超限、不稳定窗口、事务回滚、旧配置及单页 CLI 清理/不输出正文。
- 使用 computer-use 查看本机 EchoTrace 3.0.2：从备份模式切到实时模式后会话摘要更新到近期；打开一个私聊显示消息数量，但正文为空。未将该现象视为文本解码或本项目读取成功。
- 本项目未加载真实 WCDB DLL、未读取现有软件密钥、未连接真实数据库或发送微信消息；没有 Python 3.12 重验或远程 CI 证据。
- recent 要求使用者先验证原生全局时间降序；ABI 不保证此排序，旧页乱序无法检测。它不覆盖历史补录、不实现分库高水位游标，减少调用次数不证明 DLL 内部开销或真实延迟下降。

## 0.5.0 — 2026-10-10

### 新增与修复

- 新增 `list_reply_queue` MCP 工具：无需 UI/DLL 连接即可分页查看有效本机消息和已保存预览；按 ID 翻页，返回草稿阶段、过期时间及未核对实时身份标记。
- UI 预览也写入现有队列，支持重启查看与修改；两种后端的轮询均跳过已有草稿，避免反复生成。发送开关变化不会自动发送草稿，数据库仍强制预览。
- 队列查看重新检查本机授权和时效，排除其他账号、已撤销绑定、expired/dismissed/sent/unknown 消息；没有增加历史披露接口。
- 新增本机 `--list-database-sessions`，输出会话 ID/显示名与重名、改名和排除项诊断，丢弃原生摘要，不调用消息查询、不修改绑定、不创建状态库；失败关闭句柄并返回非零退出码。
- 默认 MCP 工具数量从 5 增至 6，显式开放名单管理后为 7；更新 README、状态、认证和隐私说明。

### 验证与限制

- Windows / Python 3.14.7 / mcp 1.30.0：`python -m unittest discover -q`，76 项通过（此前 61 项 + 新增 15 项）。
- 新增草稿重启/修改、分页期间删除与新增、离线 UI/数据库隔离、规则撤销、过期/未知结果过滤、外账号隔离、会话摘要剥离和 CLI 成功/失败清理测试；真实 stdio 传输验证新增工具。
- 未连接真实微信、未加载真实 WCDB DLL、未查询真实联系人或现有密钥、未发送微信消息；本轮未重验 Python 3.12，没有远程 CI 证据。
- 队列分页是实时视图，不是固定快照；离线查看不验证实时身份。原有大历史对账限额、分库游标、常驻监听、模型调度和前端限制仍在。

## 0.4.0 — 2026-10-10

### 新增与修复

- 新增独立 WCDB ctypes 读取后端，固定 EchoTrace v3.0.2 ABI，明确 DLL/账号入口；原生错误显式失败，UTF-8 返回指针统一释放，打开失败清理句柄。
- 配置账号与规范目录绑定、显式会话 ID/唯一显示名绑定；重名、改名、账号变化、入口替换停止处理，不自动读取未授权会话正文。
- 新增持久会话基线与分来源已见身份；首次仅建立基线，重启不重放历史，新增身份与预览队列在同一事务提交。
- offset 分页加入重叠及两次稳定对账；截断、身份缺失或持续变化时不推进基线。过期使用原生时间，过滤自身、非文本、未知方向和压缩内容。
- 数据库事件接入既有 poll/reply/dismiss 工具和联系人规则；回复强制预览并保存草稿，不调用 UI 发送。
- 新增本机交互密钥 CLI、当前用户 DPAPI 加密及账号路径绑定；不提供 MCP 凭据工具、不自动提取现有软件密钥，防止配置/凭据/数据库路径混用。
- 追加列迁移兼容 0.3.x 队列，保持中断 sending 转 unknown；新增配置模板、使用文档并维护状态与认证说明。

### 验证与限制

- Windows / Python 3.14.7 / mcp 1.30.0：`python -m unittest discover -v`，61 项通过（原有 34 项 + 新增 27 项）。
- 包括合成 ABI、消息流、持久化/事务、人工测试密钥 DPAPI 与真实 stdio 协议中的合成数据库到预览调用链。
- 未加载本机真实 WCDB DLL、未读取真实聊天或现有密钥、未发送微信消息；本轮未重验 Python 3.12，没有远程 CI 证据。
- 当前是有界全量对账后持久去重，尚无高效分库游标/一致快照；大历史超限会失败。账号来自本机配置与路径检查，非原生身份认证。
- 全好友常驻监听、AI 调度、前端、压缩内容解码、账号级互斥和数据库 ID 到发送目标映射仍未实现。

### 2026-10-10 — EchoTrace 读取方案参考分析

- 对照 EchoTrace v3.0.2 公开源码和本机发行文件，记录备份/实时读取、原生接口、消息身份及文件变更监听机制。
- 新增数据库读取接入设计，明确账号/会话绑定、持久游标、增量去重、新增凭据与读取/发送分离要求。
- 文档引用固定源码版本；检查本机 DLL 导出名称和文档链接，未执行第三方二进制或读取真实聊天及密钥。
- 本次只更新文档，未重新运行既有代码测试；数据库读取、全好友监听和新界面仍未实现，未将参考分析当作功能完成。

## 0.3.0 — 2026-10-10

### 新增与修复

- MCP 默认不注册 `set_reply_contacts`；Bridge 层在未授权时也拒绝写入，且不改变配置或队列。
- 新增启动参数 `--allow-contact-management`，仅对需要管理名单的可信客户端开放写入；配置热加载不能开启该能力。
- 本机 `--set-contacts` 和交互脚本仍可修改名单，运行中的服务在下一次工具调用加载。
- 状态接口新增 permissions，明确报告 stdio、当前管理能力及未提供所有者身份认证。
- 新增认证说明，按源码梳理组件、请求流程、凭据/token 生命周期及第三方依赖边界；同步 README、SECURITY 和状态矩阵。

### 验证

- Windows / Python 3.14.7 / mcp 1.30.0，隔离虚拟环境：
  `python -m unittest test_bridge test_settings test_runtime -v`，29 项通过；
  `python -m unittest test_mcp -v`，5 项通过；合计 34 项。
- 新增 3 项回归测试，验证默认写入拒绝、配置不能授予管理能力，以及真实 MCP stdio 子进程隐藏并拒绝该工具；显式开放后的名单修改、清空和输入校验仍通过。
- 只使用模拟微信适配器，未安装或运行 wxauto4，未读写真实微信；本轮未重验 Python 3.12 实机环境。安装要求仍为 Python 3.12 x64。
- 本地 diff 和待提交文件检查通过；远程 CI 尚未启用。

### 兼容性与剩余限制

- 已有 MCP 客户端若使用名单写入工具，需要显式添加启动参数并重启；其他工具和本机 CLI 不需开启该权限。
- 启动开关是能力授权，不是所有者认证；开放后仍需信任客户端，拥有文件/shell 权限的客户端可直接修改本机配置。
- 仍无账号身份绑定、全好友监听、常驻 AI 调度、草稿保护或数据库加密；消息中包含秘密时也会明文留存。
- 第三方二进制内部凭据处理与真实微信兼容性未审计或验证。

## 0.2.0 — 2026-10-10

### 新增与修复

- 同一规范状态数据库路径使用操作系统排他锁，拒绝重复 MCP 服务；进程异常退出后释放锁。
- 联系人 CLI 独立于运行数据库，可在服务运行时修改名单；所有工具调用前重新加载配置。
- 配置通过字段校验、独立进程锁和原子替换保存；无效配置阻止继续处理。backend/state_file 变更要求重启。
- 轮询仅返回当前聊天的待回复消息；15 分钟过期消息及被撤销资格的消息移出队列，避免旧消息遮挡新消息。
- 重新建立基线时保留仍有效的已入队消息；重启发现 sending 时转为 unknown，禁止盲目重发。
- 更新交互脚本、测试命令、功能状态和隐私边界说明。

### 验证

- Windows / Python 3.12：`python -m unittest discover -v`，31 项全部通过。
- 包含真实 MCP 子进程通信、外部 CLI 热加载、重复服务拒绝及模拟进程崩溃释放锁。
- 所有微信操作使用模拟适配器；没有读取或发送真实微信消息。远程 CI 尚未启用。

### 未完成与未知

- 仍无全好友后台监听、常驻 AI 调度、真实微信兼容性证据或草稿保护。
- 运行锁按数据库路径隔离，不是账号级互斥；硬链接和网络文件系统未验证。
- 配置编辑器不遵循程序锁；完整名单替换采用最后成功写入结果，没有版本冲突提示。
- 过期状态不会删除聊天文本；数据留存控制仍未实现。详见 [状态说明](docs/STATUS.md)。

## 0.1.0 — 2026-10-10

### 已实现

- 标准 MCP stdio 服务：连接状态、轮询消息、回复、忽略消息、查看与更改备注名名单。
- `wechat://policy` 资源与 Codex 助理身份前缀、首次介绍。
- 可见私人会话的 Windows 客户端适配器，以及独立模拟适配器。
- 指定名单主动代回复；其他好友仅明确呼叫 Codex 时进入回复队列。
- 默认名单为空；PowerShell 交互输入、CLI 和 MCP 更改名单。
- MCP 更改名单持久保存并在当前服务立即生效；移除联系人时撤销普通待回复消息。
- 默认预览、历史基线、自发消息及非文本过滤、发送间隔、15 分钟消息过期限制。
- SQLite 回复状态与发送结果不明时禁止盲目重试。

### 开源整理

- 增加 MIT 许可证、功能状态矩阵、未知问题、测试记录及贡献指引。
- 安装脚本改用使用者的 Python 3.12 x64，移除特定机器的默认路径。
- 示例配置与运行配置分离，忽略个人名单、数据库、日志和生成的 MCP 配置。
- 加入可复现的 MCP 模拟集成测试与未启用的 GitHub Actions 模板。
- 在 AGENTS.md 记录每次更新同步 GitHub 并维护日志的要求。

### 验证

- 16 项自动测试通过：14 项规则测试及 2 项 MCP 集成测试，覆盖 6 个工具、联系人管理及策略资源。
- 未进行真实微信读取或发送测试，未验证最新版微信兼容性。
- GitHub Actions 模板已编写，尚未启用；当前只有本地测试证据。

### 未完成与未知

- 未实现全部好友后台监听、无人值守 AI 调度、群聊或多媒体处理。
- 手动切换聊天、输入草稿、锁屏、重启后的连续性及账号平台影响未验证。
- 未实现独立权限认证、硬性隐私语义审查及准确的对话对象判断。
- 详情见 [功能状态与未知事项](docs/STATUS.md)。
