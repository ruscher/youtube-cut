"""Conversão entre segundos e timestamps de legenda/FFmpeg."""

from __future__ import annotations

import re

_TS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$")


def parse_timestamp(value: str) -> float:
    """Aceita 'HH:MM:SS.mmm', 'MM:SS', 'HH:MM:SS,mmm' (SRT) ou segundos puros."""
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    m = _TS.match(value)
    if not m:
        raise ValueError(f"timestamp inválido: {value!r}")
    hours, minutes, seconds, frac = m.groups()
    total = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
    if frac:
        total += int(frac.ljust(3, "0")) / 1000
    return total


def format_timestamp(seconds: float, millis: bool = True) -> str:
    """Segundos -> 'HH:MM:SS.mmm' (ou 'HH:MM:SS')."""
    seconds = max(0.0, seconds)
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{base}.{ms:03d}" if millis else base


def format_short(seconds: float) -> str:
    """Formato compacto para interface: '1:02:03' ou '2:03'."""
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
