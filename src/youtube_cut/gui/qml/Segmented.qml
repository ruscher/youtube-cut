import QtQuick
import "."

// Controle segmentado: model = [{ value, label }]
Rectangle {
    id: root
    property var model: []
    property var current
    signal activated(var value)

    implicitHeight: 34
    implicitWidth: row.implicitWidth + 6
    radius: Theme.radiusSmall
    color: Theme.field
    border.width: 1
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2
        Repeater {
            model: root.model
            Rectangle {
                id: seg
                required property var modelData
                readonly property bool selected: String(root.current) === String(modelData.value)
                width: Math.max(46, label.implicitWidth + 20)
                height: root.height - 6
                radius: Theme.radiusSmall - 3
                color: selected ? Theme.tint(Theme.accent, Theme.dark ? 0.22 : 0.16)
                     : hover.hovered ? Theme.hover : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
                Text {
                    id: label
                    anchors.centerIn: parent
                    text: seg.modelData.label
                    color: seg.selected ? Theme.accent : Theme.textMuted
                    font.pixelSize: 12
                    font.weight: seg.selected ? Font.DemiBold : Font.Normal
                }
                HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.activated(seg.modelData.value) }
            }
        }
    }
}
