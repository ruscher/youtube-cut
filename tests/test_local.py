import csv
import json
import threading
import time

import pytest

from youtube_cut.core import ffmpeg
from youtube_cut.core.config import Settings
from youtube_cut.core.models import Clip, Match, VideoInfo
from youtube_cut.core.pipeline import Pipeline, VideoResult, _slug, export_report, is_local_source


def test_is_local_source(media_dir):
    assert is_local_source(str(media_dir["video"]))
    assert is_local_source(media_dir["video"].as_uri())
    assert not is_local_source("@biglinux")
    assert not is_local_source("")


def test_discover_file_and_folder(media_dir):
    pipe = Pipeline(Settings())
    (single,) = pipe.discover(str(media_dir["video"]))
    assert single.video.is_local
    assert single.video.title == "Live [teste] #1"
    assert single.video.duration == pytest.approx(20, abs=0.2)

    folder = pipe.discover(str(media_dir["dir"]))
    assert [r.video.title for r in folder] == ["Live [teste] #1"]  # .vtt não entra como vídeo


def test_find_subtitle_handles_glob_characters(media_dir):
    sub = ffmpeg.find_subtitle_for(media_dir["video"])
    assert sub is not None and sub.name == "Live [teste] #1.pt.vtt"


def test_scan_local_finds_both_spellings(media_dir):
    pipe = Pipeline(Settings())
    (r,) = pipe.discover(str(media_dir["video"]))
    pipe.scan(r, ["Bárbara"])
    assert r.status == "done"
    assert [m.spoken for m in r.matches] == ["Bárbara", "Barbara!"]
    assert r.subtitle == "Live [teste] #1.pt.vtt"


def test_scan_embedded_subtitle(media_dir):
    pipe = Pipeline(Settings())
    (r,) = pipe.discover(str(media_dir["mkv"]))
    pipe.scan(r, ["barbara"])
    assert r.status == "done", r.error
    assert r.subtitle == "legenda embutida"
    assert len(r.matches) == 1 and 5 <= r.matches[0].start < 7


def test_scan_without_subtitle_marks_nosubs(media_dir, tmp_path):
    lonely = tmp_path / "sem-legenda.mp4"
    lonely.write_bytes(media_dir["video"].read_bytes())
    pipe = Pipeline(Settings())
    (r,) = pipe.discover(str(lonely))
    pipe.scan(r, ["x"])
    assert r.status == "nosubs"


@pytest.mark.parametrize("precise", [True, False])
def test_cut_local(media_dir, tmp_path, precise):
    out = tmp_path / f"corte-{precise}.mp4"
    progress = []
    ffmpeg.cut_local(media_dir["video"], 5.0, 9.0, out, precise=precise, hwaccel="none",
                     progress=progress.append)
    assert out.exists() and out.stat().st_size > 0
    duration = ffmpeg.probe_duration(out)
    # stream copy começa no keyframe anterior, então só exigimos precisão no modo preciso
    assert duration == pytest.approx(4.0, abs=0.15 if precise else 10)


def test_cut_local_vaapi_falls_back_to_cpu(media_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg, "RENDER_NODE", tmp_path / "nao-existe")
    out = tmp_path / "vaapi.mp4"
    ffmpeg.cut_local(media_dir["video"], 1.0, 3.0, out, precise=True, hwaccel="vaapi")
    assert ffmpeg.probe_duration(out) == pytest.approx(2.0, abs=0.15)


def test_cut_local_cancel_before_start(media_dir, tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        ffmpeg.cut_local(media_dir["video"], 0, 15, tmp_path / "c.mp4", hwaccel="none", cancel=cancel)
    assert not (tmp_path / "c.mp4").exists()


def test_cut_local_cancel_midway_is_fast_and_cleans_up(media_dir, tmp_path):
    cancel = threading.Event()
    out = tmp_path / "meio.mp4"
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(InterruptedError):
        # reencode lento de propósito para ainda estar rodando quando cancelar
        ffmpeg.cut_local(media_dir["video"], 0, 20, out, hwaccel="none", cancel=cancel,
                         progress=lambda _f: time.sleep(0.2))
    assert time.monotonic() - started < 1.5
    assert not out.exists()


def test_cut_local_error_message(tmp_path):
    bogus = tmp_path / "nao-e-video.mp4"
    bogus.write_text("lixo")
    with pytest.raises(ffmpeg.FFmpegError):
        ffmpeg.cut_local(bogus, 0, 1, tmp_path / "x.mp4", hwaccel="none")


def test_pipeline_cut_local_end_to_end(media_dir, tmp_path):
    s = Settings(output_dir=str(tmp_path / "saida"), before=1, after=1)
    pipe = Pipeline(s)
    (r,) = pipe.discover(str(media_dir["video"]))
    pipe.scan(r, ["Bárbara"])
    clips = pipe.clips_for(r)
    assert len(clips) == 2
    paths = [pipe.cut(r.video, c, pipe.output_path(r.video, c, ["Bárbara"])) for c in clips]
    assert all(p.exists() for p in paths)
    assert paths[0].parent.name == "Bárbara"


def test_output_path_and_slug():
    s = Settings(output_dir="/tmp/yc")
    video = VideoInfo("abc", "🔴 LIVE: 🚀 #02 O PODER / BigLinux?", "u", upload_date="20260927")
    path = Pipeline(s).output_path(video, Clip("abc", 3723.4, 3730), ["Bárbara", "Ana"])
    assert path.as_posix() == "/tmp/yc/Bárbara Ana/2026-09-27 LIVE #02 O PODER BigLinux - 01h02m03s.mp4"
    assert _slug("...") == "video"
    assert len(_slug("a" * 300, 60)) == 60


def _results():
    v = VideoInfo("vid12345678", "Live", "https://www.youtube.com/watch?v=vid12345678", upload_date="20260101")
    m = Match("vid12345678", "Bárbara", 65.0, 65.6, "Bárbara", "oi", "tudo bem", 0.9)
    return [VideoResult(v, status="done", matches=[m]), VideoResult(VideoInfo("x", "Vazio", "u"))]


def test_export_report_csv(tmp_path):
    path = export_report(_results(), tmp_path / "r.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["link"] == "https://youtu.be/vid12345678?t=63"
    assert rows[0]["inicio"] == "00:01:05.000"
    assert rows[0]["contexto"] == "oi Bárbara tudo bem"


def test_export_report_json_and_empty(tmp_path):
    data = json.loads(export_report(_results(), tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data[0]["similaridade"] == 0.9
    empty = export_report([], tmp_path / "vazio.csv")
    assert empty.read_text(encoding="utf-8").strip() == "video_id"


@pytest.mark.skipif(not ffmpeg.vaapi_available(), reason="sem VA-API nesta máquina")
def test_cut_local_real_vaapi(media_dir, tmp_path):
    out = tmp_path / "gpu.mp4"
    ffmpeg.cut_local(media_dir["video"], 2.0, 6.0, out, precise=True, hwaccel="vaapi")
    assert ffmpeg.probe_duration(out) == pytest.approx(4.0, abs=0.15)
