import QtQuick
import QtQuick.Controls

Popup {
    id: popup
    required property Item anchorItem
    property bool preferAbove: false
    property bool alignRight: true
    property real preferredWidth: 240
    property real edgeMargin: 12
    property point anchorPoint: Qt.point(0,0)
    readonly property real aboveRoom: Math.max(0,anchorPoint.y-edgeMargin-7)
    readonly property real belowRoom: Math.max(0,(parent ? parent.height : 800)-anchorPoint.y-anchorItem.height-edgeMargin-7)
    readonly property bool placedAbove: preferAbove ? aboveRoom>=implicitHeight || aboveRoom>belowRoom : belowRoom<implicitHeight && aboveRoom>belowRoom
    function updateAnchor(){if(parent && anchorItem)anchorPoint=anchorItem.mapToItem(parent,0,0)}
    parent: Overlay.overlay
    width: Math.min(preferredWidth,Math.max(0,(parent ? parent.width : preferredWidth+24)-edgeMargin*2))
    height: Math.min(popup.implicitHeight,placedAbove ? aboveRoom : belowRoom)
    implicitHeight: contentItem.implicitHeight+topPadding+bottomPadding
    x: Math.max(edgeMargin,Math.min(anchorPoint.x+(alignRight ? anchorItem.width-width : 0),(parent ? parent.width : width+24)-width-edgeMargin))
    y: placedAbove ? anchorPoint.y-height-7 : anchorPoint.y+anchorItem.height+7
    margins: edgeMargin; padding: 8; focus: true
    onAboutToShow: updateAnchor()
    onWidthChanged: if(visible)Qt.callLater(updateAnchor)
    Connections { target: popup.parent
        function onWidthChanged(){if(popup.visible)Qt.callLater(popup.updateAnchor)}
        function onHeightChanged(){if(popup.visible)Qt.callLater(popup.updateAnchor)}
    }
}
