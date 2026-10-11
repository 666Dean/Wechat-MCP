# Mac 270134 原生发送适配记录

2026-10-11。本轮直接分析原版程序代码，停止实际微信 OCR 路线。**还没有可安全调用的私聊发送 ABI，也没有真实发送。**

## 本机样本与已定位代码

严格校验腾讯签名原版 4.1.15.54 / build 270134，实际核心为 `Contents/Resources/wechat.dylib`，不是 Frameworks 下同名加载层。

- arm64 UUID：`8acf7a2f-517c-32b4-9dfb-47e8849cd444`。
- universal 核心文件 SHA256：`a1709ba62cae1b8b2705137980e23983ed42dc88affe774c4442488b82b007fe`。
- 从 Mach-O `LC_FUNCTION_STARTS` 取得函数边界，地址均为未加 slide 的虚拟地址，不能当作 universal 文件偏移或进程指针。

| 分析角色 | 函数区间，右端不包含 | 当前证据 |
| --- | --- | --- |
| 任务入口 | `0x59708f8 .. 0x5970a40` | 两个 `MMStartTask` 字符串引用，调用下列 manager；不是文本发送请求构造器 |
| 任务 manager | `0x597bd60 .. 0x597be14` | 一个同名字符串引用，入口与 manager 关系由 BL 指令验证 |
| 请求序列化候选 | `0x597da2c .. 0x597dd34` | 三个 `Req2Buf` 字符串引用；内部含间接调用，不能据此确定参数、对象布局与线程规则 |

函数完整字节 SHA256 固定在 `adapters/macos/native_qualification.py`，与整文件哈希、UUID、build、厂商签名共同核对。
上层字符串的另一个候选被排除：`0x48a6e88` 的代码用常量拼接 `SendMsgFailed` 并做字符串比较；不能把发送失败状态比较器用作发送入口。

这些属于离线代码身份与调用链证据，不是 ABI、进程当前账号、收件人、送达或后台资格。没有加载/执行候选地址、附加到进程、修改程序、请求序列化或屏幕保护。

## 可复现的校验入口

安装 AXR Python SDK 后，在 macOS 仓库根目录运行：

```sh
python -m adapters.macos.native_qualification
```

入口只允许固定安装位置，没有用户提供的地址、调用签名、收件人、正文或发送参数；不是 MCP 工具。读取 bundle 元数据和核心程序字节，前后校验原厂签名身份；拒绝链接、硬链接、非普通文件、超限及读中替换。不同 build、模块、函数字节或锚点失败即返回非零，异常隐藏路径及子进程诊断。

本机实际运行结果：3 个函数指纹、任务调用链和厂商签名通过；`native_send_available=false`、`runtime_identity_verified=false`。不会写 OwnerStore、访问 Keychain/数据库、发放权限、读取画面或发送。无需为离线程序代码校验新增聊天授权。

SDK 的 `axr.native_image.NativeImage` 是独立编写的通用离线工具，只解析 arm64 Mach-O：有界 universal32/64 切片、唯一 UUID、文件支持的代码区、函数边界/哈希、直接 BL 目标和相邻 ADRP/ADD 字符串引用。不执行文件、猜寄存器状态或自动迁移旧偏移；同样没有授予调用权限的接口。微信版本知识保持在 SDK 外。

## 原生发送尚缺的证据

现有 WCDB 的稳定账号/私聊绑定与读取授权不能代替运行中的原生收件人见证；窗口标题、一个已签名的配置字段或函数指纹也不能代替它。

进入两个指定既有私聊的真实测试前，还需要从当前样本验证：

1. 上层文本请求的原生构造、字段类型/位置、对象所有权和析构；不能把旧 C++ string / Task 布局直接搬到当前版本。
2. 原生调用所在线程、错误与取消契约，以及当前进程/模块身份。
3. 调用前后独立核对登录账号和精确私聊 ID；本人目标保持内部账号 ID 私聊，不换成文件传输助手。
4. 精确正文的单次 AET 提交，以及独立只读 WCDB 对完整正文、本人 sender、非零 server_id 和唯一记录的观察；异常保持 Unknown，不自动重发。

完成这些证据后，分别测试两个私聊的前台发送和失焦/后台提交；失焦菜单、历史后台读取或合成发送不能替代实机结果。多日运行另行验收。

## 开源路线的具体判断

[wechat_chatter 的地址定位说明](https://github.com/yincongcyincong/wechat_chatter/blob/f222f37321f66d3a199cb3c7642f77f7504d85da/tools/addrfind/README.md) 自身要求候选进行运行时验证，跨版本签名也有失配。其发送脚本还修改序列化路径并保留历史固定地址，不能直接部署到本机；仅静态阅读，未复制或运行该脚本。

[SovietExtension 的发送代码](https://github.com/MustangYM/SovietExtension/blob/a0e7533ff39b14fc135445c4c79d838544b97fdc/SovietExtension/SovietExtension/ForwardToSelfPatch.mm) 使用旧版本对象构造/析构和转发契约；当前分析没有证明该 ABI 适用 270134。

[wechat-antirecall](https://github.com/fzlzjerry/wechat-antirecall) 的公开兼容表最高为 270132，内容预览和请求功能不是原账号文本回复资格；没有运行它的安装器、撤回拦截或金融功能。当前不能把这些兼容声明升级成 270134 真实私聊发送证据。

## 本轮验收边界

新增 6 项回归覆盖非零 VM 基址与 fat 切片、畸形边界/ULEB、错架构/重叠、链接、错误脱敏、构建/签名前后身份及代码身份不升级发送权限。本机 201 项发现，199 项执行通过、2 项平台跳过。双平台 CI 另随 PR 更新；Windows 无微信实机测试。

原版签名保持有效。两个真实私聊的发送、发送后读回、后台写入和多日运行仍未完成，因此保持同一 Draft PR，暂不合入主分支。
