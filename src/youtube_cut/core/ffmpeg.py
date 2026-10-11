"""Corte de arquivos locais com FFmpeg (stream copy ou reencode, com VA-API)."""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

RENDER_NODE = Path("/dev/dri/renderD128")
SUBTITLE_EXTS = (".vtt", ".srt")


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise FFmpegError("FFmpeg não encontrado. Instale com: sudo pacman -S ffmpeg")


@functools.cache
def vaapi_available() -> bool:
    if not RENDER_NODE.exists() or not os.access(RENDER_NODE, os.R_OK | os.W_OK):
        return False
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "h264_vaapi" in out


def probe_duration(path: str | Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        return float(json.loads(out)["format"]["duration"])
    except (OSError, subprocess.SubprocessError, KeyError, ValueError, TypeError):
        return None


def find_subtitle_for(video: Path) -> Path | None:
    """Procura legenda ao lado do vídeo: video.vtt, video.pt.srt, video.pt-BR.vtt..."""
    candidates = [
        p for p in video.parent.glob(f"{_glob_escape(video.stem)}*")
        if p.suffix.lower() in SUBTITLE_EXTS
    ]
    candidates.sort(key=lambda p: (len(p.name), p.name))
    return candidates[0] if candidates else None


def _glob_escape(text: str) -> str:
    return "".join(f"[{c}]" if c in "*?[]" else c for c in text)


def extract_embedded_subtitle(video: Path, dest: Path) -> Path | None:
    """Extrai a primeira faixa de legenda embutida (MKV/MP4) para WebVTT."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", "0:s:0", "-c:s", "webvtt", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and dest.exists() and dest.stat().st_size > 10:
        return dest
    return None


def _encode_args(hwaccel: str) -> tuple[list[str], list[str]]:
    """Retorna (args antes do -i, args de codec de saída)."""
    use_vaapi = hwaccel == "vaapi" or (hwaccel == "auto" and vaapi_available())
    if use_vaapi:
        return (
            ["-vaapi_device", str(RENDER_NODE)],
            ["-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "22",
             "-c:a", "aac", "-b:a", "160k"],
        )
    return [], ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k"]


def cut_local(
    source: Path,
    start: float,
    end: float,
    output: Path,
    precise: bool = True,
    hwaccel: str = "auto",
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    require_ffmpeg()
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, end - start)

    def build(pre: list[str], codec: list[str]) -> list[str]:
        return [
            "ffmpeg", "-hide_banner", "-v", "error", "-y", "-nostdin",
            "-progress", "pipe:1", *pre,
            "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
            "-map", "0:v:0?", "-map", "0:a:0?", *codec,
            "-movflags", "+faststart", str(output),
        ]

    if precise:
        pre, codec = _encode_args(hwaccel)
        attempts = [build(pre, codec)]
        if pre:  # se a VA-API falhar, tenta na CPU
            attempts.append(build(*_encode_args("none")))
    else:
        attempts = [build([], ["-c", "copy", "-avoid_negative_ts", "make_zero"])]

    error = ""
    for cmd in attempts:
        error = _run(cmd, duration, progress, cancel)
        if not error:
            return output
    raise FFmpegError(error.strip() or "FFmpeg falhou ao cortar o vídeo.")


def _run(cmd, duration, progress, cancel) -> str:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("cancelado")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr_chunks: list[str] = []
    reader = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
    reader.start()

    def watch_cancel() -> None:
        # O FFmpeg só escreve progresso a cada ~0,5 s; não esperamos por ele para cancelar.
        while proc.poll() is None:
            if cancel.wait(0.05):
                proc.terminate()
                return

    if cancel is not None:
        threading.Thread(target=watch_cancel, daemon=True).start()
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if progress and key == "out_time_us" and value.isdigit():
            progress(min(1.0, int(value) / 1e6 / duration))
    proc.wait()
    reader.join(timeout=5)
    if cancel is not None and cancel.is_set():
        output_file = Path(cmd[-1])
        output_file.unlink(missing_ok=True)  # não deixa arquivo pela metade
        raise InterruptedError("cancelado")
    return "" if proc.returncode == 0 else "".join(stderr_chunks)
