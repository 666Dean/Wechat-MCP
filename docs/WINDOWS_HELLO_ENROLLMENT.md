# Windows Hello 登记证明

当前代码支持首次创建、既有公钥固定的 Hello 凭据、证明收集及登记响应复核。首次创建有独立原生本地审查，代码已构建并验证普通进程拒绝；尚未显示真实界面或调用硬件。Windows 已直接复用最新 Mac 的硬件登记、空账本检查与部署固定流程，补固定 LocalSystem→交互所有者原生启动、认证管道及完整性保存后的公钥固定。安装/服务登记、原生凭据迁移、中断创建的显式恢复与真实跨会话/硬件验证仍缺失，整体准入保持关闭。

## 固定入口与响应

原生 owner 宿主的 `--owner-enroll` 在 Windows 分派到 `windows_enrollment.py`。挑战只接受版本、类型、配置摘要、32 字节随机数及最长 180 秒期限；摘要必须等于受保护 `deployment.json` 的实际规范化部署配置。模型不能提供另一配置或密钥名称。

`owner-key.json` 存在时只打开其固定的既有凭据，损坏/不可读固定或不可用凭据均不回退创建。只有固定文件确实不存在时才进入首次创建；缺可信根、配置变化及无效挑战会在创建前拒绝。通过 `GetAttestationAsync` 收集有界证明，先核验硬件证明，再请求对精确挑战的 Hello 签名。只有证明、签名、配置及期限全部核对后才输出登记响应。authority 的落盘入口另行复核证明与挑战，不把子进程返回的 provider 名称或成功状态当作资格。

证明包含证书及设备关联数据，只能经本地私有登记通道传输，不是 MCP 返回值、日志或公开配置。代码没有自动恢复旧授权。

## Windows 初始化适配（2026-10-22）

共享 `authenticate_owner_setup` / `initialize_owner` / `finish_initialization` 顺序保留硬件证明、精确配置挑战、空审计账本、原生联系人目录、密封配置、资产固定及完整性保存。Windows 的受保护配置另固定 `owner_user` SID；服务账户与交互所有者的 SID 不要求相同。普通 Session 0 布尔认证不能代替此登记。

固定 `axr-authority.exe` 在受保护 Program Files 安装内，只选择与固定 SID 唯一匹配的活动 WTS 会话，启动固定 `axr-owner.exe --owner-enroll`。一次性命名管道禁止远程连接，仅允许 System 和指定 SID；每帧核对真实 PID、birth、映像摘要及用户。随机 nonce、配置摘要、双时钟期限和有界规范 JSON 帧绑定交换；不继承 stdio、环境配置、脚本、调用者会话或启动命令。JobObject 仅负责清理子进程。

authority 复核完整硬件证明后才建立新账本，完整性保存后独占创建 `owner-key.json`，已有不同或损坏文件不覆盖。管道的 received 回执仅确认收件，不代表安装成功或恢复权限。配置在认证后及最终 bootstrap 保存前重新比较，bootstrap 密钥最后写入。Windows 中断设置不复用 Mac 的同用户恢复条件，仍要求另行实现显式恢复。

原生管道测试实际执行同用户临时管道的双向 JSON、OS 身份、错误 birth、连接/读取超时取消及超长消息拒绝。软件测试模拟跨会话身份，并使用临时 RSA、证书与 CRL 验证实际原生证明和共享初始化顺序；没有获取 System token、启动真实交互 owner、显示 Hello、创建密钥、迁移真实凭据或操作微信。

## 首次创建的本地确认

`provision_windows_hello_owner` 是受保护 owner 程序的独立原生入口，没有名称、替换、算法或脚本选项。普通 Python、服务会话及不受保护安装在任何本地界面/WinRT 调用前拒绝。

本地窗口显示实际部署中的账户、完整联系人范围、状态目录、服务、独立人工审批开关、配置指纹和期限，身份值使用引号及控制字符转义。正文为只读且可滚动，默认焦点和默认动作是取消；关闭、取消及期限到达均不能批准。墙钟和单调时钟共同限制审查时间；审查窗口、定时器和控件在结束或错误时清理，等待不持有 Python 锁。

确认后只对固定凭据名称调用 `RequestCreateAsync(FailIfExists)`，最长受本次挑战剩余期限及创建预算限制；已有同名密钥明确要求恢复，不会替换、打开无固定凭据、删除或自动重试。此 API 行为见 [Microsoft 创建选项](https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.keycredentialcreationoption)。

创建请求发出后的取消、超时、进程退出或硬件证明失败可能留下未登记的 OS 凭据；此时不会返回授权、保存可信固定或清理已有凭据。后续恢复必须有独立本地审查，显式恢复流程尚未实现。完整安装及登记未接通前，不运行真实创建/窗口测试。

## 可信根与链验证

受保护安装需有 `runtime/hello-trust.json`，仅含 `version: 2` 和 `roots`。根是小写 DER 十六进制，每张不超过 8192 字节，1–8 张、不得重复。读取使用目录句柄，拒绝链接/重解析点和路径逃逸。实际可信根必须由独立部署审核提供，不能从登记响应中取出根直接信任；当前包没有自动生成或自动信任根的逻辑。

原生核验使用私有内存证书库和 Windows exclusive-root chain engine：只信任上述根，选择唯一带 AIK EKU `2.23.133.8.3` 的非 CA 证书，检查链签名、用途、当前期限及除根外整条链的吊销状态。吊销未知或离线且无有效证明时拒绝，不忽略错误。禁用 AIA 获取，吊销获取有累计时间预算；不会把证书导入系统信任库。

## TPM 证明范围

独立有界解析 PCP `KADS`/TPM2 证明及 PCP 公钥区域，核验 AIK 签名、TPM certify 类型、SHA-256 密钥名称、RSA-2048/65537 公钥和固定 TPM/父对象、TPM 生成及签名属性。证明中的公钥必须等于挑战签名公钥。未认证的 PCP 存储标志不作为本人在场或 PIN 证明。

当前只接受这一明确格式，TPM1.2、其他名称算法及不支持的结构拒绝。传统 PCP 外层 AIK 证明使用固定 PKCS#1/SHA-1；这只限证明格式，不会增加所有者挑战、authority 根或执行许可的算法。签名挑战仍用 RSA-2048/PKCS#1/SHA-256，实际设备是否返回这一格式须在代码阶段完成后验证。

`verify_windows_hello_statement` 只检查结构、签名和公钥绑定，不信任传入 AIK。只有再通过证书链检查的 `verify_windows_hello_attestation` 才能作为登记证明的一部分；两个函数本身都不授予权限，也不登记进程。

## 当前验证

参考及正式 SDK 使用临时软件 RSA 密钥、合成 TPM2 证明、私有根/AIK 证书和 CRL，验证完整链及撤销、过期、错误用途、错误根、公钥不匹配、可迁移属性、截断及篡改拒绝。完整登记响应还覆盖配置变化、错误挑战、伪造成功字段、缺根及过期拒绝。首次创建另覆盖精确审查路由、缺根/坏固定拒绝、取消及过期不签名、普通进程原生拒绝。测试没有显示实际审查窗口、调用 Hello、创建硬件凭据、安装服务或操作微信，不能作为真实 TPM/本人认证或界面可用性结论。

格式及验证要求参考 [Microsoft Windows Hello](https://learn.microsoft.com/en-us/windows/apps/develop/security/windows-hello)、[Microsoft PCP 公开格式](https://github.com/microsoft/TSS.MSR/blob/main/PCPTool.v11/inc/TpmAtt.h) 和 [Windows exclusive-root chain engine](https://learn.microsoft.com/en-us/windows/win32/api/wincrypt/ns-wincrypt-cert_chain_engine_config)。本仓库实现独立解析和核验，没有引入 TPM 工具运行库。
