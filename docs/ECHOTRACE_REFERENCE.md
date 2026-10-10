# EchoTrace 数据读取参考与接入设计

审查日期：2026-10-10。本页保留 0.3.0 的参考分析和设计。
**0.4.0 已新增独立数据库读取原型并接入预览队列，尚未验证真实读取。**
当前实现、凭据配置与分页限制见 [DATABASE_READER.md](DATABASE_READER.md)。

## 参考版本与证据

- 本机提供的软件元数据为 EchoTrace `3.0.2+1`，Windows 发行目录包含 Flutter 程序、
  `go_decrypt.dll`、`WCDB.dll` 和 `wcdb_api.dll`。
- 对照公开仓库 [ycccccccy/echotrace](https://github.com/ycccccccy/echotrace)
  的 [v3.0.2 / 98280f0](https://github.com/ycccccccy/echotrace/tree/98280f0d0d7b764b2f2027fc4d103024e8ed30fd)。
  版本号相符并不证明本机二进制与该源码可复现一致。
- 静态检查本机 `wcdb_api.dll`：x64，13 个导出名称与 Dart FFI 声明吻合，
  包括账号打开/关闭、会话查询、消息查询、显示名查询和返回字符串释放。
- 使用者报告现有软件的实时模式已经能读取聊天；本轮未运行该程序或 DLL，
  没有独立验证其实时读取得到的内容、延迟或版本兼容性。
- 0.6.0 后续 UI 检查：从备份切到实时模式并保存后会话摘要更新到近期；
  一个私聊显示条数但正文为空。没有读取现有密钥或接通本项目，
  不作为文本解码、实时增量或本项目兼容性的证据。
- 当前公开仓库 README 标注停止维护；本分析固定旧版本，不把它作为持续兼容性承诺。
- 软件源码标注 [MIT](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/LICENSE)。
  参考目录和 DLL 未复制进本仓库，原生模块内部未审计。

## 数据读取如何工作

| 路径 | 已查阅的实现 | 含义 |
|---|---|---|
| 备份模式 | `DatabaseService.connectDecryptedDatabase` | 用只读 SQLite 连接解密后的数据库；读取的是备份，不等于新消息实时可见 |
| 实时模式 | `DatabaseService.connectRealtimeDatabase` | 将数据库入口路径和十六进制密钥传给 WCDB 原生接口，获得账号句柄 |
| 会话查询 | `getSessions` / `wcdb_get_sessions` | 按 username 标识会话，再查询显示名；显示名不能替代身份标识 |
| 消息查询 | `getMessages` / `wcdb_get_messages` | 按会话 username、limit、offset 获取消息；原生接口文档描述跨 message 分库聚合 |
| 消息解析 | `Message.fromMap` | 解析 local_id、server_id、sort_seq、create_time、发送者与消息类型等字段 |
| 文件变更 | `_startRealtimeWatcher` | 监听数据库目录及 .db/.db-wal/.db-shm 的变化，通知重新读取；不是逐消息可靠投递队列 |

固定版本源码：

- [数据库服务](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/lib/services/database_service.dart)：
  97–169 行备份连接，176–251 行实时连接，272–295 行变更监听，311 行起会话查询，614 行起消息查询。
- [Dart FFI 封装](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/lib/services/wechat_wcdb_native.dart)：
  账号句柄是 Int64，返回复杂数据为 UTF-8 JSON，返回字符串必须使用 `wcdb_free_string` 释放。
- [消息模型](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/lib/models/message.dart)：
  发送者 ID 与自身账号用于辅助判断自发消息，压缩内容另行解析；字段缺失不能默认视为收到的文本。
- [原生接口文档](https://github.com/ycccccccy/echotrace/blob/98280f0d0d7b764b2f2027fc4d103024e8ed30fd/docs/wcdb_realtime.md)：
  说明状态码、密钥参数、分页和句柄同步约定；原生查询能力不代表微信发送能力。

## 对当前项目的价值

当前 `WxAdapter.snapshot` 只能读取打开的可见私人聊天，消息 UI ID 可能随切换变化。
数据库读取可以提供会话枚举、账号/联系人标识和消息时间字段，为后台多会话读取提供基础。
这是可行性判断，尚未实现或验证本项目的全好友常驻监听；新增后端只读取明确绑定会话。

不能仅把配置中的 backend 改为 DLL 名称。0.3.0 的 Bridge 假设快照属于一个可见聊天，
队列唯一键为 `(peer, native_id)`，peer 是显示名称，UI 基线仅在内存；
数据库接入需要相应改造身份、队列和持久游标。

## 待实现的接入方案

```text
选定的本机账号数据库 + 本机凭据
  → 独立 DatabaseReader（账号/会话/消息读取）
  → 账号及会话 ID 校验、文本与自发消息过滤
  → 持久基线和增量去重
  → 当前规则与待回复队列
  → AI 生成回复预览
  → 独立 Sender（完成目标身份和草稿核对后，才能开启发送）
```

1. **先完成读取适配器**：使用明确配置的 DLL 绝对路径和账号入口，不自动扫描所有账号；
   先输出连接诊断与会话数量，后按授权范围读取文本。原生错误必须显式报错，不能像参考封装
   的部分函数那样将错误统一转换成空列表，否则会把断线误判为没有新消息。
2. **绑定账号和联系人**：将 account_id、conversation_id 与 display_name 分开保存。
   账号变化停止读取；备注重名拒绝自动绑定。数据库能枚举会话不意味着所有会话都授权给 AI。
3. **持久化增量状态**：第一次连接只建立基线；每个账号、会话和分库保存游标。
   去重键需要包含账号、会话与来源，验证 server_id 非零且可靠后才使用，不能只依赖 local_id。
   文件通知只是触发重新查询，还要补充定时对账、分页、重叠读取与重启恢复。
4. **保持读取与发送分离**：首版数据库能力只用于读取和预览。现有 UI 发送仍靠显示名核对，
   无法证明其目标与数据库 conversation_id 是同一人，也不能自动发送到后台任意会话。
   必须先解决目标映射、账号级互斥、草稿保护和切换竞态。
5. **处理新增凭据**：实时接口需要数据库解密密钥，这与当前 stdio 服务无 token 的模型不同。
   密钥留在本机凭据存储中，不通过 MCP 工具参数、工具结果、日志或仓库传递；状态只报告
   是否配置和是否连接。实施后需同步更新认证文档。本次分析没有读取现有软件的密钥配置。

## 验证顺序

- 合成数据验证 FFI 签名、返回指针释放、错误处理和消息规范化。
- 合成数据库/消息流验证同名联系人、多分库 local_id 冲突、无效 server_id、同秒多条消息、
  分页期间新增消息、自发消息过滤、账号变更、首次基线及重启去重。
- 本机小范围读取验证账号识别、内容解码、消息时间与数据库变更延迟；不把备份增量等同于实时消息。
- 读取稳定后再接入预览队列；发送能力单独验证，不用数据库读取成功推断发送成功。

原有 34 项模拟测试不能作为数据库读取适配器通过的证据。
0.4.0 新增独立合成 ABI、消息流、DPAPI 与 MCP 预览测试，详见 [当前状态](STATUS.md)。
高效分库游标、文件监听及真实读取仍是后续工作，不能将本页设计视为全部已完成。
