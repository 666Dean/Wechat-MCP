# Windows 更新与 AXR 人工回信

以已合并的 Mac AXR 方案为基础，复用有界 WCDB 读取、加密收件箱、所有者批准披露、Codex 草稿和人工提交流程。Windows 使用 Credential Manager、Hello helper 和 C++ UIA；Mac 的 Keychain、Swift helper 和启动观察不能直接移植。旧 legacy 的 DLL `-100` 未因此修复；新 AXR 使用 SQLCipher 原生只读 pager。

## 安装

需要 Python 3.12 x64、CMake 3.24+、Visual Studio C++ build tools 和 Windows SDK。Hello desktop interop 要求 Windows 11 Build 22000+ 及可用的所有者认证。使用已安装的 vcpkg：

```powershell
vcpkg install openssl:x64-windows sqlite3:x64-windows nlohmann-json:x64-windows sqlcipher:x64-windows
.\setup.ps1 -AXR -Toolchain 'C:\vcpkg\scripts\buildsystems\vcpkg.cmake' -AXRState "$env:LOCALAPPDATA\wechat-codex-mcp\axr-owner-state"
```

把 vcpkg 路径替换为实际目录；也可用 `-OpenSSLRoot` 指定 OpenSSL 3，但仍需提供其余 CMake 依赖。安装器先安装 SDK，再构建 helper/UIA 并执行 CTest；任一步失败不会生成新的 MCP 配置。不带 `-AXR` 继续安装 legacy。

成功后生成被 Git 忽略的 `codex-axr.toml`，包含 Windows 路径、`--axr-state --listener --manual-replies` 和读取/任务/草稿工具名单。安装器不会修改 Codex 全局设置、初始化 owner state 或授予读取/披露权限。不要同时为同一 state 启动两个 broker。

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

本机当前 Python 为 3.14，未配置 C++/CMake 原生构建工具，不能据此称为 Python 3.12 安装或 Hello/微信设备验收。Windows 真实后台读、压缩正文、重启/锁屏、人工提交记录和长时监听仍需分别验收。本次没有读取真实聊天、取钥或发送。

`6c674f7` 的 [Mac/Windows CI](https://github.com/666Dean/wechat-codex-mcp/actions/runs/38267106329) 已通过，Windows runner 实际执行完整安装器、SDK 导入和配置/helper 检查。自主读取组件与 WeFlow 主项目的参考定位见 [WEFLOW_REFERENCE.md](WEFLOW_REFERENCE.md)。
