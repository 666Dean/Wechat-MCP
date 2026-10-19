import QtQuick
import QtQuick.Controls
import "."

ToolTip {
    id: tip
    delay: 550; timeout: 6000; padding: 11; margins: 8
    implicitWidth: Math.min(350,implicitContentWidth+leftPadding+rightPadding)
    background: GlassPanel { radius: 12 }
    contentItem: Text { text: tip.text; textFormat: Text.PlainText; color: Theme.ink; font.pixelSize: 12; wrapMode: Text.WordWrap }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motionEnabled ? 100 : 0 } }
}
