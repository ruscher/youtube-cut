import QtQuick
import QtQuick.Controls.Basic
import "."

Button {
    id: control
    property string variant: "secondary"   // primary | secondary | ghost | danger
    property string iconName
    property bool compact: false
    property string tip

    readonly property color fg: variant === "primary" ? Theme.accentText
                              : variant === "danger" ? Theme.danger : Theme.text

    implicitHeight: compact ? 32 : 40
    implicitWidth: text !== "" ? implicitContentWidth + leftPadding + rightPadding : implicitHeight
    leftPadding: text !== "" ? (compact ? 12 : 16) : 0
    rightPadding: leftPadding
    hoverEnabled: true
    font.pixelSize: compact ? 13 : 14
    font.weight: Font.DemiBold
    scale: pressed ? 0.97 : 1
    opacity: enabled ? 1 : 0.42

    Behavior on scale { NumberAnimation { duration: Theme.animFast; easing.type: Easing.Bezier; easing.bezierCurve: Theme.curve } }
    Behavior on opacity { NumberAnimation { duration: Theme.anim } }

    ToolTip.visible: hovered && tip !== ""
    ToolTip.text: tip
    ToolTip.delay: 500

    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8
            Icon {
                name: control.iconName
                visible: name !== ""
                color: control.fg
                size: control.compact ? 15 : 17
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: control.text
                visible: text !== ""
                color: control.fg
                font: control.font
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.variant === "primary" ? "transparent"
             : control.variant === "danger" ? Theme.tint(Theme.danger, 0.14)
             : control.variant === "secondary" ? Theme.field : "transparent"
        gradient: control.variant === "primary" ? accentGradient : null
        border.width: control.variant === "secondary" ? 1 : 0
        border.color: control.hovered ? Theme.borderStrong : Theme.border

        property Gradient accentGradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.accent }
            GradientStop { position: 1; color: Theme.accent2 }
        }

        Rectangle {   // camada de hover/pressão
            anchors.fill: parent
            radius: parent.radius
            color: control.variant === "primary" ? "white" : Theme.text
            opacity: control.pressed ? 0.14 : control.hovered ? 0.07 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.animFast } }
        }
        Rectangle {   // anel de foco do teclado
            anchors { fill: parent; margins: -3 }
            radius: parent.radius + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.accent
            visible: control.visualFocus
        }
    }
}
