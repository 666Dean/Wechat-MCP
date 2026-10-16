# 独立安全服务部署与应用接线

当前为**部署候选**，未达到可直接使用的 WeChat MCP。旧自动回复仍关闭；
不能用此前的有限会话验收替代本轮安全整合后的收发验收。

## 已实现

- 独立原生 authority / owner 宿主，固定嵌入式 Python 入口、隔离模块搜索路径。
  SDK 宿主通过应用注册调用微信服务，微信业务继续位于 `AXR/` 之外。
- 应用专用 C++20 WCDB 消费者。密钥从原生 OS 存储进入 SQLCipher，业务 Python
  只接收固定操作的结果；没有 SQL、路径、密钥或进程扫描 MCP 入口。现有密钥可在
  所有者初始化时原生迁移，验证后保存，不恢复旧权限。
- 文本分页固定账号、会话和 Name2Id 身份；支持多分库游标、压缩文本及明确失败。
  本地草稿和搜索记录作为自动选聊核对材料，不能独立充当发送权限。
- v2 原生执行桥先等待帮助进程就绪，再绑定实际 PID/birth 和意图；原生帮助进程
  通过自己的受认证连接认领并记录回执。发送响应丢失保留 Unknown、不重发；
  数据库发出记录与送达确认分开。
- 每个来源使用新的临时 Codex 进程，不恢复父对话。输入最多 6 条/24KB，
  只接收类型化数据；外层 macOS 沙箱拒绝读取其他来源文件和执行其他程序。
  登录供固定提供方使用，不能进入提示词。受控公开 CA 包支持沙箱内 TLS；
  CA 摘要或提供方构建变化即拒绝使用。
- macOS 打包工具复制 Python、Zstd、SQLCipher 和原生依赖闭包，重写加载路径，
  不依赖开发目录或虚拟环境。所有原生映像使用同一签名团队，保留 Hardened Runtime
  和库验证；Developer ID/厂商公证不是本机验证的前置。

## 本轮证据

本地加密合成库验证了原生查询、稳定方向、跨页游标、错误密钥失败、范围拒绝、
精确草稿和检查回调；桥接测试覆盖真实进程证据的绑定顺序及丢失回执不重发。
macOS 合成原生进程实际证明了当前来源可读、其他来源不可读、其他程序不可执行。
受限 Codex 提供方使用真实模型完成了纯合成、单来源 ReplyDraft 推理。
完整回归为 460 项发现、456 项执行通过、4 项平台跳过。候选包以独立非权限身份
实际加载正式 native、原生 WCDB、Zstd 和 Journal 运行时，无服务或密钥初始化。
这些均不是微信真实读写或最终 native authority 端到端验收。

本机可使用现有本地开发签名完成候选包。临时签名加动态依赖的实测被系统库验证
拒绝，工具因此拒绝此组合，不添加关闭库验证的例外。无本地签名团队的交付需要
完整静态宿主方案，尚未实现。候选运行时的完整第三方再分发清单也未完成准入。

## 尚未接通的环节

1. 受控 MCP 前端、应用调度与独立 authority 的完整操作路由。
2. 所有者面板/设置到独立 owner 通道的范围批准、停止和恢复流程。
3. 新安装中的客户端及提供方身份登记、旧凭据迁移、系统权限与限时任务派生。
4. 全权限读取、主动发送、新消息自动回复、数据库读回和停止开关的本机实测。
5. Windows 应用部署、Hello/硬件与微信设备验收。

应用注册的准入门控明确保持关闭；不能用配置标记、候选包签名成功或合成推理
把缺失的 MCP 前端/内容管线标为已资格。本轮未安装系统级服务、未初始化硬件密钥、
未迁移本机凭据、未开启真实授权，也未访问微信正文或发送微信。

## 构建候选

```sh
cmake -S . -B <private-build> \
  -DAXR_SECURITY_RELEASE=ON -DAXR_PYTHON=ON \
  -DAXR_AUTHORITY_HOST=ON -DAXR_PLATFORM_HELPERS=ON \
  -DWECHAT_NATIVE_CREDENTIALS=ON \
  -DPython_EXECUTABLE=<python312> -Dpybind11_DIR=<pybind11-cmake>
cmake --build <private-build> --target \
  axr-authority axr-owner axr-runtime-check axr-helper-build \
  _axr_native _wechat_credentials
python scripts/build_pinned_input.py --build <private-build> --navigation
python scripts/package_authority_macos.py \
  --build <private-build> --output <new-private-output> \
  --deployment <owner-reviewed-metadata.json> --identity <local-signing-identity>
```

部署元数据、构建记录、公开证书包和真实验收材料保存在本地，不提交仓库。
`AXR Runtime Check.app` 是单独的开发验证身份，不是产品入口，不安装到用户应用。
它只能验证候选运行时，不初始化凭据、权限、服务或微信操作。

Codex 的临时上下文及结构化输出接口参考
[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。具体提供方通过实际
OS 沙箱与模型调用验证，不能仅根据只读设置推断来源隔离。
