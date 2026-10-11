import QtQuick
import QtQuick.Controls.Basic
import "."

Rectangle {
    id: root
    property string text
    property string iconName
    property color tone: Theme.textMuted
    property string tip

    implicitHeight: 22
    implicitWidth: row.implicitWidth + 16
    radius: height / 2
    color: Theme.tint(tone, Theme.dark ? 0.15 : 0.12)

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 4
        Icon { name: root.iconName; visible: root.iconName !== ""; size: 12; color: root.tone; anchors.verticalCenter: parent.verticalCenter }
        Text {
            text: root.text
            color: root.tone
            font.pixelSize: 11
            font.weight: Font.DemiBold
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    HoverHandler { id: hover; enabled: root.tip !== "" }
    ToolTip.visible: hover.hovered
    ToolTip.text: root.tip
    ToolTip.delay: 400
}
