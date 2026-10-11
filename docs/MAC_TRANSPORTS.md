# Mac 原账号回复：替代渠道资格

2026-10-11。验收目标仍是主人授权的两个既有私聊；没有用机器人会话或文件传输助手替代本人内部 ID 私聊。公开记录不含真实身份、正文、凭据或截图。

## 腾讯官方机器人渠道

静态审查 [Tencent/openclaw-weixin](https://github.com/Tencent/openclaw-weixin/tree/c6643f6f0ac03574eb126f2d69569ea4267cc3c6)，MIT，2.4.10。
[协议](https://github.com/Tencent/openclaw-weixin/blob/c6643f6f0ac03574eb126f2d69569ea4267cc3c6/docs/protocol_zh_CN.md) 使用独立 Bot token 和 iLink 身份，扫码为 bot_type=3；发送使用机器人消息及 context_token。
仓库说明区分客户端行为与服务端契约，不能将可选字段当作服务端可用承诺。

已审查代码没有证明能枚举或使用原账号好友的 WCDB 内部 ID，也没有证明可直接操作原账号的两个既有私聊。因此没有启动扫码、保存 Bot 凭据或接入官方机器人运行服务；不能用该渠道宣称本次原账号闭环通过。

## 厂商分享扩展

已安装腾讯客户端含官方 Share Extension；bundle 中的 URL scheme 不能证明提供按私聊 ID 发送文本的 API。
本机 NSSharingService 的纯文本候选枚举没有微信；该旧 API 的一次枚举不证明现代分享菜单或厂商扩展不可用。
没有调用 perform、转发正文、选择联系人或执行真实发送。分享流程仍缺少经过验证的账号/唯一私聊身份和完成见证。

## 固定版本开源审查

| 方案 | 固定 revision | 与当前客户端的边界 |
| --- | --- | --- |
| [wechat-hook-macos](https://github.com/lovezm/wechat-hook-macos/tree/bf3a0ed1dff128eef2df8138183990d86d5fcf1f) | bf3a0ed | README 对应 4.1.8.29；send_text 实现返回未完成错误，要求重签名/注入，不能作为现有版本的真实发送实现 |
| [SovietExtension](https://github.com/MustangYM/SovietExtension/tree/a0e7533ff39b14fc135445c4c79d838544b97fdc) | a0e7533 | 已记录支持版本为 4.1.11.23 / 269079、4.1.10.53 / 268853，未证明支持本机 270102 或升级后 270134 |
| [wechat_chatter](https://github.com/yincongcyincong/wechat_chatter/tree/f222f37321f66d3a199cb3c7642f77f7504d85da) | f222f37 | GPL-3.0；有按收件人 ID 构造原生/protobuf 发送代码，版本配置最高到 4.1.12.53；没有 4.1.15.54 / 270134 的配置或精确二进制身份门禁。文档运行方式为关闭 SIP 或修改原版加载 Gadget、重签名；仅静态阅读，未运行 |
| [wechat-use](https://github.com/leeguooooo/wechat-use/tree/8538667abb2b2ca587b65cd04b58885bfc771105) | 8538667 | 宣称后台原生键盘/调试发送，安装器绑定 4.1.9；公开仓库未包含核心发送实现，不能审计当前版本。其自定义非商业学习许可证限制商业用途及再分发，不能作为本项目可直接整合的开源依赖 |

仅阅读源代码，没有执行这些插件、安装二进制或调用内部发送地址；版本不匹配不能靠猜偏移、自动重试或修改隐私保护补齐资格。之前 AX/本地 OCR 审查见 [MAC_UI_RESEARCH.md](MAC_UI_RESEARCH.md)。

进一步检查 SovietExtension 的发送运行时解析器：具体 SendMsgCGI 路径仅允许旧 build 268853；
269079 的独立转发 ABI 也有版本/UUID 条件，不能把旧地址当作本机能力。
微信 bundle 没有可用 scripting dictionary，URL scheme 也没有已验证的收件人 ID + 文本发送契约。
官方分享扩展声明图片/文件/网页等输入；纯文本、合成文件、网页的旧 NSSharingService 枚举均未返回微信。
这些枚举只属于静态/元数据检查，没有调用分享或选择联系人，不能证明现代 Share 菜单彻底不可用。

目前实际可用的非 OCR 路径是 [固定菜单导航](MAC_NAVIGATION.md)：真实 AET 从失焦微信打开会话选择面板，
窗口验证成功；内部控件仍缺失。原账号“稳定收件人 ID → 精确发送 → 独立数据库读回”的写入环节尚未资格。
后续原生发送适配需当前版本/架构/厂商签名/模块身份与 ABI 匹配、独立账户/收件人见证、
精确正文授权、单次提交和本地记录观察；未知结果不得盲重发。不把历史 hook、机器人身份或数据库写入当作发送成功。

## 继续排除表面可用的替代方案

静态审查 [macOS WeChat local toolkit](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f/c98dbb10cf23c30e83d5d744905101b0880887a0)（MIT，revision c98dbb1）：
文档报告微信 4.1.15，但发送依赖 ScreenCaptureKit/OCR、人工选定聊天与正文/草稿核验。
其捕获流程先包含应用、再更新为窗口过滤器；没有运行该代码或采用其捕获路线。
它不提供按原账号稳定收件人 ID 调用的非 OCR 发送接口，不能覆盖本机当前的空画面问题。

本机只读检查当前安装包：核心位于 Resources 下的 universal wechat.dylib，Frameworks 下同名文件是较小的加载层。
核心导出符号检查未找到可直接使用的 SendMsg/Req2Buf/openChat 入口；内部 Req2Buf 字符串不能证明 ABI 或正确地址。
针对聊天 URL 的静态检查没有得到可验证契约，没有向未知 URL 传递联系人或调用内部函数。
这些检查只读取已安装程序代码，没有访问进程消息、会话正文或凭据，也没有给 Agent 发放新的数据权限。

## 标准升级与系统选择器

[Homebrew cask 元数据](https://formulae.brew.sh/cask/wechat) 对应腾讯官方下载的 4.1.15.54 / 270134。下载包 SHA256 匹配，腾讯 Developer ID/Team 签名严格校验及 Gatekeeper 评估通过。
主人正常退出 270102 后完成标准升级；保留原签名应用副本，新版未重签名、未注入、无实验启动参数。进入既有账号后主聊天 AX 仍无输入节点，工具截图仍白屏。
应用副本不是账号数据迁移的完整回滚，不将升级后的数据可降级作为已验证承诺。

Apple 官方单窗口选择器的元数据探针已在本机运行：主人选的是主窗口，返回单窗口/PID/bundle 校验成功；未启动捕获，不保存图像，不执行 OCR 或输入。
探针关闭后不会将结果持久化为会话绑定或授予读取/发送权限。SDK 保留 legacy sharing=0 的自动捕获拒绝检查。
[Apple 对旧共享常量的说明](https://developer.apple.com/documentation/appkit/nswindow/sharingtype-swift.enum/none) 表明数值本身不能证明现代保护状态或可捕获性。

当前可证实的是 WCDB 读取与合成输入/OCR 路径；原账号真实发送、发送后读回及后台写入仍未通过。
下一项必要资格是同时取得官方可读取的目标身份、可检查的空草稿/精确正文及单次提交见证；缺失时不能进入真实发送测试。

## 所有者单帧与合成对照补充

本轮显式本地所有者入口经新的 OS 认证、精确单次授权及主人选择后，用原始 Apple 单窗口 filter 实际调用截图和本地 Vision。
两个已指定独立私聊均返回 598×640 帧，OCR 0 行、0 个不透明采样；当前空帧判为 FailedSafe，不能称为读取通过。
同一路径纯合成窗口失焦时成功：1280×1024、4 行/67 字节、4072 个不透明采样，审计有效。
这验证实现可捕获合成内容，但不确定微信内部的限制原因，不修改或绕过隐私保护。
无图片落盘、模型正文披露或真实发送；操作结束撤权及逻辑清理。窗口选择不证明内部 ID、草稿或发送资格。
合成前两次等待超时不算成功；历史元数据或旧捕获事务 Completed 不等于可用内容验收。
微信失焦下空帧不算后台读取通过，发送/发送后读回/后台写入/多日运行仍未通过。
请求格式、安全边界及复现见 [MAC_REPLY.md](MAC_REPLY.md)。
