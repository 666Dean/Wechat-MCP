pragma Singleton
import QtQuick
QtObject {
    property bool dark: false
    readonly property color canvas: dark ? "#141917" : "#F6F7F5"
    readonly property color surface: dark ? "#1D2420" : "#FFFFFF"
    readonly property color sidebar: dark ? "#181E1A" : "#FBFCFA"
    readonly property color border: dark ? "#313B35" : "#E4E8E4"
    readonly property color ink: dark ? "#E7EEE9" : "#1D302C"
    readonly property color muted: dark ? "#9EAEA4" : "#74817B"
    readonly property color brand: "#285C4D"
    readonly property color positive: dark ? "#91C8AD" : "#285C4D"
    readonly property color tint: dark ? "#25382D" : "#EFF5F0"
    readonly property color hover: dark ? "#29342D" : "#F0F3EF"
    readonly property color warning: dark ? "#D9B980" : "#8D6E35"
    readonly property color danger: dark ? "#DF9894" : "#A34843"
    readonly property int sidebarWidth: 238
    readonly property int margin: 32
    readonly property int gap: 20
    readonly property int radius: 13
    readonly property int controlRadius: 9
    readonly property int body: 14
    readonly property int caption: 12
    readonly property int heading: 28
    readonly property int section: 18
}
