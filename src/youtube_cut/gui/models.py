"""Modelos de lista expostos ao QML (vídeos e trechos)."""

from __future__ import annotations

import html
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, Signal, Property

from ..core.models import Clip
from ..core.pipeline import VideoResult
from ..core.timefmt import format_short


def _date(raw: str | None) -> str:
    if raw and len(raw) == 8:
        return f"{raw[6:]}/{raw[4:6]}/{raw[:4]}"
    return ""


def _thumb(result: VideoResult) -> str:
    return "" if result.video.is_local else f"https://i.ytimg.com/vi/{result.video.id}/mqdefault.jpg"


class _RoleModel(QAbstractListModel):
    ROLES: tuple[str, ...] = ()
    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._role_ids = {Qt.ItemDataRole.UserRole + i: name for i, name in enumerate(self.ROLES)}
        self.modelReset.connect(self.countChanged)
        self.rowsInserted.connect(self.countChanged)
        self.rowsRemoved.connect(self.countChanged)

    def roleNames(self):  # noqa: N802
        return {rid: QByteArray(name.encode()) for rid, name in self._role_ids.items()}

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        name = self._role_ids.get(role)
        if name is None or not index.isValid():
            return None
        return self.value(index.row(), name)

    def value(self, row: int, name: str):  # pragma: no cover - sobrescrito
        raise NotImplementedError

    def _get_count(self) -> int:
        return self.rowCount()

    count = Property(int, _get_count, notify=countChanged)


class VideoListModel(_RoleModel):
    ROLES = ("videoId", "title", "status", "matchCount", "subtitle", "error",
             "durationText", "dateText", "thumbnail", "isLocal", "url")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.results: list[VideoResult] = []

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.results)

    def value(self, row: int, name: str):
        r = self.results[row]
        v = r.video
        match name:
            case "videoId": return v.id
            case "title": return v.title
            case "status": return r.status
            case "matchCount": return len(r.matches)
            case "subtitle": return r.subtitle
            case "error": return r.error
            case "durationText": return format_short(v.duration) if v.duration else ""
            case "dateText": return _date(v.upload_date)
            case "thumbnail": return _thumb(r)
            case "isLocal": return v.is_local
            case "url": return v.url
        return None

    def set_results(self, results: list[VideoResult]) -> None:
        self.beginResetModel()
        self.results = results
        self.endResetModel()

    def refresh(self, row: int | None = None) -> None:
        if not self.results:
            return
        first = self.index(0 if row is None else row)
        last = self.index(len(self.results) - 1 if row is None else row)
        self.dataChanged.emit(first, last)


@dataclass(eq=False)
class ClipItem:
    result: VideoResult
    clip: Clip
    checked: bool = True
    state: str = ""  # "" | queued | cutting | done | error
    progress: float = 0.0
    output: str = ""
    message: str = ""


def _context_html(clip: Clip) -> str:
    """Frase com o termo destacado (o QML pinta <b> com a cor de destaque)."""
    m = clip.matches[0]
    esc = html.escape
    return f"{esc(m.before)} <b>{esc(m.spoken)}</b> {esc(m.after)}".strip()


class ClipListModel(_RoleModel):
    ROLES = ("videoId", "videoTitle", "thumbnail", "startText", "endText", "durationText",
             "contextHtml", "term", "mentions", "score", "checked", "cutState", "progress",
             "output", "message", "link", "dateText")
    checkedCountChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[ClipItem] = []
        self.visible: list[ClipItem] = []
        self.video_filter = ""
        self.modelReset.connect(self.checkedCountChanged)
        self.rowsInserted.connect(self.checkedCountChanged)

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.visible)

    def value(self, row: int, name: str):
        it = self.visible[row]
        c, v = it.clip, it.result.video
        match name:
            case "videoId": return v.id
            case "videoTitle": return v.title
            case "thumbnail": return _thumb(it.result)
            case "startText": return format_short(c.start)
            case "endText": return format_short(c.end)
            case "durationText": return f"{c.duration:.0f}s"
            case "contextHtml": return _context_html(c)
            case "term": return c.matches[0].term
            case "mentions": return len(c.matches)
            case "score": return min(m.score for m in c.matches)
            case "checked": return it.checked
            case "cutState": return it.state
            case "progress": return it.progress
            case "output": return it.output
            case "message": return it.message
            case "link": return v.link_at(c.matches[0].start - 2)
            case "dateText": return _date(v.upload_date)
        return None

    def _matches_filter(self, it: ClipItem) -> bool:
        return not self.video_filter or it.result.video.id == self.video_filter

    def set_items(self, items: list[ClipItem]) -> None:
        self.beginResetModel()
        self.items = items
        self.visible = [it for it in items if self._matches_filter(it)]
        self.endResetModel()

    def append_items(self, items: list[ClipItem]) -> None:
        self.items.extend(items)
        new_visible = [it for it in items if self._matches_filter(it)]
        if new_visible:
            start = len(self.visible)
            self.beginInsertRows(QModelIndex(), start, start + len(new_visible) - 1)
            self.visible.extend(new_visible)
            self.endInsertRows()

    def set_filter(self, video_id: str) -> None:
        self.video_filter = video_id
        self.set_items(self.items)

    def item_changed(self, item: ClipItem) -> None:
        try:
            row = self.visible.index(item)
        except ValueError:
            return
        self.dataChanged.emit(self.index(row), self.index(row))

    def set_checked(self, row: int, checked: bool) -> None:
        if 0 <= row < len(self.visible):
            self.visible[row].checked = checked
            self.dataChanged.emit(self.index(row), self.index(row))
            self.checkedCountChanged.emit()

    def set_all_checked(self, checked: bool) -> None:
        for it in self.visible:
            it.checked = checked
        if self.visible:
            self.dataChanged.emit(self.index(0), self.index(len(self.visible) - 1))
        self.checkedCountChanged.emit()

    def checked_items(self) -> list[ClipItem]:
        return [it for it in self.items if it.checked]

    def _checked_count(self) -> int:
        return sum(1 for it in self.items if it.checked)

    def _checked_duration(self) -> int:
        return round(sum(it.clip.duration for it in self.items if it.checked))

    checkedCount = Property(int, _checked_count, notify=checkedCountChanged)
    checkedSeconds = Property(int, _checked_duration, notify=checkedCountChanged)
