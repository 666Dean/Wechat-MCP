import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import "."
Dialog {
    id: dialog
    property var contacts: []
    property var selectedIds: []
    property var authorizedIds: []
    property bool overwriteDrafts: false
    property bool allContacts: false
    property int level: 1
    property int minutes: 30
    property int replies: 20
    property int pageIndex: 0
    property bool activeScope: false
    property bool bindingReady: false
    property string sendPolicy: "immediate"
    property bool backgroundAvailable: false
    readonly property var policies: ["when_idle","foreground_only","immediate"].concat(backgroundAvailable ? ["background_when_idle"] : [])
    readonly property string selfIdentity: {var row=contacts.find(function(c){return c.is_self===true});return row ? row.conversation_id : ""}
    readonly property bool fullReady: level!==2 || (bindingReady && !!selfIdentity)
    property var filtered: contacts.filter(function(c){var q=search.text.trim().toLowerCase();return (!q || (c.display_name+" "+c.conversation_id).toLowerCase().indexOf(q)>=0) && (filter.currentIndex===0 || filter.currentIndex===1 && authorizedIds.indexOf(c.conversation_id)>=0 || filter.currentIndex===2 && selectedIds.indexOf(c.conversation_id)>=0)})
    signal applyRequested(var targets,int minutes,int replies,int level,bool overwrite,string policy,int idle)
    signal stopped()
    signal bindingRequested()
    header: null; modal: true; title: "管理微信访问"; width: Math.min(720,parent.width-60); height: Math.min(690,parent.height-60); padding: 24
    background: GlassPanel { radius: 24; tint: Theme.dark ? "#FA2B332E" : "#FCFFFFFF" }
    Overlay.modal: Item {
        MultiEffect { anchors.fill: parent; source: Theme.glassSource; blurEnabled: true; blur: 1; blurMax: 32; autoPaddingEnabled: false }
        Rectangle { anchors.fill: parent; color: Theme.dark ? "#6B000000" : "#3D20352A" }
    }
    onOpened: {pageIndex=0;search.clear();if(level===2 && selfIdentity && !allContacts && selectedIds.indexOf(selfIdentity)<0)selectedIds=selectedIds.concat([selfIdentity])}
    component Check: CheckBox {
        id: check; implicitHeight: 34; spacing: 10
        indicator: Rectangle { x: check.leftPadding; y: (check.height-height)/2; width: 20; height: 20; radius: 6; color: check.checked ? Theme.brand : Theme.surface; border.color: check.activeFocus ? Theme.positive : check.checked ? Theme.brand : Theme.border; border.width: check.activeFocus ? 2 : 1
            Icon { anchors.centerIn: parent; name: "tick"; width: 14; height: 14; ink: "white"; visible: check.checked }
        }
        contentItem: Text { text: check.text; color: Theme.ink; font.pixelSize: 13; leftPadding: check.indicator.width+check.spacing; verticalAlignment: Text.AlignVCenter }
    }
    component Choice: GlassCombo { menuWidth: 180 }
    function toggleRecipient(identity){
        if(level===2 && identity===selfIdentity)return
        if(allContacts){selectedIds=contacts.filter(function(c){return c.conversation_id!==identity}).map(function(c){return c.conversation_id});allContacts=false;return}
        var next=selectedIds.slice();var at=next.indexOf(identity);if(at>=0)next.splice(at,1);else next.push(identity);selectedIds=next
    }
    contentItem: ColumnLayout { spacing: 14
        Text { text: "管理微信访问"; color: Theme.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
        RowLayout { Layout.fillWidth: true
            Text { text: ["仅生成草稿", "自动回复", "完全访问 · 含本人任务"][dialog.level]; font.pixelSize: 17; font.weight: Font.Medium; color: Theme.ink }
            Item { Layout.fillWidth: true }
            Choice { id: duration; model: ["15 分钟", "30 分钟", "1 小时", "直至停止"]; currentIndex: dialog.minutes===0 ? 3 : dialog.minutes===60 ? 2 : dialog.minutes===15 ? 0 : 1; onActivated: dialog.minutes=[15,30,60,0][currentIndex]; Accessible.name: "授权时长" }
            Choice { id: count; model: ["20 次", "100 次", "不限次数"]; currentIndex: dialog.replies===0 ? 2 : dialog.replies===100 ? 1 : 0; onActivated: dialog.replies=[20,100,0][currentIndex]; Accessible.name: "回复次数" }
        }
        Text { Layout.fillWidth: true; text: dialog.level===0 ? "仅读取所选会话并生成草稿，不授予自动或 MCP 发送权限。" : "新消息可交给 Codex 分析并回复。发送时微信会置前，已有输入会受到保护。"; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12 }
        RowLayout { visible: dialog.level>0; Layout.fillWidth: true
            Text { text: "发送时机"; font.pixelSize: 13; color: Theme.ink }
            Item { Layout.fillWidth: true }
            Choice { objectName: "sendPolicySelector"; model: ["空闲 15 秒后发送", "仅微信在前台且空闲时", "立即切换微信发送"].concat(dialog.backgroundAvailable ? ["后台发送 · 空闲时"] : []); menuWidth: 240; currentIndex: Math.max(0,dialog.policies.indexOf(dialog.sendPolicy)); onActivated: function(index){dialog.sendPolicy=dialog.policies[index]} }
        }
        Text { objectName: "sendPolicyExplanation"; visible: dialog.level>0; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
            text: (dialog.sendPolicy==="foreground_only" ? "等待你正常切回微信并空闲，不主动切换应用。" : dialog.sendPolicy==="when_idle" ? "电脑空闲后开始发送，届时微信仍会置前。" : dialog.sendPolicy==="background_when_idle" ? "仅使用本机已通过验证的后台路径。" : "立即置前微信，发送期间会占用输入焦点。") + (dialog.backgroundAvailable ? "" : " 当前不支持可靠的无前台发送；仅使用剪贴板不能保证微信后台接收输入。") + "剪贴板仅临时使用，未被你改动时才恢复。" }
        Rectangle { visible: dialog.level===2; Layout.fillWidth: true; implicitHeight: fullDetails.implicitHeight+20; radius: 12; color: dialog.fullReady ? Theme.tint : Theme.riskTint
            ColumnLayout { id: fullDetails; anchors.fill: parent; anchors.margins: 10; spacing: 6
                Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.ink; font.pixelSize: 12; text: !dialog.selfIdentity ? "尚未识别本人私聊，请刷新本地连接。" : !dialog.bindingReady ? "先绑定一个 Codex 对话，才能开启本人任务。当前访问保持不变。" : "本人私聊已纳入范围，用于 /agent 任务；其他联系人仍只可自动回复。" }
                GlassButton { visible: !dialog.bindingReady; text: "选择 Codex 对话"; onClicked: {dialog.close();dialog.bindingRequested()} }
            }
        }
        Check { text: "全部已核验私聊"; checked: dialog.allContacts; onToggled: dialog.allContacts=checked }
        RowLayout { Layout.fillWidth: true
            TextField { id: search; objectName: "accessSearch"; Layout.fillWidth: true; implicitHeight: 34; leftPadding: 12; rightPadding: 12; color: Theme.ink; placeholderTextColor: Theme.muted; font.pixelSize: 13; placeholderText: "搜索联系人名称或微信 ID"; selectByMouse: true; onTextChanged: dialog.pageIndex=0; Accessible.name: placeholderText
                background: Rectangle { radius: 10; color: Theme.canvas; border.color: Theme.border }
            }
            Choice { id: filter; model: ["全部联系人", "已授权", "本次已选"]; onActivated: dialog.pageIndex=0 }
        }
        Rectangle { Layout.fillWidth: true; Layout.fillHeight: true; color: Theme.canvas; radius: 14; border.color: Theme.border; clip: true
            ListView { id: list; objectName: "accessContactList"; anchors.fill: parent; anchors.margins: 8; clip: true; spacing: 2; model: dialog.filtered.slice(dialog.pageIndex*30,(dialog.pageIndex+1)*30); ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate { id: contactRow; required property var modelData; width: list.width; height: 54
                    background: Rectangle { radius: 10; color: contactRow.hovered || contactRow.activeFocus ? Theme.hover : "transparent"; border.color: contactRow.activeFocus ? Theme.focusBorder : "transparent" }
                    onClicked: dialog.toggleRecipient(modelData.conversation_id)
                    contentItem: RowLayout { spacing: 10
                        Check { checked: dialog.allContacts || dialog.selectedIds.indexOf(modelData.conversation_id)>=0; focusPolicy: Qt.NoFocus; Accessible.name: modelData.display_name; onToggled: dialog.toggleRecipient(modelData.conversation_id) }
                        ColumnLayout { Layout.fillWidth: true; spacing: 3
                            Text { Layout.fillWidth: true; text: modelData.display_name; color: Theme.ink; font.pixelSize: 14; elide: Text.ElideRight }
                            Text { text: modelData.is_self ? "本人私聊" : (dialog.authorizedIds.indexOf(modelData.conversation_id)>=0 ? "已授权" : "尚未授权"); color: Theme.muted; font.pixelSize: 11 }
                        }
                    }
                }
                Text { anchors.centerIn: parent; visible: list.count===0; text: "没有匹配的联系人"; color: Theme.muted }
            }
        }
        RowLayout { Layout.fillWidth: true
            Text { text: dialog.filtered.length+" 位 · 已选 "+(dialog.allContacts ? dialog.contacts.length : dialog.selectedIds.length)+" 位"; color: Theme.muted; font.pixelSize: 12 }
            GlassButton { text: "清空选择"; onClicked: {dialog.allContacts=false;dialog.selectedIds=dialog.level===2 && dialog.selfIdentity ? [dialog.selfIdentity] : []} }
            Item { Layout.fillWidth: true }
            GlassButton { text: "上一页"; enabled: dialog.pageIndex>0; onClicked: {dialog.pageIndex--;list.positionViewAtBeginning()} }
            Text { text: (dialog.pageIndex+1)+" / "+Math.max(1,Math.ceil(dialog.filtered.length/30)); color: Theme.muted }
            GlassButton { text: "下一页"; enabled: (dialog.pageIndex+1)*30<dialog.filtered.length; onClicked: {dialog.pageIndex++;list.positionViewAtBeginning()} }
        }
        Check { visible: dialog.level>0; text: "强制覆盖已有输入（会清空未发送的草稿）"; checked: dialog.overwriteDrafts; onToggled: dialog.overwriteDrafts=checked }
        Text { Layout.fillWidth: true; visible: dialog.activeScope; text: "变更将停止旧授权，再由本机确认；取消后保持停止。"; color: Theme.warning; font.pixelSize: 12; wrapMode: Text.WordWrap }
        RowLayout { Layout.fillWidth: true
            GlassButton { visible: dialog.activeScope; text: "停止并撤权"; onClicked: {dialog.close();dialog.stopped()} }
            Item { Layout.fillWidth: true }
            GlassButton { text: "取消"; onClicked: dialog.close() }
            GlassButton { objectName: "applyScope"; primary: true; text: "核对并认证"; enabled: dialog.fullReady && (dialog.allContacts || dialog.selectedIds.length>=1); onClicked: {dialog.close();dialog.applyRequested(dialog.allContacts ? ["*"] : dialog.selectedIds,dialog.minutes,dialog.replies,dialog.level,dialog.level>0 && dialog.overwriteDrafts,dialog.sendPolicy,15)} }
        }
    }
}
