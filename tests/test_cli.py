import json
import signal

import pytest

from youtube_cut import __version__
from youtube_cut.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_scan_requires_terms(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["scan", "@canal"])
    assert exc.value.code == 2


def test_scan_local_report_and_cut(media_dir, tmp_path, capsys):
    out, report = tmp_path / "cortes", tmp_path / "rel.json"
    code = main(["scan", str(media_dir["dir"]), "-t", "Bárbara", "--before", "1", "--after", "1",
                 "--report", str(report), "--cut", "-o", str(out), "--hwaccel", "none"])
    stdout = capsys.readouterr().out
    assert code == 0, stdout
    assert "Total: 2 menção(ões)." in stdout
    assert len(json.loads(report.read_text(encoding="utf-8"))) == 2
    assert len(list((out / "Bárbara").glob("*.mp4"))) == 2


def test_scan_fast_mode_flag(media_dir, tmp_path, monkeypatch):
    seen = {}
    import youtube_cut.core.pipeline as pipeline

    def fake_cut(self, video, clip, output, progress=None):
        seen["precise"] = self.settings.precise_cut
        return output

    monkeypatch.setattr(pipeline.Pipeline, "cut", fake_cut)
    assert main(["scan", str(media_dir["video"]), "-t", "barbara", "--cut", "--fast",
                 "-o", str(tmp_path)]) == 0
    assert seen["precise"] is False


def test_scan_no_matches(media_dir, capsys):
    assert main(["scan", str(media_dir["video"]), "-t", "inexistente"]) == 0
    assert "Total: 0 menção(ões)." in capsys.readouterr().out


def test_scan_invalid_source_exit_code(capsys):
    assert main(["scan", "https://example.com/nada", "-t", "x"]) == 1
    assert "Não reconheci" in capsys.readouterr().err


def test_scan_restores_sigint_handler(media_dir):
    before = signal.getsignal(signal.SIGINT)
    main(["scan", str(media_dir["video"]), "-t", "x"])
    assert signal.getsignal(signal.SIGINT) is before


def test_cli_does_not_touch_saved_settings(media_dir):
    from youtube_cut.core.config import SETTINGS_FILE

    main(["scan", str(media_dir["video"]), "-t", "x", "--before", "9"])
    assert not SETTINGS_FILE.exists()  # flags valem só para a execução
