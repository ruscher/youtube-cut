"""Interface testada sem tela (QT_QPA_PLATFORM=offscreen, backend de software)."""

import os
import time

import pytest

os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import youtube_cut.core.config as config  # noqa: E402
from youtube_cut.core.config import Settings  # noqa: E402
from youtube_cut.core.models import Clip, Match, VideoInfo  # noqa: E402
from youtube_cut.core.pipeline import VideoResult  # noqa: E402
from youtube_cut.gui.backend import Backend  # noqa: E402
from youtube_cut.gui.icons import IconProvider  # noqa: E402
from youtube_cut.gui.models import ClipItem, ClipListModel, VideoListModel  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def wait_until(condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not condition():
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if time.monotonic() > deadline:
            raise AssertionError("tempo esgotado esperando a condição")
        time.sleep(0.01)


def role_value(model, row, name):
    roles = {bytes(v).decode(): k for k, v in model.roleNames().items()}
    return model.data(model.index(row), roles[name])


@pytest.fixture
def backend(qapp):
    b = Backend()
    b.setConfig("hwaccel", "none")
    b.toasts = []
    b.toast.connect(lambda msg, kind, action: b.toasts.append((msg, kind, action)))
    yield b
    b.shutdown()


# -- modelos --------------------------------------------------------------

def _result(vid="vid12345678", n=2):
    v = VideoInfo(vid, f"Live {vid}", f"https://www.youtube.com/watch?v={vid}",
                  duration=3725, upload_date="20260927")
    matches = [Match(vid, "Bárbara", 60.0 * (i + 1), 60.0 * (i + 1) + 0.5, "Bárbara",
                     "oi <script>", "tudo", 1.0 if i == 0 else 0.84) for i in range(n)]
    return VideoResult(v, status="done", matches=matches, subtitle="pt-orig · automática")


def test_video_model_roles(qapp):
    m = VideoListModel()
    m.set_results([_result()])
    assert m.count == 1
    assert role_value(m, 0, "matchCount") == 2
    assert role_value(m, 0, "durationText") == "1:02:05"
    assert role_value(m, 0, "dateText") == "27/09/2026"
    assert role_value(m, 0, "thumbnail") == "https://i.ytimg.com/vi/vid12345678/mqdefault.jpg"


def test_clip_model_roles_escape_html_and_use_cut_state(qapp):
    r = _result()
    m = ClipListModel()
    m.set_items([ClipItem(r, Clip(r.video.id, 57, 66, [r.matches[0]]))])
    assert "cutState" in {bytes(v).decode() for v in m.roleNames().values()}
    assert "state" not in {bytes(v).decode() for v in m.roleNames().values()}
    assert role_value(m, 0, "contextHtml") == "oi &lt;script&gt; <b>Bárbara</b> tudo"
    assert role_value(m, 0, "startText") == "0:57"
    assert role_value(m, 0, "link") == "https://youtu.be/vid12345678?t=58"


def test_clip_model_filter_and_checked_counts(qapp):
    a, b = _result("aaaaaaaaaaa"), _result("bbbbbbbbbbb", 1)
    m = ClipListModel()
    items = [ClipItem(a, Clip(a.video.id, 0, 10, a.matches)), ClipItem(b, Clip(b.video.id, 0, 5, b.matches))]
    m.set_items(items)
    assert (m.count, m.checkedCount, m.checkedSeconds) == (2, 2, 15)
    m.set_filter("bbbbbbbbbbb")
    assert m.count == 1 and role_value(m, 0, "videoId") == "bbbbbbbbbbb"
    m.set_all_checked(False)  # só os visíveis
    assert m.checkedCount == 1
    m.set_filter("")
    m.set_checked(1, True)
    assert m.checkedCount == 2


# -- ícones ---------------------------------------------------------------

def test_icon_provider_renders_colored_icon(qapp):
    img = IconProvider().requestImage("scissors/22d3ee", QSize(), QSize(32, 32))
    assert (img.width(), img.height()) == (32, 32)
    colors = {img.pixelColor(x, y).name() for x in range(32) for y in range(32)
              if img.pixelColor(x, y).alpha() > 200}
    assert "#22d3ee" in colors


def test_icon_provider_alpha_and_unknown_name(qapp):
    img = IconProvider().requestImage("nao-existe/80ffffff", QSize(), QSize(16, 16))
    assert not img.isNull()
    alphas = [img.pixelColor(x, y).alpha() for x in range(16) for y in range(16)]
    assert 0 < max(alphas) <= 140  # 0x80 de opacidade aplicada


# -- backend --------------------------------------------------------------

def test_set_config_persists_and_coerces(backend):
    backend.setConfig("before", "7")
    backend.setConfig("max_videos", 12.0)
    backend.setConfig("nao_existe", 1)
    backend.setConfig("after", "abc")  # inválido: ignorado
    saved = Settings.load()
    assert saved.before == 7.0 and saved.max_videos == 12
    assert backend.config["after"] == 5.0
    assert config.SETTINGS_FILE.exists()


def test_start_scan_validates_input(backend):
    backend.startScan("", "Bárbara")
    backend.startScan("@canal", " , ")
    assert [k for _, k, _ in backend.toasts] == ["error", "error"]
    assert not backend.busy


def test_scan_cut_and_refresh_local(backend, media_dir):
    backend.setConfig("before", 1)
    backend.setConfig("after", 1)
    backend.startScan(str(media_dir["dir"]), "Bárbara")
    assert backend.busy
    wait_until(lambda: not backend.busy)
    assert backend.toasts[-1][1] == "success", backend.toasts
    assert backend.videos.count == 1 and backend.totalMatches == 2
    assert backend.clips.count == 2 and backend.clips.checkedCount == 2
    assert Settings.load().terms == "Bárbara"

    # margem maior junta os dois trechos (3 s e 15 s) em um só
    backend.setConfig("after", 12)
    assert backend.clips.count == 1
    backend.setConfig("after", 1)

    backend.setClipChecked(1, False)
    backend.cutSelected()
    wait_until(lambda: not backend.busy)
    msg, kind, action = backend.toasts[-1]
    assert (kind, action) == ("success", "open-folder"), msg
    states = [role_value(backend.clips, i, "cutState") for i in range(2)]
    assert states == ["done", ""]
    assert backend.clips.checkedCount == 0  # cortado sai da seleção
    assert os.path.exists(role_value(backend.clips, 0, "output"))

    backend.refreshSearch("inexistente")  # sem rede: só refaz a busca
    wait_until(lambda: not backend.busy)
    assert backend.clips.count == 0 and backend.totalMatches == 0


def test_filter_video_toggles(backend, media_dir):
    backend.startScan(str(media_dir["video"]), "Bárbara")
    wait_until(lambda: not backend.busy)
    vid = backend.videos.results[0].video.id
    backend.filterVideo(vid)
    assert backend.videoFilter == vid and backend.videoFilterTitle == "Live [teste] #1"
    backend.filterVideo(vid)
    assert backend.videoFilter == "" and backend.videoFilterTitle == ""


def test_cancel_scan(backend, media_dir, monkeypatch):
    import youtube_cut.core.pipeline as pipeline

    original = pipeline.Pipeline.scan

    def slow_scan(self, result, terms):
        time.sleep(0.3)
        original(self, result, terms)

    monkeypatch.setattr(pipeline.Pipeline, "scan", slow_scan)
    backend.startScan(str(media_dir["video"]), "Bárbara")
    backend.cancel()
    wait_until(lambda: not backend.busy)
    assert backend.toasts[-1][0] == "Operação cancelada."


# -- QML ------------------------------------------------------------------

def test_main_qml_loads_without_warnings(backend, tmp_path):
    from youtube_cut.gui.app import create_engine

    messages = []
    try:
        engine = create_engine(backend, messages)
        assert engine.rootObjects(), messages
        window = engine.rootObjects()[0]
        for _ in range(20):
            QCoreApplication.processEvents()
        image = window.grabWindow()
        image.save(str(tmp_path / "janela.png"))
        assert image.width() >= 960
        # alterna o tema e abre as configurações para exercitar todos os componentes
        backend.setConfig("theme", "light")
        window.setProperty("settingsOpen", True)
        for _ in range(20):
            QCoreApplication.processEvents()
        window.close()
    finally:
        pass
    assert messages == []


def test_engine_keeps_backend_alive(qapp):
    import gc

    from youtube_cut.gui.app import create_engine

    messages = []
    engine = create_engine(Backend(), messages)  # sem guardar o backend de propósito
    gc.collect()
    for _ in range(10):
        QCoreApplication.processEvents()
    assert engine.rootObjects() and messages == []
    engine.backend.shutdown()
    del engine


# -- IA local -------------------------------------------------------------

def _face_result(vid="vid12345678"):
    r = _result(vid, n=1)
    face = Match(vid, "Rosto: Bárbara", 300.0, 320.0, "Bárbara", score=0.82, kind="face")
    r.face_matches = [face]
    r.matches = sorted(r.matches + [face], key=lambda m: m.start)
    return r


def test_video_model_ai_roles(qapp):
    model = VideoListModel()
    r = _face_result()
    bare = VideoResult(VideoInfo("semlegenda1", "Sem legenda", "https://youtu.be/x"), status="nosubs")
    model.set_results([r, bare])
    assert role_value(model, 0, "speechCount") == 1 and role_value(model, 0, "faceCount") == 1
    assert role_value(model, 0, "progress") == -1.0
    assert role_value(model, 1, "canTranscribe") is False  # sem motor instalado
    model.transcriber_available = True
    assert role_value(model, 1, "canTranscribe") is True
    assert role_value(model, 0, "canTranscribe") is False  # já tem legenda


def test_clip_model_face_clip_has_its_own_score_and_context(qapp):
    r = _face_result()
    model = ClipListModel()
    face_clip = Clip(r.video.id, 299.0, 321.0, [r.face_matches[0]])
    mixed = Clip(r.video.id, 59.0, 66.0, [r.matches[0], Match(r.video.id, "Rosto: Bárbara", 60.0, 64.0,
                                                              "Bárbara", score=0.7, kind="face")])
    model.set_items([ClipItem(r, face_clip), ClipItem(r, mixed)])
    assert role_value(model, 0, "kind") == "face"
    assert role_value(model, 0, "contextHtml") == "<b>Bárbara</b> aparece no vídeo"
    assert role_value(model, 0, "score") == 1.0  # nada de "≈ %" de transcrição em trecho de rosto
    assert role_value(model, 0, "faceScore") == 0.82
    assert role_value(model, 1, "kind") == "mixed"
    assert "<b>Bárbara</b>" in role_value(model, 1, "contextHtml") and "oi" in role_value(model, 1, "contextHtml")


def test_start_scan_needs_terms_or_active_face(backend):
    backend.startScan("@canal", "")
    assert not backend.busy and "IA local" in backend.toasts[-1][0]


def test_transcribe_video_without_engine_explains(backend):
    backend.videos.set_results([VideoResult(VideoInfo("semlegenda1", "x", "https://youtu.be/x"), status="nosubs")])
    backend._ai = {**backend._ai, "transcriber": ""}
    backend.transcribeVideo(0)
    assert not backend.busy and "whisper-cpp" in backend.toasts[-1][0]


def test_face_reference_flow(backend, tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtCore import QUrl

    from youtube_cut.core import face_detector as fd
    from youtube_cut.core.pipeline import Pipeline

    preview = tmp_path / "rosto.png"
    preview.write_bytes(b"png")
    monkeypatch.setattr(Pipeline, "face_reference", lambda self: fd.FaceReference(
        self.settings.face_label, np.ones(128), self.settings.face_photo_list, str(preview)))
    wait_until(lambda: backend.aiStatus["ready"])
    backend._ai = {**backend._ai, "facesAvailable": True}

    photo = tmp_path / "barbara_silva.jpg"
    backend.setFacePhotos([QUrl.fromLocalFile(str(photo))])
    wait_until(lambda: backend.faceInfo["state"] == "ready")
    assert backend.faceInfo["label"] == "barbara silva" and backend.faceInfo["photos"] == 1
    assert backend.faceInfo["preview"].startswith("file://")
    assert backend.config["face_enabled"] and backend.faceSearchActive

    backend.setConfig("face_enabled", False)
    assert not backend.faceSearchActive
    backend.clearFace()
    assert backend.faceInfo["state"] == "" and backend.config["face_photos"] == ""


def test_face_reference_error_is_shown_and_disables_face_search(backend, tmp_path, monkeypatch):
    from youtube_cut.core import face_detector as fd
    from youtube_cut.core.pipeline import Pipeline

    def no_face(self):
        raise fd.FaceError("Nenhum rosto encontrado em gato.jpg.")

    monkeypatch.setattr(Pipeline, "face_reference", no_face)
    wait_until(lambda: backend.aiStatus["ready"])
    backend._ai = {**backend._ai, "facesAvailable": True}
    backend.setFacePhotos([str(tmp_path / "gato.jpg")])
    wait_until(lambda: backend.faceInfo["state"] == "error")
    assert "gato.jpg" in backend.faceInfo["message"] and not backend.faceSearchActive


def test_activity_console_keeps_recent_lines_without_repeats(backend):
    backend.clearLog()
    backend._set_status("Analisando 1 de 2")
    backend._set_status("Analisando 1 de 2")
    backend._set_status("Pronto")
    lines = backend.logModel.stringList()
    assert [ln[10:] for ln in lines] == ["Analisando 1 de 2", "Pronto"]
    for i in range(600):
        backend._log(f"linha {i}")
    assert len(backend.logModel.stringList()) == 500
    backend.clearLog()
    assert backend.logModel.stringList() == []


def test_ai_drawer_renders_in_both_themes(backend, tmp_path):
    from youtube_cut.gui.app import create_engine

    messages = []
    engine = create_engine(backend, messages)
    window = engine.rootObjects()[0]
    drawer = window.findChild(QObject, "aiDrawer")
    assert drawer is not None
    for theme in ("dark", "light"):
        backend.setConfig("theme", theme)
        drawer.setProperty("visible", True)
        for _ in range(30):
            QCoreApplication.processEvents()
        assert not window.grabWindow().isNull()
    drawer.setProperty("visible", False)
    window.close()
    assert messages == []
