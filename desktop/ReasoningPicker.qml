import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ToolButton {
    id: picker
    property var efforts: []
    property string modelTitle: "沿用对话模型"
    property string defaultEffort: ""
    property string value: ""
    function label(e){return ({none:"无推理",minimal:"最低",low:"低",medium:"中",high:"高",xhigh:"极高",max:"最高",ultra:"超高"})[e] || e}
    property string selectedLabel: value ? label(value) : defaultEffort ? label(defaultEffort)+" · 默认" : "默认强度"
    TextMetrics { id: labelMetrics; text: picker.selectedLabel; font.pixelSize: 12 }
    objectName: "reasoningSelector"; implicitHeight: 34; implicitWidth: Math.max(100,labelMetrics.advanceWidth+34); Accessible.name: "思考强度："+selectedLabel
    onClicked: sheet.open()
    background: Rectangle { radius: 11; color: picker.hovered || sheet.visible ? Theme.hover : "transparent"; border.color: picker.activeFocus ? Theme.focusBorder : "transparent" }
    contentItem: RowLayout { spacing: 6
        Text { Layout.fillWidth: true; text: picker.selectedLabel; color: Theme.ink; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter }
        Icon { name: "chevronDown"; width: 13; height: 13; ink: Theme.muted }
    }
    Popup { id: sheet; objectName: "reasoningPopup"; y: -implicitHeight-8; x: parent.width-width; width: 300; padding: 20
        implicitHeight: contentItem.implicitHeight+40
        background: GlassPanel { radius: 23 }
        contentItem: ColumnLayout { spacing: 12
            RowLayout { Layout.fillWidth: true
                Icon { name: "sparkle"; width: 18; height: 18; ink: Theme.muted }
                Text { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: picker.selectedLabel; color: Theme.positive; font.pixelSize: 19; font.weight: Font.Medium }
                ToolButton { implicitWidth: 26; implicitHeight: 26; Accessible.name: "恢复默认强度"; onClicked: picker.value=""; contentItem: Icon { name: "refresh"; ink: Theme.muted } }
            }
            Text { Layout.fillWidth: true; text: picker.modelTitle; textFormat: Text.PlainText; color: Theme.muted; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 12; elide: Text.ElideRight }
            Slider { id: slider; objectName: "reasoningSlider"; Layout.fillWidth: true; Layout.preferredHeight: 38; visible: picker.efforts.length>0; enabled: picker.efforts.length>1
                from: 0; to: Math.max(1,picker.efforts.length-1); stepSize: 1; snapMode: Slider.SnapAlways
                value: Math.max(0,picker.efforts.indexOf(picker.value || picker.defaultEffort))
                onMoved: picker.value=picker.efforts[Math.round(value)]
                Accessible.name: "思考强度档位"
                background: Rectangle { x: slider.leftPadding; y: (slider.height-height)/2; width: slider.availableWidth; height: 28; radius: 14; color: Theme.hover
                    Rectangle { width: Math.max(28,slider.visualPosition*parent.width); height: parent.height; radius: 14; color: Theme.brand }
                    Row { anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                        Repeater { model: picker.efforts.length
                            Item { required property int index; width: (slider.availableWidth-28)/Math.max(1,picker.efforts.length-1); height: 28
                                Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 4; height: 4; radius: 2; color: index<=slider.value ? "#90FFFFFF" : Theme.muted }
                            }
                        }
                    }
                }
                handle: Rectangle { x: slider.leftPadding+slider.visualPosition*(slider.availableWidth-width); y: (slider.height-height)/2; width: 32; height: 32; radius: 16; color: "white"; border.color: slider.activeFocus ? Theme.focusBorder : Theme.border; border.width: slider.activeFocus ? 2 : 1 }
            }
            Text { Layout.fillWidth: true; visible: !picker.efforts.length; text: "沿用此对话的强度。选择模型后可调整。"; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; font.pixelSize: 12 }
        }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionEnabled ? 120 : 0 } }
    }
}
