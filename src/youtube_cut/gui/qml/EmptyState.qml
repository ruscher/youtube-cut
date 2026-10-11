import QtQuick
import QtQuick.Layouts
import "."

ColumnLayout {
    id: root
    property string iconName: "scissors"
    property string title
    property string message
    property bool busy: false
    default property alias extra: extraRow.data

    spacing: 10

    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        width: 64; height: 64; radius: 20
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.tint(Theme.accent, 0.22) }
            GradientStop { position: 1; color: Theme.tint(Theme.accent2, 0.22) }
        }
        border.width: 1
        border.color: Theme.border
        Icon { anchors.centerIn: parent; name: root.iconName; size: 28; color: Theme.accent; visible: !root.busy }
        BusyDots { anchors.centerIn: parent; visible: root.busy }
    }
    Text {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 6
        text: root.title
        color: Theme.text
        font.pixelSize: 17
        font.weight: Font.DemiBold
    }
    Text {
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: 460
        text: root.message
        visible: text !== ""
        color: Theme.textMuted
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
        lineHeight: 1.25
    }
    Row {
        id: extraRow
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: 6
        spacing: 8
    }
}
