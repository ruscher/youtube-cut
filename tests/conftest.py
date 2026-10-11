import os
import shutil
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", help="roda testes que acessam o YouTube")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: acessa a internet (use --run-network)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="precisa de --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path, monkeypatch):
    """Cada teste usa config/cache próprios; nada toca o ~/.config do usuário."""
    import youtube_cut.core.config as config
    import youtube_cut.core.pipeline as pipeline

    cfg, cache = tmp_path / "config", tmp_path / "cache"
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(config, "SETTINGS_FILE", cfg / "settings.json")
    monkeypatch.setattr(config, "CACHE_DIR", cache)
    monkeypatch.setattr(config, "SUBTITLE_CACHE", cache / "subtitles")
    monkeypatch.setattr(pipeline, "CACHE_DIR", cache)
    monkeypatch.setattr(pipeline, "SUBTITLE_CACHE", cache / "subtitles")
    monkeypatch.setattr(config, "default_output_dir", lambda: tmp_path / "out")
    return tmp_path


SAMPLE_VTT = """WEBVTT

00:00:02.000 --> 00:00:04.000
Olá pessoal, hoje a Bárbara

00:00:04.000 --> 00:00:06.000
vai explicar o projeto.

00:00:14.000 --> 00:00:16.000
Obrigado, Barbara!
"""


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    """Pasta com um vídeo sintético de 20 s + legenda ao lado, e um MKV com legenda embutida."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg não instalado")
    d = tmp_path_factory.mktemp("media")
    video = d / "Live [teste] #1.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=20",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "250", "-c:a", "aac", "-shortest", str(video)],
        check=True,
    )
    (d / "Live [teste] #1.pt.vtt").write_text(SAMPLE_VTT, encoding="utf-8")

    embedded_dir = tmp_path_factory.mktemp("embedded")
    srt = embedded_dir / "s.srt"
    srt.write_text("1\n00:00:05,000 --> 00:00:07,000\na Bárbara chegou\n", encoding="utf-8")
    mkv = embedded_dir / "embutida.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(srt),
         "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt", str(mkv)],
        check=True,
    )
    srt.unlink()
    return {"dir": d, "video": video, "mkv": mkv, "mkv_dir": embedded_dir}
