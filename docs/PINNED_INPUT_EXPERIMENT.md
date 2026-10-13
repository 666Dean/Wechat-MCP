# Mac 原号私聊：固定窗口输入实验

## 实机结果 · 2026-10-14

一个已授权私聊完成了新的独立合成文本测试：Agent 自动粘贴、两次本地精确
草稿比较、一次 PID 定向 Return，并独立查到唯一完整文本、本人 sender、目标
会话及非零 server_id 的数据库发出记录。主人只初始化独立窗口、确认空输入和
完成 OS 认证，没有复制或提交消息。没有 OCR、注入、客户端修改或捕获保护绕过。

这是一项单次原型实测，不代表对端送达、全天自动回复、后台无焦点发送或正式
MCP 后端资格。收件人窗口关联来自所有者初始化；联系人数据库核对稳定 ID，
不能把窗口标题宣称为原生 wxid 控件。本人 ID 私聊的认证超时，尚未尝试发送。

更早一笔提交缺少有效原生回执，保持 Unknown，未重发。只读复核没有发现精确
发出记录，但不能用“没查到”追认安全重试。新的实测有独立文本、密封意图和
持久尝试记录，由所有者明确要求继续测试后进行，没有删除旧标记。

## 目的与实现

[实验适配器](../adapters/macos/experimental_pinned_input.swift) 使用公开 AppKit、AX
和进程定向键盘事件，减少对缺失输入 AX 节点与截图的依赖。它没有被 Service
注册为发送后端，也不会修改 `send_available`、监听或自动执行开关。

- 输入、读取均须 AXR 原生精确提交证明，绑定账号、收件人、文本、进程、窗口、
  标题和几何；准备模式还要求密封的所有者空输入/焦点初始化记录。
- 仅原版应用的唯一进程与唯一匹配独立窗口可进入输入。窗口重建、移动、失焦、
  授权失效、剪贴板变化或草稿不匹配均停止，不尝试搜索另一个联系人。
- 前台顺序使用 `optionOnScreenOnly`；`optionAll` 仅用于精确实例查找。
  本机两种列表的第一项不同，旧实现因此误拒绝目标窗口。Apple 明确说明
  [在屏列表按前后顺序返回](https://developer.apple.com/documentation/coregraphics/cgwindowlistoption/optiononscreenonly)。
- 剪贴板备份不落盘，按拥有的 changeCount 有条件恢复；超出备份预算即停止。
  有界 IPC 帧与固定错误枚举不输出正文。无法取得回执时发送状态必须是未知，
  不能从空结果推导 `send_invoked=false`。
- Return 只执行一次。原生“已调用”与独立数据库记录分开报告，均不是送达回执。

父控制器必须先通过本次 OS 认证，验证密封配置、联系人密钥 HMAC、账号目录
及准确联系人映射，检查原进程打开的该账号联系人库与会话库。消息分库可能
延迟打开，不能要求它们始终全在 lsof 中，也不能把同名 `.kvdb` 当消息 SQLite 库。
正文读回仍用已校验原消息分库和独立只读权限。

父控制器还必须持有账号 lease、在调用前持久写入尝试标记，并通过现有 Runtime
保持一次执行与 Unknown 不重试。这个低层实验程序不替代父控制器，不提供
MCP 授权、账号推断、联系人搜索、自动回复会话或持久去重服务。

## 开发验证

先按项目安装说明构建 AXR；开发者再显式构建该适配器：

```sh
python scripts/build_pinned_input.py --build .local-private/build
AXR_TEST_PINNED_INPUT="$PWD/.local-private/build/wechat-pinned-input-experimental" \
  python -m unittest test_pinned_input -v
```

四项原生证明回归使用合成身份和 `validate_scope`，不访问微信或 GUI：验证成功
仍返回 `send_available=false`；缺失证明、撤权及正文/身份/窗口/初始化替换均拒绝。
Windows 跳过这个 Mac 实验，不将跨平台编译或 fixture 通过外推为 Windows 微信验收。

实机运行使用本地所有者控制器，配置、稳定身份、精确测试文本、窗口 ID 和详细
报告留在私有目录。正式 MCP 接入、初始化有效期与焦点连续性、后台切换、多次
独立任务及本人私聊仍须另行验收；人工回复面板继续保留。
