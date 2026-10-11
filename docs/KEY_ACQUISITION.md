# Windows 本机密钥获取与导入

本项目现有 0.6.2 实机记录中，已有 DPAPI 凭据通过会话库和三个消息分库首页面
HMAC 校验，模式均为 password。先复用验证通过的凭据；DLL 返回 -100 本身不能
证明缺少密钥。下面的新缓存导入功能仅完成合成测试，尚未在真实 Windows 上验收。

## 1. 先检查已有凭据

在本项目目录、本人 Windows 交互终端运行：

```powershell
.\.venv\Scripts\python.exe .\server.py --config .\config.database.json --probe-database-key
```

`message_key_verified=true` 表示配置范围内发现的会话库和消息分库首页面全部
匹配，不需要为同一代数据库重新获取密钥。此结果不证明消息读取、账号认证、
完整分库覆盖或实时性。原生 DLL 的查询/关闭错误仍需另行解决。

## 2. 若确实没有有效密钥，尝试开源工具

参考 [chatlog-keeper 固定源码](https://github.com/labazhou2024/chatlog-keeper/tree/2225294fd0761e10ce15540f21e7dbb2ac304c3c)。
其 Windows 路线分为被动进程读取与启动调试捕获；README 声称新版本可能无法
被动获取。这是上游说明，本项目没有验证你的微信版本兼容性。

如需尝试，在独立目录安装固定版本（不要覆盖本项目环境），先保持本人微信登录：

```powershell
git clone https://github.com/labazhou2024/chatlog-keeper.git
cd chatlog-keeper
git checkout 2225294fd0761e10ce15540f21e7dbb2ac304c3c
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m chatlog_keeper.cli extract-key --source wechat --method passive
```

这里明确选择 passive。不要省略 method：上游默认 auto 可能退到启动调试方式。
本项目不会自动执行上游、附加调试器、关闭微信或导出聊天。被动尝试失败时，
应在设备上核对具体版本和失败记录，不能把失败写成已成功获取，也不要把密钥
粘贴到聊天、命令参数或 GitHub。主动启动调试属于另一项尚未实测的设备实验。

## 3. 导入明确选定的本机缓存

固定源码使用 64 位十六进制文本缓存。默认全局缓存为
`%LOCALAPPDATA%\chatlog-keeper\data\secrets\wechat_db.key`；账号缓存位于同目录的
`wechat_accounts`，文件名是上游账号目录标识的 SHA-256。若上游使用了自定义路径，
需明确选择实际缓存文件。本项目不遍历账号、不自动选择多个候选。

回到本项目目录，在交互终端运行（参数是文件路径，不是密钥）：

```powershell
.\.venv\Scripts\python.exe .\server.py --config .\config.database.json --import-keeper-key "$env:LOCALAPPDATA\chatlog-keeper\data\secrets\wechat_db.key"
.\.venv\Scripts\python.exe .\server.py --config .\config.database.json --probe-database-key
```

导入仅有界读取一个明确选择的普通缓存文件，拒绝链接、硬链接、Windows reparse
标记、超长和无效内容；使用配置账号的会话库和最多 64 个数字编号消息库首页面
重新验证。全部匹配且至少有一个消息库，才原子保存原始候选到现有账号/路径绑定
的 Windows DPAPI 凭据。不同分库使用不同密钥时整次拒绝，不部分更新。

输出只有计数和 `key_imported`，不含密钥、salt、账号、路径或正文；校验失败非零
退出且不覆盖旧凭据。保存失败也非零退出。`state_changed=false` 指未改动消息状态、
基线或队列；`key_imported=true` 单独表示凭据已写入。重启既有服务后才使用新凭据。
原始第三方缓存保持原样，本项目不复制或删除它，也不更改它的 ACL。

本流程信任用户选择的本机文件与配置，不抵抗已控制同一 Windows 用户的程序。
终端检查不是独立所有者认证。HMAC 证明候选与页面匹配，不替代联系人身份绑定。
没有新增 MCP 密钥接口，没有启动消息读取、监听、模型或发送。

## 设备验收仍需完成

记录 Windows/Python/微信版本和固定工具 revision，仅记录脱敏计数：

1. 确认已有 key 是否仍匹配；如不匹配，记录上游 passive 是否实际取得有效缓存。
2. 验证新 CLI 的 DPAPI 保存及重启后复核；用错误候选确认旧凭据不受影响。
3. 验证 Windows junction/reparse 文件拒绝、权限失败和被占用文件行为。
4. 独立验证指定私聊正文、方向、分页与增量，再讨论运行后端接入。

本轮开发环境为 Linux，DPAPI 写入在新增测试中使用 mock；合成首页面和缓存通过
不代表 Windows 取钥、进程读取、微信正文或端到端收发成功。
