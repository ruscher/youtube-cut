import fnmatch
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "youtube_cut"


def test_app_icon_is_valid_svg():
    from PySide6.QtSvg import QSvgRenderer

    from youtube_cut.gui.app import APP_ICON

    assert APP_ICON.exists()
    assert QSvgRenderer(str(APP_ICON)).isValid()
    assert (ROOT / "data" / "youtube-cut.svg").read_bytes() == APP_ICON.read_bytes()


def test_desktop_file():
    desktop = ROOT / "data" / "youtube-cut.desktop"
    text = desktop.read_text(encoding="utf-8")
    assert "Exec=youtube-cut" in text and "Icon=youtube-cut" in text
    if shutil.which("desktop-file-validate"):
        result = subprocess.run(["desktop-file-validate", str(desktop)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


def test_package_data_covers_all_gui_files():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = cfg["tool"]["setuptools"]["package-data"]["youtube_cut"]
    gui_files = [p.relative_to(PKG).as_posix() for p in (PKG / "gui" / "qml").rglob("*") if p.is_file()]
    missing = [f for f in gui_files if not any(fnmatch.fnmatch(f, pat) for pat in patterns)]
    assert gui_files and missing == []


def test_entry_point_targets_existing_function():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    module, func = cfg["project"]["scripts"]["youtube-cut"].split(":")
    import importlib

    assert callable(getattr(importlib.import_module(module), func))


@pytest.mark.parametrize("doc", ["README.md", "docs/01-arquitetura.md", "docs/02-design-ux.md",
                                 "docs/03-youtube.md", "docs/04-pipeline-corte.md", "docs/05-instalacao-testes.md"])
def test_docs_exist(doc):
    assert (ROOT / doc).stat().st_size > 500
