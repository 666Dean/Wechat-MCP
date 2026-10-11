# 开源数据库读取路线评估

初次审查日期：2026-10-10。初次只检索 GitHub、下载源码作静态阅读；没有安装或运行候选，
没有用候选读取真实微信、扫描内存、附加调试器或发送消息。现有 0.6.1 的消息查询
仍返回 -100。以下建议是基于所查看代码的判断，不是兼容承诺或完整安全审计。

## 候选与固定源码

| 项目 | 审查提交 / 许可证 | 已看到的实现 | 判断与限制 |
|---|---|---|---|
| [chatlog-keeper](https://github.com/labazhou2024/chatlog-keeper) | `2225294fd0761e10ce15540f21e7dbb2ac304c3c` / MIT | Python；首页面 HMAC 判别直接密钥与 PBKDF2 派生；主库逐页 HMAC；WAL 校验及提交边界；单会话分库 keyset 分页；zstd 正文解码 | 首选验证参考。README 声称支持 Windows 新版，但本机未验证；缓存失效仍重新解密整库，不能直接当成高效常驻增量后端 |
| [wxq](https://github.com/vpcoderli/wxq) | `8f6d0b29d2d649d4fc16fedcd9eff59c40a194d4` / MIT | Python CLI/MCP；AES 页解密、WAL 回放、zstd 消息解析；主库与 WAL mtime 缓存 | 可参考简洁的格式解析。所查看 decrypt_page/full_decrypt 未逐页验证 HMAC；decrypt_wal 未按提交标记限制回放，不能直接沿用实时一致性逻辑 |
| [wechat-cli-local](https://github.com/Chihiro521/wechat-cli-local) | `5ba6bb7adb18045ada6066a9b80f483412d1c742` / Apache-2.0 | Python 核心及 Windows CLI 包装；AES 页解密与 WAL 回放 | Windows 备选。所查看 crypto.py 同样直接使用页密钥且未逐页校验 HMAC、未按 WAL 提交标记限制回放；不是已验证的替代 DLL |

许可证仅描述对应仓库的 LICENSE；若采用代码，还需复核来源、NOTICE 和依赖许可证，
保留必要声明。本次没有将第三方源码、依赖或可执行文件纳入本项目。

审查定位：

- chatlog-keeper [wechat_db.py](https://github.com/labazhou2024/chatlog-keeper/blob/2225294fd0761e10ce15540f21e7dbb2ac304c3c/chatlog_keeper/wechat_db.py)：
  `_effective_page_key`、`_decrypt_wechat_page`、`_decrypt_db_v4_snapshot`、
  `_query_conversation_page_rows`、`_decrypt_with_cache`、`_decompress_message`。
  分页 SQL 使用每分库 `(create_time, rowid)`，不能把 rowid 直接当成全局消息 ID。
- chatlog-keeper [WAL](https://github.com/labazhou2024/chatlog-keeper/blob/2225294fd0761e10ce15540f21e7dbb2ac304c3c/chatlog_keeper/core/_wal.py)
  与 [快照](https://github.com/labazhou2024/chatlog-keeper/blob/2225294fd0761e10ce15540f21e7dbb2ac304c3c/chatlog_keeper/core/_snapshot.py)：
  检查 WAL 校验和、提交标记及侧文件。Windows 快照有打开 SHM 为 r+b 并短暂锁住写入/检查点的兜底路径，
  因此不能把整个现成导出流程视为纯只读、无客户端影响的替换。
- wxq [crypto.py](https://github.com/vpcoderli/wxq/blob/8f6d0b29d2d649d4fc16fedcd9eff59c40a194d4/src/wxq/core/crypto.py)、
  [缓存](https://github.com/vpcoderli/wxq/blob/8f6d0b29d2d649d4fc16fedcd9eff59c40a194d4/src/wxq/core/db_cache.py)、
  [消息解析](https://github.com/vpcoderli/wxq/blob/8f6d0b29d2d649d4fc16fedcd9eff59c40a194d4/src/wxq/services/message_parser.py)。
- wechat-cli-local [crypto.py](https://github.com/Chihiro521/wechat-cli-local/blob/5ba6bb7adb18045ada6066a9b80f483412d1c742/wechat_cli/core/crypto.py)。

## 不优先采用的旧项目

[PyWxDump](https://github.com/xaoyaoo/PyWxDump) 和 [chatlog](https://github.com/sjzar/chatlog)
当前主仓库声明代码及历史已移除；[WeChatMsg](https://github.com/LC044/WeChatMsg)
当前主仓库没有完整应用源码，作者声明不再更新。不能因历史关注度高而认为现在可直接接入。
[Tencent WCDB](https://github.com/Tencent/wcdb) 是数据库框架，不能单独完成微信客户端的密钥、表结构与正文解析。

## 2026-10-10 的实验计划

1. 保持已授权的单私聊范围及现有 DPAPI 凭据。先用受控本机诊断只检查必要数据库的首页面：
   尝试直接页密钥与 PBKDF2-HMAC-SHA512 派生模式，并核对 HMAC，仅输出匹配/不匹配统计。
   同为 64 位十六进制不证明密钥语义一致；元数据库成功也不证明消息分库能用同一密钥。
2. 匹配后对必要消息分库制作受控私有快照，逐页校验、只回放已提交 WAL。
   快照变化、校验失败或表结构不符必须停止。先评估 Windows 快照策略，避免直接运行现成全账号导出或自动提取命令。
3. 只查询已绑定会话的最多 20 条文本，核对方向、发送者与 zstd 解码；结果只报告统计。
   不入队、不发送，不将失败替换成空消息；明文快照的保护、失败清理和留存需同时设计。
4. 真实正文通过后再实现本项目独立后端。分库游标必须绑定账号、会话、库身份/代次，
   处理新分库、同秒消息、历史补录、重建/截断和事务提交；是否有可用索引必须检查查询计划。
   避免每次新增消息就重新解密大库，另行比较只读 SQLCipher 查询与受验证的 WAL 增量缓存。

数据库来源继续强制预览；新后端、分库游标、常驻监听和数据库到发送目标映射均未因此完成。

## 2026-10-11：密钥模式与少量正文实验

### 已实施及证据

- 新增本项目 `--probe-database-key`，只依赖标准库和既有 DPAPI 凭据；不加载 DLL，
  不运行候选的自动初始化、内存扫描或调试器。真实 CLI 校验会话库及 3 个数字编号消息库：
  checked=4、password=4、raw/unmatched/error=0。此前手工诊断包含消息目录中的辅助数据库，
  总计 6 个首页面均匹配；它们不是 5 个数字编号消息分库。
- 该结果确认已有凭据可用于所检查数据库的首页面，需要基于每库 salt 进一步派生。
  不确认 DLL 的 -100 原因，也不擅自改写 DPAPI 凭据或传给 DLL 的密钥。
- 为避免整库明文解密，改用 [apsw-sqlite3mc](https://github.com/utelle/apsw-sqlite3mc)
  3.53.4.0（SQLite3 Multiple Ciphers 2.4.0）的一次性本机实验。依赖安装在忽略目录，
  没有改变项目 requirements.txt 或打包第三方二进制；没有运行 chatlog-keeper 的提取/导出代码。
  按 [引擎文档](https://utelle.github.io/SQLite3MultipleCiphers/docs/ciphers/cipher_sqlcipher/)
  配置 sqlcipher/legacy=4 与二进制口令，查询前设置 query_only，连接 flags=READONLY。
- 临时复制一个消息库及存在的 WAL/SHM，保留加密格式；复制前后以及查询后复核源文件
  大小、mtime 与首尾内容摘要。只在副本上建立连接，原文件始终仅 rb 读取，没有明文库落盘。
  此检查仅支持本次稳定副本实验，不等价于持有数据库快照锁或成熟的实时一致性协议。
- 参数绑定检查已授权会话的 MD5 表名，仅查询该表最多 20 条 type=1 文本；严格 UTF-8
  解码 20/20 成功，发送者映射为该好友 9、本账号 11、未知 0。所选样本来自一个分库，
  不声称是跨分库全局最新 20 条，也没有重新验证显示名或原生账号身份。
- 正文、联系人标识、密钥与原始错误均未输出或存档；没有建立基线、入队或发送，
  临时加密副本与连接已清理。诊断实验使用独立进程，一次性脚本留在忽略目录。

### 尚未完成

- 原生 DLL 消息及关闭故障仍存在；MCP 运行后端仍是原有实现。
- 样本中 zstd 压缩正文计数为 0。实验已安装 zstandard 0.25.0，但不能把解码分支存在
  当成压缩正文实机验证成功；引用、媒体、群聊、撤回均未验证。
- 下一步应实现按需只读的受控后端与跨分库排序，验证 WAL 边界、改名/身份核对、
  新分库、同秒消息、历史补录、取消与错误恢复；再量化多次读取的大历史开销。
  引擎、只读副本策略及依赖许可证必须在接入产品时明确，不能直接沿用实验脚本。
