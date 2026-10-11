import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Rectangle {
    id: root
    required property int index
    required property string videoId
    required property string title
    required property string status
    required property int matchCount
    required property string subtitle
    required property string error
    required property string durationText
    required property string dateText
    required property string thumbnail
    required property bool isLocal
    property bool selected: false
    signal clicked()

    width: ListView.view ? ListView.view.width : 300
    height: 74
    radius: Theme.radiusSmall
    color: selected ? Theme.tint(Theme.accent, Theme.dark ? 0.14 : 0.10)
         : hover.hovered ? Theme.hover : "transparent"
    border.width: selected ? 1 : 0
    border.color: Theme.tint(Theme.accent, 0.45)
    Behavior on color { ColorAnimation { duration: Theme.animFast } }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: root.clicked() }
    ToolTip.visible: hover.hovered && (root.error !== "" || root.subtitle !== "")
    ToolTip.text: root.error !== "" ? root.error : "Legenda: " + root.subtitle
    ToolTip.delay: 700

    RowLayout {
        anchors { fill: parent; margins: 8 }
        spacing: 10

        Rectangle {
            Layout.preferredWidth: 96
            Layout.preferredHeight: 54
            radius: 7
            color: Theme.hover
            clip: true

            Image {
                id: thumb
                anchors.fill: parent
                source: root.thumbnail
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                opacity: status === Image.Ready ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.anim } }
            }
            Icon {
                anchors.centerIn: parent
                visible: thumb.status !== Image.Ready
                name: root.isLocal ? "file" : "video"
                color: Theme.textFaint
            }
            Rectangle {
                visible: root.durationText !== ""
                anchors { right: parent.right; bottom: parent.bottom; margins: 4 }
                width: dur.implicitWidth + 8
                height: 16
                radius: 4
                color: Qt.rgba(0, 0, 0, 0.72)
                Text {
                    id: dur
                    anchors.centerIn: parent
                    text: root.durationText
                    color: "white"
                    font.family: Theme.mono
                    font.pixelSize: 10
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 5

            Text {
                Layout.fillWidth: true
                text: root.title
                color: Theme.text
                font.pixelSize: 13
                font.weight: Font.Medium
                elide: Text.ElideRight
                maximumLineCount: 2
                wrapMode: Text.Wrap
            }
            RowLayout {
                spacing: 8
                BusyDots { visible: root.status === "scanning" }
                Text {
                    visible: root.status === "scanning" || root.status === "pending" || (root.status === "done" && root.matchCount === 0)
                    text: root.status === "scanning" ? "Lendo legenda…" : root.status === "pending" ? "Na fila" : "Nenhuma menção"
                    color: root.status === "scanning" ? Theme.accent : Theme.textFaint
                    font.pixelSize: 11
                }
                Chip {
                    visible: root.status === "done" && root.matchCount > 0
                    text: root.matchCount === 1 ? "1 menção" : root.matchCount + " menções"
                    tone: Theme.accent
                    iconName: "sparkles"
                }
                Chip { visible: root.status === "nosubs"; text: "Sem legenda"; tone: Theme.warning; iconName: "captions" }
                Chip { visible: root.status === "error"; text: "Erro"; tone: Theme.danger; iconName: "alert" }
                Text { text: root.dateText; color: Theme.textFaint; font.pixelSize: 11; visible: text !== "" }
            }
        }
    }
}
