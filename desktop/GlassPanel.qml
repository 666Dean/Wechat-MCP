import QtQuick
import QtQuick.Effects
import "."

Item {
    id: panel
    property real radius: 16
    property bool frosted: true
    property color tint: Theme.dark ? "#E52B332E" : "#EFFFFFFF"
    // Only floating surfaces sample the content below the overlay. Never sample
    // an ancestor containing this item: that would create a render feedback loop.
    property point origin: Qt.point(0,0)
    function sampleOrigin(){if(Theme.glassSource)origin=mapToItem(Theme.glassSource,0,0)}
    onVisibleChanged: if(visible)Qt.callLater(sampleOrigin)
    onParentChanged: Qt.callLater(sampleOrigin)
    onWidthChanged: Qt.callLater(sampleOrigin)
    onHeightChanged: Qt.callLater(sampleOrigin)
    Component.onCompleted: Qt.callLater(sampleOrigin)
    Connections { target: panel.parent
        function onXChanged(){panel.sampleOrigin()}
        function onYChanged(){panel.sampleOrigin()}
    }
    ShaderEffectSource {
        id: sample
        anchors.fill: parent
        sourceItem: panel.frosted && panel.visible ? Theme.glassSource : null
        sourceRect: Qt.rect(panel.origin.x,panel.origin.y,panel.width,panel.height)
        visible: false
        live: panel.visible
    }
    Rectangle { id: mask; anchors.fill: parent; radius: panel.radius; color: "white"; visible: false; layer.enabled: true }
    MultiEffect {
        anchors.fill: parent; source: sample; visible: panel.frosted && !!Theme.glassSource
        blurEnabled: true; blurMax: 20; blur: .65; autoPaddingEnabled: false
        maskEnabled: true; maskSource: mask
    }
    Rectangle { anchors.fill: parent; radius: panel.radius; color: panel.tint; border.color: Theme.dark ? "#60718465" : "#C7D6DDD7"
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "#12000000"; shadowBlur: .4; shadowVerticalOffset: 3 }
    }
}
