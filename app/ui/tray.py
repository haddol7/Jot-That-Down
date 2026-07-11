"""시스템 트레이 아이콘 — 오버레이 제어의 유일한 통로.

클릭 통과 모드에서는 오버레이 자체를 클릭할 수 없으므로,
토글과 종료는 반드시 트레이에서 가능해야 한다. (M6에서 메뉴 확장)
"""
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .overlay import OverlayWindow


def _make_icon() -> QIcon:
    """자막 바를 형상화한 간단한 아이콘을 그린다 (파일 리소스 불필요)."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(30, 30, 30)))
    painter.drawRoundedRect(4, 36, 56, 20, 8, 8)
    painter.setBrush(QBrush(QColor(80, 180, 255)))
    painter.drawRoundedRect(10, 42, 28, 8, 4, 4)
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawRoundedRect(42, 42, 12, 8, 4, 4)
    painter.end()
    return QIcon(pixmap)


def create_tray(
    overlay: OverlayWindow, on_quit: Callable[[], None]
) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(_make_icon())
    tray.setToolTip("JotThatDown — 실시간 자막")
    menu = QMenu()

    click_through = QAction("클릭 통과 (자막이 마우스를 막지 않음)", menu)
    click_through.setCheckable(True)
    click_through.toggled.connect(overlay.set_click_through)
    menu.addAction(click_through)

    menu.addSeparator()
    quit_action = QAction("종료", menu)
    quit_action.triggered.connect(on_quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()
    return tray
