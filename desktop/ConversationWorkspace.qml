import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: workspace
    required property var controller
    property bool connected: false
    property int accessLevel: 0
    property string accessSummary: "尚未授权微信访问"
    property var conversations: controller.data.owner_messages || []
    property var modelChoices: [{id:"",title:"沿用对话模型",efforts:[]}].concat(controller.codexModels || [])
    property bool waiting: conversations.some(function(c){return c.state==="AwaitingAgent" || c.state==="HandedOff"})
    signal permissionsRequested(int level)
    signal openProject(int page)
    function submit(){var value=composer.text.trim();if(value && connected && !controller.data.chat_submitting)controller.submitChat(value,effortChoice.modelId,effortChoice.value)}
    Connections { target: workspace.controller; function onChatAccepted(text){if(composer.text.trim()===text)composer.clear()} }
    function syncMessages(){
        var follow=transcript.followTail || threadModel.count===0
        var ids=conversations.map(function(m){return m.id})
        for(var i=threadModel.count-1;i>=0;i--)if(ids.indexOf(threadModel.get(i).jobId)<0)threadModel.remove(i)
        for(var j=0;j<conversations.length;j++){
            var row=conversations[j],at=-1
            for(var k=0;k<threadModel.count;k++)if(threadModel.get(k).jobId===row.id){at=k;break}
            var value={jobId:row.id,prompt:row.prompt || "",answer:row.answer || "",jobState:row.state || "",channel:row.channel || "desktop"}
            if(at<0)threadModel.append(value);else threadModel.set(at,value)
        }
        if(follow)Qt.callLater(function(){transcript.positionViewAtEnd()})
    }
    onConversationsChanged: syncMessages()
    Component.onCompleted: syncMessages()
    ListModel { id: threadModel }
    component Choice: GlassCombo { opensAbove: true; quiet: true }
    ColumnLayout { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.bottom: parent.bottom; width: Math.min(860,parent.width); spacing: 14
        ListView { id: transcript; objectName: "conversationTranscript"; Layout.fillWidth: true; Layout.fillHeight: true; model: threadModel; clip: true; spacing: 28; topMargin: 12; bottomMargin: 24
            property bool followTail: true
            onMovementEnded: followTail=atYEnd
            onContentHeightChanged: if(followTail)Qt.callLater(function(){transcript.positionViewAtEnd()})
            ScrollBar.vertical: ScrollBar {}
            add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionEnabled ? 180 : 0 } }
            delegate: ColumnLayout { required property string jobId; required property string prompt; required property string answer; required property string jobState; required property string channel
                width: transcript.width; spacing: 18
                Rectangle { objectName: "userMessageBubble"; Layout.alignment: Qt.AlignRight; Layout.preferredWidth: Math.min(transcript.width*.86,Math.max(150,userText.implicitWidth+32)); implicitHeight: userText.contentHeight+24; radius: 17; color: Theme.messageSurface
                    Text { id: userText; anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 12; leftPadding: 4; width: parent.width-28; text: prompt; textFormat: Text.PlainText; color: Theme.ink; wrapMode: Text.Wrap; font.pixelSize: 14 }
                }
                ColumnLayout { Layout.fillWidth: true; Layout.maximumWidth: 860; spacing: 10
                    RowLayout { spacing: 8
                        Icon { name: "sparkle"; ink: Theme.positive; width: 16; height: 16 }
                        Text { text: "Codex" + (channel==="self" ? " · 本人微信任务" : ""); font.weight: Font.DemiBold; color: Theme.positive; font.pixelSize: 12 }
                        Row { visible: jobState==="HandedOff" && !answer; spacing: 3
                            Repeater { model: 3
                                Rectangle { required property int index; width: 4; height: 4; radius: 2; color: Theme.muted; opacity: .45
                                    SequentialAnimation on opacity { loops: Animation.Infinite; running: visible && jobState==="HandedOff" && Theme.motionEnabled && Qt.application.state===Qt.ApplicationActive
                                        PauseAnimation { duration: index*120 }
                                        NumberAnimation { to: 1; duration: 240 }
                                        NumberAnimation { to: .3; duration: 360 }
                                        PauseAnimation { duration: (2-index)*120 }
                                    }
                                }
                            }
                        }
                    }
                    TextEdit { objectName: "assistantMessageBody"; Layout.fillWidth: true; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText
                        text: answer || ((controller.chatStreaming || {}).job_id===jobId && jobState==="HandedOff" ? (controller.chatStreaming || {}).text : "") || ({"AwaitingAgent":"等待当前任务结束…","HandedOff":"正在处理…","Queued":"等待返回微信…","Executing":"正在提交微信回复…","Unknown":"结果不确定，已停止且不会自动重做。请在 Codex 中核对。","FailedSafe":"任务已停止。"})[jobState] || ""
                        color: answer || jobState==="HandedOff" && (controller.chatStreaming || {}).text ? Theme.ink : Theme.muted; font.pixelSize: 14
                    }
                }
            }
            Item { anchors.fill: parent; visible: !threadModel.count
                ColumnLayout { anchors.centerIn: parent; width: Math.min(parent.width-60,600); spacing: 16
                    Rectangle { Layout.alignment: Qt.AlignHCenter; width: 48; height: 48; radius: 15; color: Theme.tint; Icon { anchors.centerIn: parent; name: "sparkle"; ink: Theme.positive; width: 26; height: 26 } }
                    Text { Layout.alignment: Qt.AlignHCenter; text: "有什么需要一起处理？"; color: Theme.ink; font.pixelSize: 26; font.weight: Font.Medium }
                    Text { Layout.fillWidth: true; text: "在这里下达任务，或通过本人微信私聊联系助理。\n访问范围由你决定，敏感操作会再次确认。"; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; font.pixelSize: 14; lineHeight: 1.5; wrapMode: Text.WordWrap }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: inputColumn.implicitHeight+24; radius: 20; color: Theme.surface; border.color: composer.activeFocus ? Theme.focusBorder : Theme.border
            Behavior on border.color { ColorAnimation { duration: Theme.motionEnabled ? 140 : 0 } }
            ColumnLayout { id: inputColumn; anchors.fill: parent; anchors.margins: 12; spacing: 6
                RowLayout { visible: !!(controller.composeAttachment || {}).name
                    Text { text: (controller.composeAttachment || {}).name || ""; color: Theme.ink; font.pixelSize: 12 }
                    ToolButton { text: "×"; onClicked: controller.removeComposeFile(); Accessible.name: "移除附件" }
                }
                ScrollView { Layout.fillWidth: true; Layout.preferredHeight: Math.min(150,Math.max(42,composer.contentHeight+6)); clip: true
                    TextArea { id: composer; objectName: "chatComposer"; placeholderText: "给助理发送任务…"; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; color: Theme.ink; placeholderTextColor: Theme.muted; background: null; selectByMouse: true
                        Accessible.name: "给助理发送任务"; Keys.onPressed: function(event){if((event.key===Qt.Key_Return || event.key===Qt.Key_Enter) && (event.modifiers & (Qt.ControlModifier | Qt.MetaModifier))){workspace.submit();event.accepted=true}}
                    }
                }
                RowLayout { Layout.fillWidth: true; spacing: 5
                    ToolButton { id: plus; text: "+"; font.pixelSize: 24; implicitWidth: 32; implicitHeight: 32; Accessible.name: "添加内容"; onClicked: addMenu.open()
                        Menu { id: addMenu; y: -height-8; padding: 6
                            background: GlassPanel { radius: 16 }
                            MenuItem { text: "添加文本参考资料…"; enabled: workspace.connected; onTriggered: controller.chooseComposeFile() }
                            MenuItem { text: "管理微信访问…"; onTriggered: workspace.permissionsRequested(workspace.accessLevel) }
                        }
                    }
                    Choice { id: permissionChoice; objectName: "quickAccessMenu"; model: ["仅生成草稿", "自动回复", "完全访问"]; currentIndex: workspace.accessLevel; implicitWidth: 135
                        contentItem: RowLayout { spacing: 6; Icon { name: "shield"; ink: workspace.accessLevel===2 ? Theme.warning : Theme.muted; width: 15; height: 15 } Text { Layout.fillWidth: true; text: permissionChoice.displayText; color: workspace.accessLevel===2 ? Theme.warning : Theme.ink; font.pixelSize: 12; elide: Text.ElideRight } }
                        Accessible.name: "微信访问权限"; onActivated: function(index){workspace.permissionsRequested(index);currentIndex=Qt.binding(function(){return workspace.accessLevel})}
                        GlassTip { visible: permissionChoice.hovered; text: workspace.accessSummary }
                    }
                    Item { Layout.fillWidth: true }
                    ReasoningPicker { id: effortChoice; models: workspace.modelChoices }
                    ToolButton { objectName: "stopChat"; visible: workspace.waiting; text: "■"; Accessible.name: "停止当前任务"; onClicked: controller.stopChat(); implicitWidth: 32; implicitHeight: 32 }
                    ToolButton { objectName: "chatSend"; enabled: workspace.connected && composer.text.trim().length>0 && !controller.data.chat_submitting; onClicked: workspace.submit(); Accessible.name: "发送任务"; implicitWidth: 34; implicitHeight: 34
                        scale: down ? .92 : 1; Behavior on scale { NumberAnimation { duration: Theme.motionEnabled ? 100 : 0 } }
                        background: Rectangle { radius: 17; color: parent.enabled ? Theme.ink : Theme.hover; Behavior on color { ColorAnimation { duration: Theme.motionEnabled ? 120 : 0 } } }
                        contentItem: Icon { name: "arrowUp"; ink: parent.enabled ? Theme.surface : Theme.muted; width: 18; height: 18 }
                    }
                }
            }
        }
        Item { Layout.preferredHeight: 8 }
    }
}
