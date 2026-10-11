"""Leitura de legendas WebVTT/SRT para uma lista de palavras com tempo.

Dois formatos de entrada exigem tratamentos diferentes:

* Legendas automáticas do YouTube (ASR): cada cue repete a linha anterior e
  traz a linha nova com marcações por palavra (``<00:05:44.600><c> Aqui</c>``).
  Usamos só a última linha de cada cue e aproveitamos o tempo de cada palavra,
  o que dá precisão de décimos de segundo ao corte.
* Legendas comuns (manuais/SRT): o tempo é por bloco; distribuímos as palavras
  dentro do bloco proporcionalmente ao tamanho de cada uma.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Word
from .timefmt import parse_timestamp

_TIMING = re.compile(
    r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_INLINE_TS = re.compile(r"<((?:\d+:)?\d{1,2}:\d{2}\.\d{3})>")
_TAG = re.compile(r"</?[^>]+>")

# Duração estimada de uma palavra sem marcação de fim.
_MAX_TAIL = 0.8


@dataclass(slots=True)
class _Cue:
    start: float
    end: float
    lines: list[str]


def _parse_cues(text: str) -> list[_Cue]:
    cues: list[_Cue] = []
    current: _Cue | None = None
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _TIMING.match(raw)
        if m:
            current = _Cue(parse_timestamp(m.group(1)), parse_timestamp(m.group(2)), [])
            cues.append(current)
        elif not raw.strip():
            current = None
        elif current is not None:
            current.lines.append(raw)
    return cues


def _clean(line: str) -> str:
    return " ".join(html.unescape(_TAG.sub("", line)).split())


def _spread(text: str, start: float, end: float) -> list[Word]:
    """Distribui as palavras de ``text`` entre ``start`` e ``end``."""
    tokens = text.split()
    if not tokens:
        return []
    end = max(end, start)
    weights = [len(t) + 1 for t in tokens]
    total = sum(weights)
    words, t = [], start
    for token, w in zip(tokens, weights):
        dt = (end - start) * w / total
        words.append(Word(round(t, 3), round(t + dt, 3), token))
        t += dt
    return words


def _words_from_tagged_line(line: str, cue: _Cue) -> list[Word]:
    parts = _INLINE_TS.split(line)
    # parts = [texto0, ts1, texto1, ts2, texto2, ...]
    segments: list[tuple[float, str]] = [(cue.start, parts[0])]
    for i in range(1, len(parts), 2):
        segments.append((parse_timestamp(parts[i]), parts[i + 1]))

    words: list[Word] = []
    for idx, (seg_start, seg_text) in enumerate(segments):
        clean = _clean(seg_text)
        if not clean:
            continue
        if idx + 1 < len(segments):
            seg_end = segments[idx + 1][0]
        else:
            seg_end = min(cue.end, seg_start + _MAX_TAIL)
        words.extend(_spread(clean, seg_start, seg_end))
    return words


def parse_subtitle_text(text: str) -> list[Word]:
    cues = _parse_cues(text)
    words: list[Word] = []

    if _INLINE_TS.search(text):
        last_taken = None
        for cue in cues:
            if not cue.lines:
                continue
            line = cue.lines[-1]
            clean = _clean(line)
            if not clean or clean == last_taken:
                continue
            last_taken = clean
            if _INLINE_TS.search(line):
                words.extend(_words_from_tagged_line(line, cue))
            else:
                words.extend(_spread(clean, cue.start, cue.end))
    else:
        last_text = None
        for cue in cues:
            clean = _clean(" ".join(cue.lines))
            if not clean or clean == last_text:
                continue
            last_text = clean
            words.extend(_spread(clean, cue.start, cue.end))

    words.sort(key=lambda w: w.start)
    return words


def load_subtitle(path: str | Path) -> list[Word]:
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return parse_subtitle_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return []
