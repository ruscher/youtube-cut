import QtQuick
import "."

// Barra de progresso com gradiente; value < 0 = indeterminado (faixa deslizante).
Item {
    id: root
    property real value: 0
    property bool active: true
    readonly property bool indeterminate: value < 0

    implicitHeight: 4
    clip: true

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Theme.hover
    }

    Rectangle {
        id: bar
        height: parent.height
        radius: height / 2
        visible: root.active
        width: root.indeterminate ? root.width * 0.28 : root.width * Math.max(0, Math.min(1, root.value))
        x: 0
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.accent }
            GradientStop { position: 1; color: Theme.accent2 }
        }
        Behavior on width {
            enabled: !root.indeterminate
            NumberAnimation { duration: Theme.anim; easing.type: Easing.OutCubic }
        }

        NumberAnimation on x {
            running: root.indeterminate && root.active && root.visible
            loops: Animation.Infinite
            from: -root.width * 0.28
            to: root.width
            duration: 1300
            easing.type: Easing.InOutQuad
            onRunningChanged: if (!running) bar.x = 0
        }
    }
}
