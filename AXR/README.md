# Stellaria AXR SDK Gen1

AXR 是与应用无关的授权执行 SDK。C++20 核心负责 Guard、密封意图、AES-GCM、
日志链及进程原语；Python 是薄绑定和编排层。macOS 通用 Adapter 使用 Swift，
Windows 所有者验证与沙箱使用 C++。微信选择器、数据库解析、MCP 和监听器位于仓库
`adapters/`、`axr_integration/`，不属于 AXR SDK。

通用基础设施实际抽取自 BasicX-Hub、BasicX、Connector，见
[REUSE.json](REUSE.json)。没有导出内部计算 DAG、SOF/SPX、渲染或模型实现。
许可证为 [AGPL v3 only](LICENSE)。商业许可须另行书面约定。

## C++20 独立构建

需要 CMake ≥ 3.24、OpenSSL ≥ 3、SQLite3；nlohmann/json 3.12 可由包管理器提供，
否则构建下载并校验固定 SHA-256 的官方单头文件。无需 BasicX、Qt 或微信。

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
auto reference = guard.Check(sealedAction, Now());
auto reservation = guard.Consume(sealedAction, Now());
guard.Revalidate(sealedAction, reference, reservation[1], Now());
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
`revoke GRANT` 提升全局策略版本，保守失效全部旧能力及上下文；需重新授权所需能力。
这些命令不注册为 MCP 工具。`dashboard` 显示实际计数与审计验证结果。

## 安全与验收边界

* Guard / Host / Journal 统一使用 AET：Proposed → PolicyChecked → Ready / AwaitingApproval
  → Prepared → Executing → Verifying → Completed。中断/不明提交 → Unknown，禁止重试。
  Prepared 恢复 → FailedSafe；不承诺外部服务 exactly-once 或收件人已收到。
* 访问与披露独立。来源保留账号、会话、引用、分类和 `untrusted-external`。
  已披露来源的加密 scope/class 元数据跨正文 TTL/重启保留，防止把 TTL 当作来源清洗；不留聊天历史。
  P3 默认逐动作确认；敏感/凭据/财务分类要求精确意图。没有金融或凭据操作 handler。
* Job、context、result 的正文使用原生 AES-256-GCM，带绑定及 TTL；审计保存元数据，
  BasicX 日志链加 HMAC，Hub append-only triggers，SQLite WAL + FULL durability。
  不提供完整聊天归档、全局个人知识库或遥测上传。
* 每账号执行租约、每 journal 生命周期租约；幂等来自本地记录，不是假定微信有 idempotency key。
* 一次性 helper 使用私有继承管道、有界 JSON、固定 owner command 和超时；持久 worker
  可使用 FrameCodec 的 version/epoch/sequence/HMAC。FrameCodec 不代表所有平台管道已实测。
* 可信 UI helper 在读取及实际平台 commit 前，通过 C ABI 复核 broker 提供的 grant 摘要、
  策略版本、墙钟过期及来源额度，不携带 issuer key。此 proof 只供可信私有管道使用，
  不构成公开认证协议，也不阻止拥有同用户任意 shell 权限的人直接操作应用。
  微信外部提交与撤权之间没有共同原子事务；仍可能产生 Unknown，不能承诺 exactly-once。
* macOS worker 在 deny-default sandbox-exec 下运行；Windows native AppContainer 不发放
  网络 capability，只读 owner-staged runtime，并在恢复线程前加入 JobObject。
  沙箱失败时拒绝启动。Windows AppContainer 和 Hello 尚待运行验证。
* Python Supervisor 对 Windows helper 在 Popen 后绑定 JobObject；它是可信 broker 辅助进程，
  不能把它当作不可信 agent 的安全边界。Agent 必须走原生 AppContainer launcher。
* Workspace 只允许有限大小的 md/txt/csv/json 相对路径，拒绝 symlink，原子写入并加密备份；
  同一用户的恶意并发文件系统竞争仍须 OS sandbox。附件不执行。
* 主人终端/策略目录/密钥库属于可信控制面。拥有同用户任意 shell、文件、调试或 keyring
  权限的通用 MCP 客户端不因安装 SDK 就被隔离。本 SDK 的 Guard 只约束注册的能力。
  对任意外部模型已经记忆的文本，TTL 不能强制它遗忘；必须限制 worker 生命周期和外传权限。
* 哈希/HMAC 验证不能检测整库回滚到完整旧快照；不提供硬件防回滚或独立远程审计锚点。

[集成验收矩阵](../docs/AXR_GEN1.md) 分别记录 mock、平台与端到端验证。
