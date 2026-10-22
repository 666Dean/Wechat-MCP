import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: settings
    required property var controller
    property bool connected: false
    property bool scopeActive: false
    property bool systemReady: false
    property bool independentService: false
    property bool darkMode: false
    property int accessLevel: 0
    property int section: 0
    property var status: controller.data.status || ({})
    property var autoReply: status.automatic_reply || ({})
    property string chosenThread: ""
    signal accessRequested(int level)
    signal stopRequested()
    signal revokeRequested()
    signal pageRequested(int page)
    signal themeRequested(bool dark)
    signal hooksRequested()
    signal assistantRequested(var preferences)
    signal setupRequested()
    function timeText(){return autoReply.expires ? new Date(autoReply.expires*1000).toLocaleString(Qt.locale(),"MM-dd HH:mm") : "直至停止"}
    component Label: Text { color: Theme.ink; textFormat: Text.PlainText; wrapMode: Text.WordWrap; font.pixelSize: 13 }
    component Detail: Label { color: Theme.muted; font.pixelSize: 12 }
    component Group: Rectangle {
        default property alias rows: content.data
        implicitHeight: content.implicitHeight+24; radius: 16; color: Theme.surface; border.color: Theme.border
        ColumnLayout { id: content; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 0 }
    }
    component Rule: Rectangle { Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 10; height: 1; color: Theme.border }
    component Toggle: Switch {
        id: toggle; implicitWidth: 42; implicitHeight: 26; padding: 0
        indicator: Rectangle { width: 40; height: 24; radius: 12; y: (toggle.height-height)/2; color: toggle.checked ? Theme.brand : Theme.border; border.color: toggle.activeFocus ? Theme.focusBorder : "transparent"
            Rectangle { x: toggle.checked ? 18 : 2; y: 2; width: 20; height: 20; radius: 10; color: "white"; border.color: "#18000000"
                Behavior on x { NumberAnimation { duration: Theme.motionEnabled ? 110 : 0 } }
            }
        }
    }
    component Row: Item {
        property string title: ""
        property string detail: ""
        default property alias actions: controls.data
        Layout.fillWidth: true; implicitHeight: Math.max(labels.implicitHeight,controls.implicitHeight)+24
        RowLayout { anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 16
            ColumnLayout { id: labels; Layout.fillWidth: true; Layout.minimumWidth: 70; spacing: 4
                Label { Layout.fillWidth: true; text: parent.parent.parent.title }
                Detail { Layout.fillWidth: true; visible: !!text; text: parent.parent.parent.detail }
            }
            RowLayout { id: controls; spacing: 6; Layout.fillWidth: false; Layout.alignment: Qt.AlignRight; Layout.maximumWidth: parent.width*.58 }
        }
    }
    RowLayout { anchors.fill: parent; spacing: 28
        ColumnLayout { Layout.preferredWidth: 156; Layout.fillHeight: true; Layout.topMargin: 4; spacing: 5
            Repeater { model: ["消息助理","助理偏好","连接与外观"]
                ToolButton { id: category; required property int index; required property string modelData; objectName: "settingsCategory"+index; Layout.fillWidth: true; implicitHeight: 36; leftPadding: 12; rightPadding: 12
                    onClicked: settings.section=index
                    background: Rectangle { radius: 10; color: settings.section===category.index ? Theme.glass : category.hovered ? Theme.hover : "transparent"; border.color: category.activeFocus ? Theme.focusBorder : settings.section===category.index ? Theme.border : "transparent" }
                    contentItem: Text { text: category.modelData; color: settings.section===category.index ? Theme.ink : Theme.muted; font.pixelSize: 13; font.weight: settings.section===category.index ? Font.DemiBold : Font.Normal; verticalAlignment: Text.AlignVCenter }
                }
            }
            Item { Layout.fillHeight: true }
        }
        ScrollView { id: scroll; objectName: "settingsDetailScroll"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth; ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout { width: Math.min(680,scroll.availableWidth); spacing: 16
                Label { Layout.fillWidth: true; Layout.preferredHeight: 44; verticalAlignment: Text.AlignVCenter; text: ["消息助理","助理偏好","连接与外观"][settings.section]; font.pixelSize: 20; font.weight: Font.DemiBold }
                ColumnLayout { visible: settings.section===0; Layout.fillWidth: true; spacing: 14
                    Group { Layout.fillWidth: true
                        Row { title: "当前模式"; Detail { objectName: "replyModeStatus"; text: !settings.scopeActive ? "未开启" : settings.autoReply.active ? "自动回复已开启" : "仅生成草稿 · 不自动发送" } }
                        Rule {}
                        Row { title: "微信访问"; detail: settings.scopeActive ? (settings.controller.data.grants || []).length+" 个私聊" : "选择访问对象和权限"
                            GlassCombo { objectName: "settingsAccessMenu"; model: ["仅生成草稿","自动回复","完全访问"]; currentIndex: settings.accessLevel; menuWidth: 190
                                onActivated: function(index){settings.accessRequested(index);currentIndex=Qt.binding(function(){return settings.accessLevel})} }
                        }
                        Rule {}
                        Row { title: "有效期"; Detail { text: settings.scopeActive ? settings.timeText() : "未授权" } }
                        Rule {}
                        Row { title: "回复次数"; Detail { text: !settings.scopeActive ? "未授权" : settings.autoReply.remaining===null || settings.autoReply.remaining===undefined ? "不限次数" : "剩余 "+settings.autoReply.remaining+" 次" } }
                    }
                    Group { Layout.fillWidth: true
                        Row { title: "本人任务"; detail: "敏感操作仍需确认"; Detail { text: (settings.status.scope || {}).self_agent===true ? "已开启" : "未开启" } }
                        Rule { visible: settings.status.pending_review_supported===true }
                        Row { visible: settings.status.pending_review_supported===true; title: "人工审批"; detail: "披露与发送分别核对；旧待办仍需批准"
                            Switch { objectName: "manualApprovalSwitch"; checked: settings.status.manual_approval_required!==false
                                enabled: settings.connected && !settings.controller.data.loading
                                onClicked: settings.controller.setManualApproval(checked) }
                        }
                        Rule {}
                        Row { title: "已有草稿"; Detail { text: (settings.status.scope || {}).overwrite_drafts ? "允许覆盖" : "保留"; color: (settings.status.scope || {}).overwrite_drafts ? Theme.warning : Theme.muted } }
                        Rule {}
                        Row { title: "连续消息"; Detail { text: "合并后回复" } }
                        Rule {}
                        Row { title: "发送时机"; Detail { text: ({when_idle:"电脑空闲 15 秒后",foreground_only:"仅微信在前台且空闲时",background_when_idle:"后台发送 · 空闲时",immediate:"立即切换微信"})[(settings.status.scope || {}).send_policy || "immediate"] } }
                    }
                    RowLayout { Layout.fillWidth: true; spacing: 8
                        Item { Layout.fillWidth: true }
                        GlassButton { objectName: "autoStop"; text: "停止并撤权"; enabled: settings.connected && (settings.scopeActive || settings.controller.data.automatic_pending===true); onClicked: settings.stopRequested() }
                        GlassButton { objectName: "autoStart"; text: settings.scopeActive ? "管理授权" : "选择范围并授权"; primary: true; enabled: settings.connected && settings.systemReady; onClicked: settings.accessRequested(settings.accessLevel) }
                    }
                    Detail { Layout.fillWidth: true; text: (settings.status.background_send_qualified===true ? "" : "当前不支持可靠的无前台发送。") + ((settings.status.scope || {}).send_policy==="foreground_only" ? "仅微信本已位于前台且空闲时发送，不主动切换应用。" : "空闲发送仍会将微信置前；可在管理授权中选择仅前台时发送。") + "权限变更需本机确认。" }
                    RowLayout { visible: settings.connected && !settings.systemReady
                        GlassButton { text: "数据访问"; onClicked: settings.controller.openSystemPermission("database") }
                        GlassButton { text: "设备控制"; onClicked: settings.controller.openSystemPermission("accessibility") }
                    }
                }
                ColumnLayout { visible: settings.section===1; Layout.fillWidth: true; spacing: 14
                    Group { Layout.fillWidth: true
                        Row { title: "Codex 对话"; detail: (settings.controller.assistant || {}).thread_title || "尚未绑定"
                            GlassButton { objectName: "loadThreads"; text: settings.controller.threadsLoading ? "载入中…" : "载入对话"; enabled: settings.connected && !settings.controller.threadsLoading; onClicked: settings.controller.loadThreads() }
                            GlassButton { objectName: "moreThreads"; text: "更多"; visible: settings.controller.threadsHasMore; enabled: settings.connected && !settings.controller.threadsLoading; onClicked: settings.controller.loadMoreThreads() }
                        }
                        GlassCombo { id: threads; objectName: "threadSelector"; Layout.fillWidth: true; Layout.margins: 10; enabled: count>0; model: settings.controller.codexThreads; textRole: "title"; valueRole: "id"; Accessible.name: "绑定的 Codex 对话"; onActivated: settings.chosenThread=currentValue }
                        Detail { Layout.fillWidth: true; Layout.margins: 10; text: settings.controller.codexThreads.length ? "已载入 "+settings.controller.codexThreads.length+" 个对话"+(settings.controller.threadsHasMore ? " · 可继续载入" : "") : "载入后选择对话；保存前不会改变绑定。" }
                        Row { title: "任务状态"; Detail { text: (settings.controller.data.thread_binding || {}).state==="busy" ? "忙碌时排队" : "等待连接事件" } }
                        Row { visible: !settings.independentService; title: "生命周期连接"; GlassButton { text: "配置连接"; onClicked: settings.hooksRequested() } }
                    }
                    Group { Layout.fillWidth: true
                        Row { title: "人设"; GlassButton { text: "导入"; enabled: !settings.scopeActive; onClicked: settings.controller.importPersona() } }
                        ScrollView { Layout.fillWidth: true; Layout.preferredHeight: 104; Layout.margins: 10; clip: true
                            TextArea { id: persona; text: (settings.controller.assistant || {}).persona || ""; placeholderText: "助理的身份与工作背景"; wrapMode: TextEdit.Wrap; color: Theme.ink; selectByMouse: true; background: Rectangle { radius: 10; color: Theme.canvas } }
                        }
                        Row { title: "回复风格" }
                        TextField { id: style; Layout.fillWidth: true; Layout.leftMargin: 10; Layout.rightMargin: 10; implicitHeight: 36; text: (settings.controller.assistant || {}).style || ""; color: Theme.ink; selectByMouse: true; placeholderText: "例如：自然、简短、直接"; background: Rectangle { radius: 10; color: Theme.canvas } }
                        Row { title: "AI 署名"
                            Toggle { id: attribution; checked: (settings.controller.assistant || {}).attribution !== false; Accessible.name: "在回复中显示 AI 署名" }
                        }
                    }
                    GlassButton { text: "保存助理偏好"; primary: true; enabled: settings.connected && !settings.scopeActive
                        onClicked: settings.assistantRequested({thread_id:settings.chosenThread || (settings.controller.assistant || {}).thread_id || "",thread_title:settings.chosenThread ? threads.currentText : (settings.controller.assistant || {}).thread_title || "",persona:persona.text,style:style.text,attribution:attribution.checked}) }
                    Detail { Layout.fillWidth: true; text: settings.scopeActive ? "停止当前访问后可修改助理偏好。" : "本人任务与桌面共享对话；普通私聊使用独立助理。" }
                }
                ColumnLayout { visible: settings.section===2; Layout.fillWidth: true; spacing: 14
                    Group { Layout.fillWidth: true
                        Row { title: "外观"
                            GlassCombo { model: ["浅色","深色"]; currentIndex: settings.darkMode ? 1 : 0; menuWidth: 140; onActivated: settings.themeRequested(currentIndex===1) }
                        }
                        Rule {}
                        Row { title: "减少动态效果"; Toggle { checked: settings.controller.reduceMotion; onToggled: settings.controller.setReduceMotion(checked); Accessible.name: "减少动态效果" } }
                    }
                    Group { Layout.fillWidth: true
                        Row { title: "设置向导"; GlassButton { text: "重新检查"; onClicked: settings.setupRequested() } }
                        Rule {}
                        Row { title: "连接管理"; GlassButton { text: "管理"; onClicked: settings.pageRequested(1) } }
                        Rule {}
                        Row { title: "隐私与权限"; GlassButton { text: "查看"; onClicked: settings.accessRequested(settings.accessLevel) } }
                        Rule {}
                        Row { title: "附件目录"; GlassButton { text: "管理"; onClicked: settings.pageRequested(5) } }
                        Rule {}
                        Row { title: "执行记录"; GlassButton { text: "查看"; onClicked: settings.pageRequested(4) } }
                    }
                    GlassButton { text: "撤销全部授权"; enabled: settings.connected; onClicked: settings.revokeRequested() }
                }
                Item { Layout.preferredHeight: 24 }
            }
        }
    }
}
