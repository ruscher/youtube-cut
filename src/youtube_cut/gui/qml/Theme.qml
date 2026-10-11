pragma Singleton
import QtQuick

// Tokens visuais: escuro "vidro" inspirado no Breeze/Adwaita, com destaque
// ciano → magenta. "system" segue o esquema de cores do Plasma/GNOME.
QtObject {
    property string mode: "system"
    readonly property bool dark: mode === "dark"
        || (mode === "system" && Qt.styleHints.colorScheme !== Qt.ColorScheme.Light)

    readonly property color bg: dark ? "#0d0e15" : "#eef0f6"
    readonly property color surface: dark ? Qt.rgba(0.12, 0.12, 0.19, 0.72) : Qt.rgba(1, 1, 1, 0.74)
    readonly property color surfaceStrong: dark ? "#171826" : "#fbfbfe"
    readonly property color hover: dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0.05, 0.08, 0.2, 0.05)
    readonly property color field: dark ? Qt.rgba(0, 0, 0, 0.28) : Qt.rgba(1, 1, 1, 0.95)
    readonly property color border: dark ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(0.06, 0.08, 0.2, 0.11)
    readonly property color borderStrong: dark ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(0.06, 0.08, 0.2, 0.22)
    readonly property color text: dark ? "#ececf4" : "#171a2b"
    readonly property color textMuted: dark ? "#a2a4bb" : "#545873"
    readonly property color textFaint: dark ? "#71748e" : "#83879f"
    readonly property color accent: dark ? "#22d3ee" : "#0891b2"
    readonly property color accent2: dark ? "#d946ef" : "#c026d3"
    readonly property color accentText: "#ffffff"
    readonly property color success: dark ? "#34d399" : "#059669"
    readonly property color warning: dark ? "#fbbf24" : "#b45309"
    readonly property color danger: dark ? "#fb7185" : "#e11d48"

    readonly property int radius: 14
    readonly property int radiusSmall: 10
    readonly property int animFast: 150
    readonly property int anim: 220
    // cubic-bezier(0.4, 0, 0.2, 1) — usar com easing.type: Easing.Bezier
    readonly property var curve: [0.4, 0.0, 0.2, 1.0, 1.0, 1.0]

    readonly property string sans: pick(["Inter", "Noto Sans", "Cantarell", "DejaVu Sans"])
    readonly property string mono: pick(["JetBrains Mono", "Fira Code", "Noto Sans Mono", "DejaVu Sans Mono"])

    function tint(c, alpha) { return Qt.rgba(c.r, c.g, c.b, alpha) }

    function pick(families) {
        const available = Qt.fontFamilies()
        for (const f of families)
            if (available.indexOf(f) >= 0)
                return f
        return Qt.application.font.family
    }
}
