import QtQuick
import "."

Rectangle {
    radius: Theme.radius
    color: Theme.surface
    border.width: 1
    border.color: Theme.border

    // brilho sutil na borda superior, como vidro
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 1 }
        height: Math.min(parent.height / 2, 40)
        radius: parent.radius
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.045 : 0.5) }
            GradientStop { position: 1; color: "transparent" }
        }
    }
}
