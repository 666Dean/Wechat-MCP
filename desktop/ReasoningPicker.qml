import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ToolButton {
    id: picker
    property var models: [{id:"",title:"沿用对话模型",efforts:[]}]
    property string modelId: ""
    property var selectedModel: models.find(function(m){return m.id===picker.modelId}) || models[0]
    property var efforts: selectedModel.efforts || []
    property string value: ""
    property bool choosingModel: false
    function label(e){return ({none:"无推理",minimal:"最低",low:"低",medium:"中",high:"高",xhigh:"极高",max:"最高",ultra:"超高"})[e] || e}
    property string selectedLabel: label(value || selectedModel.default_effort || "") || "沿用对话强度"
    property string summary: modelId ? selectedModel.title+" · "+selectedLabel : "模型与强度"
    function choose(model){modelId=model.id;value="";choosingModel=false;Qt.callLater(function(){modelButton.forceActiveFocus()})}
    objectName: "reasoningSelector"; implicitHeight: 32; implicitWidth: Math.min(222,Math.max(132,summaryMetrics.advanceWidth+36)); leftPadding: 12; rightPadding: 10; topPadding: 0; bottomPadding: 0; Accessible.name: summary
    TextMetrics { id: summaryMetrics; text: picker.summary; font.pixelSize: 12 }
    onClicked: {choosingModel=false;sheet.open()}
    background: Rectangle { radius: 16; color: picker.hovered || sheet.visible ? Theme.hover : Theme.tint; border.color: picker.activeFocus ? Theme.focusBorder : "transparent" }
    contentItem: RowLayout { spacing: 6
        Text { Layout.fillWidth: true; Layout.fillHeight: true; verticalAlignment: Text.AlignVCenter; text: picker.summary; textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
        Icon { name: "chevronDown"; Layout.preferredWidth: 12; Layout.preferredHeight: 12; Layout.alignment: Qt.AlignVCenter; ink: Theme.muted }
    }
    AnchoredPopup { id: sheet; objectName: "reasoningPopup"; anchorItem: picker; preferAbove: true; preferredWidth: 264; padding: 12
        background: GlassPanel { radius: 21 }
        contentItem: ColumnLayout { spacing: 6
            RowLayout { visible: !picker.choosingModel; Layout.fillWidth: true; Layout.preferredHeight: 28
                Icon { name: "sparkle"; Layout.preferredWidth: 22; Layout.preferredHeight: 17; Layout.alignment: Qt.AlignVCenter; ink: Theme.muted }
                Text { Layout.fillWidth: true; Layout.fillHeight: true; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; text: picker.selectedLabel; color: Theme.positive; font.pixelSize: 16; font.weight: Font.DemiBold }
                ToolButton { implicitWidth: 22; implicitHeight: 24; padding: 4; Accessible.name: "恢复默认强度"; onClicked: picker.value=""
                    background: Rectangle { radius: 8; color: parent.hovered ? Theme.hover : "transparent" }
                    contentItem: Icon { name: "refresh"; ink: Theme.muted }
                }
            }
            ToolButton { id: modelButton; objectName: "modelSelector"; visible: !picker.choosingModel; Layout.fillWidth: true; implicitHeight: 28; Accessible.name: "选择模型："+picker.selectedModel.title
                onClicked: {picker.choosingModel=true;Qt.callLater(function(){modelList.forceActiveFocus()})}
                background: Rectangle { radius: 9; color: modelButton.hovered ? Theme.hover : "transparent"; border.color: modelButton.activeFocus ? Theme.focusBorder : "transparent" }
                padding: 0
                contentItem: Item {
                    RowLayout { anchors.centerIn: parent; width: Math.min(parent.width,implicitWidth); spacing: 6
                        Text { Layout.maximumWidth: 190; Layout.fillWidth: true; text: picker.selectedModel.title; textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.muted; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                        Icon { name: "chevronDown"; rotation: -90; Layout.preferredWidth: 11; Layout.preferredHeight: 11; Layout.alignment: Qt.AlignVCenter; ink: Theme.muted }
                    }
                }
            }
            Slider { id: slider; objectName: "reasoningSlider"; Layout.fillWidth: true; Layout.preferredHeight: 34; visible: !picker.choosingModel && picker.efforts.length>0; enabled: picker.efforts.length>1
                from: 0; to: Math.max(1,picker.efforts.length-1); stepSize: 1; snapMode: Slider.SnapAlways
                value: Math.max(0,picker.efforts.indexOf(picker.value || picker.selectedModel.default_effort))
                onMoved: picker.value=picker.efforts[Math.round(value)]
                Accessible.name: "思考强度档位"
                background: Rectangle { x: slider.leftPadding; y: (slider.height-height)/2; width: slider.availableWidth; height: 24; radius: 12; color: Theme.hover
                    Rectangle { width: slider.handle.width/2+slider.visualPosition*(parent.width-slider.handle.width); height: parent.height; radius: 12; color: Theme.brand }
                    Repeater { model: picker.efforts.length
                        Rectangle { required property int index; x: slider.handle.width/2+index*(parent.width-slider.handle.width)/Math.max(1,picker.efforts.length-1)-2; anchors.verticalCenter: parent.verticalCenter; width: 4; height: 4; radius: 2; color: index<=slider.value ? "#90FFFFFF" : Theme.muted }
                    }
                }
                handle: Rectangle { x: slider.leftPadding+slider.visualPosition*(slider.availableWidth-width); y: (slider.height-height)/2; width: 28; height: 28; radius: 14; color: "white"; border.color: slider.activeFocus ? Theme.focusBorder : Theme.border; border.width: slider.activeFocus ? 2 : 1 }
            }
            Text { Layout.fillWidth: true; visible: !picker.choosingModel && !picker.efforts.length; text: "选择模型后调整思考强度"; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; font.pixelSize: 11 }
            RowLayout { visible: picker.choosingModel; Layout.fillWidth: true
                ToolButton { implicitWidth: 24; implicitHeight: 28; Accessible.name: "返回思考强度"; onClicked: picker.choosingModel=false; contentItem: Icon { name: "chevronDown"; rotation: 90; ink: Theme.muted } }
                Text { Layout.fillWidth: true; text: "选择模型"; color: Theme.muted; font.pixelSize: 12 }
            }
            ListView { id: modelList; objectName: "modelChoiceList"; visible: picker.choosingModel; Layout.fillWidth: true
                // Do not size a virtualized view from delegates it needs height to create.
                readonly property real rowsHeight: Math.max(0,picker.models.length*40-2)
                Layout.preferredHeight: Math.min(300,rowsHeight); implicitHeight: visible ? Math.min(300,rowsHeight) : 0
                clip: true; model: picker.models; spacing: 2; currentIndex: Math.max(0,picker.models.findIndex(function(m){return m.id===picker.modelId})); keyNavigationWraps: true
                Keys.onReturnPressed: picker.choose(picker.models[currentIndex])
                Keys.onEnterPressed: picker.choose(picker.models[currentIndex])
                Keys.onEscapePressed: {picker.choosingModel=false;modelButton.forceActiveFocus()}
                ScrollIndicator.vertical: ScrollIndicator {}
                delegate: ItemDelegate { id: option; required property var modelData; required property int index; objectName: "modelOption"+index; width: modelList.width; height: 38; padding: 0
                    onClicked: picker.choose(modelData)
                    background: Rectangle { radius: 10; color: option.hovered || modelList.activeFocus && modelList.currentIndex===index ? Theme.hover : picker.modelId===modelData.id ? Theme.tint : "transparent" }
                    contentItem: Item {
                        Text { objectName: "modelOptionText"+option.index; anchors.left: parent.left; anchors.leftMargin: 12; anchors.right: selected.left; anchors.rightMargin: 10; height: parent.height; verticalAlignment: Text.AlignVCenter; text: modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight; color: Theme.ink; font.pixelSize: 13; font.weight: picker.modelId===modelData.id ? Font.Medium : Font.Normal }
                        Icon { id: selected; objectName: "modelOptionTick"+option.index; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "tick"; ink: Theme.positive; width: 15; height: 15; opacity: picker.modelId===modelData.id ? 1 : 0 }
                    }
                }
            }
        }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionEnabled ? 100 : 0 } }
    }
}
