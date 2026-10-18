# 独立安全服务部署与应用接线

当前已完成受保护的 macOS 程序安装、首次设置、服务注册及真实 MCP 连接。独立
所有者和调度路由已经实现；**新服务的微信收发尚未实测通过**。
旧自动回复仍关闭，不能用历史验收代替新服务验收。

## 已实现

- 独立原生 authority / owner 宿主，固定嵌入式 Python 入口、隔离模块搜索路径。
  SDK 宿主通过应用注册调用微信服务，微信业务继续位于 `AXR/` 之外。
- 应用专用 C++20 WCDB 消费者。密钥从原生 OS 存储进入 SQLCipher，业务 Python
  只接收固定操作的结果；没有 SQL、路径、密钥或进程扫描 MCP 入口。现有密钥可在
  所有者初始化时原生迁移，验证后保存，不恢复旧权限。
- 文本分页固定账号、会话和 Name2Id 身份；支持多分库游标、压缩文本及明确失败。
  本地草稿和搜索记录作为自动选聊核对材料，不能独立充当发送权限。
- v2 原生执行桥先等待帮助进程就绪，再绑定实际 PID/birth 和意图；原生帮助进程
  通过自己的受认证连接认领并记录回执。发送响应丢失保留 Unknown、不重发；
  数据库发出记录与送达确认分开。
- 每个来源使用新的临时 Codex 进程，不恢复父对话。输入最多 6 条/24KB，
  只接收类型化数据；外层 macOS 沙箱拒绝读取其他来源文件和执行其他程序。
  登录供固定提供方使用，不能进入提示词。受控公开 CA 包支持沙箱内 TLS；
  CA 摘要或提供方构建变化即拒绝使用。
- macOS 打包工具复制 Python、Zstd、SQLCipher 和原生依赖闭包，重写加载路径，
  不依赖开发目录或虚拟环境。所有原生映像使用同一签名团队，保留 Hardened Runtime
  和库验证；Developer ID/厂商公证不是本机验证的前置。

## 本轮证据

本地加密合成库验证了原生查询、稳定方向、跨页游标、错误密钥失败、范围拒绝、
精确草稿和检查回调；桥接测试覆盖真实进程证据的绑定顺序及丢失回执不重发。
macOS 合成原生进程实际证明了当前来源可读、其他来源不可读、其他程序不可执行。
受限 Codex 提供方使用真实模型完成了纯合成、单来源 ReplyDraft 推理。
完整回归为 460 项发现、456 项执行通过、4 项平台跳过。候选包以独立非权限身份
实际加载正式 native、原生 WCDB、Zstd 和 Journal 运行时，无服务或密钥初始化。
这些均不是微信真实读写或最终 native authority 端到端验收。

本机可使用现有本地开发签名完成候选包。临时签名加动态依赖的实测被系统库验证
拒绝，工具因此拒绝此组合，不添加关闭库验证的例外。无本地签名团队的交付需要
完整静态宿主方案，尚未实现。候选运行时的完整第三方再分发清单也未完成准入。

## Windows 证据（2026-10-18，阶段记录）

六个受控 MCP 工具已接入 authority 的 Application 路由；真实 stdio 和本机认证命名管道完成合成读取句柄、独立披露、人工草稿及回执，服务进程身份变化后拒绝数据调用。人工审批默认开启，可由独立 owner 挑战签名切换；固定 Windows owner 控制入口已编译，GUI 和 Hello 签名提供方未接通。最新全量 502 项发现、470 执行通过、32 平台/链接权限跳过。正式原生构建拒绝普通 Python 凭据访问，不包含 fixture 凭据入口；没有用合成签名或配置解除整体准入。详见 [Windows MCP](WINDOWS_MCP.md)。

Windows 正按本地 Mac 的全部自动回复功能适配，新增 v2 原生 helper 管道、分阶段草稿/单次提交代码和 Windows 永久尝试标记。当前只验证实际进程握手及拒绝路径，未通过新服务成功操作微信或发送。实机 UIA 结构只有四个普通节点，需要继续主窗口导航与缓存见证适配；[完整对齐进度](WINDOWS_AUTOMATIC_REPLY.md)。

此前原库有界读取为适配器证据，不是本新服务的真实 MCP 正文披露或原生凭据迁移。两个平台的实现及实机证据分别维护，不能共享通过结论。

## macOS 操作路由与当前验收

原生 `AXR MCP` 仅接受固定 `--mcp` 入口，在 Python 和请求解析前应用 OS 沙箱；
初始化、工具发现与状态不创建执行租约。真正的数据和副作用请求发送到独立
Authority，角色来自受保护构建与实际 PID/birth，不使用持久 bearer。

Owner 通过硬件用户在场签名批准精确范围、目标、模型目的地、时限和次数。
可设置直至停止的站立授权，但每个派生 TaskContract 最长一小时、最多十万次；
重启不恢复站立权限。设置中的停止无需再次认证，并使当前推理和原生提交失效。
普通读取与向 MCP / 来源模型披露分别检查；不同来源使用全新隔离模型进程。

服务内调度处理新入站、类型化草稿、自动选聊、精确输入、单次提交和独立数据库
核对。MCP 主动发送采用稳定请求号；更换正文被拒绝，更换请求号也不能重发已知
不确定正文。中断任务保留 Unknown。人工草稿使用独立面板，不自动提交。
本地任务缓存容量有限，全天稳定性尚未验证。

首次设置失败后保留进度。已经保存的审批收据由原生 Root 密钥认证；仅当部署
配置、OS 用户、收据与硬件身份一致，bootstrap 尚未生效、账本无权限/任务/审计
事件、受保护审计锚仍为零时，才能接续同一初始化，**无需重复所有者认证**。
任何历史执行记录、非零审计锚、配置或收据校验失败均拒绝接续；不恢复旧权限。
已迁移的原生凭据优先重新校验并复用，不重复访问旧 Keychain 条目。

配置写入前检查大小，读写预算一致；全部目标的站立审批按来源派生有限小任务，
不会把完整联系人目录塞进每次执行证明。开启服务先检查实际数据库访问和辅助
功能权限，通过后才请求一次范围签名；同范围内不逐次认证，停止无需认证。
应用区分缺少系统权限、服务断开和审批过期，避免用重复认证掩盖前置问题。
凭据引用采用固定摘要名，原始密钥始终留在原生边界。

当前证据包括实际无重复认证的初始化接续、原生凭据迁移、独立服务连接、MCP
初始化/六项工具发现/状态请求、Secure Enclave 设备绑定重建及签名，以及加密
合成库与调度/停止/幂等回归。独立服务启动后，系统报告其数据库和辅助功能权限
尚未允许，真实开启请求在硬件认证前约 0.4 秒返回明确原因，停止无需认证；没有
触发新读取/发送审批。微信真实读取、主动发送、入站自动回复
及读回仍待本机验收。Windows 应用前端/所有者硬件提供方及微信设备验收未完成。

整合远端更新后本机全量回归 572 项发现、511 项执行通过、61 项按平台或可选条件
跳过；参考原生重建后 CTest 2/2 通过，正式宿主/前端/消费者构建通过。新 GUI 权限
前置状态和配置回归 11 项执行通过、1 项平台跳过；真实 Qt 权限状态来自服务。

硬件表示采用 [Apple CryptoKit API](https://developer.apple.com/documentation/cryptokit/secureenclave/p256/signing/privatekey/datarepresentation)，
系统存储模型参考 [Apple TN3137](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains)。
设备绑定表示不是原始私钥；不使用软件密钥降级。

## 构建候选

```sh
cmake -S . -B <private-build> \
  -DAXR_SECURITY_RELEASE=ON -DAXR_PYTHON=ON \
  -DAXR_AUTHORITY_HOST=ON -DAXR_PLATFORM_HELPERS=ON \
  -DWECHAT_NATIVE_CREDENTIALS=ON \
  -DPython_EXECUTABLE=<python312> -Dpybind11_DIR=<pybind11-cmake>
cmake --build <private-build> --target \
  axr-authority axr-owner axr-frontend axr-runtime-check axr-helper-build \
  _axr_native _wechat_credentials
python scripts/build_pinned_input.py --build <private-build> --navigation
python scripts/package_authority_macos.py \
  --build <private-build> --output <new-private-output> \
  --deployment <owner-reviewed-metadata.json> --identity <local-signing-identity>
```

部署元数据、构建记录、公开证书包和真实验收材料保存在本地，不提交仓库。
`AXR Runtime Check.app` 是单独的开发验证身份，不是产品入口，不安装到用户应用。
它只能验证候选运行时，不初始化凭据、权限、服务或微信操作。

Codex 的临时上下文及结构化输出接口参考
[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。具体提供方通过实际
OS 沙箱与模型调用验证，不能仅根据只读设置推断来源隔离。

## 本机部署流程

1. 构建并校验独立签名包，使用 `scripts/install_authority_macos.py --package <package>`
   完成系统管理员确认。只安装 Authority、Owner 和 MCP；开发验证工具不安装。
2. 在本机交互终端运行固定 Authority 的 `--initialize-owner`。独立 Owner 对配置
   摘要和新随机挑战进行硬件在场签名；原生迁移已有凭据并建立新账本，不恢复权限。
   中途失败时先检查已保存进度；符合空事务条件的原审批自动接续，不循环弹窗。
3. 运行 `scripts/register_authority_service.py` 注册用户级服务。在 Qt 设置中连接
   Codex、选择目标和期限后批准权限；服务进程不依赖 MCP 客户端保活。
4. Codex 配置的命令指向安装的 `AXR MCP.app/Contents/MacOS/axr-frontend`，参数仅
   `--mcp`。设置更新后重连 MCP。状态可查不代表微信权限已开启。

macOS 的 Full Disk Access、Accessibility 仍需系统实际允许独立程序；不得编辑
TCC 数据库、注入微信或修改其窗口共享保护。读取在后台执行，发送需要微信原版
主窗口可见并置前，不承诺无焦点发送。详细身份、密钥引用、正文、日志和真实
测试记录只保存在本地，不进入仓库。
