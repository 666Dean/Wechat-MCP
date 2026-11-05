# Windows 微信控件暴露研究

最新后续（2026-11-05）：本人针对已展示的单字节方案确认后，已有一次临时条件下 **84 节点/1 Edit** 的正向结构观察，原字节已恢复。见[本次结果](#本人确认后的单字节实机结果)；较早未执行/待确认和负结果段落保留原阶段，不能继续作为最新总状态。

2026-11-04，本人要求必要时寻找 GitHub 项目作为突破口。本记录区分外部源码、当前设备观察和未验证条件，不把其他项目的成功声明作为本项目验收。未安装、导入或执行第三方自动化包；没有复制其实现到产品。

## 已审查的参考

| 来源与固定版本 | 与当前问题有关的实现 | 本项目处理 |
| --- | --- | --- |
| [wechatauto-replica / accessibility.py](https://github.com/fanyuantaier/wechatauto-replica/blob/bc2e6f2461330eb1a53996d2f2afc18416376b52/wechatauto/accessibility.py)，`bc2e6f2` | 版本表包含 4.1.15.13；主要恢复路径通过运行进程的内存写入改变 Qt 无障碍标志，再检查 mmui 树 | 仅作待验证机制线索，不执行内存读写、地址扫描或其系统设置回退；该快照有 Apache-2.0 LICENSE，本项目未复制代码 |
| [同项目 / uia_driver.py](https://github.com/fanyuantaier/wechatauto-replica/blob/bc2e6f2461330eb1a53996d2f2afc18416376b52/wechatauto/uia_driver.py#L869)，同一提交 | 搜索入口可先是按钮，展开后才有 Edit；实现说明该入口 Invoke 无效，使用实际点击，并含坐标回退 | 确认为额外兼容条件。现有固定 ValuePattern 搜索路径没有安全展开分支；不移入坐标点击或模糊选框 |
| [wechat-notify / wechat_monitor.py](https://github.com/CueBeiXing/wechat-notify/blob/2605806b01b9c226030b4c0a7e4ad6254931c6e1/src/core/wechat_monitor.py#L49)，`2605806` | 设置标准读屏参数，同时修改 Narrator 注册表并建议其他环境修改 | 不运行其初始化/采集器，不接受其持久化组合为本机修复。只在本人另外批准后独立对照标准参数；此树未列 LICENSE，不引入实现 |
| [cluic/wxauto4](https://github.com/cluic/wxauto4/blob/d0ae14d3e435807b4dead393af9d014529bbac78/README.md)，`d0ae14d` | 当前 README 仅为停止更新说明 | 不用旧版本名称或历史宣传推定当前 4.1.15.13 可用；[wxauto 自身文档](https://docs.wxauto.org/docs/install.html)标注免费版兼容上限 4.1.8.107 |

外部的渲染后端解释也不作为本机根因：此前仅传入临时软件渲染环境，未验证实际后端。完整树出现后，账号/会话身份、草稿/搜索见证、动作模式及签名准入仍需独立验证；不能由参考控件类名直接生成生效导航配置。

## API 常量核验和本机只读对照

上述 replica 快照把读屏 GET/SET 定义成 `0x1046/0x1047`，并在注释中错误解释了另一组常量。按 [Microsoft SystemParametersInfoW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-systemparametersinfow) 和本机 Windows SDK `winuser.h`：

- `SPI_GETSCREENREADER=0x0046`，GET 用 BOOL 指针。
- `SPI_SETSCREENREADER=0x0047`，开关放在 `uiParam`。
- `SPI_GETKEYBOARDPREF/SETKEYBOARDPREF=0x0044/0x0045`。不能将 `0x1046` 查询结果当成读屏状态或键盘偏好。

本次前两份私有只读草稿对照的 SPI 字段标注有误，已保留并由 `github-accessibility-verified-constants-20261104.json` 明确替代；不把早期返回成功当作语义正确。没有调用错误 SET 常量。微软还明确说明 [Narrator 不设置此参数](https://learn.microsoft.com/en-us/windows/win32/winauto/screen-reader-parameter)，所以读屏参数为 false 不能推定 Narrator 未运行。

当前精确微信映像仍为 4.1.15.13；Win32 根类为 `Qt51514QWindowIcon`。同安装目录 DLL 版本一致、大小 201,552,944 字节，存在 Qt accessibility 日志标记；参考版本表给出的候选位置落在单个可写 PE 段。这些是只读磁盘/窗口元数据，未打开进程内存，未观察运行标志值、确认代码引用或证明最终根因。私有记录保留二进制完整哈希，公开记录不包含用户/窗口 ID、路径或聊天。

另核对了 [Qt 上游 5.15.2 的 Windows UIA 源码](https://github.com/qt/qtbase/blob/v5.15.2/src/plugins/platforms/windows/uiautomation/qwindowsuiaaccessibility.cpp)：其 WM_GETOBJECT 处理会主动设置 accessibility active。它只是公开上游设计，不是已安装微信二进制的对应源码，不能证明微信执行了该分支或直接将其修改编入微信。当前 DLL 的有限磁盘字符串检查未发现 `QT_ACCESSIBILITY` 或 `--force-renderer-accessibility` 标记，也不能仅凭缺少字符串证明不支持参数；没有因此安排另一次未经验证的参数重启。

## 独立的有限设备实验

1. 新增仅手动运行的 `wechat-msaa-tree-probe <明确选定窗口>`，沿 [AccessibleChildren](https://learn.microsoft.com/en-us/windows/win32/api/oleacc/nf-oleacc-accessiblechildren) 检查数字角色/文本角色状态，不读名称、值、描述、焦点或动作。500 节点/16 层，重复对象、未知角色及截断不作完整结果；严格 COM 失败/不一致拒绝。探针不加入 CTest，不进入正式分发；CTest 只运行独立合成对象。
2. 先用纯合成 COM 完成 21 项边界检查，再用本测试进程的 Win32 窗口验证真实 MSAA API 能识别 1 个文本角色。8 组无效参数拒绝。参考/正式构建和根 CTest 各 6/6；完整 Python 912 发现、871 执行通过、41 条件跳过（116.613 秒），19 个既有 GC 退出警告保留，导入原生扩展与参考构建哈希一致。
3. 当前微信精确选窗、用户、PID/birth 及映像前后复核后，MSAA 实际得到 47 个节点（17 个对象、30 个子元素），**0 个文本角色**。数字角色均已知，无重复对象或预算触达。这里只是返回子树的完整有界遍历，不证明它涵盖应用内部控件；26 个按钮角色不证明存在可用搜索/发送动作。
4. 本人随后单独批准一次临时标准读屏参数实验。私有脚本先通过 25 项合成检查，覆盖成功/原值已开/失败/超时/恢复失败及无初始状态时不操作。实际由 false 开到 true 并回读核对，只调用一次 12 秒期限的既有 RawView 探针；仍为 **4 节点/0 Edit**，无预算触达。随后恢复 false 并回读确认。没有 `SPIF_UPDATEINIFILE`、注册表修改、重启、内存读写、正文、输入或发送；这次明确许可已经使用，不自动重做或扩为其他实验。

新增私有记录为 `msaa-tree-device-20261104.json`、`msaa-tree-synthetic-20261104.json`、`msaa-metadata-full-tests.txt`、`github-accessibility-verified-constants-20261104.json` 和 `screenreader-parameter-device-20261104.json`，保留在既有交付根目录的 verification。测试脚本不作为产品设备计划、签名许可或正式入口分发。

## 当前边界与后续缺口

当前可验证结论是：ControlView、RawView、MSAA 子树及运行中的标准读屏参数切换，均未在已观察条件下暴露可用输入控件。不能认定客户端永久不兼容，也不把其他项目的进程内存写入结果当作本机根因证明。

参考项目提供的同版本机制线索，比继续重复前台/权限/遍历负结果更具体，但其有效路径仍越过当前“不以内存修改/坐标回退伪装通过”的边界。本轮没有执行该路径、修改永久系统设置或再次重启；若改变实验边界，须单独限定并确认具体动作，不能继承这次读屏参数许可。

即使日后恢复 provider，现有适配器仍要求已展开、具有可读/可写 ValuePattern 的固定搜索控件；收起入口的安全展开方式、实际输入与选择模式、账号及稳定私聊身份尚须适配/验证。[历史软件审计](WINDOWS_SOFTWARE_AUDIT.md)不是当前版本兼容证明，不能将这些条件概括为只缺安装。受保护部署、本人初始化、导航绑定、可信审查者与有限签名计划仍未完成，正式 gate 关闭，Unknown 不重发。

## 2026-11-05 后续源码核对

参考仓库已到 `4931f98d4b4b68dc4af8cfc10f76805eb9c743da`，相对上一快照有四个提交，包括[窗口范围和遍历循环回归](https://github.com/fanyuantaier/wechatauto-replica/blob/4931f98d4b4b68dc4af8cfc10f76805eb9c743da/tests/test_uia_traversal.py)。该变更没有提供新的无内存写入激活机制。对本项目原生枚举的独立核对发现忽略 COM 失败、缺少运行身份重复检测的问题，现已修复并补齐严格原始子树包含检查；没有复制外部实现，详见[正式遍历边界](WINDOWS_NAVIGATION_ADMISSION.md#原生遍历边界)。

静态 DLL 核对另找到参考候选的唯一 RIP 相对比较引用，但磁盘初始字节为 **1**，不能从树缺失推定运行值必为 0。磁盘初始值、运行状态和代码语义是不同证据；没有在只读分析中打开进程内存。独立私有审查脚本默认只读磁盘/OS 模块元数据，完整哈希和唯一引用不符即拒绝；28 项合成故障/恢复检查通过。实际读取并临时修改一个固定数据字节需要本人另行明确许可，且只允许一次元数据探针和恢复核对，不连接正式服务或产出设备通过材料。

## 本人确认后的单字节实机结果

2026-11-05，本人在上一轮明确展示限定方案与剩余风险后要求“进行实机测试”。本轮按该具体语境只执行一次固定数据字节对照，不将其扩大为完整微信操作或持续激活授权。执行前重新 fetch/review，源码与远端为干净 `f24b420`；核对同用户、唯一窗口、进程 birth、精确 EXE/DLL/helper 哈希、加载模块、唯一静态比较引用及可写非执行映像区。私有脚本 28 项合成检查再次通过；执行前只补充准确的读取/探针计数和失败记录字段，没有改产品运行时代码。

| 本次实际步骤 | 观察 |
| --- | --- |
| 读取固定运行字节 | **0**；与磁盘初始 1 分开记录，不以静态值替代运行值 |
| 仅临时写为 1 | 成功；不注入代码、改变页保护、磁盘文件或系统设置 |
| 一次 RawView 元数据探针，外部期限 12 秒 | **84 节点/1 Edit**；节点/深度预算均未触达，窗口复核成功 |
| 恢复原字节并核对 | 写入序列 `[1,0]`，恢复为 **0** 并回读成功；共 5 次成功读取，始终限同一个字节 |
| 恢复后的树、缓存和可用动作 | **未再次检查**；不声称缓存/整个客户端状态回滚或树会持续存在 |

此前 RawView 4/0 是较早观察，**不是本轮同步采集的基线**。本次只证明该临时条件下出现了这些结构，与参考机制相符，但没有多轮重复、恢复后树对照、编辑模式/用途、账号或稳定私聊身份的验证。一个 Edit 不一定就是聊天输入，更不能据此确认可导航、输入或发送；当前收起搜索入口的适配缺口仍在。

统计不读取名称、值、AutomationId、聊天/搜索/草稿或账号/联系人，不调用动作，没有焦点/输入/发送、截图、重启、Hello、服务安装、凭据迁移或联网模型。仅一字节临时读写是本次新明确许可覆盖的行为；不把这一许可解释为这些其他操作的权限。

原始文件为既有 verification 下的 `qt-flag-device-20261105.json`，聚合/范围解释为 `qt-flag-observation-summary-20261105.json`。原始结果中的嵌套 `review` 是静态审查输入，顶层运行字段是实际观察；`requires_separate_explicit_memory_approval` 描述该入口要求，不表示本次确认缺失。`authorization_granted=false` / `runtime_qualified=false` 指产品任务及设备资格，不能因聊天中的实验许可改成 true。复用清理逻辑的 `setting_change_attempted` 在此记录中指该数据字节，`settings_changed=false` 表示未改 Windows 系统参数。

许可已经使用，不自动重试、恢复旧任务或保持为 1；私有脚本不进入正式服务/桌面分发，不生成签名准入材料。产品运行时和 `31d6a0a` 的候选未改变，本轮没有重复 913 项回归或打包。已实时确认该实现 CI `41987995033` 的 Windows、Mac、native-fuzz 全部成功，仍仅是软件证据。后续稳定启用方案、能力/路径、账号/收件人、导航及受保护验收仍须沿现有固定审查入口独立推进，普通 gate 保持关闭。
