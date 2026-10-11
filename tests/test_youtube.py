"""Cliente do YouTube testado sem rede: o yt-dlp é substituído por um dublê."""

import os
import sys
import time
from types import SimpleNamespace

import pytest
from yt_dlp.utils import DownloadError

import youtube_cut.core.youtube as yt
from youtube_cut.core.models import VideoInfo


class FakeYDL:
    """Imita ``yt_dlp.YoutubeDL``; o comportamento vem de ``FakeYDL.script``."""

    script: dict = {}
    calls: list = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        FakeYDL.calls.append(("extract", url, download, self.opts))
        step = self.script["extract"]
        result = step(self.opts) if callable(step) else step
        if isinstance(result, BaseException):
            raise result
        return result

    def urlopen(self, url):
        FakeYDL.calls.append(("urlopen", url))
        result = self.script["urlopen"].pop(0)
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(read=lambda: result.encode())

    def prepare_filename(self, info):
        return self.opts["outtmpl"]["default"].replace("%(ext)s", "mp4")


@pytest.fixture
def client(monkeypatch):
    FakeYDL.script, FakeYDL.calls = {}, []
    monkeypatch.setattr(yt, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))
    logs = []
    c = yt.YouTubeClient(log=logs.append)
    c.sleeps = []
    monkeypatch.setattr(c, "_sleep", c.sleeps.append)
    c.logs = logs
    return c


def _video():
    return VideoInfo("abcdefghijk", "Live", "https://www.youtube.com/watch?v=abcdefghijk")


VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\noi Bárbara\n"


def test_list_videos_filters_upcoming_and_passes_limit(client):
    FakeYDL.script["extract"] = {
        "_type": "playlist",
        "entries": [
            {"id": "aaaaaaaaaaa", "title": "Passada", "duration": 3600, "live_status": "was_live"},
            {"id": "bbbbbbbbbbb", "title": "Agendada", "live_status": "is_upcoming"},
            {"id": "ccccccccccc", "title": "No ar", "live_status": "is_live"},
            None,
            {"id": "ddddddddddd"},
        ],
    }
    videos = client.list_videos(yt.Source("channel", "https://www.youtube.com/@x/streams"), limit=5)
    assert [(v.id, v.title) for v in videos] == [("aaaaaaaaaaa", "Passada"), ("ddddddddddd", "ddddddddddd")]
    opts = FakeYDL.calls[0][3]
    assert opts["playlistend"] == 5 and opts["extract_flat"] == "in_playlist"


def test_list_videos_single_video(client):
    FakeYDL.script["extract"] = {"id": "abcdefghijk", "title": "Um", "duration": 10}
    (v,) = client.list_videos(yt.Source("video", "u"))
    assert v.url == "https://www.youtube.com/watch?v=abcdefghijk"


def test_list_videos_friendly_error(client):
    FakeYDL.script["extract"] = DownloadError("ERROR: Sign in to confirm you're not a bot")
    with pytest.raises(yt.YouTubeError, match="navegador"):
        client.list_videos(yt.Source("channel", "u"))


def test_fetch_subtitle_downloads_once_then_uses_cache(client, tmp_path):
    FakeYDL.script["extract"] = {"duration": 99, "subtitles": {},
                                 "automatic_captions": {"pt-orig": [{"ext": "vtt", "url": "U"}]}}
    FakeYDL.script["urlopen"] = [VTT]
    video = _video()
    track = client.fetch_subtitle(video, "pt", tmp_path)
    assert track.automatic and track.language == "pt-orig"
    assert track.path.read_text(encoding="utf-8") == VTT
    assert video.duration == 99

    FakeYDL.calls.clear()
    again = client.fetch_subtitle(_video(), "pt", tmp_path)
    assert again.path == track.path and FakeYDL.calls == []


def test_fetch_subtitle_none_marker_expires(client, tmp_path):
    FakeYDL.script["extract"] = {"subtitles": {}, "automatic_captions": {}}
    assert client.fetch_subtitle(_video(), "pt", tmp_path) is None
    FakeYDL.calls.clear()
    assert client.fetch_subtitle(_video(), "pt", tmp_path) is None
    assert FakeYDL.calls == []  # marcador recente: nem consulta

    marker = tmp_path / "abcdefghijk.pt.none"
    old = time.time() - 2 * 86400
    os.utime(marker, (old, old))
    client.fetch_subtitle(_video(), "pt", tmp_path)
    assert len(FakeYDL.calls) == 1  # marcador vencido: consulta de novo


def _http_error(status):
    e = RuntimeError(f"HTTP Error {status}")
    e.status = status
    return e


def test_fetch_subtitle_retries_on_429(client, tmp_path):
    FakeYDL.script["extract"] = {"subtitles": {"pt": [{"ext": "vtt", "url": "U"}]}}
    FakeYDL.script["urlopen"] = [_http_error(429), _http_error(429), VTT]
    track = client.fetch_subtitle(_video(), "pt", tmp_path)
    assert not track.automatic
    assert client.sleeps == [4, 12]
    assert any("429" in m for m in client.logs)


def test_fetch_subtitle_gives_up_after_retries(client, tmp_path):
    FakeYDL.script["extract"] = {"subtitles": {"pt": [{"ext": "vtt", "url": "U"}]}}
    FakeYDL.script["urlopen"] = [_http_error(429)] * 5
    with pytest.raises(yt.YouTubeError, match="legenda"):
        client.fetch_subtitle(_video(), "pt", tmp_path)


def test_fetch_subtitle_other_http_error_is_not_retried(client, tmp_path):
    FakeYDL.script["extract"] = {"subtitles": {"pt": [{"ext": "vtt", "url": "U"}]}}
    FakeYDL.script["urlopen"] = [_http_error(404)]
    with pytest.raises(yt.YouTubeError):
        client.fetch_subtitle(_video(), "pt", tmp_path)
    assert client.sleeps == []


def test_throttle_spaces_requests(client, tmp_path):
    FakeYDL.script["extract"] = {"subtitles": {}, "automatic_captions": {}}
    client.fetch_subtitle(VideoInfo("aaaaaaaaaaa", "a", "u"), "pt", tmp_path)
    client.fetch_subtitle(VideoInfo("bbbbbbbbbbb", "b", "u"), "pt", tmp_path)
    assert len(client.sleeps) == 1 and 0 < client.sleeps[0] <= client.MIN_INTERVAL


def _write_output(opts):
    path = opts["outtmpl"]["default"].replace("%(ext)s", "mp4")
    open(path, "wb").write(b"video")
    return {"id": "abcdefghijk"}


def test_download_clip_options_and_retry(client, tmp_path):
    attempts = []

    def extract(opts):
        attempts.append(opts)
        if len(attempts) == 1:
            return DownloadError("ERROR: ffmpeg exited with code 8")
        return _write_output(opts)

    FakeYDL.script["extract"] = extract
    out = client.download_clip(_video(), 10.0, 18.5, tmp_path / "c" / "trecho.mp4", quality="720")
    assert out == tmp_path / "c" / "trecho.mp4" and out.exists()
    assert len(attempts) == 2 and 3 in client.sleeps
    opts = attempts[-1]
    assert opts["force_keyframes_at_cuts"] is True
    assert "libx264" in opts["external_downloader_args"]["ffmpeg_o"]
    assert "height<=720" in opts["format"]
    assert list(opts["download_ranges"](  # intervalo pedido chega ao yt-dlp
        {"duration": 100}, None)) == [{"start_time": 10.0, "end_time": 18.5}]


def test_download_clip_fast_mode_skips_reencode(client, tmp_path):
    FakeYDL.script["extract"] = _write_output
    client.download_clip(_video(), 0, 5, tmp_path / "f.mp4", precise=False)
    opts = FakeYDL.calls[-1][3]
    assert opts["force_keyframes_at_cuts"] is False and "external_downloader_args" not in opts


def test_download_clip_fails_after_retries(client, tmp_path):
    FakeYDL.script["extract"] = DownloadError("ERROR: ffmpeg exited with code 8")
    with pytest.raises(yt.YouTubeError, match="interrompeu"):
        client.download_clip(_video(), 0, 5, tmp_path / "x.mp4")
    assert client.sleeps.count(3) == 1 and client.sleeps.count(10) == 1


def test_download_clip_cancel_inside_hook(client, tmp_path):
    def extract(opts):
        try:
            raise yt.Cancelled()
        except yt.Cancelled:
            return DownloadError("ERROR: cancel", exc_info=sys.exc_info())

    FakeYDL.script["extract"] = extract
    with pytest.raises(yt.Cancelled):
        client.download_clip(_video(), 0, 5, tmp_path / "x.mp4")


def test_cancel_event_stops_before_request(client, tmp_path):
    client.cancel.set()
    FakeYDL.script["extract"] = {"subtitles": {}}
    with pytest.raises(yt.Cancelled):
        client.fetch_subtitle(_video(), "pt", tmp_path)


def test_base_opts(monkeypatch):
    monkeypatch.setattr(yt, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))
    monkeypatch.setattr(yt.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    opts = yt.YouTubeClient(cookies_browser="firefox", allow_remote_ejs=True)._base_opts()
    assert opts["js_runtimes"] == {"node": {}}
    assert opts["cookiesfrombrowser"] == ("firefox", None, None, None)
    assert opts["remote_components"] == ["ejs:github"]
    plain = yt.YouTubeClient()._base_opts()
    assert "cookiesfrombrowser" not in plain and "remote_components" not in plain


def test_missing_yt_dlp_has_install_hint(monkeypatch):
    monkeypatch.setattr(yt, "yt_dlp", None)
    with pytest.raises(yt.YouTubeError, match="pacman"):
        yt.YouTubeClient()


@pytest.mark.parametrize(("raw", "expected"), [
    ("ERROR: Private video. Sign in", "privado"),
    ("ERROR: could not find firefox cookies database", "cookies"),
    ("ERROR: algo estranho", "algo estranho"),
])
def test_friendly_error(raw, expected):
    assert expected in yt._friendly_error(Exception(raw))


@pytest.mark.network
def test_real_channel_and_subtitle(tmp_path):
    c = yt.YouTubeClient()
    videos = c.list_videos(yt.resolve_source("UCJZUvE04sPBhwVVuk5g9bUg"), limit=2)
    assert len(videos) == 2
    track = c.fetch_subtitle(videos[0], "pt", tmp_path)
    assert track is None or track.path.stat().st_size > 0
