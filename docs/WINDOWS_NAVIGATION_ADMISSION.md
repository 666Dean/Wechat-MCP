# Windows 导航配置与可信准入

2026-10-31 的软件接线说明。**全项目软件阶段仍未收尾，不据此开始微信、Hello、安装或联网模型测试。** 下述入口是以后本人显式操作的产品代码，本轮只运行离线/合成回归，未导入真实配置或签署准入材料。

## 导航元数据

桌面首次设置的“设备导航配置”选择本地 JSON；Windows 安装按钮要求已选配置。文件必须恰好包含 `version=2`、`account_id`、`profiles`、`attribution_prefix`、`attribution_required`。本人从其独立保存的控件元数据准备该文件；本入口不会抓取当前 UI、正文、草稿或搜索记录，也不自动猜测路径。

可参考[完整无账号示例](../examples/windows-navigation.example.json)。其中的 ID、标题、路径和全零程序哈希均为合成占位，不对应任何真实设备；不能据此开始导航或认定微信版本兼容。

`profiles` 至少包含两个不同私聊，分别用于目标和停车见证。键是稳定私聊 ID，每项只有 `label` 与 `visual_binding`。后者必须恰好包含：

| 字段 | 内容 |
| --- | --- |
| `path`、`header_path`、`account_path`、`identity_path`、`send_path`、`search_path`、`search_result_path` | UIA 从主窗口起的子控件索引；每条 1–16 层，索引为 0–499 的整数，不能用布尔值 |
| `executable_hash` | 本人核对的微信程序 SHA-256，所有 profile 必须一致 |
| `expected_identity` | 必须等于该 profile 的稳定私聊 ID |
| `expected_title`、`search_result_title` | 本人核对的目标标题、精确搜索结果标题 |

标签/标题不能含控制字符；只接受私聊，拒绝群、公众号和系统会话。账号与身份控件不能和输入/搜索/发送控件相同，四种操作控件也不能互相别名。JSON 拒绝重复键、非有限数字和超预算文件。导航配置总预算 30,000 字节；完整安装配置仍为 32,768 字节。配置里不能带 helper、管道、资源列表、凭据或授权范围。

`windows_navigation.prepare` 将安装包已审查的 UIA helper 哈希、固定安装路径及当前服务端点补入 `reply_navigation`。首次 owner 原生审查显示完整导航配置，初始化在原生联系人目录返回后再次核对全部稳定 ID；不在本人目录中的项目不能写入生效配置。此过程不授予读取、披露或发送任务。

已有部署先显式停止服务，再选择“核对并导入”。固定 UAC 动作绑定 owner、原配置哈希与本次文档；管理员只暂存导航字段。System 的既有 `--refresh-service` 核对已批准目录、helper 哈希和配置差异，先撤销旧任务，再显示完整配置并请求既有 owner 身份签名。签名成功后密封新导航并清除旧进程登记，保留账号、凭据、历史和本人公钥。独立人工审批设置不由静态安装配置重置。

取消或响应不明不会自动回滚或重发审查：原生效密封配置保留，磁盘候选留待本人检查。候选与生效配置不一致时准入拒绝。首次设置只暂存，随后仍须初始化。导入结束不自动启动服务，不验证真实 UI 可用性。

## 可信材料准备和导入

准入信任与 Hello/AIK 信任分开：前者是本人独立核对的审查者 P-256 公钥；后者仍验证 Windows Hello 的硬件证明。审查者清单形如 `{"version":2,"keys":{"<公钥原始字节 SHA-256>":"<65 字节未压缩 P-256 公钥 hex>"}}`，最多 8 项、4 KiB。材料自身提供的公钥、测试密钥和界面布尔值都不能建立信任。

首次安装可显式选择审查者清单；已有部署可通过“选择审查者公钥 → 更新组件 → 核对新构建”首次加入。安装器将清单放入固定 `runtime/admission-trust.json`，完整安装清单与本人签署的配置共同固定其内容。普通组件更新保留同一 pin，不能替换、删除或轮换既有信任根。未配置可信审查者时准入继续拒绝。信任根轮换不属于普通组件更新，不提供自动恢复或替换路径。

初始化和构建审查只绑定本次配置/程序，不产生设备验收结论。桌面“查看材料请求”生成**内存中的未签署请求**，显示本机配置、构建、owner 公钥、导航摘要和 OS 版本绑定，以及九类所需证据；不会写出交付文件，也不包含凭据、配置正文或成功标记。可选择已由可信审查者独立签署的文件进行验证；产品不持有审查者私钥、不替审查者编造测试记录。

签署封套恰有 `body`、`key_id`、`signature`，签名为 `axr.aet.canonical(body)` 的 ECDSA/P-256/SHA-256 DER hex。body 恰含：

| 字段 | 约束 |
| --- | --- |
| `version`、`product` | 整数 2、`wechat-codex-mcp/windows` |
| `sequence` | 1 至 2^53−1 的递增整数 |
| `subject` | 必须逐字段匹配本机请求；包括 `platform=windows-x64`，不接受 Mac 记录 |
| `created`、`expires` | 有限 Unix 时间；不接受未来签发、过期或超过 30 天的有效期 |
| `stage` | `software` 或 `device` |
| `code_audit` | 恰有布尔 `complete` 及全项目审计记录的 `record_sha256` |
| `evidence` | 恰有 identity、authorization、content、data、isolation、containment、distribution、adversarial、experience 九类；每项恰有 `result=pass/fail/unknown`、`kind=software/device` 与独立记录的 `record_sha256` |

签名证明“该可信审查者签署过此声明”，不证明其记录本身真实。审查者需独立保管并核对原始证据；记录摘要不能代替实际实验。`software` 材料可保存和检查，但即使全部测试通过，也不满足任何设备准入项。只有全项目审计已完成、九类记录均为 `device/pass` 的设备审查材料才可能通过材料部分；本轮没有生成这种材料。

导入要求服务停止，分别在普通桌面与提权端验证签名/当前绑定/期限。材料固定写入 ProgramData 的 `windows-admission.json`，受原配置哈希和 owner 绑定；维护租约排除并发元数据导入，旧序列及同序列不同内容拒绝。相同材料可幂等导入，但不恢复权限。已有损坏材料不能当作从未配置而静默替换。

服务启动时重新检查正式原生模块、真实 LocalSystem/固定 authority 映像、受保护完整安装、原生 MAC 构建 pin、owner 公钥、bootstrap 状态目录/端点、已密封配置、固定 provider/CA 内容、helper pin、目录及材料有效期。bootstrap 只保存锚点，完整候选从固定安装配置读取；候选尚未本人批准时不能启动。材料有效也不代替这些当前事实。

## 尚未完成的项目级工作

导航与材料入口已有代码和离线接线；整个 Windows 项目还需按 [完整代码清单](WINDOWS_CODE_COMPLETION.md) 收尾。打包/冻结后的新入口已在干净提交 a60f3d6 的开发候选中通过导入、QML 一致性和隐私检查；仍须完成全模块调用者/未实现分支审计，以及受约束设备验收入口与整体准入之间的次序设计和离线验证，避免为收集设备证据先伪造准入结论。真实 UIA、跨会话、Hello/TPM、SCM/ACL、凭据迁移、联网来源推理和微信发送均未因本轮软件验证而验收。Unknown 不重发，旧授权不恢复。
