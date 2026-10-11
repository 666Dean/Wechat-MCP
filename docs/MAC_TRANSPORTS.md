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

仅阅读源代码，没有执行这些插件、安装二进制或调用内部发送地址；版本不匹配不能靠猜偏移、自动重试或修改隐私保护补齐资格。之前 AX/本地 OCR 审查见 [MAC_UI_RESEARCH.md](MAC_UI_RESEARCH.md)。

## 标准升级与系统选择器

[Homebrew cask 元数据](https://formulae.brew.sh/cask/wechat) 对应腾讯官方下载的 4.1.15.54 / 270134。下载包 SHA256 匹配，腾讯 Developer ID/Team 签名严格校验及 Gatekeeper 评估通过。
主人正常退出 270102 后完成标准升级；保留原签名应用副本，新版未重签名、未注入、无实验启动参数。进入既有账号后主聊天 AX 仍无输入节点，工具截图仍白屏。
应用副本不是账号数据迁移的完整回滚，不将升级后的数据可降级作为已验证承诺。

Apple 官方单窗口选择器的元数据探针已在本机运行：主人选的是主窗口，返回单窗口/PID/bundle 校验成功；未启动捕获，不保存图像，不执行 OCR 或输入。
探针关闭后不会将结果持久化为会话绑定或授予读取/发送权限。SDK 保留 legacy sharing=0 的自动捕获拒绝检查。
[Apple 对旧共享常量的说明](https://developer.apple.com/documentation/appkit/nswindow/sharingtype-swift.enum/none) 表明数值本身不能证明现代保护状态或可捕获性。

当前可证实的是 WCDB 读取与合成输入/OCR 路径；原账号真实发送、发送后读回及后台写入仍未通过。
下一项必要资格是同时取得官方可读取的目标身份、可检查的空草稿/精确正文及单次提交见证；缺失时不能进入真实发送测试。
