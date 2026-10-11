import QtQuick
import "."

// Fundo com manchas de luz desfocadas (gradientes radiais). Estático: repinta
// só ao redimensionar ou trocar de tema, sem custo contínuo de GPU.
Canvas {
    id: canvas
    readonly property bool dark: Theme.dark
    onDarkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    function rgba(c, a) {
        return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + a + ")"
    }

    function blob(ctx, cx, cy, r, color, alpha) {
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r)
        g.addColorStop(0, rgba(color, alpha))
        g.addColorStop(1, rgba(color, 0))
        ctx.fillStyle = g
        ctx.fillRect(0, 0, width, height)
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        ctx.fillStyle = Theme.bg
        ctx.fillRect(0, 0, width, height)
        const k = Theme.dark ? 1 : 0.7
        const big = Math.max(width, height)
        blob(ctx, width * 0.12, height * 0.05, big * 0.55, Theme.accent, 0.16 * k)
        blob(ctx, width * 0.95, height * 0.95, big * 0.6, Theme.accent2, 0.14 * k)
        blob(ctx, width * 0.62, height * 0.18, big * 0.35, Theme.accent2, 0.06 * k)
    }
}
