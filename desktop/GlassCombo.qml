import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ComboBox {
    id: control
    property bool opensAbove: false
    property bool quiet: false
    property int menuWidth: 240
    TextMetrics { id: metrics; font: control.font; text: control.displayText }
    implicitHeight: 34; implicitWidth: Math.min(260,Math.max(100,metrics.advanceWidth+44))
    leftPadding: 12; rightPadding: 30; font.pixelSize: 13
    indicator: Icon { name: "chevronDown"; width: 13; height: 13; x: control.width-22; y: (control.height-height)/2; ink: Theme.muted }
    background: Rectangle {
        radius: 11; color: control.hovered || control.popup.visible ? Theme.hover : control.quiet ? "transparent" : Theme.tint
        border.color: control.activeFocus ? Theme.focusBorder : control.quiet ? "transparent" : Theme.border
    }
    contentItem: Text { text: control.displayText; textFormat: Text.PlainText; color: control.enabled ? Theme.ink : Theme.muted; font: control.font; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
    delegate: ItemDelegate {
        id: row
        required property int index
        width: control.popup.width-16; height: 39
        highlighted: control.highlightedIndex===index
        background: Rectangle { radius: 10; color: row.highlighted || row.hovered ? Theme.hover : "transparent" }
        contentItem: RowLayout { spacing: 12
            Text { Layout.fillWidth: true; text: control.textAt(row.index); textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: 13; elide: Text.ElideRight; font.weight: control.currentIndex===row.index ? Font.Medium : Font.Normal }
            Icon { name: "tick"; width: 16; height: 16; ink: Theme.positive; opacity: control.currentIndex===row.index ? 1 : 0 }
        }
    }
    popup: AnchoredPopup {
        id: choicePopup
        objectName: "glassChoicePopup"
        anchorItem: control; preferAbove: control.opensAbove
        preferredWidth: Math.max(control.menuWidth,control.width)
        implicitHeight: Math.min(350,control.count*41+14)
        background: GlassPanel { radius: 17 }
        contentItem: ListView { implicitHeight: Math.max(0,control.count*41-2); model: control.popup.visible ? control.delegateModel : null; clip: true; currentIndex: control.highlightedIndex; spacing: 2; ScrollIndicator.vertical: ScrollIndicator {} }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionEnabled ? 110 : 0 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.motionEnabled ? 80 : 0 } }
    }
}
