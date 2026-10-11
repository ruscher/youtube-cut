import QtQuick
import QtQuick.Controls.Basic
import "."

CheckBox {
    id: control
    spacing: 8
    hoverEnabled: true
    font.pixelSize: 13

    indicator: Rectangle {
        implicitWidth: 20
        implicitHeight: 20
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 6
        color: control.checked ? "transparent" : Theme.field
        border.width: control.checked ? 0 : 1.5
        border.color: control.hovered ? Theme.accent : Theme.borderStrong
        gradient: control.checked ? checkedGradient : null
        property Gradient checkedGradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.accent }
            GradientStop { position: 1; color: Theme.accent2 }
        }
        Icon {
            anchors.centerIn: parent
            name: control.checkState === Qt.PartiallyChecked ? "minus" : "check"
            size: 14
            color: Theme.accentText
            visible: control.checkState !== Qt.Unchecked
        }
    }

    contentItem: Text {
        text: control.text
        visible: text !== ""
        leftPadding: control.indicator.width + control.spacing
        color: Theme.text
        font: control.font
        verticalAlignment: Text.AlignVCenter
    }
}
