"""Contraste mínimo WCAG AA (4,5:1) para todo token usado como cor de texto."""

import re
from pathlib import Path

import pytest

THEME = Path(__file__).resolve().parent.parent / "src/youtube_cut/gui/qml/Theme.qml"
# cor efetiva dos cards de vidro sobre o fundo, nos dois modos
CARD = {"dark": "#1c1d2b", "light": "#fbfbfd"}
TEXT_TOKENS = ["text", "textMuted", "textFaint", "accent", "accent2", "success", "warning", "danger"]
CHIP_ALPHA = {"dark": 0.15, "light": 0.12}  # fundo tingido dos Chips (Chip.qml)
CHIP_TONES = {"textMuted", "accent", "accent2", "success", "warning", "danger"}  # tons usados em Chip


def _tokens(mode: str) -> dict[str, str]:
    out = {}
    for name, dark, light in re.findall(
        r'property color (\w+): dark \? "(#[0-9a-fA-F]{6})" : "(#[0-9a-fA-F]{6})"', THEME.read_text()
    ):
        out[name] = dark if mode == "dark" else light
    return out


def _lum(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix(fg: str, bg: str, alpha: float) -> str:
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * alpha + y * (1 - alpha)):02x}" for x, y in zip(f, b))


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("token", TEXT_TOKENS)
def test_text_tokens_meet_wcag_aa(mode, token):
    colors = _tokens(mode)
    fg = colors[token]
    backgrounds = {"fundo": colors["bg"], "card": CARD[mode]}
    if token in CHIP_TONES:
        backgrounds["chip"] = _mix(fg, CARD[mode], CHIP_ALPHA[mode])
    for where, bg in backgrounds.items():
        assert _ratio(fg, bg) >= 4.5, f"{token} ({fg}) sobre {where} ({bg}) no modo {mode}: {_ratio(fg, bg):.2f}"
