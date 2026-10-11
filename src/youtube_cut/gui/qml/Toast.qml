import QtQuick
import QtQuick.Layouts
import "."

Rectangle {
    id: root
    property string kind: "info"
    property string action: ""
    property alias message: label.text
    signal actionTriggered(string action)

    readonly property color tone: kind === "error" ? Theme.danger : kind === "success" ? Theme.success : Theme.accent

    function show(text, k, act) {
        message = text
        kind = k || "info"
        action = act || ""
        opacity = 1
        hideTimer.restart()
    }

    anchors.horizontalCenter: parent.horizontalCenter
    y: parent.height - height - (opacity > 0 ? 96 : 72)
    width: Math.min(row.implicitWidth + 32, parent.width - 48)
    height: 48
    radius: 24
    color: Theme.surfaceStrong
    border.width: 1
    border.color: Theme.tint(tone, 0.45)
    opacity: 0
    visible: opacity > 0
    z: 100

    Behavior on opacity { NumberAnimation { duration: Theme.anim } }
    Behavior on y { NumberAnimation { duration: Theme.anim; easing.type: Easing.Bezier; easing.bezierCurve: Theme.curve } }

    Timer { id: hideTimer; interval: root.kind === "error" ? 7000 : 4500; onTriggered: root.opacity = 0 }
    HoverHandler { onHoveredChanged: hovered ? hideTimer.stop() : hideTimer.restart() }

    RowLayout {
        id: row
        anchors.centerIn: parent
        width: Math.min(implicitWidth, root.width - 32)
        spacing: 10
        Icon { name: root.kind === "error" ? "alert" : root.kind === "success" ? "check" : "sparkles"; color: root.tone; size: 18 }
        Text {
            id: label
            Layout.fillWidth: true
            color: Theme.text
            font.pixelSize: 13
            elide: Text.ElideRight
        }
        AppButton {
            visible: root.action === "open-folder"
            compact: true
            variant: "ghost"
            text: "Abrir pasta"
            iconName: "folder"
            onClicked: { root.actionTriggered(root.action); root.opacity = 0 }
        }
    }
}
