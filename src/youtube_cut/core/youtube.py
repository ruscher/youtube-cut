"""Integração com o YouTube via yt-dlp.

Em vez de automatizar o navegador no YouTube Studio (frágil: seletores mudam,
o Chrome bloqueia o perfil em uso e o Google barra logins automatizados),
usamos o yt-dlp para:

* listar os vídeos/lives de um canal;
* baixar UMA faixa de legenda por vídeo (manual ou automática);
* baixar apenas o trecho necessário de cada vídeo, sem baixar a live inteira.

Vídeos privados/não listados funcionam com ``cookies_browser`` (os cookies da
sessão logada no navegador são lidos localmente pelo yt-dlp).
"""

from __future__ import annotations

import re
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import VideoInfo

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError, download_range_func
except ImportError:  # pragma: no cover - verificado em tempo de execução
    yt_dlp = None


class YouTubeError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


_CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")
_VIDEO_ID = re.compile(r"^[\w-]{11}$")
_STUDIO_TABS = {"live": "streams", "upload": "videos", "short": "shorts", "shorts": "shorts"}


@dataclass(slots=True)
class Source:
    kind: str  # channel | video | playlist
    url: str


def resolve_source(text: str, default_tab: str = "streams") -> Source:
    """Normaliza o que o usuário colou: link do Studio, canal, @handle, vídeo..."""
    text = text.strip()
    if not text:
        raise YouTubeError("Informe um canal, vídeo ou playlist do YouTube.")

    if _CHANNEL_ID.match(text):
        return Source("channel", f"https://www.youtube.com/channel/{text}/{default_tab}")
    if text.startswith("@"):
        return Source("channel", f"https://www.youtube.com/{text}/{default_tab}")
    if _VIDEO_ID.match(text):
        return Source("video", f"https://www.youtube.com/watch?v={text}")

    if not re.match(r"^https?://", text):
        text = "https://" + text

    if m := re.search(r"studio\.youtube\.com/video/([\w-]{11})", text):
        return Source("video", f"https://www.youtube.com/watch?v={m.group(1)}")
    if m := re.search(r"studio\.youtube\.com/channel/(UC[\w-]{22})(?:/videos/?(\w+)?)?", text):
        tab = _STUDIO_TABS.get(m.group(2) or "", default_tab)
        return Source("channel", f"https://www.youtube.com/channel/{m.group(1)}/{tab}")

    if m := re.search(r"(?:youtu\.be/|[?&]v=|/(?:live|shorts|embed)/)([\w-]{11})", text):
        return Source("video", f"https://www.youtube.com/watch?v={m.group(1)}")
    if m := re.search(r"[?&]list=([\w-]+)", text):
        return Source("playlist", f"https://www.youtube.com/playlist?list={m.group(1)}")

    m = re.search(r"youtube\.com/((?:channel/[\w-]+|@[^/?#]+|c/[^/?#]+|user/[^/?#]+))(/[^?#]*)?", text)
    if m:
        tab = (m.group(2) or "").strip("/").split("/")[0]
        if tab not in ("streams", "videos", "shorts"):
            tab = default_tab
        return Source("channel", f"https://www.youtube.com/{m.group(1)}/{tab}")

    raise YouTubeError(f"Não reconheci este endereço do YouTube: {text}")


@dataclass(slots=True)
class SubtitleTrack:
    path: Path
    language: str
    automatic: bool


class _QuietLogger:
    """Encaminha mensagens do yt-dlp para um callback, em vez do terminal."""

    def __init__(self, sink: Callable[[str], None] | None):
        self.sink = sink

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        if self.sink and "Falling back" not in msg:
            self.sink(f"Aviso: {msg}")

    def error(self, msg: str) -> None:
        pass  # erros chegam como exceção (DownloadError) e são tratados por quem chamou


def _video_format(quality: str) -> str:
    if quality == "best" or not quality.isdigit():
        return "bv*+ba/b"
    h = int(quality)
    # Prefere H.264/AAC (abre em qualquer editor/player); cai para o melhor disponível.
    return (
        f"bv*[height<={h}][vcodec^=avc1]+ba[ext=m4a]/"
        f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
    )


class YouTubeClient:
    MIN_INTERVAL = 1.5  # segundos entre consultas de vídeo

    def __init__(
        self,
        cookies_browser: str = "",
        allow_remote_ejs: bool = False,
        log: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ):
        if yt_dlp is None:
            raise YouTubeError(
                "yt-dlp não está instalado. Instale com: sudo pacman -S yt-dlp"
            )
        self.cookies_browser = cookies_browser
        self.allow_remote_ejs = allow_remote_ejs
        self.log = log
        self.cancel = cancel or threading.Event()
        self._last_request = 0.0

    # -- opções -----------------------------------------------------------

    def _base_opts(self) -> dict:
        opts: dict = {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "logger": _QuietLogger(self.log),
            "retries": 5,
            "extractor_retries": 3,
        }
        runtimes = {name: {} for name in ("deno", "node", "bun") if shutil.which(name)}
        if runtimes:
            opts["js_runtimes"] = runtimes
        if self.allow_remote_ejs:
            opts["remote_components"] = ["ejs:github"]
        if self.cookies_browser:
            opts["cookiesfrombrowser"] = (self.cookies_browser, None, None, None)
        return opts

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def _sleep(self, seconds: float) -> None:
        if self.cancel.wait(seconds):
            raise Cancelled()

    def _throttle(self) -> None:
        """Espaça as consultas ao YouTube para não tomar HTTP 429."""
        self._check_cancel()
        wait = self.MIN_INTERVAL - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()

    # -- listagem ---------------------------------------------------------

    def list_videos(self, source: Source, limit: int = 0) -> list[VideoInfo]:
        opts = self._base_opts() | {"extract_flat": "in_playlist", "skip_download": True}
        if limit:
            opts["playlistend"] = limit
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(source.url, download=False)
        except DownloadError as e:
            raise YouTubeError(_friendly_error(e)) from e

        entries = info.get("entries") if info.get("_type") == "playlist" else [info]
        videos: list[VideoInfo] = []
        for entry in entries or []:
            if not entry or not entry.get("id"):
                continue
            if entry.get("live_status") in ("is_upcoming", "is_live"):
                continue  # ainda não há transcrição para lives em andamento/agendadas
            videos.append(
                VideoInfo(
                    id=entry["id"],
                    title=entry.get("title") or entry["id"],
                    url=f"https://www.youtube.com/watch?v={entry['id']}",
                    duration=entry.get("duration"),
                    upload_date=entry.get("upload_date"),
                    live_status=entry.get("live_status"),
                )
            )
        return videos

    # -- legendas ---------------------------------------------------------

    def fetch_subtitle(
        self, video: VideoInfo, language: str, cache_dir: Path
    ) -> SubtitleTrack | None:
        """Baixa a melhor faixa de legenda do vídeo (com cache em disco)."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        for auto in (False, True):
            cached = cache_dir / f"{video.id}.{language}.{'auto' if auto else 'manual'}.vtt"
            if cached.exists() and cached.stat().st_size > 0:
                return SubtitleTrack(cached, language, auto)
        none_marker = cache_dir / f"{video.id}.{language}.none"
        if none_marker.exists() and time.time() - none_marker.stat().st_mtime < 86400:
            return None

        self._throttle()
        try:
            with yt_dlp.YoutubeDL(self._base_opts() | {"skip_download": True}) as ydl:
                info = ydl.extract_info(video.url, download=False)
                if info.get("duration"):
                    video.duration = info["duration"]
                choice = _choose_track(
                    info.get("subtitles") or {}, info.get("automatic_captions") or {}, language
                )
                if not choice:
                    none_marker.touch()
                    return None
                lang, auto, url = choice
                data = self._download_text(ydl, url)
        except DownloadError as e:
            raise YouTubeError(_friendly_error(e)) from e

        path = cache_dir / f"{video.id}.{language}.{'auto' if auto else 'manual'}.vtt"
        path.write_text(data, encoding="utf-8")
        return SubtitleTrack(path, lang, auto)

    def _download_text(self, ydl, url: str) -> str:
        delays = (4, 12, 30, 60)
        for attempt in range(len(delays) + 1):
            self._check_cancel()
            try:
                return ydl.urlopen(url).read().decode("utf-8", "replace")
            except Exception as e:  # yt-dlp encapsula HTTPError de formas variadas
                status = getattr(e, "status", None) or getattr(getattr(e, "cause", None), "status", None)
                if status != 429 or attempt == len(delays):
                    raise YouTubeError(f"Falha ao baixar legenda: {e}") from e
                if self.log:
                    self.log(f"YouTube limitou as requisições (429); aguardando {delays[attempt]}s…")
                self._sleep(delays[attempt])
        raise AssertionError("unreachable")

    # -- mídia para análise local (transcrição e rostos) -------------------

    def download_audio(self, video: VideoInfo, dest_dir: Path) -> Path:
        """Baixa só o áudio, na menor qualidade boa para fala (~50 kbps)."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        opts = self._base_opts() | {
            "format": "ba[abr<=80]/wa[abr>=32]/ba/b",
            "outtmpl": {"default": str(dest_dir / f"{video.id}.%(ext)s")},
            "noplaylist": True,
            "overwrites": True,
            "progress_hooks": [lambda _d: self._check_cancel()],
        }
        self._throttle()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video.url, download=True)
                path = Path(ydl.prepare_filename(info))
        except DownloadError as e:
            if isinstance(e.exc_info[1] if e.exc_info else None, Cancelled):
                raise Cancelled() from e
            raise YouTubeError(_friendly_error(e)) from e
        if not path.exists():
            raise YouTubeError("O yt-dlp terminou sem gerar o arquivo de áudio.")
        return path

    def video_stream(self, video: VideoInfo, max_height: int = 360) -> tuple[str, dict[str, str]]:
        """URL direta de um stream só de vídeo, em baixa resolução, e os cabeçalhos
        HTTP para o FFmpeg lê-lo sem salvar o vídeo em disco."""
        opts = self._base_opts() | {
            "skip_download": True,
            "format": f"bv*[height<={max_height}]/wv*/b[height<={max_height}]/w",
        }
        self._throttle()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video.url, download=False)
        except DownloadError as e:
            raise YouTubeError(_friendly_error(e)) from e
        chosen = (info.get("requested_formats") or [info])[0]
        if not chosen.get("url"):
            raise YouTubeError("O YouTube não ofereceu um stream de vídeo para analisar.")
        if info.get("duration"):
            video.duration = info["duration"]
        return chosen["url"], dict(chosen.get("http_headers") or info.get("http_headers") or {})

    # -- download de trechos ----------------------------------------------

    def download_clip(
        self,
        video: VideoInfo,
        start: float,
        end: float,
        output: Path,
        quality: str = "1080",
        precise: bool = True,
        progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Baixa só o intervalo [start, end] do vídeo para ``output`` (.mp4)."""
        output.parent.mkdir(parents=True, exist_ok=True)

        def hook(d: dict) -> None:
            self._check_cancel()
            if progress and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    progress(min(1.0, d.get("downloaded_bytes", 0) / total))
                elif d.get("elapsed") is not None and (end - start) > 0:
                    progress(-1.0)  # progresso indeterminado

        opts = self._base_opts() | {
            "format": _video_format(quality),
            "outtmpl": {"default": str(output.with_suffix("")) + ".%(ext)s"},
            "download_ranges": download_range_func(None, [(start, end)]),
            "force_keyframes_at_cuts": precise,
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
            "noplaylist": True,
            "overwrites": True,
        }
        if precise:
            # Reencoda só o trecho baixado (poucos segundos): corte no quadro exato.
            opts["external_downloader_args"] = {
                "ffmpeg_o": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
            }
        # O googlevideo às vezes recusa a conexão no meio do trecho (403/ffmpeg
        # código 8). Uma nova extração gera URLs novas e quase sempre resolve.
        delays = (3, 10)
        for attempt in range(len(delays) + 1):
            self._throttle()
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(video.url, download=True)
                    final = Path(ydl.prepare_filename(info))
                break
            except DownloadError as e:
                if isinstance(e.exc_info[1] if e.exc_info else None, Cancelled):
                    raise Cancelled() from e
                if attempt == len(delays):
                    raise YouTubeError(_friendly_error(e)) from e
                if self.log:
                    self.log(f"Falha temporária ao baixar o trecho; nova tentativa em {delays[attempt]}s…")
                self._sleep(delays[attempt])

        for candidate in (final.with_suffix(".mp4"), final):
            if candidate.exists():
                return candidate
        matches = sorted(output.parent.glob(output.stem + ".*"))
        if matches:
            return matches[0]
        raise YouTubeError("O yt-dlp terminou sem gerar o arquivo do trecho.")


def _choose_track(manual: dict, automatic: dict, language: str) -> tuple[str, bool, str] | None:
    def vtt_url(tracks: list[dict]) -> str | None:
        for t in tracks:
            if t.get("ext") == "vtt" and t.get("url"):
                return t["url"]
        return None

    def ranked(keys: list[str], prefer: list[str]) -> list[str]:
        exact = [k for k in prefer if k in keys]
        regional = sorted(k for k in keys if k.split("-")[0] == language and k not in exact)
        return exact + regional

    for key in ranked(list(manual), [language]):
        if url := vtt_url(manual[key]):
            return key, False, url
    # "xx-orig" é a transcrição original (com tempo por palavra); as demais
    # faixas automáticas são traduções. Em vídeo de outro idioma, preferimos a
    # original: nomes próprios aparecem nela e com tempo exato.
    if url := vtt_url(automatic.get(f"{language}-orig", [])):
        return f"{language}-orig", True, url
    for key in automatic:
        if key.endswith("-orig") and (url := vtt_url(automatic[key])):
            return key, True, url
    for key in ranked(list(automatic), [language]):
        if url := vtt_url(automatic[key]):
            return key, True, url
    return None


def _friendly_error(e: Exception) -> str:
    msg = str(e).removeprefix("ERROR: ")
    if "Sign in to confirm" in msg or "not a bot" in msg:
        return ("O YouTube pediu confirmação de login. Em Configurações, escolha o "
                "navegador onde você está logado para usar os cookies dele.")
    if "Private video" in msg or "members-only" in msg:
        return "Vídeo privado/restrito: selecione o navegador logado em Configurações."
    if "ffmpeg exited with code" in msg:
        return "O YouTube interrompeu o download do trecho. Tente cortar novamente em instantes."
    if "could not find" in msg.lower() and "cookies" in msg.lower():
        return "Não encontrei os cookies do navegador selecionado. Ele está instalado e logado?"
    return msg
