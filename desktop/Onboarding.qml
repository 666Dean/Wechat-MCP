import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import "."

Dialog {
    id: setup
    required property var controller
    property int step: 0
    property bool resumeAfterAccess: false
    property bool resumeAfterAssistant: false
    property string chosenThread: ""
    property var status: controller.data.status || ({})
    property var environment: controller.setupEnvironment || ({})
    signal accessRequested(int level)
    signal assistantRequested(var preferences)
    modal: true; header: null; padding: 28; closePolicy: Popup.CloseOnEscape
    width: Math.min(800,parent.width-48); height: Math.min(650,parent.height-48)
    background: GlassPanel { radius: 26; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
    Overlay.modal: Item {
        MultiEffect { anchors.fill: parent; source: Theme.glassSource; blurEnabled: true; blur: 1; blurMax: 32; autoPaddingEnabled: false }
        Rectangle { anchors.fill: parent; color: Theme.dark ? "#6B000000" : "#3D20352A" }
    }
    onOpened: controller.inspectSetupEnvironment()
    onStepChanged: {if(step===4)controller.verifySetup();if(step===1 || step===2)controller.inspectSetupEnvironment()}
    component Copy: Text { color: Theme.ink; font.pixelSize: 14; textFormat: Text.PlainText; wrapMode: Text.WordWrap }
    component Detail: Copy { color: Theme.muted; font.pixelSize: 12 }
    component Card: Rectangle {
        default property alias content: rows.data
        implicitHeight: rows.implicitHeight+32; radius: 16; color: Theme.surface; border.color: Theme.border
        ColumnLayout { id: rows; anchors.fill: parent; anchors.margins: 16; spacing: 12 }
    }
    component StateRow: RowLayout {
        property string title: ""
        property bool ready: false
        Layout.fillWidth: true; spacing: 10
        Icon { name: parent.ready ? "check" : "info"; ink: parent.ready ? Theme.positive : Theme.muted; width: 18; height: 18 }
        Copy { Layout.fillWidth: true; text: parent.title }
        Detail { text: parent.ready ? "已就绪" : "待完成" }
    }
    component FeatureRow: RowLayout {
        property string title: ""
        property string symbol: "shield"
        Layout.fillWidth: true; spacing: 12
        Icon { name: parent.symbol; ink: Theme.positive; width: 20; height: 20 }
        Copy { Layout.fillWidth: true; text: parent.title }
    }
    Connections { target: setup.controller; function onSetupCompleted(){setup.close()} }
    contentItem: ColumnLayout { spacing: 22
        RowLayout { Layout.fillWidth: true; spacing: 14
            Image { source: "icon.svg"; sourceSize.width: 192; sourceSize.height: 192; Layout.preferredWidth: 48; Layout.preferredHeight: 48 }
            ColumnLayout { Layout.fillWidth: true; spacing: 3
                Copy { text: "WeChat MCP"; font.pixelSize: 19; font.weight: Font.DemiBold }
                Detail { text: "为你的消息，安排一位助理" }
            }
            Detail { text: setup.step===0 ? "欢迎" : setup.step+" / 4" }
        }
        Rectangle { Layout.fillWidth: true; height: 3; radius: 2; color: Theme.border
            Rectangle { width: parent.width*setup.step/4; height: 3; radius: 2; color: Theme.brand; Behavior on width { NumberAnimation { duration: Theme.motionEnabled ? 160 : 0 } } }
        }
        ScrollView { id: scroll; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth; ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout { width: scroll.availableWidth; spacing: 18
                Copy { Layout.fillWidth: true; text: ["让消息，接上你的工作。","先连接你的本机环境","选择助理所在的对话","访问多少，由你决定","确认一切已经就绪"][setup.step]; font.pixelSize: 26; font.weight: Font.DemiBold }
                Detail { Layout.fillWidth: true; text: ["连接微信与 Codex，整理消息、准备回复，也接下你交办的事。","仅在本机连接数据。每项权限都由你确认。","桌面任务与本人任务会在这个 Codex 对话中接续。","从少量联系人开始。随时可以停止或调整范围。","逐项核对真实连接状态，全部通过后才能完成设置。"][setup.step] }
                ColumnLayout { visible: setup.step===0; Layout.fillWidth: true; spacing: 14
                    Card { Layout.fillWidth: true
                        FeatureRow { title: "指定会话与访问范围"; symbol: "shield" }
                        FeatureRow { title: "保留已有输入，不重发不确定消息"; symbol: "message" }
                        FeatureRow { title: "经授权后切换微信发送，结果持续核对"; symbol: "clock" }
                    }
                    Detail { Layout.fillWidth: true; text: "本向导不会自动读取聊天正文或发送测试消息。敏感操作仍需单独确认。" }
                }
                ColumnLayout { visible: setup.step===1; Layout.fillWidth: true; spacing: 12
                    Card { Layout.fillWidth: true
                        StateRow { title: "本地服务"; ready: setup.controller.data.connected===true }
                        RowLayout { visible: setup.environment.installed===true; Layout.fillWidth: true
                            GlassButton { text: "连接服务"; onClicked: setup.controller.start() }
                            GlassButton { text: "初始化连接"; onClicked: initializeConfirm.open() }
                            GlassButton { objectName: "recoverWindowsSetup"; visible: setup.environment.platform==="windows"; text: "恢复中断的初始化"; onClicked: recoveryConfirm.open() }
                        }
                        Detail { Layout.fillWidth: true; text: "首次初始化需本机认证，建立连接后仍不会授予会话访问权限。" }
                    }
                    Card { Layout.fillWidth: true
                        StateRow { title: "微信数据访问"; ready: (setup.status.permissions || {}).database===true }
                        StateRow { title: "设备控制"; ready: (setup.status.permissions || {}).accessibility===true }
                        RowLayout { GlassButton { text: "数据访问设置"; onClicked: setup.controller.openSystemPermission("database") } GlassButton { text: "设备控制设置"; onClicked: setup.controller.openSystemPermission("accessibility") } }
                    }
                    Card { Layout.fillWidth: true; visible: setup.environment.installed!==true
                        Copy { text: "安装本机安全服务"; font.weight: Font.Medium }
                        StateRow { title: "随 App 提供的组件"; ready: setup.environment.components===true }
                        GlassButton { visible: setup.environment.platform==="windows"; text: "选择本机组件"; onClicked: setup.controller.chooseSetupPackage() }
                        RowLayout { Layout.fillWidth: true
                            GlassButton { objectName: "chooseWechatData"; text: "选择微信数据"; onClicked: setup.controller.chooseWechatData() }
                            Detail { Layout.fillWidth: true; text: setup.environment.folder ? "已选择数据文件夹" : "选择本人账号的 db_storage 文件夹" }
                        }
                        TextField { objectName: "setupAccountId"; Layout.fillWidth: true; placeholderText: "确认本人微信稳定 ID"; text: setup.environment.account || ""; onTextEdited: setup.controller.setSetupAccount(text)
                            background: Rectangle { radius: 10; color: Theme.canvas; border.color: Theme.border }
                            color: Theme.ink; padding: 12; selectByMouse: true
                        }
                        GlassCombo { id: credentialMode; Layout.fillWidth: true; model: ["导入本人已有的数据凭据","迁移已有 AXR 凭据索引"] }
                        GlassCombo { objectName: "windowsCredentialMode"; visible: setup.environment.platform==="windows" && credentialMode.currentIndex===0; Layout.fillWidth: true
                            model: ["按文件声明（纯 hex 视为页密钥）","原始页密钥","32 字节口令"]
                            onActivated: setup.controller.setSetupCredentialMode(["file","raw","password"][currentIndex]) }
                        RowLayout { Layout.fillWidth: true
                            GlassButton { text: "选择凭据"; onClicked: setup.controller.chooseWechatCredential(credentialMode.currentIndex===1) }
                            Detail { Layout.fillWidth: true; text: setup.environment.credential || "仅本机导入，不上传到模型"; elide: Text.ElideMiddle }
                        }
                        Detail { Layout.fillWidth: true; text: "微信数据已加密，需你合法持有的原始数据密钥缓存，或已有 AXR 索引。App 不提取进程密钥、不改变微信保护；不需要在聊天中提供密码。" }
                        GlassButton { objectName: "installBundledService"; text: "安装安全服务"; primary: true
                            enabled: setup.environment.components===true && !!setup.environment.folder && !!setup.environment.credential && setup.environment.login===true && !setup.controller.data.loading
                            onClicked: installConfirm.open() }
                    }
                    Card { Layout.fillWidth: true
                        StateRow { title: "Codex 已安装"; ready: setup.environment.codex===true }
                        StateRow { title: "Codex 已登录"; ready: setup.environment.login===true }
                        RowLayout { Layout.fillWidth: true
                            GlassButton { text: "获取 Codex"; onClicked: setup.controller.openCodexDownload() }
                            GlassButton { visible: setup.environment.platform==="windows"; text: "选择本机程序"; onClicked: setup.controller.chooseSetupCodex() }
                            GlassButton { text: "登录 Codex"; enabled: setup.environment.codex===true && setup.environment.login!==true && !setup.controller.data.loading; onClicked: setup.controller.loginCodex() }
                            GlassButton { text: "重新检查"; enabled: !setup.controller.data.loading; onClicked: setup.controller.inspectSetupEnvironment() }
                        }
                    }
                }
                Card { visible: setup.step===2; Layout.fillWidth: true
                    GlassButton { text: "连接到 Codex"; enabled: setup.environment.installed===true && !setup.controller.data.loading; onClicked: codexConfirm.open() }
                    Copy { Layout.fillWidth: true; text: (setup.controller.assistant || {}).thread_title || "尚未绑定对话"; font.weight: Font.Medium }
                    GlassButton { text: setup.controller.threadsLoading ? "载入中…" : "载入 Codex 对话"; enabled: !setup.controller.threadsLoading; onClicked: setup.controller.loadThreads() }
                    GlassCombo { id: threads; Layout.fillWidth: true; model: setup.controller.codexThreads; textRole: "title"; valueRole: "id"; enabled: count>0; onActivated: setup.chosenThread=currentValue }
                    GlassButton { text: "更多对话"; visible: setup.controller.threadsHasMore; enabled: !setup.controller.threadsLoading; onClicked: setup.controller.loadMoreThreads() }
                    GlassButton { text: "确认绑定此对话"; primary: true; enabled: !!setup.chosenThread && !setup.status.owner_authorized
                        onClicked: setup.assistantRequested({thread_id:setup.chosenThread,thread_title:threads.currentText}) }
                    Detail { Layout.fillWidth: true; text: setup.status.owner_authorized ? "当前已有授权，保留现有绑定。更换对话前请先停止访问。" : "绑定变更需二次确认；不会自动发起对话。" }
                }
                Card { visible: setup.step===3; Layout.fillWidth: true
                    StateRow { title: "会话访问"; ready: setup.status.owner_authorized===true }
                    GlassButton { text: "仅准备回复草稿"; onClicked: setup.accessRequested(0) }
                    GlassButton { text: "自动回复指定联系人"; onClicked: setup.accessRequested(1) }
                    GlassButton { text: "完全访问 · 含本人任务"; onClicked: setup.accessRequested(2) }
                    Detail { Layout.fillWidth: true; text: "每种模式都要核对联系人和有效期。完全访问还需绑定 Codex 对话，并纳入本人私聊。" }
                }
                Card { visible: setup.step===4; Layout.fillWidth: true
                    Repeater { model: setup.controller.setupResult.checks || []
                        StateRow { required property var modelData; title: modelData.title; ready: modelData.ready }
                    }
                    BusyIndicator { visible: setup.controller.data.loading===true; running: visible; Layout.alignment: Qt.AlignHCenter }
                    GlassButton { text: "重新检查"; enabled: !setup.controller.data.loading; onClicked: setup.controller.verifySetup() }
                    Detail { Layout.fillWidth: true; text: setup.controller.setupResult.ready ? "基础连接已通过。可以开始使用；发送结果仍以每次实际核对为准。" : "完成尚未就绪的项目后重新检查。不会用演示状态替代真实连接。" }
                }
            }
        }
        RowLayout { Layout.fillWidth: true
            GlassButton { text: setup.step>0 ? "上一步" : "稍后设置"; onClicked: setup.step>0 ? setup.step-- : setup.close() }
            Item { Layout.fillWidth: true }
            GlassButton { objectName: "setupNext"; primary: true; text: setup.step===0 ? "开始设置" : setup.step===4 ? "完成设置" : "下一步"; enabled: setup.step!==4 || (setup.controller.setupResult.ready===true && !setup.controller.data.loading)
                onClicked: {if(setup.step===4)setup.controller.finishSetup();else {setup.step++;scroll.contentItem.contentY=0}} }
        }
    }
    Dialog {
        id: installConfirm; anchors.centerIn: parent; modal: true; header: null; padding: 24; width: Math.min(440,setup.width-32)
        background: GlassPanel { radius: 22; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
        contentItem: ColumnLayout { spacing: 18
            Copy { text: "安装本机安全服务？"; font.pixelSize: 20; font.weight: Font.DemiBold }
            Detail { Layout.fillWidth: true; text: "将安装已校验的 AXR 组件，并核对你选择的数据文件夹与 Codex。需要一次管理员确认，随后初始化还需本人身份确认。此步骤不读取聊天正文、不授予发送权限；已有部署和数据不会被替换。" }
            RowLayout { Layout.alignment: Qt.AlignRight
                GlassButton { text: "取消"; onClicked: installConfirm.close() }
                GlassButton { text: "确认安装"; primary: true; onClicked: {installConfirm.close();setup.controller.installBundledService()} }
            }
        }
    }
    Dialog {
        id: codexConfirm; anchors.centerIn: parent; modal: true; header: null; padding: 24; width: Math.min(420,setup.width-32)
        background: GlassPanel { radius: 22; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
        contentItem: ColumnLayout { spacing: 18
            Copy { text: "连接到 Codex？"; font.pixelSize: 20; font.weight: Font.DemiBold }
            Detail { Layout.fillWidth: true; text: "仅添加或更新 wechat_axr 连接，保留其他设置并保存本地备份。随后执行真实 MCP 连接检查；已打开的 Codex 可能需要刷新此连接。" }
            RowLayout { Layout.alignment: Qt.AlignRight
                GlassButton { text: "取消"; onClicked: codexConfirm.close() }
                GlassButton { text: "确认连接"; primary: true; onClicked: {codexConfirm.close();setup.controller.connectSetupCodex()} }
            }
        }
    }
    Dialog {
        id: initializeConfirm; anchors.centerIn: parent; modal: true; header: null; padding: 24
        width: Math.min(420,setup.width-32)
        background: GlassPanel { radius: 22; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
        contentItem: ColumnLayout { spacing: 18
            Copy { text: "初始化本机连接？"; font.pixelSize: 20; font.weight: Font.DemiBold }
            Detail { Layout.fillWidth: true; text: "将建立本机服务身份并连接已准备的微信数据凭据，需要系统认证。不会恢复旧授权或发送消息。" }
            RowLayout { Layout.alignment: Qt.AlignRight
                GlassButton { text: "取消"; onClicked: initializeConfirm.close() }
                GlassButton { text: "继续初始化"; primary: true; onClicked: {initializeConfirm.close();setup.controller.initializeSetup()} }
            }
        }
    }
    Dialog {
        id: recoveryConfirm; anchors.centerIn: parent; modal: true; header: null; padding: 24; width: Math.min(440,setup.width-32)
        background: GlassPanel { radius: 22; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
        contentItem: ColumnLayout { spacing: 18
            Copy { text: "恢复未完成的初始化？"; font.pixelSize: 20; font.weight: Font.DemiBold }
            Detail { Layout.fillWidth: true; text: "仅适用于首次设置中断。需要管理员确认，并由本人核对既有 Windows Hello 密钥和本次配置。不会创建或替换密钥、恢复旧授权或发送消息。已有正式部署会拒绝此操作。" }
            RowLayout { Layout.alignment: Qt.AlignRight
                GlassButton { text: "取消"; onClicked: recoveryConfirm.close() }
                GlassButton { text: "审查并恢复"; primary: true; onClicked: {recoveryConfirm.close();setup.controller.recoverSetup()} }
            }
        }
    }
}
