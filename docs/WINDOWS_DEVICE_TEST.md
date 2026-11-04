# Windows 设备测试接口

2026-11-04：本人在微信登录后明确要求开始测试，并要求补齐接口直接调用。新增 `desktop.windows_device_test.inspect_device`、命令入口和桌面“检查当前设备”按钮。不通过旁路操作真实输入；正式验收继续调用已有签名有限计划入口。

## 接口与命令

`inspect_device()` 仅枚举当前交互桌面的微信可见窗口，读取程序版本、SHA-256 与服务/受保护安装/配置状态。输出不包含窗口文字、程序路径、PID、用户 SID、账号、联系人、凭据或正文。安装缺失时仍返回具体阻塞，不把普通进程诊断写成 System 跨会话就绪。未调用 helper 时，控件结构状态为 `NotRequested`。

```powershell
python -m scripts.windows_device_test inspect
python -m scripts.windows_device_test inspect --package "<已审查服务开发包目录>" --wechat-sha256 "<本人核对的64位小写哈希>"
```

第二条显式启用现有原生 helper 的 `structure` 操作；先校验包的完整清单，再固定运行包内 `wechat-uia.exe`。请求只能包含 `op=structure` 和微信映像 pin，读取有界 ControlView 路径、类型与子节点数，不取控件名称/值、不激活窗口、不输入。不导出 AutomationId；节点出现正文/额外字段会拒绝。操作前后复核窗口、PID、进程 birth、用户及程序哈希。超过节点预算或没有暴露 Edit 控件均记录阻塞；即使出现 Edit，也不代表账号、收件人、导航或发送通过。

```powershell
python -m scripts.windows_device_test qualify --permit "<本机对应的已签署有限计划.json>"
```

该命令只转交 `windows_lifecycle.qualify_once`，复用签名验证、固定 UAC/SCM 与本人 Hello 审查；没有直接执行读取/发送的调试函数，也不创建审查者私钥、自签材料、安装服务或恢复权限。认证窗口由本人操作。详见[一次性验收](WINDOWS_QUALIFICATION.md)。

冻结桌面程序提供相同入口：`WeChatMCP.exe --windows-device-test inspect --output "<本人选择的新JSON路径>"`。无控制台时必须指定输出；新文件以排他方式创建，已有文件在任何设备操作前拒绝，不覆盖旧结果。正常桌面按钮在内存中显示中文检查结果，不自动导出文件。

退出码：`PrerequisitesObserved` / `Recorded` 为 0，其余为 2。`PrerequisitesObserved` 仅表示元数据前置条件存在；计划文件的存在不表示签名/有效期有效。`Recorded` 仍按原验收协议解释，不能成为设备准入。所有返回保持 `runtime_qualified=false`，不因诊断开放正式服务。

## 本次真实元数据观察

登录后的微信版本为 **4.1.15.13**，Windows **10.0.26200 / AMD64**，有一个可见主窗口。当前正式原生 helper 实际返回 **3 个节点，均为 Other，没有 Edit**，未触及 500 节点上限。主窗口并非最小化、处于启用状态；微信与测试进程的完整性级别一致。为排除前后台影响，后续只用既有 Computer Use 激活微信，再经 Win32 元数据确认它处于前台；此时结构仍是相同 3 个节点。没有截图、控件文字读取、搜索/输入区点击或输入。上述结果只说明当前观察条件，未把根因定为客户端永久不兼容。

该设备没有受保护组件安装、服务登记、生效本人配置/初始化或签名验收计划。因此本次结果为 `Blocked`：控件未暴露与部署前置条件都尚未满足。此结果不证明该客户端版本永远不能提供辅助功能，也不证明正式 System/owner 通道已经验证；当前配置下不能进行完整选聊/草稿/发送验收。没有读取聊天、搜索框或草稿，没有发送、真实认证、安装、凭据迁移或联网模型披露。旧 WCDB 记录不重复执行，Unknown 不重发。

## 软件验证与分发边界

新增 10 项回归覆盖 GUI 调用、元数据无权限、错误身份/窗口歧义、映像 pin 和进程变化、结构预算/字段拒绝、已有输出文件拒绝和固定签名计划转交。完整回归 **908 发现、867 执行通过、41 条件跳过，118.507 秒**；125% / 150% Qt 各 **26 项通过**，19 个既有 GC 退出警告保留。原有参考/正式组件及既有服务包作为离线夹具，不能把这些测试当作新的设备或包构建。最新实现 `4372e20` 的云端 Windows/Mac/native-fuzz 已全部成功。

接口实现 `b80cb1e5411184599f8985ec4350481a04c815dc` 已推送。新桌面候选构建时 `source_dirty=false`，2,395 个文件全部重算哈希通过，两个新模块均在冻结归档内，冻结 QML 与源码一致；正式 SDK、隔离 EXE 实际启动/中文合成渲染、1,362 个归档项隐私检查通过。已实际调用冻结 EXE 的诊断接口，返回 Blocked、控件检查为 NotRequested、服务 Absent，全部正文/输入/发送/模型/授权标记为 false。候选继续使用未改变的 `4372e20` 正式服务组件，不把它称为本轮新服务构建。完整文件夹保存在本人指定交付根目录的 `desktop-device-interface`，没有安装或发布。

## 标准事件订阅对照

根据 [Microsoft 的 UIA 事件说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-eventsforclients)和[订阅者检测接口](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationcoreapi/nf-uiautomationcoreapi-uiaclientsarelistening)，检查正常事件客户端在场是否改变当前控件结构。这是待验证假设，不是已确认的微信根因。

新增手动构建目标 `wechat-uia-listener-probe`，只接受本次明确选择的窗口，MTA 注册该子树的结构事件；回调不查看 sender、runtime ID 或事件内容，仅前后统计 ControlType，1.5 秒后解除订阅。外部执行设置 12 秒期限，没有失败后重试。该目标仅 Windows/BUILD_TESTING 构建，**不注册 CTest**、不进入服务包、不自动发现或操作真实微信。参考/正式目标均已编译，根 CTest 仍各 5/5。

本机真实结果：订阅与解除均成功；订阅前 **3 nodes / 0 Edit**，订阅后仍为 **3 nodes / 0 Edit**。这次普通客户端事件订阅没有恢复控件，未扩大为其他订阅机制或重启后结论。没有文字、截图、输入、模型或进程内存读取。

本人随后明确允许重启微信作临时软件渲染参数对照。只停止本次可见微信主进程及同映像/本人/birth 核对后的子进程，共 5 个；没有终止其他应用。对新启动子进程传入 `QT_ANGLE_PLATFORM=software`、`QT_OPENGL=software`、`QT_QUICK_BACKEND=software`，未修改安装文件、全局环境或系统设置。登录/手机确认由本人操作。

### 本人确认登录后的结果

本人随后明确确认“已进入聊天主界面”。以同一正式包/helper 与同一微信映像 pin 调用结构接口，仍为 **3 nodes / 0 Edit**，未触达预算上限。此时安装/初始化缺项仍存在，最终结果 Blocked，没有读取聊天、搜索或草稿、输入、发送或联网模型。参数传入不等于客户端实际采用软件渲染；本次没有验证实际渲染后端，且子进程继承了测试进程的运行库搜索路径，不能把负结果归因为显卡，也不能称为严格单变量实验。没有因此再次中断本人已登录的客户端。

| 观察条件 | UIA 节点 | Edit | 边界 |
| --- | ---: | ---: | --- |
| 重启前，单窗口/同完整性/前台 | 3 | 0 | 普通交互用户结构元数据 |
| 重启前，标准结构事件订阅 | 3 → 3 | 0 → 0 | 订阅和解除成功，未改善树 |
| 临时参数重启后，本人确认登录 | 3 | 0 | 实际渲染后端未验证 |
| 重启后，传统接口与结构事件订阅 | 3 → 3 | 0 → 0 | MSAA 接口调用成功，但未获得操作控件 |

手动诊断目标增加显式 `--legacy-client`：按 [Microsoft 文档](https://learn.microsoft.com/en-us/windows/win32/api/oleacc/nf-oleacc-accessibleobjectfromwindow)仅获取本次窗口 `OBJID_CLIENT` 的 IAccessible，再读取 [ChildCount](https://learn.microsoft.com/en-us/windows/win32/api/oleacc/nf-oleacc-iaccessible-get_accchildcount)。不枚举其名称、值或正文，不调用动作。实际 HRESULT=0，直接子对象数=2；随后 UIA 仍是 3/0，事件订阅和解除均成功。接口存在和 ChildCount=2 不证明应用提供了完整无障碍树，不能据此发放导航/发送权限。

该分支仍不加入 CTest 或正式服务/桌面分发。参考/正式目标重新编译，根 CTest 各 5/5；5 组无效窗口/参数检查均在 UIA 前拒绝。Python/桌面运行实现没有改变，完整 908/867/41 和冻结候选 `b80cb1e` 仍按上文原日期/提交记录，不冒称本轮重跑全量或重新打包。实际 JSON 记录留在本人选择的私有验证目录，公开文档只保留聚合事实。
