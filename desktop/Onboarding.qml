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
    signal accessRequested(int level)
    signal assistantRequested(var preferences)
    modal: true; header: null; padding: 28; closePolicy: Popup.CloseOnEscape
    width: Math.min(800,parent.width-48); height: Math.min(650,parent.height-48)
    background: GlassPanel { radius: 26; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
    Overlay.modal: Item {
        MultiEffect { anchors.fill: parent; source: Theme.glassSource; blurEnabled: true; blur: 1; blurMax: 32; autoPaddingEnabled: false }
        Rectangle { anchors.fill: parent; color: Theme.dark ? "#6B000000" : "#3D20352A" }
    }
    onStepChanged: if(step===4)controller.verifySetup()
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
                        FeatureRow { title: "电脑空闲后再发送，减少打扰"; symbol: "clock" }
                    }
                    Detail { Layout.fillWidth: true; text: "本向导不会自动读取聊天正文或发送测试消息。敏感操作仍需单独确认。" }
                }
                ColumnLayout { visible: setup.step===1; Layout.fillWidth: true; spacing: 12
                    Card { Layout.fillWidth: true
                        StateRow { title: "本地服务"; ready: setup.controller.data.connected===true }
                        RowLayout { Layout.fillWidth: true
                            GlassButton { text: "连接服务"; onClicked: setup.controller.start() }
                            GlassButton { text: "初始化连接"; onClicked: initializeConfirm.open() }
                        }
                        Detail { Layout.fillWidth: true; text: "首次初始化需本机认证，建立连接后仍不会授予会话访问权限。" }
                    }
                    Card { Layout.fillWidth: true
                        StateRow { title: "微信数据访问"; ready: (setup.status.permissions || {}).database===true }
                        StateRow { title: "设备控制"; ready: (setup.status.permissions || {}).accessibility===true }
                        RowLayout { GlassButton { text: "数据访问设置"; onClicked: setup.controller.openSystemPermission("database") } GlassButton { text: "设备控制设置"; onClicked: setup.controller.openSystemPermission("accessibility") } }
                    }
                    Card { Layout.fillWidth: true; visible: setup.controller.data.connected!==true
                        Copy { text: "尚未安装本地组件？"; font.weight: Font.Medium }
                        Detail { Layout.fillWidth: true; text: setup.controller.setupPackage ? "所选安装包："+setup.controller.setupPackage+"。安装需要管理员确认，不授予聊天访问。" : "选择为本机账号准备的服务安装包，再确认安装。" }
                        RowLayout { GlassButton { text: "选择安装包"; onClicked: setup.controller.chooseSetupPackage() } GlassButton { text: "确认安装"; enabled: !!setup.controller.setupPackage; onClicked: setup.controller.installSetupPackage() } }
                    }
                }
                Card { visible: setup.step===2; Layout.fillWidth: true
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
}
