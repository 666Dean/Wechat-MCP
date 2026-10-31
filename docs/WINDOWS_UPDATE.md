# Windows 更新与 AXR 人工回信

## 导航配置与可信准入接线（2026-10-31）

新增[导航与准入流程](WINDOWS_NAVIGATION_ADMISSION.md)：首次 Windows 桌面配置可包含 `reply_navigation`；已有部署通过受限 UAC 暂存、System 固定构建审查及既有本人签名更新导航。helper/管道不能从文件导入，私聊 ID 与原生目录再次核对；停止/撤权、取消和候选未批准均不恢复权限。

可信审查者清单可在安装或组件更新时首次显式固定；已有 pin 保留。桌面可查看内存中的未签署材料请求，选择并验证已有签名材料。软件材料不能满足设备门槛；Windows 总准入从固定占位改为核对真实保护部署与绑定签名证据，缺材料继续关闭。全项目软件收尾审计及受约束验收入口仍须完成。本次已从干净实现提交生成并检查 184 文件服务包和 2,392 文件桌面开发候选；完整回归 866/822/44，根 CTest 各 5/5。未安装或进行微信/Hello/模型实验。

## 空闲/前台策略与显式覆盖（2026-10-28）

Windows 新服务已接本人签署的 `immediate`、`when_idle`、`foreground_only` 及 `overwrite_drafts`。固定 owner 交互 helper 返回不含输入内容的活动事实，未知/锁屏/断开时队列保留并等待；空闲只在整笔事务首次导航时准入，后续阶段持续核对精确前台窗口，不因自身输入重置计时而误停。仅前台模式不调用激活；其他两种模式只在初次导航允许一次普通前台请求，系统拒绝或失焦即停止，不重试抢焦点。

草稿覆盖默认关闭，仅使用已签署范围的显式允许；未知/超预算缓存、写前 live 草稿变化仍拒绝，搜索框不覆盖。完整缓存见证、精确比较、永久单次尝试和独立观察继续执行，Unknown 不重发。Windows 后台发送不提供试验放行。原生策略的合成事实检查已加入 Windows CI；完整验证见 [当前状态](STATUS.md)。本次没有真实微信、硬件/Hello、服务安装或联网模型操作，也没有生成新的发行包。设备绑定配置与可信准入流程仍待完成。

2026-10-24 持续适配：已新增正式自包含运行时、管理员安装/按需 SCM、原生凭据导入和有收据的审查恢复；Windows 桌面首次设置与显式恢复、固定 UAC 桥及独立候选包已接线。参考及正式 CTest 各 3/3；180 文件服务运行时与 2,388 文件桌面候选独立检查通过，中文合成布局和隐私扫描通过，未实际安装服务。当前回归计数及证据范围见 [当前状态](STATUS.md)和[安装与恢复](WINDOWS_DISTRIBUTION.md)。完整生命周期、目录申请/扩围、时机/覆盖与准入事实继续推进，整体软件阶段尚未完成。

## 隔离原生 MCP 前端（2026-10-24）

固定 `axr-frontend.exe --mcp` 已接共享六工具协议，先启动同映像的新 AppContainer，实际核对 AAP 访问退出、零网络能力、唯一 SID 和映像，再导入 Python。服务在握手前及接受调用时核对实际 OS 令牌和已登记映像；低完整性命名管道只提供受检传输。工具发现不要求服务在线，操作仅连接固定 System host，失败不重试。

实际合成程序已验证文件/网络隔离、客户端登记和管道双方身份；完整回归 754/711/43，参考及正式 CTest 各 3/3。尚未安装服务或操作微信；完整安装还需为不可写公开运行时配置受限应用只读 ACL，继续安装、迁移与恢复适配。

## 单来源推理原生隔离（2026-10-24）

共享 `WeChatService.infer` 已接 Windows 固定原生来源执行器。每批新建 AppContainer/专用 SID，退出 ALL_APPLICATION_PACKAGES 通用访问，恢复线程前核对真实令牌、唯一 SID、internet-client 能力及映像；固定 AMD64 控制台 CLI/CA 和受保护正式宿主。每次新工作区、无父历史/工具、受控环境与继承句柄，原生层准备并清理私有登录副本，Python 不读取其内容；原始文件和 ACL 不变。单进程/UI 限制、双时钟、撤权、事件预算及来源类型验证均已接线，失败不重放。

合成程序已实际验证工作区读写、拒绝其他来源与原始登录、父环境隔离、拒绝其他程序、中文长路径、junction 拒绝、取消/错误清理及共享审批到草稿的一次链路。正式 SDK 独立验证普通 Python 在配置/凭据读取和启动前拒绝。本机 CLI 的版本/帮助已检查所需公开参数；未使用真实登录或联网模型。完整安装、原生 MCP、客户端登记和恢复仍继续实现，尚不进入微信实机阶段。

## 预授权就绪检查适配（2026-10-23）

继续以最新 Mac 为功能基线，补齐 Windows 预授权检查：通过已接入的受保护 LocalSystem→交互 UIA helper 通道检查登记 owner 的唯一活动会话，不再从服务会话直接启动旧 `status`。helper 和微信程序均核对固定哈希，实际创建 UIA 根和 walker 后才报告可用；无窗口或多个窗口均不可用。检查只返回五个布尔元数据，不读取控件名称、正文、草稿或搜索记录，不切换窗口或输入，不登记任务、不签发/认领权限。普通 stdin/v2 入口不能调用这条预授权路径。

共享 Mac 调度、独立审批和 Windows owner/桌面控制保持接线；双方核对真实进程身份，读写可取消，Unknown 不重发。本轮验证仅含构建、合成通道和未安装/普通进程拒绝，没有获取 System token、创建硬件密钥、部署服务或操作微信。真实跨会话启动、UIA 客户端可用性及完整部署仍待代码阶段结束后独立验收。

下文保留较早流程与历史数字。当前软件验证、剩余代码缺口和平台证据以 [STATUS](STATUS.md)、[全项目清单](WINDOWS_CODE_COMPLETION.md) 和 [MCP 边界](WINDOWS_MCP.md) 为准，整体准入保持关闭。

## 当前 Windows 迭代边界（2026-10-18）

最新要求是先完成[整个项目的代码阶段](WINDOWS_CODE_COMPLETION.md)，再统一实机测试。独立回复控制器、八工具接口、owner 精确计划审查、Windows UIA 导航及合成选聊到数据库观察链路已接通；并发回连、取消和长路径隔离已补回归。仍有完整入站/自动会话、来源隔离提供方、Hello、部署和 GUI 代码缺口，不宣称只差设备验证。下文的历史实机数字不因本次软件变更更新，本次没有微信实机操作。

当前继续按本地 Mac 实现完成全部自动回复功能，包含自动提交；[逐项对齐与证据](WINDOWS_AUTOMATIC_REPLY.md)。本轮新增 Windows 原生 v2 桥与永久尝试标记，502 项全量发现、470 执行通过、32 跳过；真实 UIA 结构无输入控件，选聊/完整调度/硬件签名和真实发送仍待接通。没有通过切换平台标记恢复旧权限。

已同步 2026-10-16 独立安全服务候选架构，六个受控 MCP 工具及独立人工审批开关已实现，固定 Windows owner 控制入口已编译，真实认证命名管道的合成闭环通过；最新全量 502 项发现、470 项执行通过、32 项跳过。Windows 部署、所有者 GUI、Hello 本人在场签名提供方和新服务设备验收仍未完成，旧自动回复路径保持关闭。详见 [新 MCP 接口与边界](WINDOWS_MCP.md)。下文安装与人工回信步骤保留为旧版流程记录，不能作为新安全服务已可用的说明，也不能据此恢复旧权限；当前总状态见 [独立服务状态](INDEPENDENT_SERVICE.md)。

本轮 Windows 原库适配器层复测：微信登录运行期间，SQLCipher/SQLite3mc 各在三个分库扫描 20 条、返回并解码 17 条文本，重复页一致，实际后续一条无重复，三次轮询零错误且连接释放，有限主库/WAL 指纹一致；未观察绑定的新入站。当前 SDK、原生消费者六项合成测试、CTest 及全量 463 项（427 执行通过、36 平台/链接权限跳过）通过，Windows 运行库安装问题已修复。这些结果不证明新 authority 或原生凭据消费者的真实凭据迁移与端到端资格，详见 [本轮测试日记](WINDOWS_WCDB_ACCEPTANCE.md)。

最新小范围设备结果见 [2026-10-13 Windows WCDB 实机测试日记](WINDOWS_WCDB_ACCEPTANCE.md)：已有密钥和独立只读引擎的有界正文读取通过，完整 AXR/MCP/Hello 与实时新入站仍未设备验收。

以已合并的 Mac AXR 方案为基础，复用有界 WCDB 读取、加密收件箱、所有者批准披露、Codex 草稿和人工提交流程。Windows 使用 Credential Manager、Hello helper 和 C++ UIA；Mac 的 Keychain、Swift helper 和启动观察不能直接移植。旧 legacy 的 DLL `-100` 未因此修复；新 AXR 使用 SQLCipher 原生只读 pager。

## 安装

需要 Python 3.12 x64、CMake 3.24+、Visual Studio C++ build tools 和 Windows SDK。Hello desktop interop 要求 Windows 11 Build 22000+ 及可用的所有者认证。使用已安装的 vcpkg：

```powershell
vcpkg install openssl:x64-windows sqlite3:x64-windows nlohmann-json:x64-windows sqlcipher:x64-windows
.\setup.ps1 -AXR -Toolchain 'C:\vcpkg\scripts\buildsystems\vcpkg.cmake' -AXRState "$env:LOCALAPPDATA\wechat-codex-mcp\axr-owner-state"
```

把 vcpkg 路径替换为实际目录；也可用 `-OpenSSLRoot` 指定 OpenSSL 3，但仍需提供其余 CMake 依赖。安装器先安装 SDK，再构建 helper/UIA 并执行 CTest；任一步失败不会生成新的 MCP 配置。不带 `-AXR` 继续安装 legacy。

成功后生成被 Git 忽略的 `codex-axr.toml`，包含 Windows 路径、`--axr-state --listener --manual-replies` 和读取/任务/草稿工具名单。安装器不会修改 Codex 全局设置、初始化 owner state 或授予读取/披露权限。不要同时为同一 state 启动两个 broker。

Windows CI 另在全部检查成功后生成 `windows-axr-runtime-<源码提交>` artifact，供 Python 3.12 x64 环境部署。包只包含 SDK wheel、原生 helper/UIA、SQLCipher/OpenSSL/SQLite 运行库和许可证；`manifest.json` 绑定源码提交/链接与逐文件 SHA-256，不包含所有者配置或状态。下载时核对 workflow 的提交和 Windows job 成功状态、GitHub artifact digest，再核对清单中的全部文件；保留许可证。运行库位于 bin，SDK wheel 可在选定虚拟环境安装。该方式不替代 Hello、所有者初始化或设备测试；部署不自动修改全局设置或发放权限。

```powershell
$TaskPython = Join-Path $PWD '.venv\Scripts\python.exe'
$TaskState = "$env:LOCALAPPDATA\wechat-codex-mcp\axr-owner-state"
$TaskHelper = Join-Path $PWD '.local-private\build\AXR\Release\axr-owner-auth.exe'
& $TaskPython -m axr.owner --state $TaskState --helper $TaskHelper init --policy 'C:\private\wechat-policy.json'
```

私有 policy 以 `examples/axr.database.example.json` 为模板，填入本人确认的账号/私聊、SQLCipher DLL 和分库，保持三个开关关闭。密钥索引和绑定文件只保存在 Git 外的 owner state。参考 [Gen1](AXR_GEN1.md) 和 [所有者 WCDB 初始化](WCDB_OWNER.md)。

## Windows 密钥语义

已有 Windows 首页面实验匹配的是 32 字节二进制口令，须按各库 salt 用 PBKDF2-HMAC-SHA512/256000 派生页密钥；Mac 启动观察得到的是原始页密钥。相同的 64 位 hex 外观不能证明语义相同。

主人在本地交互终端显式选择语义，经过 Hello 认证并隐藏输入；HMAC 不匹配不写入凭据库：

```powershell
& $TaskPython -m adapters.wcdb_owner --state $TaskState --helper $TaskHelper --account-root 'C:\private\ACCOUNT\db_storage' import-key --database 'contact/contact.db' --key-mode password
& $TaskPython -m adapters.wcdb_owner --state $TaskState --helper $TaskHelper --account-root 'C:\private\ACCOUNT\db_storage' import-key --database 'message/message_0.db' --key-mode password
```

每个必要数字消息分库单独导入。`--key-mode raw` 为兼容既有 Mac 使用方式的默认值，不自动猜测。password 模式只保存验证后的每库原始页密钥，索引继续使用 `wcdb4-raw`，缓存再次按 salt/HMAC 复核。原始口令不写入索引，不修改 legacy DPAPI 文件。首页面通过不等于整库正文或账号验证通过。

随后使用明确的 SQLCipher DLL 和精确标签复核联系人/账号：

```powershell
& $TaskPython -m adapters.wcdb_owner --state $TaskState --helper $TaskHelper --account-root 'C:\private\ACCOUNT\db_storage' qualify --sqlcipher-library 'C:\vcpkg\installed\x64-windows\bin\sqlcipher.dll' --account-id 'OWNER_ACCOUNT_ID' --contact 'OWNER_EXACT_CONTACT'
```

将私有 `wcdb-qualified-local.json` 的账号、绑定和数据库配置合入 policy，经本地 `configure` 认证后重启 broker。示例账号和路径均为占位符；工具不自动绑定全部好友、取钥或开启发送。

## 显式选择 SQLite3mc 只读引擎

已安装 AXR 的环境可额外安装 [固定依赖](../requirements.sqlite3mc.txt)，然后在本地 `qualify` 时显式选择引擎；原生 Guard/helper 和所有者认证仍是完整 AXR 流程的必要条件。

```powershell
& $TaskPython -m pip install -r .\requirements.sqlite3mc.txt
& $TaskPython -m adapters.wcdb_owner --state $TaskState --helper $TaskHelper --account-root 'C:\private\ACCOUNT\db_storage' qualify --engine sqlite3mc --account-id 'OWNER_ACCOUNT_ID' --contact 'OWNER_EXACT_CONTACT'
```

生成的私有配置使用 `database.engine="sqlite3mc"`，无需 SQLCipher DLL 路径；不填写 engine 时仍为原 `sqlcipher`。密钥仍须由本地 import-key 验证并保存，连接只使用已归一化的原始页密钥；`hexkey` 的口令派生语义不能直接用于这些页密钥。该语义参照 [SQLite3mc 官方 key 文档](https://utelle.github.io/SQLite3MultipleCiphers/docs/configuration/config_sql_pragmas/)。

当前仅接受 apsw-sqlite3mc 3.53.4.0 / Multiple Ciphers 2.4.0 和 SQLCipher-4 配置；依赖缺失、普通 APSW、其他版本/配置都明确失败，不自动回退。查询保留 5 秒 VM 预算、1001 行/单元格 1 MiB 预算、事务关闭与即时取消。本机适配器的小范围与近期只读测试通过，完整 AXR/MCP/Hello 仍未设备验收；见本页顶部日记。

## 草稿与人工提交

按 [人工回信指南](CODEX_MANUAL_REPLY.md) 在本地终端启动所有者限时会话，另用新 Codex worker 或生成的 MCP 配置。两个 broker 入口择一：

```powershell
& $TaskPython -m axr_integration.owner_codex --state $TaskState --helper $TaskHelper session --ttl 3600 --uses 400 --batches 12
# 另一个终端，沿用相同的 TaskPython/TaskState 路径
& $TaskPython .\scripts\run_codex_manual.py --state $TaskState --duration 1800
```

模型只收到已精确批准的上下文并产生草稿。主人在本地面板核对目标和文字后复制、人工提交；精确数据库记录观察不等于对方送达。安装或 Mac 验收不授予此 Windows 设备的披露/发送权限。

## 验证边界

本次 Windows 本地回归覆盖口令归一化、salt 绑定、错误/篡改页拒绝，以及含中文、空格、美元符号和引号的路径生成 TOML。AXR 缺失时原生用例明确跳过，不使用替代 Guard。原生 SQLCipher 合成口令库的页密钥只读重开/拒写测试交由双平台 CI。

2026-10-12 的本机回归使用 Python 3.14，原生构建工具未在当轮验证，不能据此称为 Python 3.12 或 Hello/微信设备验收。该轮没有读取真实聊天、取钥或发送。后续 Python 3.12 和小范围读取结果见本页顶部测试日记；后台失焦、重启/锁屏、人工提交记录和长时监听仍需分别验收。

`6c674f7` 的 [Mac/Windows CI](https://github.com/666Dean/wechat-codex-mcp/actions/runs/38267106329) 已通过，Windows runner 实际执行完整安装器、SDK 导入和配置/helper 检查。自主读取组件与 WeFlow 主项目的参考定位见 [WEFLOW_REFERENCE.md](WEFLOW_REFERENCE.md)。
