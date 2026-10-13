# Mac 原号私聊发送：GitHub 源码复核

2026-10-13。五份源码已克隆到私有研究目录并固定版本；未安装依赖、执行发送器、
导入其 Skill 或运行初始化脚本。此处是源码结论，不是本机兼容性或发送验收。

## 可发送私聊的实现

| 项目与审查提交 | 源码实际路径 | 对本机的意义 |
| --- | --- | --- |
| [macos-wechat-sender](https://github.com/yunkai/macos-wechat-sender/tree/ba9de4abd409efd94b0f5801006fb9e4177ea22d) | `scripts/send_wechat.py`：Cmd+F、粘贴名称、两次 Return，再粘贴正文并 Return | 文本路径不需要 OCR，但没有当前收件人/输入草稿核验；等待时间不能证明目标正确 |
| [wechat-controller](https://github.com/dragonking-T/wechat-controller/tree/47b6191d0af5488687f9617ab67c256804e64988) | `wechat_controller/operations/send_message.py`：坐标搜索、Vision 选名称匹配行、输入框坐标与 Return | 依赖真实画面及 Vision provider；名称匹配不是平台 ID，不直接运行云端截图路线 |
| [wechat-mcp](https://github.com/dustin573/wechat-mcp/tree/c6c600ae068c113224f984656db40f8cec4d0164) | `reply_to_messages_by_chat_utils.py`：寻找 `chat_input_field`，AXValue 写入，再全局 Return | 本机聊天树不提供该输入节点；复核提交与此前相同，没有新的控件恢复实现 |
| [macOS WeChat local toolkit](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f/c98dbb10cf23c30e83d5d744905101b0880887a0) | `Send.swift`：手动打开聊天、OCR 标题/空草稿/精确正文，PID Unicode 输入和 Return；另有数据库读回 | 有去重与不确定不重试设计，但仍需要可用画面，且 UI 标题不能证明内部 ID；提交与此前相同 |
| [wechat-mac-rpa](https://github.com/wq19901103wq/wechat-mac-rpa/tree/5c9b1e123b1bc6a975eb0050888e0a0cc0630866) | `src/action/message_sender.py`：前台检查、底部坐标、剪贴板粘贴，再 Cmd+A/C 读回草稿 | 提供不依赖 OCR 的草稿读回思路，但前台应用和草稿匹配仍不能证明当前收件人 |

后四项有 MIT LICENSE；第一项 README 声明 MIT，但本次 checkout 没有独立 LICENSE 文件。
未复制第三方实现。许可证、作者宣称支持微信 4.x、一般版本测试均不能代替本机
270134 的实测，也不代表腾讯允许原账号自动化。

`wechat-mac-rpa` 的 `src/db/repository.py` 还会为无真实身份的 OCR 会话生成名称哈希
合成 ID；这种 ID 可用于应用内部索引，不能当作微信收件人身份。其全局发送锁可供
设计参考，但已有 AXR 事务/执行 claim，不能引入另一个绕开批准的发送服务。

[fastbridge issue #1](https://github.com/huj28-creator/wechat-fastbridge/issues/1) 另记录了
多个 4.1.x 版本的聊天 AX 树缺失，当前 issue 仍开放。它是独立设备的报告，
并非本机故障原因证明，也不证明所有版本都不可用。

## 发消息专用 Computer Use 的可行范围

按键输入与 OCR 是不同环节。没有可用截图并不必然阻止系统发送键盘事件；
当前缺失的是发送前的可靠目标、焦点和正文见证，不是已经证明系统拒绝一切输入。
不通过“搜索后取第一项”、名称哈希或发后发现错误来替代发前核对。

若获得适用接入依据与真实身份/输入见证，可以沿用现有发送事务而非另造权限通道：

1. 密封原账号、内部收件人 ID、原文和来源，取得本地精确批准。
2. 绑定签名客户端、进程/窗口实例和对应收件人见证；切换账号、窗口重建、焦点或
   目标变化均停止。仅窗口标题、PID 和数据库中的同名联系人不足以完成这个绑定。
3. 单独核对空输入框，使用受限输入动作。剪贴板读回只能在已确认的输入区域进行，
   只在本地比较精确正文，不把整份剪贴板或其他窗口内容交给模型。
4. 最终提交前再次核对目标、正文、焦点、授权和能力，只发送一次。
5. 通过独立读取核对发出记录；失败、超时或证据不足保留 Unknown，不自动重试。

该方案的输入回读思路可以减少 OCR 依赖，但它目前没有补齐本机稳定收件人见证。
尚未实现新的剪贴板发送后端，没有真实发送或后台写入，也不声称自制 Computer Use
已跑通。官方单窗口透明帧与 AX 控件缺失仍按既有失败安全规则处理。
公开分享和其他接口、平台协议范围见 [接入条件与验收](INTEGRATION_REQUIREMENTS.md)。
人工回复保持独立面板；临时切到前台再恢复不等于无前台依赖或锁屏后台发送。
