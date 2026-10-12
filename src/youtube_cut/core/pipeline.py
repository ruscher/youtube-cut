"""Orquestra descoberta de vídeos, busca nas legendas e cortes.

Usado tanto pela CLI quanto pela interface gráfica. Nada aqui depende de Qt.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import face_detector, ffmpeg, subtitles_fallback
from .clips import build_clips
from .config import CACHE_DIR, SUBTITLE_CACHE, Settings
from .models import Clip, Match, VideoInfo, Word
from .search import find_matches, parse_terms
from .subtitles import load_subtitle
from .timefmt import format_timestamp
from .youtube import Source, YouTubeClient, resolve_source

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts", ".flv"}

# Avisa a interface que o estado/progresso de um vídeo mudou (chamado na thread do worker).
OnChange = Callable[["VideoResult"], None]


@dataclass
class VideoResult:
    video: VideoInfo
    # pending | scanning | transcribing | faces | done | nosubs | error
    status: str = "pending"
    words: list[Word] = field(default_factory=list, repr=False)
    matches: list[Match] = field(default_factory=list)  # fala + rosto, na ordem do vídeo
    face_matches: list[Match] = field(default_factory=list)
    subtitle: str = ""  # descrição da faixa usada, ex.: "pt-orig · automática"
    error: str = ""
    progress: float = -1.0  # progresso da etapa longa atual (transcrição/rostos); -1 = sem medida

    @property
    def has_subtitles(self) -> bool:
        return bool(self.words)


def local_path(text: str) -> Path | None:
    """Caminho local (aceita ``file://`` com %-codificação) ou None se não existir."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("file://"):
        text = unquote(urlparse(text).path)
    path = Path(text).expanduser()
    return path.resolve() if path.exists() else None


def is_local_source(text: str) -> bool:
    return local_path(text) is not None


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
        self._faces: face_detector.FaceEngine | None = None
        self._reference: face_detector.FaceReference | None = None

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
        path = local_path(text)
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

    def load_words(self, result: VideoResult, on_change: OnChange | None = None) -> None:
        """Carrega a legenda do vídeo; sem legenda, transcreve localmente se ativado."""
        if self._load_native(result):
            return
        if self.settings.whisper_fallback and subtitles_fallback.pick_engine():
            self.transcribe(result, on_change)
        else:
            result.status = "nosubs"

    def _load_native(self, result: VideoResult) -> bool:
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
                return False
            result.words = load_subtitle(sub)
            result.subtitle = label
            return True

        track = self.yt.fetch_subtitle(video, self.settings.language, SUBTITLE_CACHE)
        if track is None:
            return False
        result.words = load_subtitle(track.path)
        kind = "automática" if track.automatic else "manual"
        result.subtitle = f"{track.language} · {kind}"
        return True

    def transcribe(self, result: VideoResult, on_change: OnChange | None = None) -> None:
        """Gera a legenda no computador (Whisper) e carrega as palavras.

        O resultado fica em cache como VTT: repetir a busca não transcreve de novo.
        """
        s, video = self.settings, result.video
        cached = subtitles_fallback.cache_path(SUBTITLE_CACHE, video.id, s.language, s.whisper_model)
        if not cached.exists():
            result.status, result.progress = "transcribing", -1.0
            _notify(on_change, result)
            if video.is_local:
                media = Path(video.local_path)
            else:
                self.log(f"Baixando o áudio de “{video.title}” para transcrever…")
                media = self.yt.download_audio(video, CACHE_DIR / "audio")
            try:
                words = subtitles_fallback.transcribe(
                    media, s.language, s.whisper_model, models_dir=CACHE_DIR / "models",
                    log=self.log, cancel=self.cancel, progress=_throttled(result, on_change),
                )
            finally:
                if not video.is_local:
                    media.unlink(missing_ok=True)  # o áudio só serve para a transcrição
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(subtitles_fallback.words_to_vtt(words), encoding="utf-8")
        result.words = load_subtitle(cached)
        result.subtitle = f"transcrição local · Whisper {s.whisper_model}"
        result.progress = -1.0
        result.status = "scanning" if result.words else "nosubs"

    def search(self, result: VideoResult, terms: list[str]) -> None:
        text = find_matches(result.words, terms, result.video.id, self.settings.fuzzy) if result.words else []
        result.matches = sorted(text + result.face_matches, key=lambda m: m.start)
        if result.status not in ("nosubs", "error"):
            result.status = "done"

    def scan(self, result: VideoResult, terms: list[str], on_change: OnChange | None = None) -> None:
        result.status, result.error = "scanning", ""
        try:
            if not result.words:
                self.load_words(result, on_change)
            self.search(result, terms)
        except Exception as e:  # um vídeo com problema não deve parar a varredura
            if self.cancel.is_set():
                raise
            result.status = "error"
            result.error = str(e)
        if self.faces_requested:
            self.scan_faces(result, on_change)

    # -- rostos -----------------------------------------------------------

    @property
    def faces_requested(self) -> bool:
        return self.settings.face_enabled and bool(self.settings.face_photo_list)

    def face_engine(self) -> face_detector.FaceEngine:
        if self._faces is None:
            ok, detail = face_detector.available()
            if not ok:
                raise face_detector.FaceError(detail)
            detector, recognizer = face_detector.ensure_models(CACHE_DIR / "models", self.log, self.cancel)
            self._faces = face_detector.FaceEngine(detector, recognizer)
        return self._faces

    def face_reference(self) -> face_detector.FaceReference:
        """Referência montada a partir das fotos das configurações (uma vez por execução)."""
        if self._reference is None:
            s = self.settings
            self._reference = self.face_engine().reference(
                [Path(p) for p in s.face_photo_list], s.face_label,
                preview_dir=CACHE_DIR / "faces" / "previews",
            )
        return self._reference

    def scan_faces(self, result: VideoResult, on_change: OnChange | None = None) -> None:
        """Marca os momentos em que a pessoa da referência aparece no vídeo.

        Uma falha aqui não apaga as menções faladas já encontradas.
        """
        s, video = self.settings, result.video
        previous = result.status
        try:
            reference = self.face_reference()
            cache = face_detector.cache_file(CACHE_DIR / "faces", video.id, reference,
                                             s.face_fps, s.face_threshold)
            segments = face_detector.load_cached(cache)
            if segments is None:
                result.status, result.progress = "faces", 0.0
                _notify(on_change, result)
                if video.is_local:
                    def open_source():
                        return video.local_path, None
                else:
                    def open_source():
                        return self.yt.video_stream(video)
                segments = face_detector.scan(
                    self.face_engine(), reference, open_source, s.face_fps, s.face_threshold,
                    video.duration, _throttled(result, on_change), self.cancel, self.log,
                )
                face_detector.save_cached(cache, segments)
        except Exception as e:
            if self.cancel.is_set():
                raise
            result.status, result.error, result.progress = "error", f"Reconhecimento facial: {e}", -1.0
            return
        result.face_matches = [
            Match(video.id, f"Rosto: {reference.label}", seg.start, seg.end, reference.label,
                  score=seg.score, kind="face")
            for seg in segments
        ]
        speech = [m for m in result.matches if not m.is_face]
        result.matches = sorted(speech + result.face_matches, key=lambda m: m.start)
        result.progress = -1.0
        result.status = previous if previous in ("done", "nosubs", "error") else "done"

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
                "tipo": "rosto" if m.is_face else "fala",
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


def _notify(on_change: OnChange | None, result: VideoResult) -> None:
    if on_change is not None:
        on_change(result)


def _throttled(result: VideoResult, on_change: OnChange | None, interval: float = 0.25) -> Callable[[float], None]:
    """Callback de progresso que atualiza ``result.progress`` e avisa no máximo 4x/s."""
    last = 0.0

    def update(fraction: float) -> None:
        nonlocal last
        result.progress = fraction
        now = time.monotonic()
        if now - last >= interval:
            last = now
            _notify(on_change, result)

    return update


def _slug(text: str, limit: int = 80) -> str:
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", text)
    # Remove emojis e símbolos que atrapalham em sistemas de arquivos/editores.
    text = "".join(c for c in text if c.isalnum() or c in " -_.,()[]&'#+!")
    text = " ".join(text.split()).strip(" .")
    return text[:limit].rstrip(" .") or "video"


__all__ = ["Pipeline", "VideoResult", "export_report", "is_local_source", "parse_terms"]
