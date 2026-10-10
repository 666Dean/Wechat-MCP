# WCDB 实时数据库读取原型（0.4.0）

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

## 轮询与预览

仍使用 `poll_messages`、`reply_to_message`、`dismiss_message`，没有凭据或绑定写入 MCP 工具。
读取由客户端每次调用触发，可读取显式绑定的后台会话；没有文件监听、定时器或 AI 调度。
状态报告 `coverage=configured_database_conversations_only`。

- 每个账号与会话第一次成功读取只记录身份基线，历史不入队；新增绑定也先建立基线。
- 基线、已见身份和新消息队列在同一 SQLite 事务提交，失败不确认新消息。
- 重启继续使用持久基线；已处理消息不重新入队，仍有效的 pending 事件继续返回。
- 去重包含账号、会话、来源及原生元数据，不仅使用 local_id。
  有 `source_db` 时按分库区分；无分库标识时要求正的 server_id，并合并 local_id、时间和 sort_seq。
  已有分库标识时，server_id 从零变为有效值不会产生第二个事件。
  server_id 稳定性尚未实机验证；缺少两种身份依据时明确报错。
- 只接收可确定方向的未压缩文本；自身、非文本、未知方向和压缩/二进制内容被过滤。
  新身份全部记录为已见，过滤后的正文不保存；后续补解码不会自动重放这些消息。
- 过期按原生 `create_time` 计算，不因读取或重启重新获得 15 分钟资格；未来时间不入队。
- 返回合计最多 50 条事件，包含 `account_id`、`conversation_id` 和 `source`；预览草稿持久保存。
- 数据库来源强制预览，即使 `send_enabled=true` 也不能调用 UI 发送。
  状态中 `send_enabled=false` 是有效权限，`configured_send_enabled` 是原始设置。
- 预览再次核对账号绑定和显示名。UI 名称不能证明与数据库 ID 相同，发送映射待实现。

状态库固定到一个账号和入口规范路径，其他账号或入口使用独立 `state_file`。
数据库配置、会话绑定和读取限额变化需重启；主动回复名单仍可热加载。
0.3.x 队列按追加列迁移，保留正文和回复状态，中断 sending 恢复为 unknown。
后端之间不混用事件；切换后失去资格的旧 pending 标为 dismissed。

## 分页策略与限制

ABI 只有 offset 分页，没有分库游标或一致快照。首版每次进行有界完整对账，分页重叠 20%，
最多三轮寻找两次相同结果，再根据持久已见集合输出增量。
`reader_conversations.reconciled_at` 记录对账时间，`reader_seen` 保存分来源身份集合；
**尚未实现高效分库高水位游标**。

超过 `max_pages`、结果持续变化、未知身份或原生错误时停止，不推进基线。
默认 `page_size=200`、`max_pages=100`，重叠后覆盖约 1.6 万条。
大历史会话开销较高；稳定检查不是原生事务快照，不能保证零漏收。
删除消息、撤回、历史补录、压缩文本、数据库替换恢复及长期性能待处理。

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
