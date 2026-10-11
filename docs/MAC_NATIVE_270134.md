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

文件复核保留原句柄，用只读重新打开的精确路径取得另一份 fstat；核对设备、inode、大小、mtime、ctime、mode、nlink 全七字段。读中变化与路径指向替换分别拒绝，避免 stat/fstat 视图混比，不放宽时间精度或身份规则。

本机实际运行结果：原 3 个函数、任务调用链和厂商签名通过；本轮进一步核对下节 15 个对象/账号函数及 7 条普通微信分支调用边。报告为 `offline_layout_and_ownership_only`，`native_send_available=false`、`runtime_identity_verified=false`。不会写 OwnerStore、访问 Keychain/数据库、发放权限、读取画面或发送。无需为离线程序代码校验新增聊天授权。

SDK 的 `axr.native_image.NativeImage` 是独立编写的通用离线工具，只解析 arm64 Mach-O：有界 universal32/64 切片、唯一 UUID、文件支持的代码区、函数边界/哈希、直接 BL 目标和相邻 ADRP/ADD 字符串引用。不执行文件、猜寄存器状态或自动迁移旧偏移；同样没有授予调用权限的接口。微信版本知识保持在 SDK 外。

## 当前对象布局、所有权和账号路径

本轮对照腾讯严格签名的只读历史程序样本与 270134 代码，没有安装、运行或降级历史客户端。跨版本归一化只用于找候选，最终结论来自当前函数的实际指令和调用方；小型 getter 的签名歧义没有被当作定位成功。AppContext 入口由 1321 个匹配调用方指向同一当前入口，另由上层转发链交叉核对。

| 当前角色 | 未加 slide 的函数入口 | 当前代码证据 |
| --- | --- | --- |
| 消息默认构造 | `0x4d560dc` | 初始化 vtable、strings、shared_ptr 与容器，末字段写至 +0x34c |
| Message → 转换对象 | `0x4cbcbd8` | 0x350 字节存储；正文写入 +0xb8，输入 type=1 使用正文转换辅助函数 |
| 对象复制 / 析构 | `0x393574` / `0x394770` | +0xb8 string 的长/短字符串分支、分配/释放；shared_ptr 计数成对增加/减少 |
| 上层转发入口 | `0x186f544` | 保存 x0–x3 和隐藏返回 x8；普通目标 kind=2 分支独立于 wxwork 分支 |
| 目标查询 / 插入候选 | `0x17b5000` / `0x17b4d68` | 查询 kind=2 容器及字符串集合；不是联系人身份见证 |
| 普通目标展开 | `0x418b078` | 按目标/消息组合构造发送输入，后续仍需核对最终 wire request |
| 普通任务构造 / 订阅 | `0x4123510` / `0x186e00c` | 任务持有消息 shared_ptr 副本；订阅调用 `0x2ba25c`，结果通过 x8 返回 |
| AppContext / 账号 getter | `0x4666bd4` / `0x466dae0` | 全局 context 槽 `0xa459f98`；账号 getter 取得 account context、虚调用并释放临时 shared_ptr |
| account context / 登录状态候选 | `0x466775c` / `0x466e3c4` | 前者复制 +0x68 的 shared_ptr；后者是进一步的虚调用，不能从静态地址判断已登录 |

旧实现的 0x340 对象、+0xb0 正文与 0x358 shared allocation **不适用**。当前普通分支分配 0x368，并在 +0x18 调用 0x350 对象的原生复制构造；输入不是可 memset 后直接写入的字节数组。正文是具有内存所有权的 string，不能只填裸地址。任务构造会增加引用计数并清理局部副本，但这尚未证明取消句柄、异常、登录切换或线程契约完整。

当前代码的 shared payload 销毁辅助 `0x4e3174` 将 x0 加 0x18 后尾调用 `0x394770`；释放辅助 `0x4e317c` 使用 0x368 的分配大小。这补充对象/控制块分别销毁的静态证据，不证明异步取消或实际投递行为。任务执行仍有后续间接路径，不能在构造后立即认定已发送。

账号 getter 的结果有借用生命周期：代码在返回前释放局部 account context 引用。未来运行适配必须持有对应强引用，并在同一执行租约内重验账号、上下文和精确收件人；不能只调用 getter 后跨线程保存裸指针，更不能把当前聊天对象、显示名或 WCDB 配置当作运行账号。本轮没有解读或输出实际账号/收件人。

`native_contract.py` 固定当前函数完整哈希、普通分支调用位置，并独立解码 MOVZ/ADD 的大小、正文位置、shared allocation 和目标 kind。拒绝旧布局、错寄存器、错位宽、移位立即数、不同调用分支或析构字段；报告仍明确 `native_request_abi_verified=false`、`runtime_recipient_verified=false`。它不是发送后端，也不把这些地址转换成可执行函数指针。

## 运行中原版资格探针

Swift 本地工具只从固定安装路径选取唯一运行的微信，并通过 Security.framework 核对进程腾讯签名。仅申请系统的 **只读** task port，立即释放；即使系统允许，也不读内存、暂停/调试进程、请求写端口或调用任何微信函数。不注册 MCP、不授予聊天权限，不输出 PID、标识、路径、正文或凭据。

```sh
mkdir -p .local-private/native-270134
swiftc adapters/macos/native_runtime_probe.swift -o .local-private/native-270134/runtime-probe
.local-private/native-270134/runtime-probe
```

本机原版实际结果：`running_vendor_verified=true`、`read_port_available=false`、API status=-1、errno=1（EPERM），探针返回非零。无端口、内存读取或原生调用。Full Disk Access 不能据此视为进程读取许可，OS 认证也不能据此宣称改变了该权限。运行中账号和收件人仍未验证；没有重签原版、关闭 SIP 或绕过屏幕隐私保护。

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

[wechat-antirecall 的对象/账号记录](https://github.com/fzlzjerry/wechat-antirecall/blob/4b80f8dd4e0ca8fb6ba3989d699b61811bd51fc5/Docs/red-packet-269624.md) 提供 270102/270132 的对照线索；本轮只静态阅读并独立核对当前代码，没有运行安装器、撤回拦截或金融功能。其兼容声明不能升级成 270134 真实私聊发送证据。历史程序来自 [版本归档](https://github.com/zsbai/wechat-versions/releases/tag/4.1.11.23)，另核对腾讯严格签名；第三方源码、安装包与程序样本没有进入提交。

## 本轮验收边界

原有 6 项回归继续覆盖 Mach-O/固定样本安全；新增 3 项对象语义回归拒绝旧布局、不同目标 kind/调用边、错误析构及指令位宽/寄存器/移位。本机全量 204 项发现、202 执行通过、2 项跳过；Swift 探针编译并实测预期拒绝路径。双平台 CI 新增 Mac 编译检查，不在 CI 调用微信，结果随本轮 PR 更新；Windows 无微信实机测试。

原版签名保持有效。两个真实私聊的发送、发送后读回、后台写入和多日运行仍未完成，因此保持同一 Draft PR，暂不合入主分支。
