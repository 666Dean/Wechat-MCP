# WCDB 实时数据库读取原型（0.6.0）

2026-10-10：代码与合成测试已完成，**尚未连接真实微信数据库**。
ABI 对照 [EchoTrace v3.0.2 FFI 源码](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/lib/services/wechat_wcdb_native.dart)
与 [原生接口文档](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/docs/wcdb_realtime.md)。
不打包 DLL、不自动搜索账号、不提取现有软件密钥、不提供发送接口。

## 本机配置

需要 Windows x64 Python，以及使用者自行提供的兼容 DLL、配套依赖和数据库密钥。
UI 后端和数据库后端二选一；数据库模式无需 wxauto4 的 UI 初始化。

1. 复制 `config.database.example.json` 为本机 `config.database.json`（已排除 Git）。
2. 修改 `account_id` 为自己的账号 ID；`session_db` 为该账号 `db_storage/session/session.db`
   的绝对路径。账号目录须为 `account_id` 或以 `account_id_` 开头的目录。
3. 配置 `wcdb_api.dll` 的绝对路径。不会扫描其他安装目录或自动回退到模拟后端。
4. `key_file` 设置为私有目录中的独立 `.dpapi` 文件绝对路径；目录需要已存在。
   凭据文件、配置、状态库、微信数据库和 DLL 不得共用路径。
5. 填写允许读取的私人好友 ID 和当前唯一显示名，例如：

   ```json
   "conversations": [
     {"conversation_id": "wxid_friend_example", "display_name": "测试好友唯一备注"}
   ]
   ```

   这是读取授权范围。`active_contacts` 决定哪些绑定会话可主动代回复；
   其余绑定会话仅在明确呼叫 Codex 时入队。未绑定会话不查询消息正文。
   同名、改名或会话缺失会停止轮询，不自动寻找替代对象。
   群、公众号、本人和已知系统会话不能加入绑定；其他 ID 的私人好友性质由使用者核对。
6. 在本机交互终端录入密钥，不通过 MCP、聊天、参数或管道传入：

   ```powershell
   .\.venv\Scripts\python.exe .\server.py --config .\config.database.json --store-database-key
   .\.venv\Scripts\python.exe .\server.py --config .\config.database.json --doctor
   ```

录入不回显。DPAPI 使用当前 Windows 用户加密，并绑定账号和数据库规范路径；
不同账号路径不能复用凭据。原子保存，密钥不进入配置、SQLite 或工具结果。
更换密钥后重启；删除文件不能撤销已打开的原生句柄。
同一 Windows 用户下其他程序仍属于信任边界；这不提供独立所有者认证。

`--doctor` 打开句柄、查询会话与显示名并核对绑定，报告数量，不查询正文。
`connected=true` 表示原生查询成功，不代表发送可用或已验证完整消息格式。
MCP 参数使用 `--config` 指向本机配置，不添加 `--demo`。

## 查询会话 ID 与诊断改名

配置账号、入口、DLL 和本机密钥后，可以先保持 `conversations=[]`，运行：

```powershell
.\.venv\Scripts\python.exe .\server.py --config .\config.database.json --list-database-sessions
```

此本机 CLI 只调用会话和显示名接口，输出 ID、名称、`can_bind`、`configured`、
`binding_matches` 和排除原因。原生会话记录可能含消息摘要，代码丢弃这些字段；
不调用消息查询、不输出摘要、不修改绑定、不创建状态库，也不提供对应的 MCP 发现工具。
输出包含私人联系人元数据，请在本机核对，不公开分享。

`can_bind` 只排除已知群、公众号、本人、系统 ID 及缺失/重名显示名，不证明好友身份。
已有会话改名时，此命令仍可查看新名称，手工修正本机绑定后重启；
正常状态、轮询和预览仍拒绝名称不符，不因诊断查询放宽授权。
查询或打开失败返回非零退出码，已打开句柄会关闭。

## 小范围消息验证

配置并绑定一个测试好友后，在本机运行：

```powershell
.\.venv\Scripts\python.exe .\server.py --config .\config.database.json --probe-database-messages wxid_friend_example --probe-limit 20
```

仅查询该绑定会话 offset=0 的一页，限额 1–50（默认 20）；读取前后核对所有配置绑定。
输出样本数、可读收到文本数、分库身份数和观察到的时间降序情况，不输出正文、账号、
联系人名或消息身份，不创建状态库、不建立基线、不入队、不发送；成功或失败都会关闭句柄。
身份缺失、原生错误或改名会非零退出，不能用空结果掩盖读取失败。
空页和单条消息的排序结果为 null；单页降序并不证明整个会话的排序或实时新增可靠。
该 CLI 不能替代本机人工内容核对及双次读取的新消息延迟实验。

## 轮询与预览

使用 `poll_messages`、`list_reply_queue`、`reply_to_message`、`dismiss_message`，没有凭据或绑定写入 MCP 工具。
读取由客户端每次调用触发，可读取显式绑定的后台会话；没有文件监听、定时器或 AI 调度。
状态报告 `coverage=configured_database_conversations_only`。

- 每个账号与会话第一次成功读取只记录身份基线，历史不入队；新增绑定也先建立基线。
- 基线、已见身份和新消息队列在同一 SQLite 事务提交，失败不确认新消息。
- 重启继续使用持久基线；已处理消息不重新入队，仍有效且尚无草稿的 pending 事件继续返回。
- 去重包含账号、会话、来源及原生元数据，不仅使用 local_id。
  有 `source_db` 时按分库区分；无分库标识时要求正的 server_id，并合并 local_id、时间和 sort_seq。
  已有分库标识时，server_id 从零变为有效值不会产生第二个事件。
  server_id 稳定性尚未实机验证；缺少两种身份依据时明确报错。
- 只接收可确定方向的未压缩文本；自身、非文本、未知方向和压缩/二进制内容被过滤。
  新身份全部记录为已见，过滤后的正文不保存；后续补解码不会自动重放这些消息。
- 过期按原生 `create_time` 计算，不因读取或重启重新获得 15 分钟资格；未来时间不入队。
- 返回合计最多 50 条事件，包含 `account_id`、`conversation_id` 和 `source`；预览草稿持久保存。
- 已保存预览从轮询事件中移除，通过 `list_reply_queue` 分页查看；读取队列无需连接原生数据库。
  队列仍检查本机授权和时效，离线结果不验证实时账号或目标，详见 [队列使用说明](../README.md#查看已保存的预览)。
- 数据库来源强制预览，即使 `send_enabled=true` 也不能调用 UI 发送。
  状态中 `send_enabled=false` 是有效权限，`configured_send_enabled` 是原始设置。
- 预览再次核对账号绑定和显示名。UI 名称不能证明与数据库 ID 相同，发送映射待实现。

状态库固定到一个账号和入口规范路径，其他账号或入口使用独立 `state_file`。
数据库配置、会话绑定和读取限额变化需重启；主动回复名单仍可热加载。
0.3.x 队列按追加列迁移，保留正文和回复状态，中断 sending 恢复为 unknown。
后端之间不混用事件；切换后失去资格的旧 pending 标为 dismissed。

## 分页策略与限制

ABI 只有 offset 分页，没有分库游标或一致快照。默认 `scan_mode="full"` 每次进行有界完整对账，分页重叠 20%，
最多三轮寻找两次相同结果，再根据持久已见集合输出增量。
`reader_conversations.reconciled_at` 记录对账时间，`reader_seen` 保存分来源身份集合；
**尚未实现高效分库高水位游标**。

超过 `max_pages`、结果持续变化、未知身份或原生错误时停止，不推进基线。
默认 `page_size=200`、`max_pages=100`，重叠后覆盖约 1.6 万条。
大历史会话开销较高；稳定检查不是原生事务快照，不能保证零漏收。
删除消息、撤回、历史补录、压缩文本、数据库替换恢复及长期性能待处理。

### 可选近期窗口

0.6.0 增加 `database_reader.scan_mode="recent"`，旧配置省略字段仍为 full。
**仅在本机确认原生返回按 create_time 从新到旧排序后显式启用**；ABI 没有承诺此顺序。
模式改动需要重启。状态和轮询结果报告实际 scan_mode，不会自动开启。

每次轮询固定当前时间减 900 秒为截止时间；仍重叠分页、要求两次相同结果，遇到整页
均已过期即可停止。页内或跨页观察到时间逆序、超过 max_pages、持续变化或无效身份时
明确失败，不推进基线或已见集合，不自动回退。高频会话的近 15 分钟仍可能超限。
窗口中首次可见消息只建立基线，重启去重与队列仍原子提交；只为实际扫描的身份保存已见记录。
切回 full 可补充历史身份，过期历史不会获得新回复资格。

这是按现有回复时效裁剪扫描范围，**不是分库高水位游标、历史备份或完整对账**。
未扫描的旧页中出现乱序新消息无法检测；历史补录、时间调整、删除/恢复及原生排序变化
都可能造成漏读，不能以已观察页面有序推断全历史有序。未实机验证该模式。
合成的 1 万条过期历史、page_size=4 场景只需两次各一页；新增一条近期消息后各两页。
这只证明 Python 侧调用次数下降，原生接口内部仍可能扫描/排序全库，不代表实测延迟提升。

账号绑定来自使用者配置和目录检查；ABI 无本人身份接口，不能认证实际登录账号。
运行中入口被替换会停止查询；微信重登录、升级恢复尚未验证。
代码只调用读取接口，未审计原生内部文件操作或日志，不能作为二进制安全证明。
队列正文和草稿为本机明文，过期不删除，见 [认证说明](AUTHENTICATION.md)。

## 验证证据

合成 ctypes C 回调验证 Int64、UTF-8、成功/错误路径指针释放与打开失败清理；
合成流验证基线、重启、同秒消息、分库冲突、分页新增、账号变化、事务回滚和规则撤销。
真实 MCP stdio 传输搭配合成读取器验证轮询到预览。
Windows DPAPI 使用人工生成测试密钥验证往返和绑定，没有读取现有软件凭据。
这些证据不等于真实 WCDB 或微信收发验证。
