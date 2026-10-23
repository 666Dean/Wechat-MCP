# Windows 安装、迁移和恢复的软件边界

当前仍在全项目软件适配阶段，以下是代码入口和离线证据，不是实机执行记录。完成[代码清单](WINDOWS_CODE_COMPLETION.md)前，不运行服务安装、Hello 或微信验收。

## 公开运行时

`python -m scripts.package_authority_windows` 从正式 Release 构建生成新的暂存目录。必需参数为 `--build`、`--dependencies`、`--output`、`--vc-runtime` 和 `--vc-notice`。输出目录必须不存在；VC 参数指向本人构建工具的 x64 CRT 目录和发行说明。

打包前独立加载正式 SDK/消费者，验证普通宿主不能取得凭据、来源执行或修改身份查询 ACL。包包含固定 authority/owner/frontend/验证宿主、UIA、隔离 Python 3.12、应用源码、pywin32、Zstandard、SQLCipher 及所需运行库和许可证。静态解析 AMD64 PE 的普通/延迟导入，只从显式构建/依赖目录解析非系统 DLL；不使用调用者 PATH，也不把缺失依赖视为成功。同名 SQLite 固定为一份 vcpkg 运行库，并通过真实嵌入式 Python 检查。

独立 `axr-runtime-check.exe --validate-runtime` 只验证导入、压缩、SQLite 和正式构建边界，不能访问正式凭据/硬件根或启动 authority。通过后生成逐文件 SHA-256、源码提交及是否存在未提交修改。公开包不包含账号、状态、凭据、聊天、Hello 配置或供应方 Codex 程序。CI 单独上传 `windows-formal-authority-<提交>`，参考 SDK 包继续使用其原名称。

## 安装和服务

`python -m scripts.install_authority_windows` 是显式管理员入口，要求已核对的包、私有配置及本人选择的 Codex 原生程序、公开 CA 与 Hello 证书根。它不会自行提取凭据或自动取得管理员权限。安装目标由 OS Known Folder 固定为 Program Files 下的 `Stellaria AXR`；账号旁置配置位于 ProgramData 下同名目录，owner SID 只有读取权限，受限应用没有访问权限。所有者状态固定为其 `state/wechat` 子目录。

代码目录由管理员/System 控制，普通用户和受限应用只有读取/执行权限。复制使用 NT 相对句柄与逐文件哈希，复制后再次核对完整清单。新增 `installation-review.json` 固定 Python、DLL、原生程序和本地公开来源组件；正式原生宿主同时验证保护 ACL、无 reparse、文件身份和完整内容。缓存绑定真实文件 ID、大小、创建/变更/修改时间，同大小且重置 mtime 的修改仍拒绝。OwnerDeployment 另固定该清单的哈希，替换依赖也需要新的本人构建确认。

命令 `python -m scripts.windows_service` 仅接受 `status/register/initialize/refresh/recover/start/stop`。注册固定 LocalSystem、独立进程、按需启动的 SCM 服务，拒绝其他映像、账号、自动启动或交互服务。初始化/更新通过固定一次性服务参数运行，成功后恢复普通服务入口；失败、取消、超时不会自动重做。注册本身不启动服务或授予权限。现阶段仅使用模拟 SCM 回归，没有注册或启动真实服务。

停止后的更新保留原状态目录和精确 Hello 公钥固定，不复制旧连接身份或恢复授权。旧代码保留为受保护备份；新构建需要固定 owner 窗口审查和既有 Hello 签名。更新在审查前撤销旧权限；取消也不会恢复。安装和更新都不修改 Codex 全局配置。

## 原生凭据迁移

Windows 已实现 `import_owner_credentials`。文件格式可以是 64 位 hex 原始页密钥、`{"keys": {"<salt hex>": "<key hex>"}}`，或显式带 `version: 1`、`key_mode: "raw"/"password"` 的盐映射。口令模式按每个 salt 做 PBKDF2-HMAC-SHA512/256000；不猜测模式。原生层核对文件哈希、类型、单链接、预算及所有分库的实际解密，先验证所有目标及既有凭据冲突，再写入 System 原生凭据库。OS 写入中断可以留下相同的部分项，重跑不得替换冲突项。没有原始 key 返回 Python/MCP。

旧 keyring 迁移明确绑定登记 owner SID 的唯一活动会话，用该登录 token 进行局部原生 `CredReadW`，只接受对应名称及有效 base64 格式，返回前恢复线程身份。没有 Python 回调在模拟身份下执行；缺少该会话/凭据时不回退 System 或其他用户。实现依据 [WTSQueryUserToken](https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsqueryusertoken) 和 [CredReadW 的登录会话语义](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credreadw)。本轮未获取 token 或读取真实 keyring；正向证据目前限于原生文件导入的加密合成库，跨用户迁移须随后独立验收。

## 初始化恢复

有受保护 MAC 配置收据的中断初始化可以重新审查同一配置、精确构建和既有 Hello 公钥。恢复路径只打开该既有凭据，不创建/替换密钥；缺失 pin 只能由已验证收据恢复，格式错误或不同的既有 pin 保留拒绝。空初始账本可以继续完成，已完整持久化但 bootstrap 尚未发布的阶段还须验证独立审计/完整性，且不能有旧任务、授权、内容、披露或执行记录。

硬件创建成功但尚无配置收据或 pin 时，另有显式 `recover` 一次性服务入口：拒绝历史状态及任何既有 pin，只打开既有凭据，原生审查显示实际公钥 SHA-256，并重新核对 TPM2/AIK、完整构建和签名。普通初始化失败不会进入此路径；不会创建、替换或删除密钥。首次登记及恢复的构建摘要已同时进入挑战与 MAC 收据，完成前再次核对。完整桌面向导和发行接线仍需继续实现。

本轮无真实微信正文读取、输入、发送、服务部署、Hello 或模型调用。临时文件/模拟 SCM 的成功不证明管理员 ACL、SCM、跨用户凭据或真实硬件可用。
