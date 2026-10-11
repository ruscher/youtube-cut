"""Estruturas de dados compartilhadas entre núcleo, CLI e interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class Word:
    """Uma palavra falada, com início e fim em segundos."""

    start: float
    end: float
    text: str


@dataclass(slots=True)
class VideoInfo:
    id: str
    title: str
    url: str
    duration: float | None = None
    upload_date: str | None = None
    live_status: str | None = None
    local_path: str | None = None  # preenchido no modo arquivo local

    @property
    def is_local(self) -> bool:
        return self.local_path is not None

    def link_at(self, seconds: float) -> str:
        if self.is_local:
            return self.url
        return f"https://youtu.be/{self.id}?t={max(0, int(seconds))}"


@dataclass(slots=True)
class Match:
    """Uma ocorrência de um termo dentro de um vídeo."""

    video_id: str
    term: str
    start: float
    end: float
    spoken: str  # texto exatamente como aparece na transcrição
    before: str = ""  # palavras anteriores, para dar contexto
    after: str = ""  # palavras seguintes
    score: float = 1.0  # 1.0 = exato; menor que 1 = aproximado (fuzzy)

    @property
    def context(self) -> str:
        return " ".join(p for p in (self.before, self.spoken, self.after) if p)


@dataclass(slots=True)
class Clip:
    """Trecho a ser cortado; pode agrupar várias ocorrências próximas."""

    video_id: str
    start: float
    end: float
    matches: list[Match] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return asdict(self)
