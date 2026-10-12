"""Ponte entre o QML e o núcleo. O trabalho pesado roda em threads; os
resultados voltam para a thread da interface por sinais Qt (conexão enfileirada)."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import asdict, fields
from pathlib import Path

from PySide6.QtCore import Property, QObject, QStringListModel, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from ..core import face_detector, subtitles_fallback
from ..core.config import Settings
from ..core.pipeline import Pipeline, VideoResult, export_report, is_local_source
from ..core.search import parse_terms
from ..core.youtube import Cancelled
from .models import ClipItem, ClipListModel, VideoListModel

_REBUILD_KEYS = {"before", "after", "merge_gap"}
_RESEARCH_KEYS = {"fuzzy"}
_FACE_REFERENCE_KEYS = {"face_photos", "face_label"}
_LOG_LIMIT = 500


def _clip_key(clip) -> tuple:
    return (clip.video_id, clip.start, clip.end)


class Backend(QObject):
    configChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    progressChanged = Signal()
    filterChanged = Signal()
    statsChanged = Signal()
    aiStatusChanged = Signal()
    faceChanged = Signal()
    toast = Signal(str, str, str)  # mensagem, tipo (info|success|error), ação ("" | open-folder)

    # sinais internos: worker -> thread da interface
    _discovered = Signal(object)
    _videoUpdated = Signal(int)
    _clipUpdated = Signal(object)
    _workerLog = Signal(str)
    _workerProgress = Signal(float, str)
    _workerDone = Signal(str, str, str)
    _aiProbed = Signal(object)
    _faceReady = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings.load()
        self.videos = VideoListModel(self)
        self.clips = ClipListModel(self)
        self.logs = QStringListModel(self)
        self._busy = ""
        self._status = "Pronto"
        self._progress = 0.0
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._terms: list[str] = []
        self._last_output = ""
        self._ai = {"ready": False, "facesAvailable": False, "facesDetail": "", "engines": [],
                    "transcriber": ""}
        self._face = {"state": "", "label": "", "preview": "", "photos": 0, "message": ""}
        self._face_job = 0  # descarta resultados de referências antigas

        self._discovered.connect(self._on_discovered)
        self._videoUpdated.connect(self._on_video_updated)
        self._clipUpdated.connect(self._on_clip_updated)
        self._workerLog.connect(self._set_status)
        self._workerProgress.connect(self._on_progress)
        self._workerDone.connect(self._on_done)
        self._aiProbed.connect(self._on_ai_probed)
        self._faceReady.connect(self._on_face_ready)
        self.clips.checkedCountChanged.connect(self.statsChanged)
        # importar faster-whisper/ctranslate2 leva até ~1 s: não atrasa a abertura da janela
        threading.Thread(target=self._probe_ai, daemon=True).start()

    # -- propriedades -----------------------------------------------------

    def _get_config(self) -> dict:
        return asdict(self.settings)

    config = Property("QVariantMap", _get_config, notify=configChanged)
    videosModel = Property(QObject, lambda self: self.videos, constant=True)
    clipsModel = Property(QObject, lambda self: self.clips, constant=True)
    busy = Property(bool, lambda self: bool(self._busy), notify=busyChanged)
    phase = Property(str, lambda self: self._busy, notify=busyChanged)
    status = Property(str, lambda self: self._status, notify=statusChanged)
    progress = Property(float, lambda self: self._progress, notify=progressChanged)
    videoFilter = Property(str, lambda self: self.clips.video_filter, notify=filterChanged)

    def _filter_title(self) -> str:
        vid = self.clips.video_filter
        return next((r.video.title for r in self.videos.results if r.video.id == vid), "") if vid else ""

    videoFilterTitle = Property(str, _filter_title, notify=filterChanged)

    def _total_matches(self) -> int:
        return sum(len(r.matches) for r in self.videos.results)

    def _scanned(self) -> int:
        return sum(1 for r in self.videos.results if r.status in ("done", "nosubs", "error"))

    totalMatches = Property(int, _total_matches, notify=statsChanged)
    scannedCount = Property(int, _scanned, notify=statsChanged)
    hasResults = Property(bool, lambda self: bool(self.videos.results), notify=statsChanged)

    # IA local: motores disponíveis, referência do rosto e console de atividade
    aiStatus = Property("QVariantMap", lambda self: self._ai, notify=aiStatusChanged)
    faceInfo = Property("QVariantMap", lambda self: self._face, notify=faceChanged)
    logModel = Property(QObject, lambda self: self.logs, constant=True)

    def _face_search_active(self) -> bool:
        """A busca procura o rosto: ligada, com foto válida e OpenCV disponível."""
        return self.settings.face_enabled and self._face["state"] == "ready"

    faceSearchActive = Property(bool, _face_search_active, notify=faceChanged)

    # -- configurações ----------------------------------------------------

    @Slot(str, "QVariant")
    def setConfig(self, key: str, value) -> None:  # noqa: N802
        if key not in {f.name for f in fields(Settings)}:
            return
        current = getattr(self.settings, key)
        try:
            value = type(current)(value)
        except (TypeError, ValueError):
            return
        if value == current:
            return
        setattr(self.settings, key, value)
        self.settings.save()
        self.configChanged.emit()
        if key in _REBUILD_KEYS:
            self._rebuild_clips()
        elif key in _RESEARCH_KEYS and self._terms and not self._busy:
            self.refreshSearch(", ".join(self._terms))
        elif key in _FACE_REFERENCE_KEYS:
            self._load_face_reference()
        elif key == "face_enabled":
            self.faceChanged.emit()

    # -- ações ------------------------------------------------------------

    @Slot(str, str)
    def startScan(self, source: str, terms_text: str) -> None:  # noqa: N802
        if self._busy:
            return
        terms = parse_terms(terms_text)
        if not source.strip():
            self.toast.emit("Informe um canal, vídeo ou pasta para analisar.", "error", "")
            return
        if not terms and not self._face_search_active():
            self.toast.emit("Digite pelo menos um termo para procurar (ex.: Bárbara) "
                            "ou ative a busca pelo rosto em IA local.", "error", "")
            return
        self._terms = terms
        self.setConfig("source", source.strip())
        self.setConfig("terms", terms_text.strip())
        self.clips.set_filter("")
        self.filterChanged.emit()
        self._start("discovering", self._scan_worker, source.strip(), terms)

    @Slot(str)
    def refreshSearch(self, terms_text: str) -> None:  # noqa: N802
        """Refaz a busca nas legendas já carregadas, sem acessar a rede."""
        terms = parse_terms(terms_text)
        if self._busy or not terms or not any(r.words for r in self.videos.results):
            return
        self._terms = terms
        self.setConfig("terms", terms_text.strip())
        self._start("searching", self._research_worker, terms)

    @Slot()
    def cutSelected(self) -> None:  # noqa: N802
        if self._busy:
            return
        items = [it for it in self.clips.checked_items() if it.state != "done"]
        if not items:
            self.toast.emit("Nenhum trecho novo selecionado para cortar.", "info", "")
            return
        for it in items:
            it.state, it.progress, it.message = "queued", 0.0, ""
            self.clips.item_changed(it)
        names = list(self._terms)
        if any(r.face_matches for r in self.videos.results):
            names.append(f"rosto {self._face['label'] or 'pessoa'}")  # nome da pasta de saída
        self._start("cutting", self._cut_worker, items, names)

    # -- IA local ---------------------------------------------------------

    @Slot("QVariantList")
    def setFacePhotos(self, urls) -> None:  # noqa: N802
        """Define as fotos de referência (QUrl, file:// ou caminho)."""
        paths = [self.urlToPath(str(u.toString() if hasattr(u, "toString") else u)) for u in urls]
        paths = [p for p in paths if p]
        if not self.settings.face_label and paths:
            self.settings.face_label = Path(paths[0]).stem.replace("_", " ").replace("-", " ").strip()
        self.setConfig("face_photos", "\n".join(paths))
        if paths:
            self.setConfig("face_enabled", True)

    @Slot()
    def clearFace(self) -> None:  # noqa: N802
        self.setConfig("face_enabled", False)
        self.setConfig("face_label", "")
        self.setConfig("face_photos", "")

    @Slot()
    def scanFaces(self) -> None:  # noqa: N802
        """Procura o rosto nos vídeos já carregados, sem buscar legendas de novo."""
        if self._busy or not self.videos.results:
            return
        if self._face["state"] != "ready":
            self.toast.emit("Escolha primeiro uma foto do rosto em IA local.", "error", "")
            return
        self.setConfig("face_enabled", True)
        self._start("faces", self._faces_worker)

    @Slot(int)
    def transcribeVideo(self, row: int) -> None:  # noqa: N802
        """Gera a legenda localmente para um vídeo sem legenda."""
        if self._busy or not 0 <= row < len(self.videos.results):
            return
        if not self._ai["transcriber"]:
            self.toast.emit("Instale o whisper.cpp (sudo pacman -S whisper-cpp) ou o faster-whisper "
                            "para gerar legendas no computador.", "error", "")
            return
        self._start("transcribing", self._transcribe_worker, row, list(self._terms))

    @Slot()
    def copyLog(self) -> None:  # noqa: N802
        QGuiApplication.clipboard().setText("\n".join(self.logs.stringList()))
        self.toast.emit("Atividade copiada para a área de transferência.", "info", "")

    @Slot()
    def clearLog(self) -> None:  # noqa: N802
        self.logs.setStringList([])

    def _probe_ai(self) -> None:
        faces_ok, faces_detail = face_detector.available()
        engines = subtitles_fallback.engines()
        self._aiProbed.emit({
            "ready": True,
            "facesAvailable": faces_ok,
            "facesDetail": faces_detail,
            "engines": [{"name": e.name, "available": e.available, "detail": e.detail} for e in engines],
            "transcriber": next((e.name for e in engines if e.available), ""),
        })

    def _on_ai_probed(self, status: dict) -> None:
        self._ai = status
        self.videos.transcriber_available = bool(status["transcriber"])
        self.videos.refresh()
        self.aiStatusChanged.emit()
        self._load_face_reference()

    def _load_face_reference(self) -> None:
        """Monta a referência do rosto em segundo plano (pode baixar os modelos)."""
        photos = self.settings.face_photo_list
        self._face_job += 1
        if not photos:
            self._face = {"state": "", "label": "", "preview": "", "photos": 0, "message": ""}
            self.faceChanged.emit()
            return
        if not self._ai["ready"]:
            return  # _on_ai_probed chama de novo
        if not self._ai["facesAvailable"]:
            self._face = {"state": "error", "label": self.settings.face_label, "preview": "",
                          "photos": len(photos), "message": self._ai["facesDetail"]}
            self.faceChanged.emit()
            return
        self._face = {**self._face, "state": "loading", "photos": len(photos), "message": "",
                      "label": self.settings.face_label}
        self.faceChanged.emit()
        job, settings = self._face_job, Settings(**asdict(self.settings))

        def work() -> None:
            pipe = Pipeline(settings, log=self._workerLog.emit)
            try:
                ref = pipe.face_reference()
            except Exception as e:  # noqa: BLE001 - mostrado ao usuário
                self._faceReady.emit({"job": job, "state": "error", "message": str(e)})
                return
            self._faceReady.emit({"job": job, "state": "ready", "label": ref.label,
                                  "preview": QUrl.fromLocalFile(ref.preview).toString() if ref.preview else ""})

        threading.Thread(target=work, daemon=True).start()

    def _on_face_ready(self, info: dict) -> None:
        if info.pop("job") != self._face_job:
            return  # as fotos mudaram enquanto esta referência era montada
        self._face = {**self._face, **info}
        self.faceChanged.emit()
        if info["state"] == "ready":
            self._log(f"Referência do rosto pronta: {info['label']} ({self._face['photos']} foto(s)).")

    @Slot()
    def cancel(self) -> None:
        if self._busy:
            self._cancel.set()
            self._set_status("Cancelando…")

    @Slot(int, bool)
    def setClipChecked(self, row: int, checked: bool) -> None:  # noqa: N802
        self.clips.set_checked(row, checked)

    @Slot(bool)
    def setAllChecked(self, checked: bool) -> None:  # noqa: N802
        self.clips.set_all_checked(checked)

    @Slot(str)
    def filterVideo(self, video_id: str) -> None:  # noqa: N802
        self.clips.set_filter("" if video_id == self.clips.video_filter else video_id)
        self.filterChanged.emit()

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802
        QDesktopServices.openUrl(QUrl(url) if "://" in url else QUrl.fromLocalFile(url))

    @Slot(str)
    def revealFile(self, path: str) -> None:  # noqa: N802
        try:
            # Abre o gerenciador de arquivos com o arquivo selecionado (Dolphin, Nautilus…).
            subprocess.Popen([
                "dbus-send", "--session", "--dest=org.freedesktop.FileManager1", "--type=method_call",
                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                f"array:string:{QUrl.fromLocalFile(path).toString()}", "string:",
            ])
        except OSError:
            self.openUrl(str(Path(path).parent))

    @Slot()
    def openOutputFolder(self) -> None:  # noqa: N802
        folder = Path(self._last_output or self.settings.output_dir).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        self.openUrl(str(folder))

    @Slot(str)
    def exportReport(self, file_url: str) -> None:  # noqa: N802
        path = Path(QUrl(file_url).toLocalFile() or file_url)
        if path.suffix.lower() not in (".csv", ".json"):
            path = path.with_suffix(".csv")
        try:
            export_report(self.videos.results, path)
        except OSError as e:
            self.toast.emit(f"Não foi possível salvar o relatório: {e}", "error", "")
            return
        self.toast.emit(f"Relatório salvo em {path.name}", "success", "")

    @Slot(result=str)
    def suggestedReportName(self) -> str:  # noqa: N802
        name = "-".join(self._terms) or "relatorio"
        folder = Path(self.settings.output_dir).expanduser()
        return QUrl.fromLocalFile(str(folder / f"youtube-cut-{name}.csv")).toString()

    @Slot(str, result=bool)
    def isLocalSource(self, text: str) -> bool:  # noqa: N802
        return is_local_source(text)

    @Slot(str, result=str)
    def urlToPath(self, url: str) -> str:  # noqa: N802
        return QUrl(url).toLocalFile() or url

    # -- execução em segundo plano ----------------------------------------

    def _start(self, phase: str, target, *args) -> None:
        self._cancel = threading.Event()
        self._busy = phase
        self.busyChanged.emit()
        self._on_progress(-1.0, "")
        # Cópia das configurações: o worker não vê mudanças feitas durante a execução, e
        # só procura rostos se a referência estiver pronta (foto inválida não vira erro por vídeo).
        settings = Settings(**asdict(self.settings))
        settings.face_enabled = self._face_search_active()
        pipe = Pipeline(settings, log=self._workerLog.emit, cancel=self._cancel)
        self._thread = threading.Thread(target=self._guard, args=(target, pipe, *args), daemon=True)
        self._thread.start()

    def _guard(self, target, pipe: Pipeline, *args) -> None:
        try:
            message, kind, action = target(pipe, *args)
        except (Cancelled, InterruptedError):
            message, kind, action = "Operação cancelada.", "info", ""
        except Exception as e:  # noqa: BLE001 - mostrado ao usuário
            message, kind, action = str(e), "error", ""
        self._workerDone.emit(message, kind, action)

    def _scan_worker(self, pipe: Pipeline, source: str, terms: list[str]):
        self._workerLog.emit("Buscando a lista de vídeos…")
        results = pipe.discover(source)
        if not results:
            return "Nenhum vídeo encontrado nessa fonte.", "info", ""
        self._discovered.emit(results)
        n = len(results)
        for i, r in enumerate(results):
            if self._cancel.is_set():
                raise Cancelled()
            self._workerProgress.emit(i / n, f"Analisando {i + 1} de {n}: {r.video.title}")
            r.status = "scanning"
            self._videoUpdated.emit(i)
            pipe.scan(r, terms, on_change=lambda _r, i=i: self._videoUpdated.emit(i))
            self._videoUpdated.emit(i)
        total = sum(len(r.matches) for r in results)
        faces = sum(len(r.face_matches) for r in results)
        if not total:
            hint = ("Experimente ativar a tolerância a erros de transcrição nas configurações."
                    if terms else "A pessoa não foi encontrada; tente o rigor “Flexível” em IA local.")
            return f"Nenhuma menção encontrada. {hint}", "info", ""
        detail = f" ({faces} com o rosto)" if faces and faces != total else ""
        return f"{total} trecho(s) encontrado(s){detail} em {n} vídeo(s).", "success", ""

    def _faces_worker(self, pipe: Pipeline):
        results = self.videos.results
        reference = pipe.face_reference()
        n = len(results)
        for i, r in enumerate(results):
            if self._cancel.is_set():
                raise Cancelled()
            self._workerProgress.emit(i / n, f"Procurando {reference.label} em {i + 1} de {n}: {r.video.title}")
            pipe.scan_faces(r, on_change=lambda _r, i=i: self._videoUpdated.emit(i))
            self._videoUpdated.emit(i)
        faces = sum(len(r.face_matches) for r in results)
        if not faces:
            return f"{reference.label} não foi encontrada nesses vídeos.", "info", ""
        found = sum(1 for r in results if r.face_matches)
        return f"{reference.label} aparece em {faces} trecho(s) de {found} vídeo(s).", "success", ""

    def _transcribe_worker(self, pipe: Pipeline, row: int, terms: list[str]):
        r = self.videos.results[row]
        self._workerProgress.emit(-1.0, f"Gerando a legenda de {r.video.title}…")
        pipe.transcribe(r, on_change=lambda _r: self._videoUpdated.emit(row))
        pipe.search(r, terms)
        self._videoUpdated.emit(row)
        if not r.words:
            return "A transcrição não encontrou fala nesse vídeo.", "info", ""
        mentions = len(r.matches) - len(r.face_matches)
        return f"Legenda gerada ({len(r.words)} palavras): {mentions} menção(ões).", "success", ""

    def _research_worker(self, pipe: Pipeline, terms: list[str]):
        results = self.videos.results
        for r in results:
            if self._cancel.is_set():
                raise Cancelled()
            if r.words:
                pipe.search(r, terms)
        self._discovered.emit(None)  # sinaliza recarga completa da lista
        total = sum(len(r.matches) for r in results)
        return f"{total} menção(ões) para “{', '.join(terms)}”.", "success" if total else "info", ""

    def _cut_worker(self, pipe: Pipeline, items: list[ClipItem], terms: list[str]):
        done = failed = 0
        n = len(items)
        last_emit = 0.0
        for i, it in enumerate(items):
            if self._cancel.is_set():
                raise Cancelled()
            it.state = "cutting"
            self._clipUpdated.emit(it)
            self._workerProgress.emit(i / n, f"Cortando {i + 1} de {n}: {it.result.video.title}")
            out = pipe.output_path(it.result.video, it.clip, terms)

            def on_progress(frac: float, it=it, i=i) -> None:
                nonlocal last_emit
                now = time.monotonic()
                if now - last_emit < 0.15:
                    return
                last_emit = now
                it.progress = frac
                self._clipUpdated.emit(it)
                if frac >= 0:
                    self._workerProgress.emit((i + frac) / n, "")

            try:
                path = pipe.cut(it.result.video, it.clip, out, on_progress)
            except (Cancelled, InterruptedError):
                it.state = ""
                self._clipUpdated.emit(it)
                raise
            except Exception as e:  # noqa: BLE001
                it.state, it.message = "error", str(e)
                failed += 1
            else:
                # desmarca: o botão "Cortar" passa a contar só o que falta cortar
                it.state, it.output, it.progress, it.checked = "done", str(path), 1.0, False
                self._last_output = str(path.parent)
                done += 1
            self._clipUpdated.emit(it)

        if failed and not done:
            return f"Nenhum trecho foi cortado ({failed} falha(s)). Veja o motivo em cada item.", "error", ""
        msg = f"{done} trecho(s) salvo(s)" + (f", {failed} com falha" if failed else "") + "."
        return msg, "success" if not failed else "info", "open-folder"

    # -- reações na thread da interface -----------------------------------

    def _on_discovered(self, results: list[VideoResult] | None) -> None:
        if results is not None:
            self.videos.set_results(results)
        else:
            self.videos.refresh()
        self._rebuild_clips()

    def _on_video_updated(self, row: int) -> None:
        # Sinais enfileirados chegam atrasados: quando este é processado o worker
        # pode já ter terminado o vídeo (ou a lista inteira). Por isso comparamos
        # o que deveria existir com o que já existe, em vez de só acrescentar.
        self.videos.refresh(row)
        r = self.videos.results[row]
        clips = Pipeline(self.settings).clips_for(r)
        current = [_clip_key(it.clip) for it in self.clips.items if it.result is r]
        if [_clip_key(c) for c in clips] != current:
            if current:
                self._rebuild_clips()
            else:
                self.clips.append_items([ClipItem(r, c) for c in clips])
        self.statsChanged.emit()

    def _rebuild_clips(self) -> None:
        """Recalcula os trechos preservando seleção e estado dos que não mudaram."""
        previous = {(id(it.result), _clip_key(it.clip)): it for it in self.clips.items}
        pipe = Pipeline(self.settings)
        items = []
        for r in self.videos.results:
            for c in pipe.clips_for(r):
                old = previous.get((id(r), _clip_key(c)))
                items.append(old if old else ClipItem(r, c))
        self.clips.set_items(items)
        self.statsChanged.emit()

    def _on_clip_updated(self, item: ClipItem) -> None:
        self.clips.item_changed(item)
        if item.state == "done":
            self.clips.checkedCountChanged.emit()

    def _on_progress(self, value: float, text: str) -> None:
        self._progress = value
        self.progressChanged.emit()
        if text:
            self._set_status(text)

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()
        self._log(text)

    def _log(self, text: str) -> None:
        """Acrescenta uma linha ao console de atividade (com hora), sem repetir a anterior."""
        lines = self.logs.stringList()
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        if lines and lines[-1][10:] == text:
            return
        lines.append(line)
        self.logs.setStringList(lines[-_LOG_LIMIT:])

    def _on_done(self, message: str, kind: str, action: str) -> None:
        self._busy = ""
        self._progress = 0.0 if kind == "error" else 1.0
        self.busyChanged.emit()
        self.progressChanged.emit()
        self.statsChanged.emit()
        self._set_status(message)
        self.toast.emit(message, kind, action)

    def shutdown(self) -> None:
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
