"""Inicialização da interface Qt Quick."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .backend import Backend
from .icons import IconProvider

QML_DIR = Path(__file__).parent / "qml"
APP_ICON = QML_DIR / "assets" / "youtube-cut.svg"


def create_engine(backend: Backend, warnings: list[str] | None = None) -> QQmlApplicationEngine:
    """Carrega a interface. Avisos do QML vão para stderr e, se pedido, para ``warnings``."""
    # "Basic" permite estilizar todos os controles; o tema vem de Theme.qml.
    QQuickStyle.setStyle("Basic")
    engine = QQmlApplicationEngine()

    def report(items) -> None:
        for item in items:
            text = item.toString()
            if warnings is not None:
                warnings.append(text)
            print(text, file=sys.stderr)

    engine.warnings.connect(report)
    # O QML só guarda um ponteiro C++: sem esta referência o Python poderia
    # coletar o backend e todas as ligações passariam a ver `backend = null`.
    engine.backend = backend
    engine.addImageProvider("icon", IconProvider())
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    return engine


def run(argv: list[str] | None = None) -> int:
    QApplication.setApplicationName("YouTube Cut")
    QApplication.setOrganizationName("youtube-cut")
    QApplication.setDesktopFileName("youtube-cut")  # ícone correto no Wayland
    app = QApplication(argv or sys.argv[:1])
    app.setWindowIcon(QIcon(str(APP_ICON)))

    backend = Backend()
    engine = create_engine(backend)
    if not engine.rootObjects():
        return 1
    app.aboutToQuit.connect(backend.shutdown)
    code = app.exec()
    # Destrói a árvore QML antes do backend: senão as ligações ainda ativas
    # leem modelos já destruídos e enchem o terminal de TypeError ao sair.
    del engine
    return code
