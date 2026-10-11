import QtQuick
import "."

Row {
    id: root
    property color color: Theme.accent
    property bool running: true
    spacing: 3

    Repeater {
        model: 3
        Rectangle {
            id: dot
            required property int index
            width: 6; height: 6; radius: 3
            color: root.color
            opacity: 0.25
            SequentialAnimation on opacity {
                running: root.running && root.visible
                loops: Animation.Infinite
                PauseAnimation { duration: dot.index * 140 }
                NumberAnimation { to: 1; duration: 320; easing.type: Easing.OutQuad }
                NumberAnimation { to: 0.25; duration: 320; easing.type: Easing.InQuad }
                PauseAnimation { duration: (2 - dot.index) * 140 }
            }
        }
    }
}
