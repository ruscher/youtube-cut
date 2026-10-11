"""Transforma ocorrências em trechos de corte, com margem e fusão."""

from __future__ import annotations

from .models import Clip, Match


def build_clips(
    matches: list[Match],
    before: float = 3.0,
    after: float = 5.0,
    duration: float | None = None,
    merge_gap: float = 1.0,
) -> list[Clip]:
    """Aplica margens e junta trechos que se sobrepõem (ou ficam a menos de
    ``merge_gap`` segundos), evitando clipes repetidos quando o nome é dito
    várias vezes seguidas."""
    clips: list[Clip] = []
    for m in sorted(matches, key=lambda m: (m.video_id, m.start)):
        start = max(0.0, m.start - before)
        end = m.end + after
        if duration:
            end = min(end, duration)
        if clips and clips[-1].video_id == m.video_id and start <= clips[-1].end + merge_gap:
            clips[-1].end = max(clips[-1].end, end)
            clips[-1].matches.append(m)
        else:
            clips.append(Clip(m.video_id, round(start, 3), round(end, 3), [m]))
    for c in clips:
        c.end = round(c.end, 3)
    return clips
