"""Orquestra descoberta de vídeos, busca nas legendas e cortes.

Usado tanto pela CLI quanto pela interface gráfica. Nada aqui depende de Qt.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import ffmpeg
from .clips import build_clips
from .config import CACHE_DIR, SUBTITLE_CACHE, Settings
from .models import Clip, Match, VideoInfo, Word
from .search import find_matches, parse_terms
from .subtitles import load_subtitle
from .timefmt import format_timestamp
from .youtube import Source, YouTubeClient, resolve_source

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".flv"}


@dataclass
class VideoResult:
    video: VideoInfo
    status: str = "pending"  # pending | scanning | done | nosubs | error
    words: list[Word] = field(default_factory=list, repr=False)
    matches: list[Match] = field(default_factory=list)
    subtitle: str = ""  # descrição da faixa usada, ex.: "pt-orig · automática"
    error: str = ""


def is_local_source(text: str) -> bool:
    text = text.strip()
    if text.startswith("file://"):
        text = text[7:]
    return bool(text) and Path(text).expanduser().exists()


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        log: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ):
        self.settings = settings
        self.log = log or (lambda _msg: None)
        self.cancel = cancel or threading.Event()
        self._yt: YouTubeClient | None = None

    @property
    def yt(self) -> YouTubeClient:
        if self._yt is None:
            self._yt = YouTubeClient(
                cookies_browser=self.settings.cookies_browser,
                allow_remote_ejs=self.settings.allow_remote_ejs,
                log=self.log,
                cancel=self.cancel,
            )
        return self._yt

    # -- descoberta -------------------------------------------------------

    def discover(self, source_text: str) -> list[VideoResult]:
        if is_local_source(source_text):
            return [VideoResult(v) for v in self._discover_local(source_text)]
        source: Source = resolve_source(source_text, self.settings.channel_tab)
        self.log(f"Consultando {source.url} …")
        videos = self.yt.list_videos(source, self.settings.max_videos)
        return [VideoResult(v) for v in videos]

    def _discover_local(self, text: str) -> list[VideoInfo]:
        path = Path(text.removeprefix("file://")).expanduser().resolve()
        files = (
            sorted(p for p in path.iterdir() if p.suffix.lower() in VIDEO_EXTS)
            if path.is_dir() else [path]
        )
        videos = []
        for f in files:
            digest = hashlib.sha1(str(f).encode()).hexdigest()[:11]
            videos.append(
                VideoInfo(id=digest, title=f.stem, url=f.as_uri(),
                          duration=ffmpeg.probe_duration(f), local_path=str(f))
            )
        return videos

    # -- legendas e busca -------------------------------------------------

    def load_words(self, result: VideoResult) -> None:
        video = result.video
        if video.is_local:
            source = Path(video.local_path)
            sub = ffmpeg.find_subtitle_for(source)
            label = sub.name if sub else ""
            if sub is None:
                sub = ffmpeg.extract_embedded_subtitle(
                    source, CACHE_DIR / "embedded" / f"{video.id}.vtt"
                )
                label = "legenda embutida"
            if sub is None:
                result.status = "nosubs"
                return
            result.words = load_subtitle(sub)
            result.subtitle = label
            return

        track = self.yt.fetch_subtitle(video, self.settings.language, SUBTITLE_CACHE)
        if track is None:
            result.status = "nosubs"
            return
        result.words = load_subtitle(track.path)
        kind = "automática" if track.automatic else "manual"
        result.subtitle = f"{track.language} · {kind}"

    def search(self, result: VideoResult, terms: list[str]) -> None:
        if result.status in ("nosubs", "error"):
            return
        result.matches = find_matches(result.words, terms, result.video.id, self.settings.fuzzy)
        result.status = "done"

    def scan(self, result: VideoResult, terms: list[str]) -> None:
        result.status = "scanning"
        try:
            if not result.words:
                self.load_words(result)
            self.search(result, terms)
        except Exception as e:  # um vídeo com problema não deve parar a varredura
            if self.cancel.is_set():
                raise
            result.status = "error"
            result.error = str(e)

    def clips_for(self, result: VideoResult) -> list[Clip]:
        s = self.settings
        return build_clips(result.matches, s.before, s.after, result.video.duration, s.merge_gap)

    # -- cortes -----------------------------------------------------------

    def output_path(self, video: VideoInfo, clip: Clip, terms: list[str]) -> Path:
        folder = Path(self.settings.output_dir).expanduser() / _slug(" ".join(terms) or "cortes")
        date = video.upload_date or ""
        if len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]} "
        stamp = format_timestamp(clip.start, millis=False).replace(":", "h", 1).replace(":", "m") + "s"
        return folder / f"{date}{_slug(video.title, 60)} - {stamp}.mp4"

    def cut(
        self,
        video: VideoInfo,
        clip: Clip,
        output: Path,
        progress: Callable[[float], None] | None = None,
    ) -> Path:
        s = self.settings
        if video.is_local:
            return ffmpeg.cut_local(
                Path(video.local_path), clip.start, clip.end, output,
                precise=s.precise_cut, hwaccel=s.hwaccel, progress=progress, cancel=self.cancel,
            )
        ffmpeg.require_ffmpeg()
        return self.yt.download_clip(
            video, clip.start, clip.end, output,
            quality=s.quality, precise=s.precise_cut, progress=progress,
        )


def export_report(results: list[VideoResult], path: Path) -> Path:
    """Gera CSV ou JSON (pela extensão) com todas as ocorrências e links."""
    rows = []
    for r in results:
        for m in r.matches:
            rows.append({
                "video_id": r.video.id,
                "titulo": r.video.title,
                "data": r.video.upload_date or "",
                "termo": m.term,
                "dito": m.spoken,
                "inicio": format_timestamp(m.start),
                "fim": format_timestamp(m.end),
                "link": r.video.link_at(m.start - 2),
                "contexto": m.context,
                "similaridade": m.score,
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["video_id"])
            writer.writeheader()
            writer.writerows(rows)
    return path


def _slug(text: str, limit: int = 80) -> str:
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", text)
    # Remove emojis e símbolos que atrapalham em sistemas de arquivos/editores.
    text = "".join(c for c in text if c.isalnum() or c in " -_.,()[]&'#+!")
    text = " ".join(text.split()).strip(" .")
    return text[:limit].rstrip(" .") or "video"


__all__ = ["Pipeline", "VideoResult", "export_report", "is_local_source", "parse_terms"]
