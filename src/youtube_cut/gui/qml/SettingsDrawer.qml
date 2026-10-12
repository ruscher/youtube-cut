import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts
import "."

Drawer {
    id: drawer
    readonly property var cfg: backend.config

    edge: Qt.RightEdge
    width: Math.min(440, parent.width * 0.92)
    height: parent.height
    padding: 0

    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, Theme.dark ? 0.45 : 0.25) }

    background: Rectangle {
        color: Theme.surfaceStrong
        Rectangle { width: 1; height: parent.height; color: Theme.border }
    }

    FolderDialog {
        id: folderDialog
        title: "Pasta onde salvar os cortes"
        onAccepted: backend.setConfig("output_dir", backend.urlToPath(selectedFolder.toString()))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 20
            Text {
                Layout.fillWidth: true
                text: "Configurações"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.Bold
            }
            AppButton { variant: "ghost"; iconName: "x"; tip: "Fechar (Esc)"; onClicked: drawer.close() }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: 28

                Item { implicitHeight: 1 }

                DrawerSection {
                    title: "Busca"
                    iconName: "search"

                    SettingRow {
                        label: "Idioma da legenda"
                        description: "Usa a legenda manual nesse idioma; senão, a transcrição automática original do vídeo."
                        AppCombo {
                            implicitWidth: 130
                            model: [{ v: "pt", t: "Português" }, { v: "en", t: "Inglês" }, { v: "es", t: "Espanhol" },
                                    { v: "fr", t: "Francês" }, { v: "de", t: "Alemão" }, { v: "it", t: "Italiano" }]
                            textRole: "t"
                            valueRole: "v"
                            currentIndex: Math.max(0, indexOfValue(drawer.cfg.language))
                            onActivated: backend.setConfig("language", currentValue)
                        }
                    }
                    SettingRow {
                        label: "Aba do canal"
                        description: "Quando o link é de um canal, quais vídeos analisar."
                        Segmented {
                            model: [{ value: "streams", label: "Lives" }, { value: "videos", label: "Vídeos" }, { value: "shorts", label: "Shorts" }]
                            current: drawer.cfg.channel_tab
                            onActivated: v => backend.setConfig("channel_tab", v)
                        }
                    }
                    SettingRow {
                        label: "Vídeos por busca"
                        description: "Os mais recentes primeiro. Legendas ficam em cache: repetir a busca é instantâneo."
                        NumberStepper {
                            value: drawer.cfg.max_videos; from: 0; to: 5000; step: 10; zeroText: "todos"
                            onEdited: v => backend.setConfig("max_videos", v)
                        }
                    }
                    SettingRow {
                        label: "Tolerância a erros de transcrição"
                        description: drawer.cfg.fuzzy > 0
                            ? "Aceita grafias parecidas (“Barbra”, “Bárbra”) com " + Math.round((1 - drawer.cfg.fuzzy) * 100) + "% de semelhança."
                            : "Só a palavra exata (acentos e maiúsculas são ignorados)."
                        Segmented {
                            model: [{ value: 0, label: "Exata" }, { value: 0.15, label: "Leve" }, { value: 0.25, label: "Alta" }]
                            current: drawer.cfg.fuzzy
                            onActivated: v => backend.setConfig("fuzzy", v)
                        }
                    }
                }

                DrawerSection {
                    title: "Corte"
                    iconName: "scissors"

                    SettingRow {
                        label: "Margem antes da menção"
                        NumberStepper {
                            value: drawer.cfg.before; from: 0; to: 120; step: 1; suffix: " s"
                            onEdited: v => backend.setConfig("before", v)
                        }
                    }
                    SettingRow {
                        label: "Margem depois da menção"
                        NumberStepper {
                            value: drawer.cfg.after; from: 0; to: 300; step: 1; suffix: " s"
                            onEdited: v => backend.setConfig("after", v)
                        }
                    }
                    SettingRow {
                        label: "Juntar menções próximas"
                        description: "Trechos separados por menos que isso viram um só corte."
                        NumberStepper {
                            value: drawer.cfg.merge_gap; from: 0; to: 60; step: 1; suffix: " s"
                            onEdited: v => backend.setConfig("merge_gap", v)
                        }
                    }
                    SettingRow {
                        label: "Qualidade máxima"
                        Segmented {
                            model: [{ value: "480", label: "480p" }, { value: "720", label: "720p" },
                                    { value: "1080", label: "1080p" }, { value: "2160", label: "4K" }, { value: "best", label: "Máx" }]
                            current: drawer.cfg.quality
                            onActivated: v => backend.setConfig("quality", v)
                        }
                    }
                    SettingRow {
                        label: "Corte preciso"
                        description: drawer.cfg.precise_cut
                            ? "Reencoda só o trecho (segundos) para começar no quadro exato."
                            : "Cópia direta, mais rápida: o corte pode começar alguns segundos antes."
                        AppSwitch {
                            checked: drawer.cfg.precise_cut
                            onToggled: backend.setConfig("precise_cut", checked)
                        }
                    }
                    SettingRow {
                        label: "Aceleração de vídeo"
                        description: "Para arquivos locais. VA-API usa a GPU (AMD/Intel)."
                        Segmented {
                            model: [{ value: "auto", label: "Auto" }, { value: "vaapi", label: "VA-API" }, { value: "none", label: "CPU" }]
                            current: drawer.cfg.hwaccel
                            onActivated: v => backend.setConfig("hwaccel", v)
                        }
                    }
                    SettingRow {
                        label: "Pasta de saída"
                        description: drawer.cfg.output_dir
                        AppButton { compact: true; iconName: "folder"; text: "Escolher…"; onClicked: folderDialog.open() }
                    }
                }

                DrawerSection {
                    title: "Conta do YouTube"
                    iconName: "user"

                    SettingRow {
                        label: "Usar login do navegador"
                        description: "Necessário para vídeos privados ou não listados, e quando o YouTube pede para confirmar que você não é um robô. Os cookies são lidos só no seu computador."
                        AppCombo {
                            implicitWidth: 130
                            model: [{ v: "", t: "Não usar" }, { v: "firefox", t: "Firefox" }, { v: "chrome", t: "Chrome" },
                                    { v: "chromium", t: "Chromium" }, { v: "brave", t: "Brave" }, { v: "vivaldi", t: "Vivaldi" },
                                    { v: "edge", t: "Edge" }, { v: "opera", t: "Opera" }]
                            textRole: "t"
                            valueRole: "v"
                            currentIndex: Math.max(0, indexOfValue(drawer.cfg.cookies_browser))
                            onActivated: backend.setConfig("cookies_browser", currentValue)
                        }
                    }
                    SettingRow {
                        label: "Baixar solucionador de desafios"
                        description: "Se o YouTube bloquear downloads, permite que o yt-dlp baixe do GitHub o script que resolve o desafio. Prefira instalar o pacote yt-dlp-ejs."
                        AppSwitch {
                            checked: drawer.cfg.allow_remote_ejs
                            onToggled: backend.setConfig("allow_remote_ejs", checked)
                        }
                    }
                }

                DrawerSection {
                    title: "Aparência"
                    iconName: "palette"
                    Layout.bottomMargin: 24

                    SettingRow {
                        label: "Tema"
                        Segmented {
                            model: [{ value: "system", label: "Sistema" }, { value: "dark", label: "Escuro" }, { value: "light", label: "Claro" }]
                            current: drawer.cfg.theme
                            onActivated: v => backend.setConfig("theme", v)
                        }
                    }
                }
            }
        }
    }
}
