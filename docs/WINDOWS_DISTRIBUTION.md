# Windows 安装、迁移和恢复的软件边界

2026-11-05 后续：分发检查暴露并修复了 Windows 安装内容的元数据摘要缓存漏检，详见[内容重新校验](#内容重新校验)。先前候选保留历史/夹具范围，不能作为修复后组件或完整安全保证；`f071ff1` 新生成候选也因独立分发 13 项中 1 项失败而未通过，新 SDK/服务/桌面输出单独记录，不覆盖旧包。

修复后已从干净 `31d6a0a5c2af6781f19cef62fc53b1b5ef655e22` 独立生成 `service-uia-integrity-20261105` 和 `desktop-uia-integrity-20261105`，在既有指定交付根目录中保留新目录。服务 186 文件、桌面 2,395 文件全部重算哈希通过，正式 helper/SDK 与最新构建一致，冻结解析器/QML、隔离 EXE 真实启动/中文合成渲染及 1,362 归档项隐私检查通过。新包独立 14 项分发回归通过，另在正式 SDK 实际验证 32 次修改全部拒绝；桌面设备命令实际为 Blocked/NotRequested、服务 Absent。没有安装或恢复任何旧授权，完整文件夹和 _internal 必须一并保留。新汇总是 `verification/uia-integrity-freeze-summary-20261105.json`，不使用早期 summary.json 代替本轮证据。

2026-11-04：已完成[代码清单](WINDOWS_CODE_COMPLETION.md)定义的代码、接线、构建、离线与冻结分发阶段，以下仍是软件入口和离线证据，不是设备执行记录。本轮没有安装服务、Hello 或微信验收；后续须本人另行安排。

最新候选基于干净实现 `4372e20140d224c41a48951608e10102af911601`：`service/` 186 文件，`desktop/dist/WeChatMCP/` 2,394 文件，桌面入口为其中 `WeChatMCP.exe`，需要保留整个目录。逐文件哈希、正式 SDK、冻结入口/QML、隔离 EXE 实际启动/合成渲染与隐私检查通过；新服务包另跑 13 项分发回归，桌面 1,360 个 Python 归档项无私密路径。保存根目录由本人指定，`verification/summary.json` 记录聚合证据。未安装、压缩或发布 Windows Release，下文旧候选数字保留原日期。

2026-10-31：Windows 首次桌面安装要求选择导航元数据；配置准备从已审查组件包固定 helper 哈希。已有部署另有停止后导航导入/本人构建审查入口。可信审查者公钥清单可首次安装时选择，或通过组件更新首次补入；受完整安装清单和本人配置签名固定，普通更新保留既有 pin。签名准入材料独立验证/导入，不改变包、不恢复授权或自动启动服务。详见[导航和准入](WINDOWS_NAVIGATION_ADMISSION.md)。取得所有者指定保存根目录后，已从干净提交 a60f3d6 生成并独立验证 184 文件服务包和 2,392 文件桌面开发候选。新包的 13 项分发回归、正式 SDK 一致性、隔离启动、中文合成渲染、入口导入及 1,357 个 Python 归档项隐私检查通过；尚未安装或发布，不能作为设备资格。

## 公开运行时

2026-11-06 桌面打包补充：桌面 Python 搜索路径原先只固定正式 SDK；源码目录存在参考原生消费者时，PyInstaller 可能将其收集为桌面模块。首个 ACL 桌面候选经独立哈希核对被拒绝且未安装。打包现在同时固定服务包的 `axr` 与 `axr_applications`，设置分析工作目录和 PYTHONPATH，并在模块图生成后将两个原生扩展的收集来源显式固定到正式输入。仅暂存或调整搜索路径仍可能被模块图选中源码扩展，相关候选均被输出哈希核对拒绝并保留失败目录。

最终干净桌面代码 `27c28e8`、组件代码 `80bc087` 的新候选为 186 文件服务包和 2,396 文件桌面。全部桌面文件重算哈希、两个原生扩展与正式服务包一致、真实隔离运行检查（含 `windows_formal_consumer=true`）、合成中文界面及 1,362 归档项隐私检查均通过，已查看截图；新服务包另有 14 项分发检查通过。核对 editable 环境实际 SDK 路径并同步本次参考构建后，全量 913/872/41（129.808 秒），19 个既有 GC 警告保留；原生 46 项 ACL 判断及两套根 CTest 8/8 独立通过。汇总位于既有 verification 的 `api-final-freeze-summary-20261106.json`。这些是软件/分发证据，不是本人认证、原生凭据迁移、MCP 业务或设备准入结论。

`python -m scripts.package_authority_windows` 从正式 Release 构建生成新的暂存目录。必需参数为 `--build`、`--dependencies`、`--output`、`--vc-runtime` 和 `--vc-notice`。输出目录必须不存在；VC 参数指向本人构建工具的 x64 CRT 目录和发行说明。

打包前独立加载正式 SDK/消费者，验证普通宿主不能取得凭据、来源执行或修改身份查询 ACL。包包含固定 authority/owner/frontend/验证宿主、UIA、隔离 Python 3.12、应用源码、pywin32、Zstandard、SQLCipher 及所需运行库和许可证。静态解析 AMD64 PE 的普通/延迟导入，只从显式构建/依赖目录解析非系统 DLL；不使用调用者 PATH，也不把缺失依赖视为成功。同名 SQLite 固定为一份 vcpkg 运行库，并通过真实嵌入式 Python 检查。

独立 `axr-runtime-check.exe --validate-runtime` 只验证导入、压缩、SQLite 和正式构建边界，不能访问正式凭据/硬件根或启动 authority。通过后生成逐文件 SHA-256、源码提交及是否存在未提交修改。公开包不包含账号、状态、凭据、聊天、Hello 配置或供应方 Codex 程序。CI 单独上传 `windows-formal-authority-<提交>`，参考 SDK 包继续使用其原名称。

## 安装和服务

`python -m scripts.install_authority_windows` 是显式管理员入口，要求已核对的包、私有配置及本人选择的 Codex 原生程序和公开 CA；Hello 默认为本机计算机证书根，仍可显式提供限定根集合。它不会自行提取凭据或自动取得管理员权限。安装目标由 OS Known Folder 固定为 Program Files 下的 `Stellaria AXR`；账号旁置配置位于 ProgramData 下同名目录，owner SID 只有读取权限，受限应用没有访问权限。所有者状态固定为其 `state/wechat` 子目录。

代码目录由管理员/System 控制，普通用户和受限应用只有读取/执行权限。复制使用 NT 相对句柄与逐文件哈希，复制后再次核对完整清单。新增 `installation-review.json` 固定 Python、DLL、原生程序和本地公开来源组件；正式原生宿主同时验证保护 ACL、无 reparse、单链接文件类型和完整内容。每次校验通过所持只读句柄重新流式计算 SHA-256，不凭文件 ID/大小/时间戳复用旧摘要。OwnerDeployment 另固定该清单的哈希，替换依赖也需要新的本人构建确认。

### 内容重新校验

2026-11-05：此前的摘要缓存包含卷/文件 ID、大小、CreationTime、ChangeTime 和 LastWriteTime，但 Windows 时间戳不是内容世代号。32 次同大小内容修改并复原 mtime 的本机合成实验中，23 次整组时间戳相同，均错误复用了旧摘要。前次全量通过及单次时间戳测试无法证明该缓存安全；独立分发回归已将其判为失败，没有修改测试以迁就缓存。

现已移除进程内摘要缓存。每个清单项都重新打开只读句柄、拒绝普通并发写入/删除，核对类型/单链接/大小并读取实际全部字节进行 SHA-256。原清单覆盖、未知文件/reparse/预算拒绝以及保护 ACL 均保留；内容核对和保护部署仍是独立条件，不声称一次校验持续锁定整个运行时。

新增快速修改回归，修复后 32/32 修改拒绝、完整 Python 913/872/41（115.276 秒）、参考/正式全目标重建与根 CTest 各 7/7；19 个既有 GC 退出警告保留。约 33.8 MB/187 文件复制夹具的三次校验耗时为 46.865/39.040/39.793 ms，不是实际受保护安装或长期负载测试。旧含缓存的 SDK/宿主/服务/桌面包不当作包含本修复；必须使用随后独立核对的新包并沿既有本人构建审查流程推进，不恢复任何任务授权。

命令 `python -m scripts.windows_service` 仅接受 `status/register/initialize/refresh/recover/reconfigure/qualify/start/stop`。注册固定 LocalSystem、独立进程、按需启动的 SCM，拒绝其他映像/账号或自动启动。维护/验收结束后恢复普通服务命令但不自动启动；验收另要求独立可信有限计划与本人精确签名，见[边界](WINDOWS_QUALIFICATION.md)。失败/取消/超时不自动重做，注册本身不授予权限。当前 SCM 回归使用模拟，没有注册或启动真实服务。

现已新增固定 `reconfigure` 模式和桌面生命周期按钮。更新先停止服务，查询到固定原生客户端仍运行时要求先关闭；不自动终止用户程序。更新后单独核对新构建，首次设置则继续初始化。临时目录完整复制/更新测试验证原公钥与历史文件保留，顺带更换凭据源会拒绝；这不构成真实 SCM、映像更新竞态或旧进程关闭的设备验收。

`reconfigure` 只读取固定 ProgramData 请求，由原生 System authority 先检查受保护 bootstrap 确实不存在，再检查既有公钥 pin、MAC 配置收据和历史；部分空初始化还必须通过原生保护的初始审计。只允许更改 `credential_import` 引用/显式模式或旧命名空间，账号、数据库/盐、代码/CA、owner 与状态目录均保留。不导入/替换密钥、不删除历史，不允许管理员根据不可读状态自称空账本。请求与固定结果绑定 owner、nonce 和配置原始哈希，旧请求、丢失结果及异常均不自动重试。

停止后的更新保留原状态目录和精确 Hello 公钥固定，不复制旧连接身份或恢复授权。旧代码保留为受保护备份；新构建需要固定 owner 窗口审查和既有 Hello 签名。更新在审查前撤销旧权限；取消也不会恢复。安装和更新都不修改 Codex 全局配置。

## ProgramData 祖先目录兼容性

2026-11-06：本人授权通过现有 API 部署。正式安装入口已完成受保护组件与旁置配置安装；后续配置校验在本机 `ProgramData` 的 Users `0x116` ACE 上拒绝。该 ACE 含创建文件/目录、写扩展属性与写属性，没有删除子项、删除目录、改 ACL 或所有者权限。先前对所有祖先沿用应用对象的属性写拒绝，造成安装完成却无法继续初始化。未修改系统目录 ACL。

Windows 原生 ACL 校验现独立为可测试策略。仅对保护对象的祖先排除四个具体权限位 `FILE_ADD_FILE`、`FILE_ADD_SUBDIRECTORY`、`FILE_WRITE_EA`、`FILE_WRITE_ATTRIBUTES`；`FILE_DELETE_CHILD`、`DELETE`、`WRITE_DAC`、`WRITE_OWNER`、`GENERIC_WRITE`、`GENERIC_ALL` 继续拒绝非受信主体。应用代码根、应用数据根、配置文件和全部代码内容仍使用完整写拒绝；应用数据根此次显式作为保护对象，不能套用祖先规则。所有者信任、未知 ACE、重解析点、链接与逐文件内容核对保持原规则。

微软分别定义了[目录与文件的具体访问权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-access-rights-constants)；创建旁置项和修改祖先元数据不等于对已保护子项的访问权。这里的祖先含有不可由普通用户删除/替换的保护子项，因此不能被清空；[FSCTL_SET_REPARSE_POINT](https://learn.microsoft.com/en-us/windows-hardware/drivers/ifs/fsctl-set-reparse-point) 对非空目录拒绝设置重解析点。路径本身仍逐级检查重解析点，不接受已有重定向。

新增 46 项由 Windows 解析真实 SDDL 的合成判断，覆盖本机 ACE、保护对象拒绝、六类危险权限及组合、受信/非受信所有者、NULL DACL 与仅继承 ACE。参考/正式全目标构建与根 CTest 各 8/8 通过；配置完整原生夹具后的 Python 全量 913/872/41（117.095 秒），19 个既有 GC 警告保留。新正式 SDK 在独立进程只读验证实际安装、部署路径和原配置一致；未运行本人初始化、凭据原生导入、模型或微信业务。新包更新和后续设备结果单独记录，不能用旧安装器成功或本次 ACL 修复宣称服务/设备通过。

## 服务错误回执

2026-11-06 后续：事件版服务已实际更新，真正初始化仍失败，已在 OS Application 日志采集到 owner-bootstrap 失败元数据。先前白名单遗漏原生现有 `hello_` 码族，通道因此仍可能只显示通用码；现补齐该族，并仅把无法保留原文的常见 Python 异常映射为固定类别。已知机器码保留，未知类名、路径及字段名不导出；不改变实际失败或认证/准入。新包的具体 owner 错误另行采集。

2026-11-06：本人继续后已实际完成修复版更新，服务登记为按需启动、当前停止；但首次初始化在本人审查/Hello 窗口出现前退出，SCM 只提供 1066/1。服务进程没有可用的调用者 stderr，因此原先无法据此区分具体失败原因。更新后的 MCP stdio 启动仍为 `0xC0000022`，没有取得初始化或业务响应。

原生固定宿主退出时生成有界、仅元数据的回执：操作、Completed/Failed、筛选机器码、结束时间与进程号。异常路径、换行、任意消息、账号样式及纯 hex 值不导出；非已知前缀或超预算异常变成固定通用码，不记录 stdout、审查正文、凭据或 traceback。回执仅写固定保护数据目录的 `service-last-result.json`，同时用 [RegisterEventSourceW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-registereventsourcew) / [ReportEventW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-reporteventw) 向本机 Application 日志写同一份筛选后的元数据，没有更改事件源注册表或系统 ACL。日志写入失败不改变实际终态。

控制器仅在 SCM 已报告失败时，才允许使用严格字段、4096 字节预算、同一模式及本次开始/当前时间范围内的失败回执解释错误。缺失、损坏、过期、未来、其他模式、额外字段或伪造成功记录均退回原通用失败；该文件不参与身份认证、签名、权限、准入或成功判定。合成检查不启动真实服务、不改变系统日志或认证状态。两套根 CTest 各 9/9、相关 Python 14 项以及最终完整 917/876/41（117.446 秒）通过；首次全量的既有异步用例超时保留在私有验证记录，复测未放宽断言。诊断服务包另经 14 项分发检查并实际更新，随后初始化失败文件回执为 `windows_owner_setup_denied`；Application 事件未独立确认，不把未出现窗口或这一通用码当成唯一原因证明。

## 初始化身份查询

2026-11-06：原生 owner 必须在显示配置审查和 Hello 之前，核对 System 管道对端的映像、签名、用户及 token 身份。代码中原先仅在初始化后的 `create_authority` 给 owner 开放查询权限，形成首次登记次序缺口。现在在 bootstrap 创建描述符及启动 owner 之前，仅给固定登记用户 `PROCESS_QUERY_LIMITED_INFORMATION` 和 `TOKEN_QUERY`。正式入口仍核对固定保护 System authority 和整个安装；该步骤没有 LPAC ACE、token 复制/模拟身份、内存访问或任务权限，不跳过 owner 审查、Hello、响应验签或准入。

同一变更新增有界传输阶段与 Win32 数字错误码，失败仍按原协议结束，不自动重试。合成测试核对 owner 精确权限、LPAC ACE 不变和正式构建拒绝普通宿主；参考/正式根 CTest 各 9/9，完整 Python 917/876/41（120.460 秒）通过，既有 GC 警告保留。此顺序修复尚待新包实机验证，不能据此宣称登记或凭据迁移成功，也不解决另存的 MCP `0xC0000022`。

## 原生凭据迁移

2026-11-06 初始化排障补充：`c8ca4f0` 已实际更新，随后一次登记仍为 FailedSafe/`windows_owner_setup_io_os_109`，没有凭据迁移成功证据。stderr 原型只验证同会话，因 Windows 禁止 Session 0 跨会话继承句柄已撤回，未用该版初始化。现保持原无句柄继承启动，固定 owner 失败退出时仅向 OS Application 日志的 `StellariaAXROwner` 来源写六项筛选元数据，保留内部机器错误；不注册日志源或改 ACL。事件投递是可选诊断，不改变失败退出、对端身份、Hello、签名或授权，也不记录审查、路径、账号或密钥。实际采集另记。

Windows 已实现 `import_owner_credentials`。文件格式可以是 64 位 hex 原始页密钥、`{"keys": {"<salt hex>": "<key hex>"}}`，或显式带 `version: 1`、`key_mode: "raw"/"password"` 的盐映射。向导也可显式指定纯 hex 文件解释方式，不改写或在 Python 中解析原文件；与 JSON 内声明冲突时拒绝。口令模式按每个 salt 做 PBKDF2-HMAC-SHA512/256000；不猜测模式。原生层核对文件哈希、类型、单链接、预算及所有分库的实际解密，先验证所有目标及既有凭据冲突，再写入 System 原生凭据库。OS 写入中断可以留下相同的部分项，重跑不得替换冲突项。没有原始 key 返回 Python/MCP。

旧 keyring 迁移明确绑定登记 owner SID 的唯一活动会话，用该登录 token 进行局部原生 `CredReadW`，只接受对应名称及有效 base64 格式，返回前恢复线程身份。没有 Python 回调在模拟身份下执行；缺少该会话/凭据时不回退 System 或其他用户。实现依据 [WTSQueryUserToken](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsqueryusertoken) 和 [CredReadW 的登录会话语义](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credreadw)。本轮未获取 token 或读取真实 keyring；正向证据目前限于原生文件导入的加密合成库，跨用户迁移须随后独立验收。

## 初始化恢复

有受保护 MAC 配置收据的中断初始化可以重新审查同一配置、精确构建和既有 Hello 公钥。恢复路径只打开该既有凭据，不创建/替换密钥；缺失 pin 只能由已验证收据恢复，格式错误或不同的既有 pin 保留拒绝。空初始账本可以继续完成，已完整持久化但 bootstrap 尚未发布的阶段还须验证独立审计/完整性，且不能有旧任务、授权、内容、披露或执行记录。

硬件创建成功但尚无配置收据或 pin 时，另有显式 `recover` 一次性服务入口：拒绝历史状态及任何既有 pin，只打开既有凭据，原生审查显示实际公钥 SHA-256，并重新核对 TPM2/AIK、完整构建和签名。普通初始化失败不会进入此路径；不会创建、替换或删除密钥。首次登记及恢复的构建摘要已同时进入挑战与 MAC 收据，完成前再次核对。

## 桌面安装与公开证书

Windows 向导已接本机原生 Codex 选择、登录状态检查、数据/凭据元数据准备、明确密钥解释方式、公开组件选择、安装、初始化与显式孤立恢复。管理员操作通过固定程序的 UAC 入口完成；请求位于 OS ProfileList 指定 owner 的固定私有缓存，绑定操作、owner、随机 nonce 和 SHA-256。提权端只允许固定安装/服务操作，不接受脚本、shell、目标目录或任意输出文件。超时/丢失结果返回 Unknown，不重试。初始化和启动共用一次管理员操作，已初始化仅表示不重复创建；七项实际就绪检查仍独立进行。

公开 TLS CA 从 `LocalMachine\ROOT` 只读导出，原生证明验证使用同一计算机根库作为 exclusive roots，不接受 CurrentUser 根或对端根。仍检查证书用途、TPM2 公钥绑定、链、有效期和吊销；这依赖本机管理员管理的 PKI，不能称为供应商根白名单。实现依据 [Windows 证书存储位置](https://learn.microsoft.com/en-us/windows/win32/seccrypto/system-store-locations) 与 [exclusive root 配置](https://learn.microsoft.com/en-us/windows/win32/api/wincrypt/ns-wincrypt-cert_chain_engine_config)。该准备不读取任何私钥，不修改证书库，也不创建 Hello 凭据。

桌面候选打包入口为 `python -m scripts.package_desktop_windows --components <公开组件目录> --qt-notices <Qt/PySide 6.10.2 上游许可目录> --output <不存在的新目录>`，要求 Python 3.12 x64、PyInstaller 6.22.0 与 PySide6 6.10.2。公开组件与正式 SDK 一起冻结，候选记录源码是否有未提交修改；不包含本人配置、登录、凭据或供应方程序。动态 Qt 替换说明与原许可一并提供。该入口不会安装、提权、联系模型或初始化硬件；版本发布和完整生命周期界面仍随项目清单继续完成。

当前候选已验证 2,388 文件、正式 SDK、Qt 6.10.2、独立运行时、中文真实字形及合成截图，并查看中文布局；1,350 个 Python 归档项与原始文件扫描未发现用户/构建路径或外部链接。构建机 vcpkg 的 ICU 不能遮蔽 Qt 所需的 Windows 系统 ICU；离屏测试显式登记本机中文 TTC 字体，不复制/发行系统字体。此证据不等于其他 Windows 版本、机器字体、硬件或微信控件验收；[Qt 平台基线](https://doc.qt.io/qt-6.10/supported-platforms.html)与 AXR 设备要求须分别核对。

生命周期补充后的候选为 2,389 文件、1,352 个 Python 归档项，181 文件服务运行时、独立启动/中文字形/合成渲染与隐私检查通过；已查看 Windows 维护界面并用实际 Qt 按钮确认取消不提权。完整回归 814 项发现、773 执行通过、41 跳过，参考及正式 CTest 各 3/3。仍没有运行真实提权、SCM、硬件、模型或微信；设备绑定配置准备和最终准入事实还在整体软件清单中。

本轮无真实微信正文读取、输入、发送、服务部署、Hello 或模型调用。临时文件/模拟 SCM 的成功不证明管理员 ACL、SCM、跨用户凭据或真实硬件可用。

2026-10-28 联系人接线检查点：开发服务包为 182 文件，桌面开发候选为 2,390 文件/1,353 个 Python 归档项，独立启动、中文渲染及隐私检查通过。Windows 公开前端现为共享六工具加两个申请/查询工具；目录刷新与本人审查/拒绝入口已有接线，申请不授予权限。包仍为软件阶段开发候选，未执行安装、服务、硬件、联网模型或微信验收，也未发布 Windows Release。
