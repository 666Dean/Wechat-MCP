# Mac 回复、混合读取与本地 OCR

2026-10-11。本文说明已接入的代码路径；当前微信 4.1.15 / macOS 27.0.1 的真实发送仍未通过。
SDK 是应用无关的 AXR 能力；微信布局、WCDB 和 MCP 编排均在 SDK 外。

## 数据读取与发送独立

- `mode: wcdb`：只读数据库，不发送；原有边界保持。
- `mode: ui`：经身份见证的 AX 读取，可选本地 OCR 预览；发送仍需独立批准。
- `mode: hybrid`：同时配置 `database` 与 `ui`，数据库读取、UI 提交；读取权限不会成为发送权限。

三种模式只使用所有者密封策略里的稳定账号与会话 ID。新的模式或布局须用本机
`axr-owner configure` 完成 OS 认证，旧能力失效并重启 broker。所有读取仍经过数据分类、额度与 AET，
所有发送仍经 `wechat_prepare_reply` → `wechat_propose_send` → 本地精确批准 → `axr_execute`。

`wechat_observe_send_record(job_id)` 对 Completed/Unknown 的本人发送提议创建独立读取 AET：
有界关键词/本人 sender/提议时间之后查询，核对完整正文、真实 outgoing、本人 sender、非零整数 server_id、
无截断与唯一匹配。只返回计数与独立读取事务状态，不创建可披露的正文 context；保留原发送的所有来源分类，敏感内容不能降级为个人分类；没有读取权限则 AwaitingApproval，不访问适配器。
相同正文也可能由主人手动发送，因此结果只叫 `database_record_observed`，不宣称收件人送达，
不将 Unknown 改为 Completed，也不重发。长文本或分页/截断不足时不确认观察结果。

## Mac 进程定向输入

默认发送仍是 `ax_press`。在已资格的会话 layout 中可选择：

```json
{"send_method":"pid_return", "return_sends_message":true,
 "input_path":[0,1], "header_path":[0,2], "messages_path":[0,3]}
```

示例路径是占位，不适用于实际微信。`identity_witness` 仍必须经所有者资格验证，提供账号与内部会话 ID
的真实平台路径；显示名、数据库 ID、配置里的 verified 布尔值不能凭空补出屏幕证据。
Return 的发送语义须按实际客户端设置资格验证。该路径限不超过 200 字符的单行文本，拒绝控制字符。

helper 在准备前检查精确身份、空草稿及可验证的 AX 输入焦点，准备后再核对完整草稿、身份和焦点；
控件必须属于同一聊天窗口，缓存输入 handle 必须仍对应当前路径；OCR 的 AX 身份也须对应被捕获窗口。
马上重新核验 native commit proof，再向唯一微信 PID 投递一次 Return 的 down/up。
不使用全局事件 tap、系统剪贴板、坐标猜测、清空已有草稿或随机延迟。任何异常不自动重试。
新气泡增加且输入变空才报告客户端见证；这不是收件人送达证明。两平台见证遍历都限制 1500 节点/12 层，
Windows 草稿必须取得真实 ValuePattern 值，不能把空 Name 当作空草稿。

通用、不带完整发送检查的旧 `press` / `set_value` 入口已关闭。升级应同步更新 SDK 和 native helper；
新 proof 必须含原始 action，缺失时拒绝。scoped commit 同时核对实际请求的资源、操作、正文及 OCR 布局，
来源 access/disclosure 的 descriptor 不得省略或换序，SDK 最多接受 200 个来源。

## 本地 OCR 预览

会话绑定可设 `read_method: ocr` 和所有者密封的 `visual_binding`：

```json
{"pid":12345,"window_id":123,"bounds":[100,100,800,600],
 "regions":{"account":[0.02,0.05,0.50,0.08],"identity":[0.02,0.15,0.50,0.08],
            "header":[0.50,0.05,0.48,0.08],"messages":[0.50,0.20,0.48,0.50]}}
```

PID、窗口 ID、几何与坐标均为占位，需要实机资格，不能直接使用。region 使用窗口内归一化坐标。
若账号/内部会话 ID/header 有真实 AX 路径，可在 visual_binding 中提供
`identity_paths: {account:[…], identity:[…], header:[…]}`，此时可只配置 messages 区域。
没有 AX 路径时，三个身份区域都必须识别出完整精确字符串且置信度至少 0.98；名称匹配不能替代内部 ID。

仅预检已有 Screen Recording 权限，不自动弹窗申请；保护状态为 0、隐藏、PID/几何改变、跨屏或身份不足即拒绝。
ScreenCaptureKit 过滤器只包含一个指定窗口，按 region 裁取；不会扩展到桌面、其他应用或应用全部窗口。
Apple 文档说明 [单独窗口过滤器会忽略 sourceRect](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/sourcerect)，
所以实现使用单窗口白名单的 display filter 保持区域有效；不会尝试过滤器切换去规避窗口保护。
Vision 在本机处理，图片只在 worker 内存中，不存 PNG、不提供云端截图接口。授权与身份在前后复核；
一次操作最多 30 秒、单区最多 100 行/64000 字节，父进程 35 秒后终止 worker。

OCR 文本保留置信度和 untrusted 来源，不推测 sender、时间或 outgoing，不触发主动模型唤醒；
拒绝 OCR 的 sender/时间/cursor 筛选。正文经加密 context 留存，模型披露须另批准。
OCR 没看到文字不能证明输入框为空，所以本轮没有开放 OCR 坐标盲发。

## 可复现的合成输入验证

SDK 提供默认不构建、不安装的 Cocoa fixture，只含固定合成身份与输入框：

```sh
cmake -S . -B build -DAXR_MAC_UI_FIXTURE=ON
cmake --build build --target axr-mac-input-fixture axr-helper-build
# 手动打开 build/AXR/axr-mac-input-fixture.app，关闭其他同 bundle 的 fixture。
python scripts/probe_mac_input_fixture.py --helper build/AXR/axr-helper
```

脚本只访问 `dev.axr.input-fixture`，不启动或操作微信；临时测试 Guard 不使用生产 OwnerStore。
篡改文本须拒绝，成功须新气泡与空草稿，测试 grant 在 finally 撤销；失败不重试。
本机合成窗口失焦下输入通过，本地 OCR 读回相同合成正文通过。纯 OCR 身份置信度 0.5 被拒绝，
随后使用真实合成 AX 身份路径完成读取。最小化焦点实验未通过，不能外推微信后台发送资格。

## 当前实机边界

主人打开指定私聊的官方独立窗口后，AX 仍只有窗口/菜单/系统按钮，截图白屏；
主聊天与独立私聊窗口处于不共享状态。其他可截图窗口不是已授权聊天输入证据。
本轮没有改变微信隐私设置、窗口共享属性或厂商安装，没有真实发送。
已完成的 WCDB 30 分钟读取属于之前实际启动版本；本轮的合成失焦输入/OCR 不是两个真实目标的读写验收。
