"""Legenda de reserva (Whisper local): formato, motores e integração com o pipeline.

Os motores de verdade (faster-whisper, whisper.cpp) são substituídos por falsos
que imitam a interface real; o áudio passa pelo FFmpeg de verdade.
"""

import shutil
import stat
import sys
import types

import pytest

from youtube_cut.core import subtitles_fallback as sf
from youtube_cut.core.config import Settings
from youtube_cut.core.models import Word
from youtube_cut.core.pipeline import Pipeline
from youtube_cut.core.subtitles import parse_subtitle_text


def _words(text, start=1.0, step=0.4):
    return [Word(round(start + i * step, 3), round(start + i * step + 0.35, 3), t) for i, t in enumerate(text.split())]


# -- formato ----------------------------------------------------------------

def test_words_to_vtt_round_trips_through_the_subtitle_parser():
    words = _words("hoje a Bárbara vai a a explicar o projeto e a Bárbara volta já")
    back = parse_subtitle_text(sf.words_to_vtt(words, per_cue=5))
    assert [w.text for w in back] == [w.text for w in words]  # inclusive palavras repetidas ("a a")
    assert [w.start for w in back] == [w.start for w in words]


def test_words_to_vtt_empty():
    assert parse_subtitle_text(sf.words_to_vtt([])) == []


def test_parse_word_cues_rounds_and_skips_blank_cues():
    vtt = ("WEBVTT\n\n00:00:00.010 --> 00:00:00.490\n Bom\n\n00:00:00.490 --> 00:00:00.990\n\n\n"
           "00:00:01.140 --> 00:00:01.100\n dia\n")
    words = sf.parse_word_cues(vtt)
    assert words == [Word(0.01, 0.49, "Bom"), Word(1.14, 1.14, "dia")]  # fim nunca antes do início


def test_cache_path_includes_model():
    assert sf.cache_path(__import__("pathlib").Path("/c"), "vid", "pt", "small").name == "vid.pt.whisper-small.vtt"


# -- escolha do motor -------------------------------------------------------

def _engines(monkeypatch, fw: bool, cpp: bool):
    monkeypatch.setattr(sf, "engines", lambda: [sf.EngineInfo("faster-whisper", fw, ""),
                                                 sf.EngineInfo("whisper.cpp", cpp, "")])


def test_pick_engine_order_and_preference(monkeypatch):
    _engines(monkeypatch, True, True)
    assert sf.pick_engine() == "faster-whisper"
    assert sf.pick_engine("whisper.cpp") == "whisper.cpp"
    _engines(monkeypatch, False, True)
    assert sf.pick_engine("faster-whisper") == "whisper.cpp"
    _engines(monkeypatch, False, False)
    assert sf.pick_engine() is None


def test_transcribe_without_engine_explains_how_to_install(monkeypatch, tmp_path):
    _engines(monkeypatch, False, False)
    with pytest.raises(sf.TranscriptionError, match="whisper-cpp"):
        sf.transcribe(tmp_path / "a.wav")


def test_transcribe_rejects_unknown_model(tmp_path):
    with pytest.raises(sf.TranscriptionError, match="Modelo desconhecido"):
        sf.transcribe(tmp_path / "a.wav", model="enorme")


# -- faster-whisper (módulo falso) ------------------------------------------

@pytest.fixture
def fake_faster_whisper(monkeypatch):
    """faster_whisper/ctranslate2 falsos: a GPU falha como sem libcublas e a CPU funciona."""
    calls = []

    class Model:
        def __init__(self, name, device, compute_type, download_root):
            self.device = device
            calls.append((name, device, compute_type))

        def transcribe(self, audio, language, word_timestamps, vad_filter):
            assert word_timestamps and vad_filter and language == "pt"
            assert audio.dtype.name == "float32" and audio.size > 16000  # áudio real via FFmpeg
            if self.device == "cuda":
                raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
            w = types.SimpleNamespace
            segments = [w(end=3.0, words=[w(word=" Hoje", start=1.0, end=1.4), w(word=" a", start=1.4, end=1.5),
                                          w(word=" Bárbara", start=1.5, end=2.1)]),
                        w(end=6.0, words=[w(word=" chegou.", start=2.2, end=2.9), w(word="  ", start=3, end=3)])]
            return iter(segments), w(duration=20.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model, __version__="9.9"))
    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=lambda: 1))
    sf._fw_model.cache_clear()
    yield calls
    sf._fw_model.cache_clear()


def test_faster_whisper_falls_back_to_cpu_and_reports_progress(fake_faster_whisper, media_dir, tmp_path):
    logs, progress = [], []
    words = sf.transcribe(media_dir["video"], "pt", "base", engine="faster-whisper",
                          models_dir=tmp_path, log=logs.append, progress=progress.append)
    assert [w.text for w in words] == ["Hoje", "a", "Bárbara", "chegou."]
    assert words[2] == Word(1.5, 2.1, "Bárbara")
    assert [c[1] for c in fake_faster_whisper] == ["cuda", "cpu"]
    assert fake_faster_whisper[1][2] == "int8"
    assert any("bibliotecas CUDA ausentes" in m for m in logs)
    assert progress == [0.15, 0.3] and all(type(p) is float for p in progress)


def test_faster_whisper_engine_info_mentions_missing_cuda_libs(fake_faster_whisper, monkeypatch):
    monkeypatch.setattr(sf, "_cuda_runtime_loadable", lambda: False)
    info = sf._faster_whisper_info()
    assert info.available and "9.9" in info.detail and "CUDA 12" in info.detail


# -- whisper.cpp (binário falso) --------------------------------------------

FAKE_WHISPER_CLI = r"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
out = args[args.index("-of") + 1]
assert "-ml" in args and args[args.index("-ml") + 1] == "1" and "-sow" in args and "-ovtt" in args
assert args[args.index("-l") + 1] == "pt"
sys.stderr.write("whisper_init: carregando\nprogress = 50%\nprogress = 100%\n")
open(out + ".vtt", "w").write(
    "WEBVTT\n\n00:00:01.000 --> 00:00:01.400\n Oi\n\n00:00:01.400 --> 00:00:02.000\n Bárbara\n")
"""


def test_whisper_cpp_uses_packaged_model_and_parses_word_cues(media_dir, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    cli = bindir / "whisper-cli"
    cli.write_text(FAKE_WHISPER_CLI)
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}:{__import__('os').environ['PATH']}")
    models = tmp_path / "share" / "whisper.cpp-model-tiny"
    models.mkdir(parents=True)
    (models / "ggml-tiny.bin").write_bytes(b"modelo")
    monkeypatch.setattr(sf, "_GGML_SYSTEM_DIRS", (str(tmp_path / "share" / "whisper.cpp-model-{model}"),))
    monkeypatch.setattr(sf.download, "fetch", lambda *a, **k: pytest.fail("não deveria baixar o modelo"))
    _engines(monkeypatch, False, True)

    progress = []
    words = sf.transcribe(media_dir["video"], "pt", "tiny", progress=progress.append)
    assert words == [Word(1.0, 1.4, "Oi"), Word(1.4, 2.0, "Bárbara")]
    assert progress == [0.5, 1.0]


def test_whisper_cpp_failure_is_reported(media_dir, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    cli = bindir / "whisper-cli"
    cli.write_text("#!/bin/sh\necho 'GGML_ASSERT(device) failed' >&2\nexit 3\n")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{__import__('os').environ['PATH']}")
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "ggml-tiny.bin").write_bytes(b"x")
    monkeypatch.setattr(sf, "_GGML_SYSTEM_DIRS", (str(tmp_path / "m"),))
    _engines(monkeypatch, False, True)
    with pytest.raises(sf.TranscriptionError, match="código 3.*GGML_ASSERT"):
        sf.transcribe(media_dir["video"], "pt", "tiny")


# -- integração com o pipeline ----------------------------------------------

@pytest.fixture
def bare_video(media_dir, tmp_path):
    """O vídeo de teste sem a legenda ao lado (nem embutida)."""
    video = tmp_path / "sem legenda.mp4"
    shutil.copy(media_dir["video"], video)
    return video


def test_pipeline_without_fallback_reports_nosubs(bare_video):
    pipe = Pipeline(Settings())
    [r] = pipe.discover(str(bare_video))
    pipe.scan(r, ["Bárbara"])
    assert r.status == "nosubs" and r.matches == []


def test_pipeline_transcribes_when_no_subtitle_and_caches_result(bare_video, monkeypatch):
    calls = []

    def fake_transcribe(media, language, model, **kwargs):
        calls.append((media.name, language, model))
        kwargs["progress"](0.5)
        return _words("bom dia hoje a Bárbara chegou", start=4.0)

    monkeypatch.setattr(sf, "pick_engine", lambda preferred="auto": "faster-whisper")
    monkeypatch.setattr(sf, "transcribe", fake_transcribe)
    settings = Settings(whisper_fallback=True, whisper_model="base")
    statuses = []
    pipe = Pipeline(settings)
    [r] = pipe.discover(str(bare_video))
    pipe.scan(r, ["Bárbara"], on_change=lambda res: statuses.append(res.status))

    assert calls == [("sem legenda.mp4", "pt", "base")]
    assert "transcribing" in statuses
    assert r.status == "done" and r.subtitle == "transcrição local · Whisper base"
    assert [(m.spoken, m.start) for m in r.matches] == [("Bárbara", 5.6)]

    # nova busca (outro Pipeline, palavras descartadas): vem do cache, sem transcrever de novo
    r.words, r.status = [], "pending"
    Pipeline(settings).scan(r, ["Bárbara"])
    assert len(calls) == 1 and r.status == "done" and len(r.matches) == 1


def test_pipeline_transcription_without_speech_is_nosubs(bare_video, monkeypatch):
    monkeypatch.setattr(sf, "pick_engine", lambda preferred="auto": "whisper.cpp")
    monkeypatch.setattr(sf, "transcribe", lambda *a, **k: [])
    pipe = Pipeline(Settings(whisper_fallback=True))
    [r] = pipe.discover(str(bare_video))
    pipe.scan(r, ["x"])
    assert r.status == "nosubs"


def test_pipeline_transcription_error_marks_video(bare_video, monkeypatch):
    def boom(*a, **k):
        raise sf.TranscriptionError("motor quebrou")

    monkeypatch.setattr(sf, "pick_engine", lambda preferred="auto": "whisper.cpp")
    monkeypatch.setattr(sf, "transcribe", boom)
    pipe = Pipeline(Settings(whisper_fallback=True))
    [r] = pipe.discover(str(bare_video))
    pipe.scan(r, ["x"])
    assert r.status == "error" and "motor quebrou" in r.error


def test_native_subtitle_wins_over_fallback(media_dir, monkeypatch):
    monkeypatch.setattr(sf, "transcribe", lambda *a, **k: pytest.fail("havia legenda; não deveria transcrever"))
    monkeypatch.setattr(sf, "pick_engine", lambda preferred="auto": "faster-whisper")
    pipe = Pipeline(Settings(whisper_fallback=True))
    [r] = pipe.discover(str(media_dir["video"]))
    pipe.scan(r, ["Bárbara"])
    assert r.status == "done" and len(r.matches) == 2


def test_decode_audio_is_float32_mono_16k_and_cancellable(media_dir):
    import threading

    from youtube_cut.core.youtube import Cancelled

    audio = sf.decode_audio(media_dir["video"], threading.Event())
    assert audio.dtype.name == "float32" and abs(audio.size - 20 * sf.SAMPLE_RATE) < sf.SAMPLE_RATE
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        sf.decode_audio(media_dir["video"], cancel)
