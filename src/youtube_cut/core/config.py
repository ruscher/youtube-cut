"""Configurações persistentes e diretórios (padrão XDG)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_ID = "youtube-cut"


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback) / APP_ID


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config")
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache")
SUBTITLE_CACHE = CACHE_DIR / "subtitles"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


def default_output_dir() -> Path:
    try:
        videos = subprocess.run(
            ["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=2
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        videos = ""
    base = Path(videos) if videos and Path(videos) != Path.home() else Path.home() / "Vídeos"
    return base / "YouTube Cut"


@dataclass
class Settings:
    source: str = ""
    terms: str = ""
    language: str = "pt"
    before: float = 3.0
    after: float = 5.0
    merge_gap: float = 1.0
    fuzzy: float = 0.0
    max_videos: int = 30  # 0 = todos
    channel_tab: str = "streams"  # streams | videos | shorts
    cookies_browser: str = ""  # "", chrome, firefox, chromium, brave...
    quality: str = "1080"  # 2160 | 1080 | 720 | 480 | best
    precise_cut: bool = True
    hwaccel: str = "auto"  # auto | vaapi | none
    output_dir: str = ""
    allow_remote_ejs: bool = False
    theme: str = "system"  # system | dark | light
    # IA local
    whisper_fallback: bool = False  # transcreve no computador quando não há legenda
    whisper_model: str = "small"  # tiny | base | small | medium
    face_enabled: bool = False  # procura também o rosto em cada vídeo
    face_photos: str = ""  # caminhos das fotos de referência, um por linha
    face_label: str = ""  # nome mostrado nos trechos ("Rosto: Bárbara")
    face_threshold: float = 0.38  # similaridade mínima (SFace: 0,363 = mesma pessoa)
    face_fps: float = 1.0  # quadros analisados por segundo de vídeo

    @property
    def face_photo_list(self) -> list[str]:
        return [p for p in self.face_photos.splitlines() if p.strip()]

    def __post_init__(self) -> None:
        if not self.output_dir:
            self.output_dir = str(default_output_dir())

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        defaults = cls()
        known = {f.name for f in fields(cls)}
        kwargs = {}
        for key, value in data.items():
            if key in known:
                try:
                    kwargs[key] = type(getattr(defaults, key))(value)
                except (TypeError, ValueError):
                    pass
        return cls(**kwargs)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
