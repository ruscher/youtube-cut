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


def test_face_flags_scan_export_and_cut(media_dir, tmp_path, monkeypatch, capsys):
    import numpy as np

    from youtube_cut.core import face_detector as fd
    from youtube_cut.core.pipeline import Pipeline

    class Engine:  # a "pessoa" aparece entre 5 e 9 s
        current = 0.0

        def similarity(self, frame, reference):
            return 0.9 if 5.0 <= Engine.current <= 9.0 else 0.0

    real_frames = fd.frames

    def frames(*args, **kwargs):
        for t, frame in real_frames(*args, **kwargs):
            Engine.current = t
            yield t, frame

    monkeypatch.setattr(fd, "frames", frames)
    monkeypatch.setattr(Pipeline, "face_engine", lambda self: Engine())
    monkeypatch.setattr(Pipeline, "face_reference", lambda self: fd.FaceReference(
        self.settings.face_label or "foto", np.ones(128), self.settings.face_photo_list))
    out, faces_json = tmp_path / "cortes", tmp_path / "rosto.json"
    code = main(["scan", str(media_dir["video"]), "--face", str(tmp_path / "barbara.jpg"),
                 "--face-label", "Bárbara", "--face-json", str(faces_json), "--before", "0", "--after", "0",
                 "--cut", "--fast", "-o", str(out)])
    stdout = capsys.readouterr().out
    assert code == 0, stdout
    assert "Rosto de referência: Bárbara" in stdout and "rosto de Bárbara até 0:09" in stdout
    data = json.loads(faces_json.read_text(encoding="utf-8"))
    assert data[0]["blocos"] == [{"start": "00:00:04", "end": "00:00:09", "start_seconds": 4.5,
                                  "end_seconds": 9.5, "similarity": 0.9}]
    assert len(list((out / "rosto Bárbara").glob("*.mp4"))) == 1


def test_ai_flags_map_to_settings_for_this_run_only():
    from youtube_cut.cli import _build_parser, _settings_from_args

    args = _build_parser().parse_args(["scan", "x", "-t", "a", "--whisper", "--whisper-model", "base",
                                       "--face", "f.jpg", "--face-sensitivity", "strict", "--face-fps", "2"])
    s = _settings_from_args(args)
    assert s.whisper_fallback and s.whisper_model == "base"
    assert s.face_enabled and s.face_photo_list[0].endswith("f.jpg")
    assert s.face_threshold == 0.45 and s.face_fps == 2.0
    plain = _settings_from_args(_build_parser().parse_args(["scan", "x", "-t", "a"]))
    assert not plain.face_enabled  # rosto só quando pedido na própria execução
