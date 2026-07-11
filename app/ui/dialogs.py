"""프레임리스 테마 다이얼로그 — OS 타이틀바 대신 자체 제목줄.

모든 앱 다이얼로그의 공통 베이스: 테마 배경/테두리(QSS #framelessDialog),
제목 + ✕ 닫기, 아무 곳이나 잡고 드래그 이동. 내용은 self.body에 추가한다.
"""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class FramelessDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)  # 작업표시줄/Alt+Tab 표시용 (타이틀바는 없음)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("framelessDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._drag_offset: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 16)
        outer.setSpacing(10)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setProperty("cssClass", "dialogTitle")
        header.addWidget(title_label)
        header.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setProperty("cssClass", "ghost")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        outer.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)

    # --- 드래그 이동 (타이틀바가 없으므로) ---

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
