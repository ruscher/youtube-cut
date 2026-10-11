import QtQuick
import QtQuick.Controls.Basic
import "."

Switch {
    id: control
    hoverEnabled: true
    padding: 0
    implicitWidth: 40
    implicitHeight: 24
    indicator: Rectangle {
        implicitWidth: 40
        implicitHeight: 22
        radius: 11
        y: (control.height - height) / 2
        color: control.checked ? "transparent" : Theme.field
        border.width: control.checked ? 0 : 1
        border.color: control.hovered ? Theme.borderStrong : Theme.border
        gradient: control.checked ? onGradient : null
        property Gradient onGradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.accent }
            GradientStop { position: 1; color: Theme.accent2 }
        }
        Rectangle {
            width: 16; height: 16; radius: 8
            y: 3
            x: control.checked ? parent.width - width - 3 : 3
            color: control.checked ? "white" : Theme.textMuted
            Behavior on x { NumberAnimation { duration: Theme.anim; easing.type: Easing.Bezier; easing.bezierCurve: Theme.curve } }
        }
    }
    contentItem: Item {}
}
