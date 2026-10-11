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

仅预检已有 Screen Recording 权限，不自动弹窗申请；legacy sharing 为 0 时，自动捕获路径保守拒绝并报告 `legacy_window_sharing_unqualified`。隐藏、PID/几何改变、跨屏或身份不足也拒绝。
Apple 已将 [NSWindow.SharingType.none](https://developer.apple.com/documentation/appkit/nswindow/sharingtype-swift.enum/none) 描述为不再使用的旧常量；该数值不能单独证明现代捕获保护或可用性。状态探测只报告 `capture_privacy: unqualified`，不会因此发放读取或发送权限。
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
主聊天与独立私聊窗口的 legacy sharing 元数据为 0。其他可截图窗口不是已授权聊天输入证据。
本轮没有改变微信隐私设置或窗口共享属性。完成腾讯签名的标准客户端升级后，新版主窗口仍无聊天/输入树、截图白屏，没有真实发送。
已完成的 WCDB 30 分钟读取属于之前实际启动版本；本轮的合成失焦输入/OCR 不是两个真实目标的读写验收。

## 所有者系统选择器与精确单帧 OCR

macOS 15.2+ 可选择构建独立探针；默认不构建、不安装。CI 只编译，不打开选择器：

```sh
python scripts/build_axr.py --mac-selection-probe
.local-private/build/AXR/axr-mac-selection-probe.app/Contents/MacOS/axr-selection-probe com.example.authorized-app 120
```

上述默认模式仅返回元数据。显式读取用交互式本地所有者入口：

```sh
python -m axr.owner_window_ocr --state /private/owner/state \
  --helper /path/to/axr-helper \
  --picker /path/to/axr-mac-selection-probe.app/Contents/MacOS/axr-selection-probe \
  --request /private/window-request.json
```

请求文件须当前用户独占、权限 0600、普通文件、无软/硬链接，最多 16 KiB；以下均为占位：

```json
{"resource":{"platform":"example","account_id":"owner-account","conversation_id":"authorized-chat"},
 "visual_binding":{"bundle":"com.example.authorized-app","pid":12345,"window_id":123,
 "title":"Owner selected conversation","bounds":[100,100,800,600]}}
```

这不是配置向导，实际绑定必须由所有者资格流程提供，不能把显示名当作内部 ID。
本地终端先 OS 认证，再发放资源和完整窗口绑定密封的精确读取能力，最长 240 秒、一次使用。
系统选择器必须由主人手动选定；窗口/PID/bundle/标题/几何在捕获前后及 OCR 后再次核验。
只使用选择器返回的原始单窗口 filter，排除其他应用和同应用其他窗口，不构造桌面过滤器或切换捕获路线。
[Apple WWDC23](https://developer.apple.com/videos/play/wwdc2023/10136/?time=276) 明确说明选择器 filter 可直接供截图 API 使用。

仅一帧、最大 2048×2048；Vision 本地识别最多 100 行/64000 UTF-8 字节。选择等待最多 180 秒，
捕获/OCR 最多 15 秒，父进程最多 200 秒。图片仅存内存，无音频/麦克风、网络或输入操作。
正文只经私有管道进入加密短期结果；对外只返回计数、尺寸、粗略像素统计和审计状态。
结束时撤权并逻辑删除结果正文，不承诺 SQLite/存储介质物理擦除。
窗口变化、取消、空帧、权限变化、超时均 FailedSafe；收到图像对象不代表聊天读取通过。
此入口不注册 MCP、不授权披露/监听/发送；`owner_selected_window_unqualified_for_send` 不证明平台账号或会话 ID。

### 270134 本机对照

主人分别完成新的 OS 认证并选定两个已经打开的独立私聊。指定合作私聊和本人内部微信 ID 私聊
返回 598×640 图像对象，均为 0 行 OCR；像素统计均为 0 个不透明采样、无有效变化。
旧试验的 Completed 只代表捕获事务返回，不能作为内容读取成功；当前实现将空帧判为 FailedSafe。
当时微信失焦，但空帧不能作为后台聊天读取资格。本人窗口由主人明确选择，仍不把窗口标题提升为内部 ID 见证。
未获得可用聊天画面或正文，没有保存图像、披露正文或真实发送；每次能力撤销，结果逻辑清理。

相同 filter/截图/Vision 路径在纯合成 Cocoa 窗口失焦时通过：1280×1024、4 行/67 字节、
4072 个不透明采样，审计有效，无图像落盘或模型正文披露。前两次合成选择未收到回调而超时，不算成功。
这验证了该实现可以取得合成内容，不能据此确定微信返回空帧的内部原因或绕过其隐私保护。
合成脚本固定 app/resource/title，不访问 Keychain 或生产策略；最多等待 260 秒、单次能力最长 299 秒，
仍受 SDK 五分钟精确能力上限约束，实际捕获/OCR 仍限 15 秒。复现须先手动打开 Cocoa fixture：

```sh
python scripts/probe_mac_picker_fixture.py --picker /path/to/axr-selection-probe \
  --request /private/synthetic-window-request.json
```

独立窗口适合固定、明确授权的会话范围；当前需要主人打开窗口并逐次选择，不能作为所有好友自动切换或无人值守方案。
真实发送需要可验证的会话身份、空输入框、精确草稿及提交后见证。当前两目标没有这些证据，不投递盲回车或坐标点击。
替代渠道及客户端升级证据见 [MAC_TRANSPORTS.md](MAC_TRANSPORTS.md)。
