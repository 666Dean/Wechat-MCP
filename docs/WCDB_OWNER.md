# AXR 模式的本地 WCDB 初始化

此工具属于微信集成，位于 `adapters/`，不属于应用无关 AXR SDK。
主人必须在自己的交互终端运行；MCP 不提供密钥获取、导入、审批或授权工具。
先按 [Gen1 说明](AXR_GEN1.md) 初始化 AXR 所有者状态与系统认证 helper。

指定自己的 v4 `db_storage` 目录。工具仅盘点有限数量的加密数据库首个页，
不导出消息或完整联系人列表；首个页 HMAC 校验成功后才将原始密钥保存到
同一个 AXR 所有者的 Keychain / Windows Credential Manager。索引只含路径、
salt、profile 和凭据引用，保存在私有状态目录。

已有密钥的 macOS / Windows 使用方式：

```sh
python -m adapters.wcdb_owner --state STATE --helper HELPER --account-root ACCOUNT_DB_STORAGE import-key --database message/message_0.db
```

密钥只能在隐藏输入中录入，不能放入 argv、环境变量、聊天、配置文件或管道。
本轮没有提供 Windows 自动取得密钥的实现或微信设备验收。

macOS 可选的启动观察方式：

```sh
python -m adapters.wcdb_owner --state STATE --helper HELPER --account-root ACCOUNT_DB_STORAGE observe-mac --observer ROOT_BUILD/libwechat-key-observer.dylib --allow-temporary-copy
```

主人先正常退出已安装微信。明确选择此模式并完成系统认证后，工具制作私有临时副本，
先严格验证副本 Tencent 签名及 Identifier / TeamIdentifier / CDHash 与原版一致，再给该副本临时 ad-hoc 签名，并在其启动时加载本项目构建的 C++20 KDF observer。
observer 调用 Apple 原有 KDF，保持参数、结果与返回状态，只将匹配的派生结果经
当前用户的 0600 FIFO 交给父进程。父进程只接受选定账户数据库的 salt/HMAC 校验结果，
120 秒、128 条记录封顶；没有调试附加、进程内存扫描、登录 token 读取或 SIP 修改。
这属于临时副本内的可选 interposition，并非普通无注入读取模式。
该副本正常启动可能产生微信自身的网络与本地状态活动。

原版签名有效且已确认正常退出后，即使复制、签名或临时启动失败，也会清理临时目录、
复核原安装签名并以干净环境恢复原版；用户已重新打开原版时不再重复启动。临时进程退出
后才关闭 FIFO 读端。不同账户的捕获还共享当前用户的客户端互斥锁。认证失败不会进入
副本准备，也不会改变客户端生命周期；已完整校验的缓存可直接返回，不改变客户端状态。未观察到的数据库不标为支持；超时保留已验证的 Keychain 条目，
不导出原始 key。已有条目每次重新校验，完整覆盖时可直接复用，免去副本启动。
FIFO、主人终端、构建产物和凭据库属于同用户可信控制面，不抵抗已控制同用户的程序。

绑定账户与指定私聊：

```sh
python -m adapters.wcdb_owner --state STATE --helper HELPER --account-root ACCOUNT_DB_STORAGE qualify --sqlcipher-library SQLCIPHER_LIBRARY --account-id OWNER_ACCOUNT_ID --contact EXACT_CONTACT_LABEL --contact OWNER_ACCOUNT_ID
```

v4 目录名候选与 contact 表必须唯一匹配账户 ID；指定名称/备注/ID 必须唯一匹配
活跃私聊联系人。群聊、公众号、删除项、同名私聊与重复身份被拒绝。消息分库还须
通过原生 SQLCipher 只读 schema 打开验证。工具输出仅为计数，生成私有
`wcdb-qualified-local.json` 配置片段，主人审阅并合入 policy 后再用 `axr-owner configure`
认证启用；不会自动修改 policy、发放 capability 或开启监听/模型/发送。

当前仅支持已校验的 SQLCipher4 4096-byte / HMAC-SHA512 原始 key 与所列 v4 schema。
WCDB 压缩类型 4/5 使用有界完整 Zstd frame；2/3 的字典模式明确拒绝。
参考 [Tencent 压缩类型定义](https://github.com/Tencent/wcdb/blob/master/src/common/core/compression/CompressionConst.hpp)。
配置与 key reference 不证明当前 UI 账号/目标；数据库身份不能替代 UI 发前稳定 witness。
