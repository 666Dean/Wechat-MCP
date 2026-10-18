# Windows Hello 登记证明

当前代码支持既有、已固定公钥的 Hello 凭据收集证明及登记响应复核。它不代表完整 Windows 初始化：首次创建、从 LocalSystem 启动所有者交互进程、安装登记和最终保存公钥固定仍需实现；`initialize_owner` 的启动/资产布局仍有 Mac 专用代码。整体准入保持关闭。

## 固定入口与响应

原生 owner 宿主的 `--owner-enroll` 在 Windows 分派到 `windows_enrollment.py`。挑战只接受版本、类型、配置摘要、32 字节随机数及最长 180 秒期限；摘要必须等于受保护 `deployment.json` 的实际规范化部署配置。模型不能提供另一配置或密钥名称。

入口只打开 `owner-key.json` 固定的既有凭据，通过 `GetAttestationAsync` 收集有界证明；先核验硬件证明，再请求对精确挑战的 Hello 签名。只有证明、签名、配置及期限全部核对后才输出登记响应。authority 的落盘入口另行复核证明与挑战，不把子进程返回的 provider 名称或成功状态当作资格。

证明包含证书及设备关联数据，只能经本地私有登记通道传输，不是 MCP 返回值、日志或公开配置。代码没有自动恢复旧授权。

## 可信根与链验证

受保护安装需有 `runtime/hello-trust.json`，仅含 `version: 2` 和 `roots`。根是小写 DER 十六进制，每张不超过 8192 字节，1–8 张、不得重复。读取使用目录句柄，拒绝链接/重解析点和路径逃逸。实际可信根必须由独立部署审核提供，不能从登记响应中取出根直接信任；当前包没有自动生成或自动信任根的逻辑。

原生核验使用私有内存证书库和 Windows exclusive-root chain engine：只信任上述根，选择唯一带 AIK EKU `2.23.133.8.3` 的非 CA 证书，检查链签名、用途、当前期限及除根外整条链的吊销状态。吊销未知或离线且无有效证明时拒绝，不忽略错误。禁用 AIA 获取，吊销获取有累计时间预算；不会把证书导入系统信任库。

## TPM 证明范围

独立有界解析 PCP `KADS`/TPM2 证明及 PCP 公钥区域，核验 AIK 签名、TPM certify 类型、SHA-256 密钥名称、RSA-2048/65537 公钥和固定 TPM/父对象、TPM 生成及签名属性。证明中的公钥必须等于挑战签名公钥。未认证的 PCP 存储标志不作为本人在场或 PIN 证明。

当前只接受这一明确格式，TPM1.2、其他名称算法及不支持的结构拒绝。传统 PCP 外层 AIK 证明使用固定 PKCS#1/SHA-1；这只限证明格式，不会增加所有者挑战、authority 根或执行许可的算法。签名挑战仍用 RSA-2048/PKCS#1/SHA-256，实际设备是否返回这一格式须在代码阶段完成后验证。

`verify_windows_hello_statement` 只检查结构、签名和公钥绑定，不信任传入 AIK。只有再通过证书链检查的 `verify_windows_hello_attestation` 才能作为登记证明的一部分；两个函数本身都不授予权限，也不登记进程。

## 当前验证

参考及正式 SDK 使用临时软件 RSA 密钥、合成 TPM2 证明、私有根/AIK 证书和 CRL，验证完整链及撤销、过期、错误用途、错误根、公钥不匹配、可迁移属性、截断及篡改拒绝。完整登记响应还覆盖配置变化、错误挑战、伪造成功字段、缺根及过期拒绝。测试没有调用 Hello、创建硬件凭据、安装服务或操作微信，不能作为真实 TPM/本人认证结论。

格式及验证要求参考 [Microsoft Windows Hello](https://learn.microsoft.com/en-us/windows/apps/develop/security/windows-hello)、[Microsoft PCP 公开格式](https://github.com/microsoft/TSS.MSR/blob/main/PCPTool.v11/inc/TpmAtt.h) 和 [Windows exclusive-root chain engine](https://learn.microsoft.com/en-us/windows/win32/api/wincrypt/ns-wincrypt-cert_chain_engine_config)。本仓库实现独立解析和核验，没有引入 TPM 工具运行库。
