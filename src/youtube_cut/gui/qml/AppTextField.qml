import QtQuick
import QtQuick.Controls.Basic
import "."

TextField {
    id: control
    property string iconName

    implicitHeight: 44
    leftPadding: iconName !== "" ? 42 : 14
    rightPadding: 14
    color: Theme.text
    placeholderTextColor: Theme.textFaint
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    font.pixelSize: 14
    hoverEnabled: true

    background: Rectangle {
        radius: Theme.radiusSmall
        color: Theme.field
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accent : control.hovered ? Theme.borderStrong : Theme.border
        Behavior on border.color { ColorAnimation { duration: Theme.animFast } }

        Icon {
            name: control.iconName
            visible: control.iconName !== ""
            x: 14
            anchors.verticalCenter: parent.verticalCenter
            color: control.activeFocus ? Theme.accent : Theme.textMuted
        }
    }
}
