"""Reconhecimento facial: blocos de tempo, quadros do FFmpeg, download verificado e pipeline.

O reconhecimento de verdade (modelos do OpenCV Zoo + fotos de duas pessoas) roda
no teste marcado ``network``; os demais usam um motor falso e são offline.
"""

import hashlib
import json
import shutil
import subprocess
import threading

import pytest

from youtube_cut.core import download
from youtube_cut.core import face_detector as fd
from youtube_cut.core.config import Settings
from youtube_cut.core.models import Match
from youtube_cut.core.pipeline import Pipeline, export_report
from youtube_cut.core.youtube import Cancelled

np = pytest.importorskip("numpy")


# -- blocos de tempo --------------------------------------------------------

def test_segments_group_hits_and_tolerate_short_gaps():
    # 1 amostra/s: rosto de 10 a 14 s com uma falha em 12 s, e de novo de 30 a 33 s
    sims = {t: 0.8 for t in (10, 11, 13, 14, 30, 31, 32, 33)}
    samples = [(float(t), sims.get(t, 0.1)) for t in range(40)]
    segs = fd.segments_from_samples(samples, step=1.0, threshold=0.38)
    assert [(s.start, s.end) for s in segs] == [(9.5, 14.5), (29.5, 33.5)]
    assert all(s.score == 0.8 for s in segs)


def test_segments_split_on_long_gap_and_drop_flicker():
    samples = [(0.0, 0.9), (5.0, 0.5), (6.0, 0.6), (7.0, 0.4)]
    segs = fd.segments_from_samples(samples, step=1.0, threshold=0.38, min_duration=1.5)
    # 0 s sozinho dura 1 s (< 1,5 s): descartado; 5–7 s vira um bloco com a maior similaridade
    assert [(s.start, s.end, s.score) for s in segs] == [(4.5, 7.5, 0.6)]


def test_segments_respect_threshold_boundary_and_order():
    samples = [(3.0, 0.38), (1.0, 0.379), (2.0, 0.5)]
    segs = fd.segments_from_samples(samples, step=1.0, threshold=0.38)
    assert [(s.start, s.end) for s in segs] == [(1.5, 3.5)]


def test_to_json_uses_requested_format():
    data = fd.to_json([fd.FaceSegment(83.2, 105.9, 0.81)])
    assert data == [{"start": "00:01:23", "end": "00:01:45", "start_seconds": 83.2,
                     "end_seconds": 105.9, "similarity": 0.81}]


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "faces" / "x.json"
    segs = [fd.FaceSegment(1.0, 2.5, 0.7)]
    fd.save_cached(path, segs)
    assert fd.load_cached(path) == segs
    assert fd.load_cached(tmp_path / "nao-existe.json") is None


def test_available_reports_status():
    ok, detail = fd.available()
    assert isinstance(ok, bool) and detail


# -- download verificado ----------------------------------------------------

def test_fetch_verifies_sha256_and_never_leaves_partial_files(tmp_path):
    source = tmp_path / "modelo.onnx"
    source.write_bytes(b"pesos" * 1000)
    good = hashlib.sha256(source.read_bytes()).hexdigest()
    dest = tmp_path / "cache" / "modelo.onnx"

    with pytest.raises(download.DownloadError, match="corrompido"):
        download.fetch(source.as_uri(), dest, "0" * 64)
    assert not dest.exists() and not list(dest.parent.glob("*.part"))

    progress = []
    assert download.fetch(source.as_uri(), dest, good, progress=progress.append) == dest
    assert dest.read_bytes() == source.read_bytes() and progress[-1] == 1.0

    source.unlink()  # já baixado e íntegro: não acessa a origem de novo
    assert download.fetch(source.as_uri(), dest, good) == dest


def test_fetch_cancel_and_unreachable(tmp_path):
    source = tmp_path / "grande.bin"
    source.write_bytes(b"x" * (1 << 18))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        download.fetch(source.as_uri(), tmp_path / "out.bin", cancel=cancel)
    assert not (tmp_path / "out.bin.part").exists()
    with pytest.raises(download.DownloadError):
        download.fetch((tmp_path / "sumiu.bin").as_uri(), tmp_path / "y.bin")


# -- quadros do FFmpeg ------------------------------------------------------

def test_frames_are_sampled_scaled_and_timestamped(media_dir):
    items = list(fd.frames(str(media_dir["video"]), fps=1.0))
    assert [t for t, _ in items] == [float(i) for i in range(20)]
    assert items[0][1].shape == (360, 640, 3) and items[0][1].dtype == np.uint8
    later = list(fd.frames(str(media_dir["video"]), fps=2.0, start=15.0))
    assert later[0][0] == 15.0 and later[1][0] == 15.5 and len(later) == 10


def test_frames_bad_source_raises(tmp_path):
    with pytest.raises(fd.FaceError, match="FFmpeg"):
        list(fd.frames(str(tmp_path / "nada.mp4")))


def test_frames_stop_on_cancel(media_dir):
    cancel = threading.Event()
    gen = fd.frames(str(media_dir["video"]), fps=1.0, cancel=cancel)
    next(gen)
    cancel.set()
    with pytest.raises(Cancelled):
        next(gen)


# -- varredura com motor falso ----------------------------------------------

class FakeEngine:
    """Similaridade alta entre 5 e 9 s (a pessoa "aparece" nesse intervalo)."""

    def __init__(self):
        self.frames = 0
        self.current = 0.0

    def similarity(self, frame, reference):
        self.frames += 1
        return 0.9 if 5.0 <= self.current <= 9.0 else 0.05


def _fake_reference(label="Bárbara"):
    return fd.FaceReference(label, np.ones(128) / np.sqrt(128), ["foto.jpg"], "")


def test_scan_resumes_after_stream_interruption(monkeypatch):
    engine = FakeEngine()
    opened = []

    def fake_frames(source, fps, start, headers, cancel):
        opened.append((source, start))
        t = start
        while t < 12.0:
            if len(opened) == 1 and t >= 4.0:  # a primeira URL "expira" aos 4 s
                raise fd.FaceError("conexão recusada")
            engine.current = t
            yield t, None
            t += 1 / fps

    monkeypatch.setattr(fd, "frames", fake_frames)
    urls = iter(["https://googlevideo/1", "https://googlevideo/2"])
    logs = []
    segs = fd.scan(engine, _fake_reference(), lambda: (next(urls), {}), fps=1.0, duration=12.0, log=logs.append)
    assert opened == [("https://googlevideo/1", 0.0), ("https://googlevideo/2", 4.0)]
    assert engine.frames == 12  # nenhum segundo analisado duas vezes nem pulado
    assert [(s.start, s.end) for s in segs] == [(4.5, 9.5)]
    assert any("retomando" in m for m in logs)


def test_scan_gives_up_after_retries(monkeypatch):
    def broken(*a, **k):
        raise fd.FaceError("sempre falha")
        yield  # pragma: no cover

    monkeypatch.setattr(fd, "frames", broken)
    with pytest.raises(fd.FaceError, match="sempre falha"):
        fd.scan(FakeEngine(), _fake_reference(), lambda: ("x", None), retries=2)


@pytest.fixture
def face_pipeline(monkeypatch, tmp_path):
    """Pipeline com rosto ativado e motor falso que acompanha o tempo do quadro real."""
    engine = FakeEngine()
    real_frames = fd.frames

    def tracking_frames(*args, **kwargs):
        for t, frame in real_frames(*args, **kwargs):
            engine.current = t
            yield t, frame

    monkeypatch.setattr(fd, "frames", tracking_frames)
    monkeypatch.setattr(Pipeline, "face_engine", lambda self: engine)
    monkeypatch.setattr(Pipeline, "face_reference", lambda self: _fake_reference())
    settings = Settings(face_enabled=True, face_photos=str(tmp_path / "foto.jpg"), before=1, after=1)
    return engine, settings


def test_pipeline_combines_speech_and_face_matches(media_dir, face_pipeline):
    engine, settings = face_pipeline
    pipe = Pipeline(settings)
    [r] = pipe.discover(str(media_dir["video"]))
    statuses = []
    pipe.scan(r, ["Bárbara"], on_change=lambda res: statuses.append(res.status))

    assert "faces" in statuses and r.status == "done"
    assert [m.kind for m in r.matches] == ["speech", "face", "speech"]  # ordem do vídeo
    face = r.face_matches[0]
    assert (face.term, face.start, face.end, face.score) == ("Rosto: Bárbara", 4.5, 9.5, 0.9)
    assert len(pipe.clips_for(r)) == 2  # menção em 3,3 s funde com o rosto (4,5–9,5 s)

    # nova busca de texto mantém os trechos do rosto
    pipe.search(r, ["obrigado"])
    assert [m.kind for m in r.matches] == ["face", "speech"]

    # a varredura do rosto fica em cache: não decodifica de novo
    frames_before = engine.frames
    r.face_matches = []
    Pipeline(settings).scan(r, ["Bárbara"])
    assert engine.frames == frames_before and len(r.face_matches) == 1


def test_face_only_search_without_subtitle_and_report(media_dir, face_pipeline, tmp_path):
    _engine, settings = face_pipeline
    video = tmp_path / "sem legenda.mp4"
    shutil.copy(media_dir["video"], video)
    pipe = Pipeline(settings)
    [r] = pipe.discover(str(video))
    pipe.scan(r, [])
    assert r.status == "nosubs" and len(r.matches) == 1 and r.matches[0].is_face
    rows = json.loads(export_report([r], tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rows[0]["tipo"] == "rosto" and rows[0]["termo"] == "Rosto: Bárbara"


def test_face_failure_keeps_speech_matches(media_dir, monkeypatch, tmp_path):
    def broken(self):
        raise fd.FaceError("foto sem rosto")

    monkeypatch.setattr(Pipeline, "face_reference", broken)
    pipe = Pipeline(Settings(face_enabled=True, face_photos=str(tmp_path / "x.jpg")))
    [r] = pipe.discover(str(media_dir["video"]))
    pipe.scan(r, ["Bárbara"])
    assert r.status == "error" and "foto sem rosto" in r.error
    assert len(r.matches) == 2 and not any(m.is_face for m in r.matches)


def test_faces_not_requested_without_photos(media_dir, monkeypatch):
    monkeypatch.setattr(Pipeline, "scan_faces", lambda *a, **k: pytest.fail("sem fotos não procura rosto"))
    pipe = Pipeline(Settings(face_enabled=True, face_photos=""))
    [r] = pipe.discover(str(media_dir["video"]))
    pipe.scan(r, ["Bárbara"])
    assert r.status == "done"


def test_match_kind_defaults_to_speech():
    m = Match("v", "x", 1.0, 2.0, "x")
    assert m.kind == "speech" and not m.is_face


# -- reconhecimento real (modelos do OpenCV Zoo) -----------------------------

@pytest.mark.network
def test_real_recognition_finds_the_right_person(tmp_path):
    ok, detail = fd.available()
    if not ok:
        pytest.skip(detail)
    samples = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/"
    lena = download.fetch(samples + "lena.jpg", tmp_path / "lena.jpg")
    messi = download.fetch(samples + "messi5.jpg", tmp_path / "messi5.jpg")
    video = tmp_path / "pessoas.mp4"
    # Lena 0–4 s, Messi 4–8 s, Lena menor e fora do centro 8–12 s
    fit = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-t", "4", "-i", str(lena),
         "-loop", "1", "-t", "4", "-i", str(messi), "-loop", "1", "-t", "4", "-i", str(lena),
         "-filter_complex", (f"[0]{fit}[a];[1]{fit}[b];[2]scale=480:-2,pad=1280:720:700:150,setsar=1,fps=25[c];"
                             "[a][b][c]concat=n=3:v=1[v]"),
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )
    engine = fd.FaceEngine(*fd.ensure_models(tmp_path / "models"))
    reference = engine.reference([lena], "Lena", preview_dir=tmp_path / "prev")
    assert reference.preview.endswith(".png")
    segs = fd.scan(engine, reference, lambda: (str(video), None), fps=2.0, duration=12.0)
    assert [(s.start, s.end) for s in segs] == [(0.0, 3.75), (7.75, 11.75)]
    assert all(s.score > 0.7 for s in segs)
    messi_ref = engine.reference([messi], "Messi")
    assert float(np.dot(messi_ref.embedding, reference.embedding)) < 0.3
