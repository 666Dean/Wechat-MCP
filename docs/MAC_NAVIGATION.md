# Mac 非 OCR 菜单操作

2026-10-11。本轮停止继续尝试实际微信 OCR，保留此前默认关闭的实验代码与历史证据。
聊天树不可访问与空捕获帧不能确定客户端的内部机制或意图。

## Agent 可用入口

`wechat_ui_navigate("open_chat_selector")` 提议打开中文客户端“文件 → 发起会话”面板。
`wechat_ui_navigate("open_preferences")` 同样可提议打开“微信 → 设置”。
它们返回 AET 提议；本地所有者批准后通过 `axr_execute` 执行。只实现这两个固定命令，
不开放任意菜单、快捷键、剪贴板、联系人选择、消息读取或发送。调用不会创建群聊。

所有者配置默认没有 `navigation`。要启用，在原有完整策略中加入：

```json
{"navigation":{"native_helper":"/absolute/path/to/axr-helper","actions":["open_chat_selector","open_preferences"]}}
```

这是占位路径；用本地 `axr-owner configure` 认证、密封配置并重启 broker。
命令在 Mac 实现，Windows 明确报告不可用，未声称 Windows 菜单资格。
MCP 无法修改菜单目录、helper 路径或自签批准。

## 授权与验证

- 资源是独立的应用菜单范围 `axr:application-ui`，目的为原用途加 `:ui-navigation`。
  会话读取权限不能授权它，这个资源也不能作为聊天绑定。
- C++ Guard 强制完整 intent、最长 300 秒、单次额度；常规 owner 批准最长 240 秒。
  C ABI 必须精确匹配 `navigation_binding`，不能省略或替换 bundle、PID、两级菜单及预期窗口。
- 原生 helper 检查唯一进程、精确菜单名与 enabled，命令前后复核 commit proof。
  只读取菜单和窗口外壳；面板已存在、菜单歧义、重启或权限变化时拒绝。
  只有命令后唯一预期标题/subrole 出现才报告验证成功。worker 最长 12 秒，见证等待最多 2 秒。
- 导航是外部副作用。无法确认提交结果时保持 `Unknown`，重复执行同一事务不会再次调用 helper。
  失败清理仅针对该次打开的菜单，不发送 Escape 给任意聊天框。
- AXR/ 保留应用无关的 Swift 菜单执行与 C++ 授权能力；微信目录和 Python MCP 编排在 SDK 外。

## 实机复现

本地交互验收入口（不注册 MCP、不修改生产密封配置）：

```sh
python -m axr_integration.owner_navigation --state /absolute/path/to/owner-state \
  --helper /absolute/path/to/axr-helper --command open_chat_selector
```

入口显示固定菜单/PID/窗口条件，由主人完成 OS 认证；要求监听、模型与自动执行关闭。
它使用实际 Guard、Journal、账号租约和同一 NavigationAdapter，结束撤销单次权限、清理结果。
输出只有窗口验证、状态、失焦与审计，不包含账号、联系人或正文。

在腾讯签名原版 4.1.15.54 / 270134 上，本次事务 **Completed**、`foreground=false`、
预期面板唯一出现、审计有效、没有读取正文或发送。Computer Use 独立确认实际面板，
随后将其取消并确认返回主窗口。实际面板内部仍没有可访问联系人/输入节点。
这是失焦菜单操作的实机证据；不是最小化、锁屏、后台发送或指定私聊回复验收。

“微信 → 设置”经 Computer Use 语义点击打开、确认实际设置窗口并关闭，没有修改任何选项。
该命令已接入同一执行器，但本轮没有另授 OS 能力做设置命令的真实 AET 资格；GUI 成功不能替代它。

替代发送渠道与版本/许可证边界见 [MAC_TRANSPORTS.md](MAC_TRANSPORTS.md)。
