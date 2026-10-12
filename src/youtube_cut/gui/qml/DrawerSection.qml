import QtQuick
import QtQuick.Layouts
import "."

// Grupo de opções com título em versalete e ícone, usado nos painéis laterais.
ColumnLayout {
    id: section
    property string title
    property string iconName
    default property alias rows: body.data

    Layout.fillWidth: true
    Layout.leftMargin: 20
    Layout.rightMargin: 20
    spacing: 14

    RowLayout {
        spacing: 8
        Icon { name: section.iconName; size: 16; color: Theme.accent }
        Text {
            text: section.title.toUpperCase()
            color: Theme.textMuted
            font.pixelSize: 11
            font.weight: Font.Bold
            font.letterSpacing: 1.2
        }
    }
    ColumnLayout { id: body; Layout.fillWidth: true; spacing: 18 }
}
