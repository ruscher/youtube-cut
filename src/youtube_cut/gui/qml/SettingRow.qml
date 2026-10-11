import QtQuick
import QtQuick.Layouts
import "."

ColumnLayout {
    id: root
    property string label
    property string description
    default property alias control: slot.data

    Layout.fillWidth: true
    spacing: 6

    RowLayout {
        Layout.fillWidth: true
        spacing: 12
        Text {
            Layout.fillWidth: true
            text: root.label
            color: Theme.text
            font.pixelSize: 13
            font.weight: Font.Medium
            wrapMode: Text.WordWrap
        }
        Row { id: slot; spacing: 8 }
    }
    Text {
        Layout.fillWidth: true
        text: root.description
        visible: text !== ""
        color: Theme.textFaint
        font.pixelSize: 12
        wrapMode: Text.WordWrap
        lineHeight: 1.2
    }
}
