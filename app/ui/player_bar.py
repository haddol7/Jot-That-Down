"""세션 오디오 플레이어 바 — 자막 타임라인 하단 (M6+).

- ▶/⏹ 전체 재생, 탐색 슬라이더, 진행 시간
- ● 이어서 녹음: 지난 세션에 녹음을 덧붙인다 (resume_requested)
녹음 트랙이 없으면 재생 컨트롤은 숨기고 녹음 버튼만 보인다.
"""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QWidget,
)

from ..audio.player import MixPlayer
from ..core.clock import format_ms

_SEGMENT_TICK = QColor(127, 127, 127, 110)  # 자막 위치 — 얇고 흐리게
_RESUME_TICK = QColor("#f2a860")            # 이어서 녹음 지점 — 주황·굵게
_BOOKMARK_TICK = QColor("#2f9e4a")          # 북마크 — 초록·굵게


class _TickSlider(QSlider):
    """자막 위치(|)·이어녹음 지점(|)·북마크(|)를 눈금으로 그리는 탐색 슬라이더."""

    def __init__(self) -> None:
        super().__init__(Qt.Horizontal)
        self._segment_ticks: list[int] = []
        self._resume_ticks: list[int] = []
        self._bookmark_ticks: list[int] = []

    def set_marks(
        self, segment_ms: list[int], resume_ms: list[int],
        bookmark_ms: list[int] | None = None,
    ) -> None:
        self._segment_ticks = segment_ms
        self._resume_ticks = resume_ms
        if bookmark_ms is not None:
            self._bookmark_ticks = bookmark_ms
        self.update()

    def set_bookmarks(self, bookmark_ms: list[int]) -> None:
        self._bookmark_ticks = bookmark_ms
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        total = self.maximum()
        if total <= 0 or not (
            self._segment_ticks or self._resume_ticks or self._bookmark_ticks
        ):
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self
        )
        span_x = groove.x() + handle.width() // 2
        span_w = groove.width() - handle.width()
        center_y = groove.center().y()

        painter = QPainter(self)
        painter.setPen(QPen(_SEGMENT_TICK, 1))
        for t in self._segment_ticks:
            x = span_x + int(t / total * span_w)
            painter.drawLine(x, center_y - 3, x, center_y + 3)
        painter.setPen(QPen(_RESUME_TICK, 2))
        for t in self._resume_ticks:
            x = span_x + int(t / total * span_w)
            painter.drawLine(x, center_y - 6, x, center_y + 6)
        painter.setPen(QPen(_BOOKMARK_TICK, 2))
        for t in self._bookmark_ticks:
            x = span_x + int(t / total * span_w)
            painter.drawLine(x, center_y - 6, x, center_y + 6)
        painter.end()


class PlayerBar(QWidget):
    resume_requested = Signal()
    position_changed = Signal(int)  # 재생 위치 ms, 정지 시 -1 (자막 하이라이트용)

    def __init__(self) -> None:
        super().__init__()
        self._player = MixPlayer()
        self._paths: list[Path] = []
        self._total_ms = 0
        self._dragging = False
        self._playing_shown = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # 상단 녹음 바 안에 있으므로 여백 최소
        layout.setSpacing(8)

        from .icons import make_ui_icon

        self._icon_play = make_ui_icon("play", 16, "#2383e2")
        self._icon_stop = make_ui_icon("stop", 16, "#e25757")
        self._play_btn = QPushButton()
        self._play_btn.setIcon(self._icon_play)
        self._play_btn.setIconSize(QSize(18, 18))
        self._play_btn.setProperty("cssClass", "ghost")
        self._play_btn.setCursor(Qt.PointingHandCursor)
        self._play_btn.setToolTip("세션 녹음 전체 재생")
        self._play_btn.clicked.connect(self._toggle_play)
        layout.addWidget(self._play_btn)

        self._slider = _TickSlider()
        self._slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self._slider.sliderReleased.connect(self._on_seek)
        layout.addWidget(self._slider, stretch=1)

        self._time = QLabel("00:00 / 00:00")
        self._time.setProperty("cssClass", "stamp")
        layout.addWidget(self._time)

        self._record_btn = QPushButton("● 계속 녹음")
        self._record_btn.setProperty("cssClass", "primary")
        self._record_btn.setCursor(Qt.PointingHandCursor)
        self._record_btn.setToolTip("이 세션에 녹음·자막을 덧붙입니다 (시간도 이어짐)")
        self._record_btn.clicked.connect(self.resume_requested)
        layout.addWidget(self._record_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

        self.hide()

    # --- 외부 API ---

    @property
    def has_audio(self) -> bool:
        return self.isVisible() and bool(self._paths) and self._total_ms > 0

    def play_from(self, t_ms: int) -> None:
        """자막 행 클릭 → 그 시각부터 리플레이."""
        if not self.has_audio:
            return
        t_ms = min(max(0, t_ms), self._total_ms)
        self._slider.setValue(t_ms)
        self._update_time(t_ms)
        self._player.play(self._paths, t_ms)
        self._play_btn.setIcon(self._icon_stop)
        self._playing_shown = True

    def configure(
        self,
        paths: list[Path],
        offer_resume: bool,
        segment_ticks: list[int] | None = None,
        resume_ticks: list[int] | None = None,
        bookmark_ticks: list[int] | None = None,
    ) -> None:
        """지난 세션(또는 정지된 세션)에서 호출된다."""
        self.stop()
        self._paths = [p for p in paths if p.exists()]
        self._total_ms = MixPlayer.total_ms(self._paths)
        has_audio = bool(self._paths) and self._total_ms > 0

        self._play_btn.setVisible(has_audio)
        self._slider.setVisible(has_audio)
        self._time.setVisible(has_audio)
        self._record_btn.setVisible(offer_resume)
        if has_audio:
            self._slider.setRange(0, self._total_ms)
            self._slider.setValue(0)
            self._slider.set_marks(
                segment_ticks or [], resume_ticks or [], bookmark_ticks or []
            )
            self._update_time(0)
        self.setVisible(has_audio or offer_resume)

    def set_bookmark_ticks(self, bookmark_ms: list[int]) -> None:
        self._slider.set_bookmarks(bookmark_ms)

    def clear(self) -> None:
        """라이브 세션 중에는 재생 UI를 숨긴다 (하울링 방지)."""
        self.stop()
        self.hide()

    def stop(self) -> None:
        self._player.stop()
        self._play_btn.setIcon(self._icon_play)
        self._playing_shown = False
        self.position_changed.emit(-1)

    # --- 내부 ---

    def _toggle_play(self) -> None:
        if self._player.playing:
            self.stop()
        else:
            start = self._slider.value()
            if start >= self._total_ms - 300:
                start = 0
            self._player.play(self._paths, start)
            self._play_btn.setIcon(self._icon_stop)
            self._playing_shown = True

    def _on_seek(self) -> None:
        self._dragging = False
        if self._player.playing:
            self._player.play(self._paths, self._slider.value())

    def _tick(self) -> None:
        if not self.isVisible():
            return
        if self._player.playing:
            if not self._dragging:
                self._slider.setValue(min(self._player.position_ms, self._total_ms))
            self._update_time(self._player.position_ms)
            self.position_changed.emit(self._player.position_ms)
        elif self._playing_shown:
            self._play_btn.setIcon(self._icon_play)  # 재생이 끝까지 가서 스스로 멈춘 경우
            self._playing_shown = False
            self.position_changed.emit(-1)

    def _update_time(self, position_ms: int) -> None:
        self._time.setText(
            f"{format_ms(min(position_ms, self._total_ms))} / {format_ms(self._total_ms)}"
        )
