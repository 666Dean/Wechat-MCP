# WeFlow 参考与 Windows 只读组件设计

审查日期：2026-10-12；固定 revision：`2f23e72cebf7f309a0f4d129307d16d7b0cd41c3`。
主项目：[hicccc77/WeFlow](https://github.com/hicccc77/WeFlow)。仅静态阅读，没有安装应用、加载其插件、运行取钥或访问真实聊天。

## 参考定位

| 来源 | 本项目采用的判断 |
|---|---|
| [README](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/README.md) / [组件说明](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/docs/third-party-components.md) | 应用与原生解密组件分离，调用协议不等于组件实现或 Windows 可读证明；该 revision 不内置解密组件 |
| [wcdbCore.ts](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/electron/services/wcdbCore.ts) | 核对生命周期、可选导出、64 位账号/游标句柄、返回字符串释放；游标三接口须完整存在 |
| [wcdbService.ts](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/electron/services/wcdbService.ts) / [wcdbWorker.ts](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/electron/wcdbWorker.ts) | 后台调用分层，连接操作串行化，故障后清除连接身份及待办；本项目已有串行 legacy worker，隔离进程与故障恢复仍待实现 |
| [keyProviderService.ts](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/electron/services/keyProviderService.ts) | 取钥本身也是外部 provider 协议；这份源码不是内置 Windows 取钥算法。当前采用主人本地认证/隐藏导入/逐库校验，不运行外部 provider |
| [HTTP-API.md](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/docs/HTTP-API.md) | 已安装且正确配置组件的 WeFlow 可另评估 loopback API/SSE 桥接；本项目尚未接入，不以 HTTP health 代替账号/会话或正文资格 |

WeFlow 此 revision 的 [LICENSE](https://github.com/hicccc77/WeFlow/blob/2f23e72cebf7f309a0f4d129307d16d7b0cd41c3/LICENSE) 标为 CC BY-NC-SA 4.0。本次只参考公开协议与架构，不复制其源码/二进制到本项目 MIT/AGPL 树，不将该协议标成 MIT。

## 自主组件：复用开源密码引擎，独立实现读取业务

当前采用 AXR 已有的自主适配器 `adapters/wcdb.py`，通过 SQLCipher 的 `sqlite3_*` C ABI 使用原生只读 pager；它不依赖旧 EchoTrace `wcdb_*` DLL。SQLCipher 负责页 HMAC、事务与已提交 WAL，本项目负责明确绑定、消息表/方向/正文/排序、游标和准入。

| 层次 | 当前实现 | 后续验证 |
|---|---|---|
| Windows 安装 | helper/UIA、SDK 构建及人工模式配置；Python 3.12 Windows CI 完整安装通过 | 本机 Hello/目录权限/设备安装 |
| 口令与页密钥 | 显式 password/raw 语义，逐库 salt 派生/HMAC 后只存页密钥，缓存再次复核 | 本机必要分库及更新后的 salt |
| 读取 | READONLY、query_only、参数绑定、查询/单元格预算、关闭连接 | 本机正文、压缩、持续写 WAL/重启 |
| 身份与排序 | 精确 contact 绑定、Name2Id 方向、分库代次与跨库合并 | 新分库、改名、同秒消息、历史补录、大库性能 |
| 任务与草稿 | AXR 精确能力、限时加密任务、持久去重、获准披露、人工提交 | Windows 完整回信/人工提交记录闭环 |

自主业务实现无需重写 SQLCipher 密码算法。若以后需要兼容 WeFlow 的 `wcdb_*` 协议，应另写只读 ABI 包装并逐项资格验证；当前 AXR 适配器不是可直接填入 WeFlow 的 DLL。

## 本次落地的 legacy 能力诊断

- 五个生命周期/释放接口仍为必需，缺失时在初始化和读取凭据前明确拒绝。
- 会话、显示名、消息查询按需检测；消息接口缺失时会话目录仍可诊断，消息读取明确报不可用，不返回空消息。
- `wechat_status.native_capabilities` 显示接口存在性。游标打开/取批次/关闭三个导出同时存在才报告完整；不会调用游标，`message_cursor_enabled=false`、`runtime_qualified=false`。
- 不绑定任意 SQL、编辑/删除、反撤回、全账号导出、云上报或取钥接口。接口存在不证明第三方 DLL 内部只读，来源与实机资格仍须独立核对。

消息游标的真实快照语义、后台通知管道和 HTTP/SSE 适配尚未实现。不会把新增导出检测描述成已修复 `-100` 或已完成实时监听。
