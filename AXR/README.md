# Stellaria AXR SDK Gen1

独立官方仓库：[Stellaria-Studio/Stellaria-AXR-SDK](https://github.com/Stellaria-Studio/Stellaria-AXR-SDK)。

## Security Architecture 2

新增统一 TaskContract、原生策略判定、受认证的独立权限服务协议、隔离内容解析、
受保护审计检查点、局部遏制和签名更新防回退。**目前为开发整合，整套安全发行
尚未通过完整设备准入。** 独立原生服务、固定受控前端及应用注册入口已实现；
本机部署、首次设置和服务连接已验证，应用端真实收发仍须单独验收。
不能通过旧令牌或 Gen1 提交路径降级开启。
现有 AET、Guard、Host、Journal 继续保留。实现、威胁边界与验收缺口见
[Security Architecture 2](SECURITY_ARCHITECTURE.md)。

受控更新通过固定所有者入口登记精确新构建，保留凭据、历史审计和不确定执行记录，
并撤销原有权限。已认领的短时许可可在同一帮助进程中本地验签，减少逐键通信；
最终外部提交仍需服务端新鲜认领。该机制不允许模型签发、延期或恢复权限。


**面向 Agent 应用的授权执行基础设施。**

Stellaria AXR 为产品开发团队提供统一的权限校验、执行事务、来源追踪与审计能力，
将模型提出的行动转换为可核验、可撤销、可追溯的执行流程。SDK 不依赖特定模型、
MCP 客户端或业务应用，可独立集成到桌面软件与本地 Agent 系统。

## 产品能力

| 能力 | 集成价值 |
| --- | --- |
| Guard | 按身份、资源、目的、操作、有效期和额度验证授权 |
| Authorized Execution Transaction | 密封意图、执行前复核、明确的成功与未知状态 |
| Journal | 加密短期结果、执行凭据、完整性可验证的审计链 |
| Provenance | 保留数据来源与分类，分别约束访问和外部披露 |
| Host | 平台辅助进程、执行租约、有界通信与运行限制 |
| Owner Control | 结合系统身份认证，独立于模型管理权限 |

核心采用 C++20；Python 提供绑定和编排。macOS 平台支持层采用 Swift，
Windows 采用 C++。具体应用的数据库、内容解析、模型调度、界面和业务适配器
由集成方维护。微信集成位于本仓库 `adapters/`、`axr_integration/` 与 `desktop/`，
不属于 AXR SDK。

## 许可与交付

`AXR/` 自有代码采用 **GNU AGPL v3 only 或 Stellaria Commercial License 1.0** 双授权，
SPDX 表达式为 `AGPL-3.0-only OR LicenseRef-Stellaria-Commercial-1.0`。
AGPL 允许符合其条件的商业使用；SCL 通用文本不自动授予专有集成等权利，须另有有效专项协议。
完整边界见 [SDK 许可说明](LICENSES.md)，第三方材料保持原许可。
新 SDK 贡献按照 [Stellaria CLA 1.0](CONTRIBUTING.md) 完成有效签署与具体接受记录；
历史贡献不因新 CLA 追溯转让。本仓库其他代码的许可见 [许可边界](../LICENSES.md)。

Gen1 当前为开发版本。支持范围以构建、回归与具体设备验收为准：SDK 编译成功
不代表任意应用的控制接口已经可用。详见下方安全边界与
[应用验收矩阵](../docs/AXR_GEN1.md)。

Python 支持层新增通用 `axr.native_image.NativeImage` 离线 Mach-O 代码身份工具：有界切片、UUID、函数边界/哈希和直接调用/字符串引用；不加载程序或授权内部函数调用。微信 build 与候选指纹在 SDK 外的适配器中，见 [应用侧资格记录](../docs/MAC_NATIVE_270134.md)。

## C++20 独立构建

需要 CMake ≥ 3.24、OpenSSL ≥ 3、SQLite3；nlohmann/json 3.12 可由包管理器提供，
否则构建下载并校验固定 SHA-256 的官方单头文件。SDK 可独立构建和使用。

```sh
cmake -S AXR -B build-axr -DCMAKE_BUILD_TYPE=Debug
cmake --build build-axr --parallel 4
ctest --test-dir build-axr --output-on-failure
cmake --install build-axr --prefix /your/sdk/prefix
```

macOS 的 Homebrew OpenSSL 可增加 `-DOPENSSL_ROOT_DIR=$(brew --prefix openssl@3)`。
Windows 推荐 vcpkg 的 `openssl sqlite3 nlohmann-json`，通过 CMake toolchain 指定。
消费工程使用 `find_package(StellariaAXR CONFIG REQUIRED)`，链接 `Stellaria::AXR`。

```cpp
#include <axr/Core.hpp>
using namespace Stellaria::AXR;
// OS secret store supplies the 32-byte key. No agent-facing capability issuer.
Guard guard(ownerControlledDatabase, osKey);
// sealedAction includes a unique execution_id for this proposal.
guard.Check(sealedAction, Now());
auto reservation = guard.Consume(sealedAction, Now());
guard.Revalidate(sealedAction, reservation[0], reservation[1], Now());
// Revalidate again immediately before the registered application commit.
```

## Python 与本地所有者入口

```sh
python -m pip install ./AXR
axr-owner --state /private/owner/state --helper /path/to/axr-helper init --policy /private/policy.json
```

安装会编译原生绑定与平台辅助程序，辅助程序在 `axr/bin/`。开发构建可用仓库
`scripts/build_axr.py`。Windows helper 为 `axr-owner-auth.exe`，macOS 为 `axr-helper`。
密钥保存在 macOS Keychain / Windows Credential Manager，不降级到明文文件。
`secret` 子命令只接受本地终端隐藏输入；不得通过 MCP、聊天、argv 或环境变量传密钥。
Windows owner auth 使用 UserConsentVerifier / Windows Hello；设备无可用验证方式时拒绝。
macOS 使用 LocalAuthentication，用户须完成系统身份验证。

`grant` 绑定 principal、platform/account/conversation、operation、purpose、workflow、
TTL、次数；`--class personal` 可明确允许本地个人数据草稿，敏感分类仍须精确审批。
`approve JOB --principal PRINCIPAL` 显示精确意图并调用系统认证，发放
最长 240 秒、一次使用的能力；正文、目标或来源改变后旧能力无效。
execution_id 也在密封意图内；取消后旧审批不能授权同内容的新任务。
Journal 的持久 execution claim 在正文 TTL/重启后仍拒绝原 ID 重放。
`revoke GRANT` 提升全局策略版本，保守失效全部旧能力及上下文；需重新授权所需能力。
这些命令不注册为 MCP 工具。`dashboard` 显示实际计数与审计验证结果。

## 所有者单窗口读取验收

可选构建 `AXR_MAC_SELECTION_PROBE` 提供 Apple 官方单窗口选择器。默认仅元数据；
`python -m axr.owner_window_ocr` 是交互式、本地所有者入口，不注册为 MCP。
新读取须 OS 认证，精确绑定资源、bundle/PID、窗口 ID、标题及几何，一次授权最长 240 秒。
仅使用主人选择器返回的原始 filter，读取一帧并执行本地 Vision；不保存图片、不联网、不输入。
取消、范围变化、空帧和超时失败关闭；操作结束撤权并逻辑清理加密 OCR 结果。
这不授予平台身份、模型披露、监听或发送资格。构建、私有请求格式及实测边界见
[单窗口验收](../docs/MAC_REPLY.md)。SDK 的合成失焦窗口对照通过，不能外推真实应用可用性。

## 安全与验收边界

* Guard / Host / Journal 统一使用 AET：Proposed → PolicyChecked → Ready / AwaitingApproval
  → Prepared → Executing → Verifying → Completed。中断/不明提交 → Unknown，禁止重试。
  Prepared 恢复 → FailedSafe；不承诺外部服务 exactly-once 或收件人已收到。
* 访问与披露独立。来源保留账号、会话、引用、分类和 `untrusted-external`。
  已披露来源的加密 scope/class 元数据跨正文 TTL/重启保留，防止把 TTL 当作来源清洗；不留聊天历史。
  来源访问授权须覆盖实际分类。自身读取的分类查询由主授权校验，单次精确读取及最后一页的预留额度可完成；派生操作仍复核其他来源访问额度。
  P3 默认逐动作确认；敏感/凭据/财务分类要求精确意图。没有金融或凭据操作 handler。
* Job、context、result 的正文使用原生 AES-256-GCM，带绑定及 TTL；审计保存元数据，
  AXR 日志链加 HMAC，append-only triggers，SQLite WAL + FULL durability。
  不提供完整聊天归档、全局个人知识库或遥测上传。
* 每账号执行租约、每 journal 生命周期租约；幂等来自本地记录，不是假定微信有 idempotency key。
* 一次性 helper 使用私有继承管道、有界 JSON、固定 owner command 和超时；持久 worker
  可使用 FrameCodec 的 version/epoch/sequence/HMAC。FrameCodec 不代表所有平台管道已实测。
* 可信 UI helper 在读取及实际平台 commit 前，通过 C ABI 复核 broker 提供的 grant 摘要、
  策略版本、墙钟过期及来源额度，不携带 issuer key。此 proof 只供可信私有管道使用，
  不构成公开认证协议，也不阻止拥有同用户任意 shell 权限的人直接操作应用。
  微信外部提交与撤权之间没有共同原子事务；仍可能产生 Unknown，不能承诺 exactly-once。
  通用 `menu_navigate` 仅接受精确 `application.navigate` 能力，密封两级菜单与窗口验证条件、bundle/PID；
  签发、broker 校验及 native commit 均拒绝无 intent、多次或剩余期限超过 300 秒的导航权限。
  应用菜单目录由 SDK 外的集成实现；SDK 不提供联系人、微信账号或发送逻辑。
* macOS worker 在 deny-default sandbox-exec 下运行；Windows native AppContainer 不发放
  网络 capability，只读 owner-staged runtime，并在恢复线程前加入 JobObject。
  沙箱失败时拒绝启动。Windows CI 合成进程已验证受管启动、staged 文件读取、私有文件
  及 loopback 隔离；这不代表微信实机成功。Hello 的所有者认证全过程尚待设备验证。
* Python Supervisor 对 Windows helper 在 Popen 后绑定 JobObject；它是可信 broker 辅助进程，
  不能把它当作不可信 agent 的安全边界。Agent 必须走原生 AppContainer launcher。
* Workspace 只允许有限大小的 md/txt/csv/json 相对路径，拒绝 symlink，原子写入并加密备份；
  同一用户的恶意并发文件系统竞争仍须 OS sandbox。附件不执行。
* 主人终端/策略目录/密钥库属于可信控制面。拥有同用户任意 shell、文件、调试或 keyring
  权限的通用 MCP 客户端不因安装 SDK 就被隔离。本 SDK 的 Guard 只约束注册的能力。
  对任意外部模型已经记忆的文本，TTL 不能强制它遗忘；必须限制 worker 生命周期和外传权限。
* 哈希/HMAC 验证不能检测整库回滚到完整旧快照；不提供硬件防回滚或独立远程审计锚点。

[集成验收矩阵](../docs/AXR_GEN1.md) 分别记录 mock、平台与端到端验证。
