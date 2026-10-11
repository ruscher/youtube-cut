import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

ApplicationWindow {
    id: win
    readonly property var cfg: backend.config
    readonly property var videos: backend.videosModel
    readonly property var clips: backend.clipsModel
    property alias settingsOpen: settingsDrawer.visible

    width: 1280
    height: 820
    minimumWidth: 960
    minimumHeight: 620
    visible: true
    title: "YouTube Cut"
    color: Theme.bg
    font.family: Theme.sans

    palette.window: Theme.bg
    palette.windowText: Theme.text
    palette.base: Theme.surfaceStrong
    palette.text: Theme.text
    palette.button: Theme.surfaceStrong
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.accentText
    palette.toolTipBase: Theme.surfaceStrong
    palette.toolTipText: Theme.text
    palette.placeholderText: Theme.textFaint

    Binding { target: Theme; property: "mode"; value: win.cfg.theme }

    function startOrCancel() {
        if (backend.busy) backend.cancel()
        else backend.startScan(sourceField.text, termsField.text)
    }

    function sourceKind(text) {
        const t = text.trim()
        if (!t) return ""
        if (backend.isLocalSource(t)) return "Arquivo/pasta local"
        if (/[?&]list=/.test(t)) return "Playlist"
        if (/(youtu\.be\/|[?&]v=|\/live\/|\/shorts\/|studio\.youtube\.com\/video\/)/.test(t) || /^[\w-]{11}$/.test(t))
            return "Vídeo"
        const tabs = { streams: "lives", videos: "vídeos", shorts: "shorts" }
        let tab = tabs[win.cfg.channel_tab]
        if (/\/videos\/live/.test(t) || /\/streams/.test(t)) tab = "lives"
        else if (/\/videos\/upload/.test(t) || /youtube\.com\/[^/]+\/videos/.test(t)) tab = "vídeos"
        return "Canal · " + tab
    }

    Aurora { anchors.fill: parent }

    Shortcut { sequence: "Ctrl+,"; onActivated: settingsDrawer.open() }
    Shortcut { sequence: "Escape"; enabled: backend.busy && !settingsDrawer.visible; onActivated: backend.cancel() }
    Shortcut { sequence: "Ctrl+L"; onActivated: { sourceField.forceActiveFocus(); sourceField.selectAll() } }
    Shortcut { sequence: "Ctrl+Return"; enabled: !backend.busy && clips.checkedCount > 0; onActivated: backend.cutSelected() }

    Connections {
        target: backend
        function onToast(message, kind, action) { toast.show(message, kind, action) }
    }

    FileDialog {
        id: videoDialog
        title: "Escolher vídeo local"
        nameFilters: ["Vídeos (*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.ts)", "Todos os arquivos (*)"]
        onAccepted: sourceField.text = backend.urlToPath(selectedFile.toString())
    }
    FolderDialog {
        id: sourceFolderDialog
        title: "Escolher pasta com vídeos"
        onAccepted: sourceField.text = backend.urlToPath(selectedFolder.toString())
    }
    FileDialog {
        id: reportDialog
        title: "Salvar relatório"
        fileMode: FileDialog.SaveFile
        nameFilters: ["Planilha CSV (*.csv)", "JSON (*.json)"]
        onAccepted: backend.exportReport(selectedFile.toString())
    }

    ColumnLayout {
        anchors { fill: parent; margins: 20 }
        spacing: 16

        // ---------------------------------------------------------------- cabeçalho
        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            Rectangle {
                width: 44; height: 44; radius: 14
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.accent }
                    GradientStop { position: 1; color: Theme.accent2 }
                }
                Icon { anchors.centerIn: parent; name: "scissors"; size: 22; color: "white" }
            }
            ColumnLayout {
                spacing: 1
                Text { text: "YouTube Cut"; color: Theme.text; font.pixelSize: 21; font.weight: Font.Bold }
                Text {
                    text: "Encontre o momento em que um nome é dito e recorte só aquele trecho"
                    color: Theme.textMuted
                    font.pixelSize: 13
                }
            }
            Item { Layout.fillWidth: true }
            AppButton {
                variant: "ghost"
                iconName: Theme.dark ? "sun" : "moon"
                tip: Theme.dark ? "Tema claro" : "Tema escuro"
                onClicked: backend.setConfig("theme", Theme.dark ? "light" : "dark")
            }
            AppButton {
                iconName: "sliders"
                text: "Configurações"
                tip: "Ctrl+,"
                onClicked: settingsDrawer.open()
            }
        }

        // ---------------------------------------------------------------- busca
        GlassCard {
            Layout.fillWidth: true
            implicitHeight: searchGrid.implicitHeight + 36

            ColumnLayout {
                id: searchGrid
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AppTextField {
                        id: sourceField
                        Layout.fillWidth: true
                        iconName: "link"
                        text: win.cfg.source
                        placeholderText: "Canal, @handle, link do YouTube Studio, vídeo, playlist ou pasta local"
                        enabled: !backend.busy
                        onAccepted: termsField.forceActiveFocus()
                        Accessible.name: "Fonte dos vídeos"
                    }
                    AppButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 44
                        iconName: "folder"
                        text: "Local…"
                        tip: "Escolher um vídeo ou uma pasta do computador"
                        enabled: !backend.busy
                        onClicked: localMenu.popup()
                        Menu {
                            id: localMenu
                            MenuItem { text: "Arquivo de vídeo…"; onTriggered: videoDialog.open() }
                            MenuItem { text: "Pasta com vídeos…"; onTriggered: sourceFolderDialog.open() }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AppTextField {
                        id: termsField
                        Layout.fillWidth: true
                        iconName: "search"
                        text: win.cfg.terms
                        placeholderText: "Nomes ou palavras, separados por vírgula — ex.: Bárbara, Ana Paula"
                        onAccepted: win.startOrCancel()
                        Accessible.name: "Termos a procurar"
                        Component.onCompleted: if (sourceField.text) forceActiveFocus()
                    }
                    AppButton {
                        // refaz a busca nas legendas já baixadas, sem acessar o YouTube
                        Layout.preferredHeight: 44
                        visible: backend.hasResults && !backend.busy && termsField.text.trim() !== win.cfg.terms
                        iconName: "sparkles"
                        text: "Atualizar"
                        tip: "Procurar os novos termos nas legendas já carregadas (instantâneo)"
                        onClicked: backend.refreshSearch(termsField.text)
                    }
                    AppButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 44
                        variant: backend.busy ? "danger" : "primary"
                        iconName: backend.busy ? "x" : "search"
                        text: backend.busy ? "Cancelar" : "Buscar"
                        tip: backend.busy ? "Esc" : "Enter"
                        onClicked: win.startOrCancel()
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Chip {
                        visible: text !== ""
                        text: win.sourceKind(sourceField.text)
                        iconName: text.indexOf("local") >= 0 ? "file" : "video"
                        tone: Theme.accent
                    }
                    Chip {
                        text: "Margem −" + win.cfg.before + " s / +" + win.cfg.after + " s"
                        iconName: "clock"
                        tip: "Ajuste em Configurações"
                    }
                    Chip {
                        text: win.cfg.fuzzy > 0 ? "Tolerância a erros ligada" : "Busca exata"
                        iconName: "sparkles"
                        tone: win.cfg.fuzzy > 0 ? Theme.accent2 : Theme.textMuted
                        tip: "Ignora acentos e maiúsculas. Com tolerância, aceita grafias parecidas."
                    }
                    Chip {
                        visible: win.cfg.cookies_browser !== ""
                        text: "Login do " + win.cfg.cookies_browser
                        iconName: "user"
                    }
                }
            }
        }

        // ---------------------------------------------------------------- conteúdo
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            GlassCard {
                Layout.preferredWidth: Math.max(320, win.width * 0.27)
                Layout.fillHeight: true

                ColumnLayout {
                    anchors { fill: parent; margins: 12 }
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 6
                        Layout.rightMargin: 2
                        Layout.preferredHeight: 32
                        Text { text: "Vídeos"; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Text {
                            visible: win.videos.count > 0
                            text: backend.scannedCount + "/" + win.videos.count
                            color: Theme.textFaint
                            font.family: Theme.mono
                            font.pixelSize: 12
                        }
                        Item { Layout.fillWidth: true }
                        AppButton {
                            visible: backend.videoFilter !== ""
                            compact: true
                            variant: "ghost"
                            text: "Mostrar todos"
                            onClicked: backend.filterVideo(backend.videoFilter)
                        }
                    }

                    ListView {
                        id: videoList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 4
                        model: win.videos
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: VideoDelegate {
                            selected: backend.videoFilter === videoId
                            onClicked: backend.filterVideo(videoId)
                        }

                        EmptyState {
                            anchors.centerIn: parent
                            width: parent.width - 32
                            visible: win.videos.count === 0
                            busy: backend.phase === "discovering"
                            iconName: "video"
                            title: backend.phase === "discovering" ? "Consultando o YouTube…" : "Nenhum vídeo ainda"
                            message: backend.phase === "discovering" ? "" : "Os vídeos analisados aparecem aqui."
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors { fill: parent; margins: 12 }
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 6
                        Layout.rightMargin: 6
                        Layout.preferredHeight: 32
                        spacing: 10
                        Text { text: "Trechos encontrados"; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                        Chip { visible: win.clips.count > 0; text: String(win.clips.count); tone: Theme.accent }
                        Text {
                            Layout.fillWidth: true
                            visible: backend.videoFilterTitle !== ""
                            text: "em " + backend.videoFilterTitle
                            color: Theme.textFaint
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                        Item { Layout.fillWidth: backend.videoFilterTitle === "" }
                        AppCheck {
                            visible: win.clips.count > 0
                            text: "Selecionar todos"
                            tristate: false
                            checkState: win.clips.checkedCount === 0 ? Qt.Unchecked
                                      : win.clips.checkedCount >= win.clips.count && backend.videoFilter === "" ? Qt.Checked
                                      : Qt.PartiallyChecked
                            nextCheckState: function() { return checkState === Qt.Checked ? Qt.Unchecked : Qt.Checked }
                            onClicked: backend.setAllChecked(checkState === Qt.Checked)
                        }
                    }

                    ListView {
                        id: clipList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 10
                        model: win.clips
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: ClipDelegate { showVideo: backend.videoFilter === "" }

                        add: Transition {
                            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.anim }
                            NumberAnimation { property: "y"; from: clipList.contentHeight + 20; duration: Theme.anim; easing.type: Easing.OutCubic }
                        }

                        EmptyState {
                            anchors.centerIn: parent
                            width: Math.min(parent.width - 48, 560)
                            visible: win.clips.count === 0
                            busy: backend.busy && backend.phase !== "cutting"
                            iconName: backend.hasResults ? "search" : "scissors"
                            title: backend.busy ? "Lendo as legendas…"
                                 : backend.hasResults ? "Nenhuma menção encontrada"
                                 : "Encontre o momento exato"
                            message: backend.busy ? "Os trechos aparecem aqui assim que forem encontrados."
                                   : backend.hasResults ? "A transcrição automática às vezes escreve nomes de outro jeito. Ative a tolerância a erros ou tente outra grafia."
                                   : "Cole o link de um canal (vale o do YouTube Studio), escreva um nome e clique em Buscar. O YouTube Cut lê as legendas, acha cada menção e recorta só aquele pedaço — sem baixar a live inteira."

                            AppButton {
                                visible: backend.hasResults && !backend.busy && win.cfg.fuzzy === 0
                                text: "Ativar tolerância a erros"
                                iconName: "sparkles"
                                onClicked: backend.setConfig("fuzzy", 0.25)
                            }
                            Repeater {
                                model: backend.hasResults || backend.busy ? [] : ["1  Cole o link", "2  Digite o nome", "3  Corte"]
                                Chip { required property string modelData; text: modelData; tone: Theme.accent; implicitHeight: 28 }
                            }
                        }
                    }
                }
            }
        }

        // ---------------------------------------------------------------- rodapé
        GlassCard {
            Layout.fillWidth: true
            implicitHeight: 64

            ProgressGlow {
                anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 14; rightMargin: 14; topMargin: 1 }
                height: 3
                active: backend.busy || backend.progress > 0
                value: backend.progress
                opacity: backend.busy ? 1 : 0.55
            }

            RowLayout {
                anchors { fill: parent; leftMargin: 18; rightMargin: 12 }
                spacing: 10

                BusyDots { visible: backend.busy }
                Text {
                    Layout.fillWidth: true
                    text: backend.status
                    color: backend.busy ? Theme.text : Theme.textMuted
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
                AppButton {
                    variant: "ghost"
                    iconName: "report"
                    text: "Relatório"
                    tip: "Salvar todas as menções com links (CSV ou JSON)"
                    enabled: backend.totalMatches > 0
                    onClicked: { reportDialog.selectedFile = backend.suggestedReportName(); reportDialog.open() }
                }
                AppButton {
                    variant: "ghost"
                    iconName: "folder"
                    text: "Abrir pasta"
                    onClicked: backend.openOutputFolder()
                }
                AppButton {
                    variant: "primary"
                    iconName: "scissors"
                    enabled: !backend.busy && win.clips.checkedCount > 0
                    text: win.clips.checkedCount > 0
                          ? "Cortar " + win.clips.checkedCount + (win.clips.checkedCount === 1 ? " trecho" : " trechos")
                            + " · " + win.clips.checkedSeconds + " s"
                          : "Cortar"
                    tip: "Ctrl+Enter"
                    onClicked: backend.cutSelected()
                }
            }
        }
    }

    DropArea {
        id: drop
        anchors.fill: parent
        keys: ["text/uri-list"]
        onDropped: event => {
            if (event.hasUrls && event.urls.length > 0)
                sourceField.text = backend.urlToPath(event.urls[0].toString())
        }
        Rectangle {
            anchors { fill: parent; margins: 12 }
            visible: drop.containsDrag
            radius: Theme.radius + 4
            color: Theme.tint(Theme.accent, 0.08)
            border.width: 2
            border.color: Theme.accent
            EmptyState {
                anchors.centerIn: parent
                iconName: "download"
                title: "Solte o vídeo ou a pasta aqui"
            }
        }
    }

    SettingsDrawer { id: settingsDrawer }

    Toast {
        id: toast
        onActionTriggered: action => { if (action === "open-folder") backend.openOutputFolder() }
    }
}
