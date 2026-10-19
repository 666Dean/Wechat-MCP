import QtQuick
import QtQuick.Controls
import "."

Button {
    id: control
    property bool primary: false
    Keys.onReturnPressed: control.clicked()
    Keys.onEnterPressed: control.clicked()
    implicitHeight: 35; leftPadding: 13; rightPadding: 13
    background: Rectangle { radius: 10; color: control.primary ? Theme.brand : control.hovered ? Theme.hover : "transparent"; border.color: control.activeFocus ? Theme.focusBorder : control.primary ? "transparent" : Theme.border; border.width: control.activeFocus ? 2 : 1; opacity: control.enabled ? 1 : .45 }
    contentItem: Text { text: control.text; textFormat: Text.PlainText; font.pixelSize: 13; color: !control.enabled ? Theme.muted : control.primary ? "white" : Theme.ink; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    Accessible.name: text
}
