import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "."

Rectangle {
    id: root
    required property int index
    required property string videoTitle
    required property string startText
    required property string endText
    required property string durationText
    required property string contextHtml
    required property string term
    required property int mentions
    required property real score
    required property bool checked
    required property string cutState
    required property real progress
    required property string output
    required property string message
    required property string link
    required property string dateText
    required property string kind  // speech | face | mixed
    required property real faceScore
    property bool showVideo: true

    width: ListView.view ? ListView.view.width : 600
    implicitHeight: content.implicitHeight + 28
    radius: Theme.radius
    color: hover.hovered ? Qt.lighter(Theme.surface, Theme.dark ? 1.25 : 1.0) : Theme.surface
    border.width: 1
    border.color: root.cutState === "done" ? Theme.tint(Theme.success, 0.45)
                : root.cutState === "error" ? Theme.tint(Theme.danger, 0.5)
                : hover.hovered ? Theme.borderStrong : Theme.border
    Behavior on border.color { ColorAnimation { duration: Theme.animFast } }
    opacity: root.checked || root.cutState === "done" ? 1 : 0.62
    Behavior on opacity { NumberAnimation { duration: Theme.anim } }

    HoverHandler { id: hover }

    RowLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
        spacing: 12

        AppCheck {
            Layout.alignment: Qt.AlignTop
            checked: root.checked
            onToggled: backend.setClipChecked(root.index, checked)
            Accessible.name: "Incluir trecho " + root.startText
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Rectangle {   // código de tempo: clicar abre o YouTube no segundo exato
                    implicitWidth: timeRow.implicitWidth + 16
                    implicitHeight: 26
                    radius: 8
                    color: timeHover.hovered ? Theme.tint(Theme.accent, 0.24) : Theme.tint(Theme.accent, 0.13)
                    Row {
                        id: timeRow
                        anchors.centerIn: parent
                        spacing: 6
                        Icon { name: "play"; size: 11; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: root.startText + "  →  " + root.endText
                            color: Theme.accent
                            font.family: Theme.mono
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    HoverHandler { id: timeHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: backend.openUrl(root.link) }
                    ToolTip.visible: timeHover.hovered
                    ToolTip.text: "Assistir neste momento"
                    ToolTip.delay: 400
                }
                Chip { text: root.durationText; iconName: "clock" }
                Chip { visible: root.mentions > 1; text: root.mentions + " menções juntas"; tone: Theme.accent2 }
                Chip {
                    visible: root.kind !== "speech"
                    text: "Rosto · " + Math.round(root.faceScore * 100) + "%"
                    iconName: "scan-face"
                    tone: Theme.accent2
                    tip: root.kind === "mixed"
                         ? "O nome é dito enquanto a pessoa aparece. Similaridade com a foto de referência."
                         : "Trecho em que a pessoa aparece. Similaridade com a foto de referência."
                }
                Chip {
                    visible: root.score < 1
                    text: "≈ " + Math.round(root.score * 100) + "%"
                    tone: Theme.warning
                    tip: "Correspondência aproximada: a transcrição escreveu diferente"
                }
                Item { Layout.fillWidth: true }

                Text { visible: root.cutState === "queued"; text: "Na fila"; color: Theme.textFaint; font.pixelSize: 12 }
                Text {
                    visible: root.cutState === "cutting"
                    text: root.progress >= 0 ? Math.round(root.progress * 100) + "%" : "Baixando…"
                    color: Theme.accent
                    font.family: Theme.mono
                    font.pixelSize: 12
                }
                Chip { visible: root.cutState === "done"; text: "Salvo"; tone: Theme.success; iconName: "check" }
                Chip { visible: root.cutState === "error"; text: "Falhou"; tone: Theme.danger; iconName: "alert"; tip: root.message }
            }

            Text {
                Layout.fillWidth: true
                textFormat: Text.StyledText
                // reticências indicam trecho de fala; o rosto é descrito por inteiro
                readonly property string dots: root.kind === "face" ? "" : "…"
                text: dots + root.contextHtml.replace("<b>", "<b><font color=\"" + Theme.accent + "\">")
                                             .replace("</b>", "</font></b>") + dots
                color: Theme.textMuted
                font.pixelSize: 14
                wrapMode: Text.WordWrap
                lineHeight: 1.25
            }

            Text {
                Layout.fillWidth: true
                visible: root.showVideo
                text: root.videoTitle + (root.dateText ? "  ·  " + root.dateText : "")
                color: Theme.textFaint
                font.pixelSize: 11
                elide: Text.ElideRight
            }

            ProgressGlow {
                Layout.fillWidth: true
                visible: root.cutState === "cutting"
                value: root.progress
            }
        }

        Row {
            Layout.alignment: Qt.AlignTop
            spacing: 2
            AppButton {
                visible: root.cutState === "done"
                variant: "ghost"; compact: true; iconName: "folder"
                tip: "Mostrar arquivo"
                onClicked: backend.revealFile(root.output)
            }
            AppButton {
                visible: root.cutState === "done"
                variant: "ghost"; compact: true; iconName: "play"
                tip: "Reproduzir o corte"
                onClicked: backend.openUrl(root.output)
            }
            AppButton {
                variant: "ghost"; compact: true; iconName: "external"
                tip: "Abrir no YouTube neste momento"
                onClicked: backend.openUrl(root.link)
            }
        }
    }
}
