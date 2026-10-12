import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

// Painel "IA local": reconhecimento facial, legenda por Whisper e console de atividade.
// Tudo roda no computador do usuário; o painel só mostra estado e repassa escolhas ao backend.
Drawer {
    id: drawer
    readonly property var cfg: backend.config
    readonly property var ai: backend.aiStatus
    readonly property var face: backend.faceInfo
    // Medido: ~25 ms por quadro (decodificação + detecção + reconhecimento, CPU).
    readonly property real secondsPerFrame: 0.025

    edge: Qt.LeftEdge
    width: Math.min(460, parent.width * 0.92)
    height: parent.height
    padding: 0

    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, Theme.dark ? 0.45 : 0.25) }

    background: Rectangle {
        color: Theme.surfaceStrong
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.border }
    }

    FileDialog {
        id: photoDialog
        title: "Fotos do rosto (de frente e nítidas)"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Imagens (*.jpg *.jpeg *.png *.webp *.bmp)", "Todos os arquivos (*)"]
        onAccepted: backend.setFacePhotos(selectedFiles)
    }

    function analysisEstimate(fps) {
        const minutes = 3600 * fps * drawer.secondsPerFrame / 60
        return minutes < 1 ? "menos de 1 min" : "~" + Math.round(minutes) + " min"
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------------ cabeçalho
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 20
            spacing: 12
            Rectangle {
                width: 38; height: 38; radius: 12
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.accent }
                    GradientStop { position: 1; color: Theme.accent2 }
                }
                Icon { anchors.centerIn: parent; name: "sparkles"; size: 19; color: "white" }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text { text: "IA local"; color: Theme.text; font.pixelSize: 20; font.weight: Font.Bold }
                Text {
                    Layout.fillWidth: true
                    text: "Rostos e legendas processados no seu computador"
                    color: Theme.textMuted
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }
            AppButton { variant: "ghost"; iconName: "x"; tip: "Fechar (Esc)"; onClicked: drawer.close() }
        }

        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: scroll.availableWidth
                spacing: 28

                Item { implicitHeight: 1 }

                // ------------------------------------------------ reconhecimento facial
                DrawerSection {
                    title: "Reconhecimento facial"
                    iconName: "scan-face"

                    Rectangle {
                        id: faceCard
                        Layout.fillWidth: true
                        implicitHeight: Math.max(112, faceBody.implicitHeight + 28)
                        radius: Theme.radius
                        color: photoDrop.containsDrag ? Theme.tint(Theme.accent, 0.10) : Theme.field
                        border.width: photoDrop.containsDrag || drawer.face.state === "" ? 1.5 : 1
                        border.color: photoDrop.containsDrag ? Theme.accent
                                    : drawer.face.state === "error" ? Theme.tint(Theme.danger, 0.6)
                                    : drawer.face.state === "ready" ? Theme.tint(Theme.accent, 0.45)
                                    : Theme.borderStrong
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                        Behavior on border.color { ColorAnimation { duration: Theme.animFast } }

                        DropArea {
                            id: photoDrop
                            anchors.fill: parent
                            keys: ["text/uri-list"]
                            onDropped: drop => { if (drop.hasUrls) backend.setFacePhotos(drop.urls) }
                        }
                        HoverHandler { id: cardHover; enabled: drawer.face.state === ""; cursorShape: Qt.PointingHandCursor }
                        TapHandler { enabled: drawer.face.state === ""; onTapped: photoDialog.open() }

                        RowLayout {
                            id: faceBody
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                            spacing: 14

                            // retrato redondo (PNG com fundo transparente gerado pelo núcleo)
                            Rectangle {
                                Layout.preferredWidth: 72
                                Layout.preferredHeight: 72
                                Layout.alignment: Qt.AlignTop
                                radius: 36
                                color: Theme.tint(Theme.accent, drawer.face.state === "" ? 0.10 : 0.16)
                                border.width: drawer.face.state === "ready" ? 2 : 0
                                border.color: Theme.accent

                                Image {
                                    id: portrait
                                    anchors { fill: parent; margins: 3 }
                                    visible: drawer.face.preview !== ""
                                    source: drawer.face.preview
                                    fillMode: Image.PreserveAspectFit
                                    cache: false
                                    asynchronous: true
                                    opacity: status === Image.Ready ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.anim } }
                                }
                                BusyDots { anchors.centerIn: parent; visible: drawer.face.state === "loading" }
                                Icon {
                                    anchors.centerIn: parent
                                    visible: drawer.face.preview === "" && drawer.face.state !== "loading"
                                    name: drawer.face.state === "error" ? "alert" : "scan-face"
                                    size: 30
                                    color: drawer.face.state === "error" ? Theme.danger : Theme.accent
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                // vazio: convite
                                Text {
                                    visible: drawer.face.state === ""
                                    Layout.fillWidth: true
                                    text: "Arraste fotos do rosto ou clique para escolher"
                                    color: Theme.text
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                    wrapMode: Text.WordWrap
                                }
                                Text {
                                    visible: drawer.face.state === ""
                                    Layout.fillWidth: true
                                    text: "De 1 a 5 fotos nítidas, de frente. Mais fotos deixam a comparação mais precisa."
                                    color: Theme.textFaint
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }

                                // carregando
                                Text {
                                    visible: drawer.face.state === "loading"
                                    Layout.fillWidth: true
                                    text: "Preparando a referência…"
                                    color: Theme.accent
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    visible: drawer.face.state === "loading"
                                    Layout.fillWidth: true
                                    text: "Na primeira vez os modelos de rosto (39 MB) são baixados."
                                    color: Theme.textFaint
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }

                                // pronto: nome editável
                                AppTextField {
                                    id: nameField
                                    visible: drawer.face.state === "ready"
                                    Layout.fillWidth: true
                                    iconName: "user"
                                    text: drawer.cfg.face_label
                                    placeholderText: "Nome da pessoa"
                                    onEditingFinished: backend.setConfig("face_label", text.trim())
                                    Accessible.name: "Nome da pessoa procurada"
                                }
                                Text {
                                    visible: drawer.face.state === "ready"
                                    text: drawer.face.photos === 1 ? "1 foto de referência" : drawer.face.photos + " fotos de referência"
                                    color: Theme.textFaint
                                    font.pixelSize: 12
                                }

                                // erro
                                Text {
                                    visible: drawer.face.state === "error"
                                    Layout.fillWidth: true
                                    text: drawer.face.message
                                    color: Theme.danger
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                }

                                RowLayout {
                                    visible: drawer.face.state === "ready" || drawer.face.state === "error"
                                    spacing: 6
                                    AppButton {
                                        compact: true
                                        iconName: "image"
                                        text: drawer.face.state === "error" ? "Escolher outras…" : "Trocar fotos…"
                                        onClicked: photoDialog.open()
                                    }
                                    AppButton {
                                        compact: true
                                        variant: "ghost"
                                        iconName: "trash"
                                        text: "Remover"
                                        onClicked: backend.clearFace()
                                    }
                                }
                            }
                        }
                    }

                    SettingRow {
                        label: "Procurar este rosto ao buscar"
                        description: !drawer.ai.facesAvailable && drawer.ai.ready ? drawer.ai.facesDetail
                            : drawer.cfg.face_enabled
                              ? "Cada vídeo é analisado quadro a quadro. Lives do YouTube são lidas em 360p, sem salvar o vídeo; os trechos com a pessoa entram na lista junto com as menções."
                              : "Desligado: a busca usa só as legendas."
                        AppSwitch {
                            enabled: drawer.face.state === "ready"
                            checked: drawer.cfg.face_enabled
                            onToggled: backend.setConfig("face_enabled", checked)
                            Accessible.name: "Procurar este rosto ao buscar"
                        }
                    }
                    SettingRow {
                        label: "Rigor da comparação"
                        description: drawer.cfg.face_threshold >= 0.45
                            ? "Só aceita quando a semelhança é alta: quase nenhum falso positivo, mas perde rostos de perfil ou distantes."
                            : drawer.cfg.face_threshold <= 0.32
                              ? "Aceita semelhanças menores: encontra mais aparições, com risco de confundir pessoas parecidas."
                              : "Equilíbrio recomendado para a maioria das gravações."
                        Segmented {
                            model: [{ value: 0.45, label: "Rigoroso" }, { value: 0.38, label: "Normal" }, { value: 0.32, label: "Flexível" }]
                            current: drawer.cfg.face_threshold
                            onActivated: v => backend.setConfig("face_threshold", v)
                        }
                    }
                    SettingRow {
                        label: "Amostragem"
                        description: "Análise de " + drawer.analysisEstimate(drawer.cfg.face_fps)
                                     + " por hora de vídeo na CPU (mais o tempo de leitura pela internet)."
                                     + (drawer.cfg.face_fps < 1 ? " Aparições de menos de 2 s podem passar despercebidas." : "")
                        Segmented {
                            model: [{ value: 0.5, label: "0,5/s" }, { value: 1, label: "1/s" }, { value: 2, label: "2/s" }]
                            current: drawer.cfg.face_fps
                            onActivated: v => backend.setConfig("face_fps", v)
                        }
                    }
                    AppButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        variant: "primary"
                        iconName: "scan-face"
                        text: backend.hasResults ? "Procurar nos vídeos carregados" : "Busque vídeos para procurar o rosto"
                        tip: "Analisa os vídeos da lista atual, sem buscar as legendas de novo"
                        enabled: backend.hasResults && drawer.face.state === "ready" && !backend.busy
                        onClicked: backend.scanFaces()
                    }
                }

                // ------------------------------------------------ legenda por IA
                DrawerSection {
                    title: "Legenda por IA"
                    iconName: "mic"

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: engines.implicitHeight + 24
                        radius: Theme.radiusSmall
                        color: Theme.field
                        border.width: 1
                        border.color: Theme.border

                        ColumnLayout {
                            id: engines
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
                            spacing: 8

                            Text {
                                visible: !drawer.ai.ready
                                text: "Verificando os motores instalados…"
                                color: Theme.textFaint
                                font.pixelSize: 12
                            }
                            Repeater {
                                model: drawer.ai.engines
                                RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 10
                                    Rectangle {
                                        width: 8; height: 8; radius: 4
                                        color: modelData.available ? Theme.success : Theme.textFaint
                                    }
                                    Text {
                                        text: modelData.name
                                        color: modelData.available ? Theme.text : Theme.textMuted
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.detail
                                        color: Theme.textFaint
                                        font.family: modelData.available ? Theme.sans : Theme.mono
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                    Chip {
                                        visible: modelData.name === drawer.ai.transcriber
                                        text: "em uso"
                                        tone: Theme.success
                                    }
                                }
                            }
                            Text {
                                visible: drawer.ai.ready && drawer.ai.transcriber === ""
                                Layout.fillWidth: true
                                text: "Instale um dos dois para gerar legendas no computador. O whisper.cpp está nos repositórios oficiais do Arch/BigLinux."
                                color: Theme.warning
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }
                    }

                    SettingRow {
                        label: "Gerar legenda quando o vídeo não tiver"
                        description: "Transcreve o áudio com Whisper e procura os termos no resultado, com tempo por palavra. Também dá para gerar a legenda de um vídeo só pelo botão “Gerar legenda” na lista."
                        AppSwitch {
                            enabled: drawer.ai.transcriber !== ""
                            checked: drawer.cfg.whisper_fallback
                            onToggled: backend.setConfig("whisper_fallback", checked)
                            Accessible.name: "Gerar legenda quando o vídeo não tiver"
                        }
                    }
                    SettingRow {
                        label: "Modelo"
                        description: ({
                            tiny: "O mais rápido; erra bastante nomes próprios.",
                            base: "Rápido; bom para fala clara.",
                            small: "Equilíbrio entre precisão e tempo (recomendado).",
                            medium: "O mais preciso; cerca de 3× mais lento que o small. Ideal com GPU."
                        })[drawer.cfg.whisper_model] || ""
                        Segmented {
                            model: [{ value: "tiny", label: "Tiny" }, { value: "base", label: "Base" },
                                    { value: "small", label: "Small" }, { value: "medium", label: "Medium" }]
                            current: drawer.cfg.whisper_model
                            onActivated: v => backend.setConfig("whisper_model", v)
                        }
                    }
                }

                // ------------------------------------------------ atividade
                DrawerSection {
                    title: "Atividade"
                    iconName: "terminal"
                    Layout.bottomMargin: 24

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 210
                        radius: Theme.radiusSmall
                        color: Theme.field
                        border.width: 1
                        border.color: Theme.border

                        ListView {
                            id: console_
                            anchors { fill: parent; margins: 10 }
                            clip: true
                            model: backend.logModel
                            spacing: 3
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            onCountChanged: Qt.callLater(positionViewAtEnd)
                            delegate: Text {
                                required property string display
                                width: ListView.view.width - 8
                                text: display
                                color: Theme.textMuted
                                font.family: Theme.mono
                                font.pixelSize: 11
                                wrapMode: Text.WrapAnywhere
                                textFormat: Text.PlainText
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: console_.count === 0
                            text: "O andamento das análises aparece aqui."
                            color: Theme.textFaint
                            font.pixelSize: 12
                        }
                    }
                    RowLayout {
                        spacing: 6
                        AppButton { compact: true; variant: "ghost"; iconName: "copy"; text: "Copiar"; enabled: console_.count > 0; onClicked: backend.copyLog() }
                        AppButton { compact: true; variant: "ghost"; iconName: "trash"; text: "Limpar"; enabled: console_.count > 0; onClicked: backend.clearLog() }
                    }
                }
            }
        }
    }
}
