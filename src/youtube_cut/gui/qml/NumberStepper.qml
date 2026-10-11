import QtQuick
import "."

Rectangle {
    id: root
    property real value: 0
    property real from: 0
    property real to: 100
    property real step: 1
    property string suffix: ""
    property string zeroText: ""   // texto alternativo para o valor 0 (ex.: "todos")
    signal edited(real value)

    function change(delta) {
        const v = Math.round(Math.max(from, Math.min(to, value + delta)) * 100) / 100
        if (v !== value) edited(v)
    }

    implicitWidth: 118
    implicitHeight: 34
    radius: Theme.radiusSmall
    color: Theme.field
    border.width: 1
    border.color: Theme.border

    Repeater {
        model: [{ sign: "−", delta: -1, left: true }, { sign: "+", delta: 1, left: false }]
        Rectangle {
            id: btn
            required property var modelData
            width: 30
            height: parent.height - 6
            anchors.verticalCenter: parent.verticalCenter
            x: modelData.left ? 3 : root.width - width - 3
            radius: Theme.radiusSmall - 3
            color: area.pressed ? Theme.tint(Theme.accent, 0.25) : area.containsMouse ? Theme.hover : "transparent"
            Text { anchors.centerIn: parent; text: btn.modelData.sign; color: Theme.text; font.pixelSize: 16 }
            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.change(btn.modelData.delta * root.step)
                pressAndHoldInterval: 350
                onPressAndHold: repeat.start()
                onReleased: repeat.stop()
                Timer { id: repeat; interval: 70; repeat: true; onTriggered: root.change(btn.modelData.delta * root.step) }
            }
        }
    }
    Text {
        anchors.centerIn: parent
        text: root.value === 0 && root.zeroText !== "" ? root.zeroText : root.value + root.suffix
        color: Theme.text
        font.family: Theme.mono
        font.pixelSize: 12
    }
    WheelHandler { onWheel: event => root.change((event.angleDelta.y > 0 ? 1 : -1) * root.step) }
}
