# Windows 更新与 AXR 人工回信

## 当前 Windows 迭代边界（2026-10-18）

已同步 2026-10-16 独立安全服务候选架构，当前完整 MCP 接线与 Windows 部署、Hello 和设备验收仍未完成，旧自动回复路径保持关闭。下文安装与人工回信步骤保留为旧版流程记录，不能作为新安全服务已可用的说明，也不能据此恢复旧权限；当前总状态见 [独立服务状态](INDEPENDENT_SERVICE.md)。

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
