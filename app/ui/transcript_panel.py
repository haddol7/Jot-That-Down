"""자막 타임라인 패널.

- 행 = [시각] [자막 텍스트] — 출처는 색으로 구분 (마이크=파랑, 시스템=기본색)
- 행 클릭: 녹음이 있으면 그 시각부터 리플레이, 없으면(라이브) 노트 블록 점프
- 모델 로딩 등 대기 상태는 하단 배너로 표시
- 하단: 세션 오디오 플레이어 바 (전체 재생 / 이어서 녹음)
"""
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.clock import format_ms
from ..core.models import AudioSource, TranscriptSegment
from .player_bar import PlayerBar

_SOURCE_CLASS = {AudioSource.MIC: "segMic", AudioSource.SYSTEM: "segSys"}


class _SegmentLabel(QLabel):
    """자막 텍스트 라벨.

    - 클릭: 리플레이
    - 드래그 선택 후 놓기: [복사 / 교정 사전에 추가] 메뉴
    """

    def __init__(self, text: str, on_click, on_correction) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._on_click = on_click
        self._on_correction = on_correction

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        selected = self.selectedText()
        if selected:
            self._show_selection_menu(event.globalPosition().toPoint(), selected)
        else:
            self._on_click()

    def _show_selection_menu(self, global_pos, selected: str) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("복사")
        correction_action = menu.addAction("교정 사전에 추가")
        chosen = menu.exec(global_pos)
        if chosen == copy_action:
            QGuiApplication.clipboard().setText(selected)
        elif chosen == correction_action:
            self._on_correction(selected)


class _SegmentRow(QWidget):
    _STAMP_W = 42
    _MARGINS_W = 10 + 10 + 8  # 좌우 여백 + 스탬프-본문 간격
    _MARGINS_H = 5 + 5
    _STAMP_COL_H = 38  # 시각 + 북마크 버튼

    def __init__(
        self, segment: TranscriptSegment, on_click, on_correction,
        bookmarked: bool = False, on_bookmark=None,
    ) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)  # 재생 하이라이트 배경용
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        # 시각 + 그 아래 북마크 토글
        from .icons import make_ui_icon

        self._icon_off = make_ui_icon("bookmark", 13)
        self._icon_on = make_ui_icon("bookmark_on", 13, "#2f9e4a")
        stamp_col = QVBoxLayout()
        stamp_col.setContentsMargins(0, 0, 0, 0)
        stamp_col.setSpacing(1)
        stamp = QLabel(format_ms(segment.t_start_ms))
        stamp.setProperty("cssClass", "stamp")
        stamp.setFixedWidth(self._STAMP_W)
        stamp_col.addWidget(stamp)
        self._bookmarked = bookmarked
        self._on_bookmark = on_bookmark
        self._bm_btn = QPushButton()
        self._bm_btn.setFixedSize(18, 18)
        self._bm_btn.setCursor(Qt.PointingHandCursor)
        self._bm_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
        )
        self._bm_btn.setToolTip("북마크")
        self._bm_btn.setIcon(self._icon_on if bookmarked else self._icon_off)
        self._bm_btn.clicked.connect(self._toggle_bookmark)
        stamp_col.addWidget(self._bm_btn, alignment=Qt.AlignLeft)
        stamp_col.addStretch()
        layout.addLayout(stamp_col)

        self.label = _SegmentLabel(segment.text, on_click, on_correction)
        self.label.setProperty("cssClass", _SOURCE_CLASS[segment.source])
        layout.addWidget(self.label, stretch=1, alignment=Qt.AlignTop)

    def _toggle_bookmark(self) -> None:
        self._bookmarked = not self._bookmarked
        self._bm_btn.setIcon(self._icon_on if self._bookmarked else self._icon_off)
        if self._on_bookmark:
            self._on_bookmark(self._bookmarked)

    def set_font_pt(self, pt: int) -> None:
        f = self.label.font()
        f.setPointSize(pt)
        self.label.setFont(f)  # heightForWidth 계산용
        # 전역 QSS(font-size: 13px)가 폴리시 때 setFont를 덮어써서 새 행이
        # 기본 크기로 나오므로, 우선순위가 가장 높은 인라인 스타일로 고정
        self.label.setStyleSheet(f"font-size: {pt}pt;")

    def preferred_height(self, total_width: int) -> int:
        """실제 폭 기준 줄바꿈 높이 — 타임스탬프와 본문이 딱 맞게."""
        text_width = max(60, total_width - self._STAMP_W - self._MARGINS_W)
        return (
            max(self.label.heightForWidth(text_width), self._STAMP_COL_H)
            + self._MARGINS_H
        )


class TranscriptPanel(QWidget):
    row_activated = Signal(object)        # TranscriptSegment (클릭 → 리플레이/점프)
    correction_requested = Signal(str)    # 선택 텍스트 (→ 교정 사전)
    source_toggled = Signal(object, bool)  # AudioSource, 켜짐 (라이브 세션)
    stop_requested = Signal()              # ■ 정지
    bookmark_toggled = Signal(object, bool)  # TranscriptSegment, 켜짐
    dock_requested = Signal(str)             # 패널 위치: left|right|top|bottom

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 상단 녹음/재생 컨트롤 바 — 녹음 관련은 전부 여기 모인다 (얇지 않게)
        control_bar = QWidget()
        control_bar.setObjectName("recordBar")
        control_bar.setAttribute(Qt.WA_StyledBackground, True)
        bar_layout = QVBoxLayout(control_bar)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        bar_layout.setSpacing(6)

        # 1행: 제목/녹음 경과 + (라이브) 소스 토글 · 정지
        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        header = QLabel("받아쓰기")
        header.setProperty("cssClass", "sectionLabel")
        header_row.addWidget(header)

        # 패널 위치 이동 버튼 (좌/우/상/하)
        from .icons import make_ui_icon as _icon

        for side, tip in (
            ("left", "받아쓰기를 왼쪽으로"), ("right", "받아쓰기를 오른쪽으로"),
            ("top", "받아쓰기를 위로"), ("bottom", "받아쓰기를 아래로"),
        ):
            dock_btn = QPushButton()
            dock_btn.setIcon(_icon(f"dock_{side}", 14))
            dock_btn.setFixedSize(20, 20)
            dock_btn.setProperty("cssClass", "ghost")
            dock_btn.setCursor(Qt.PointingHandCursor)
            dock_btn.setToolTip(tip)
            dock_btn.clicked.connect(lambda _, s=side: self.dock_requested.emit(s))
            header_row.addWidget(dock_btn)

        # 녹음 경과 시간 (● 03:12) — 라이브에서만. 폭 고정(자릿수 변화로 안 흔들리게)
        self._rec_label = QLabel()
        self._rec_label.setProperty("cssClass", "recElapsed")
        self._rec_label.setMinimumWidth(120)
        self._rec_label.hide()
        header_row.addWidget(self._rec_label)
        header_row.addStretch()

        # ● 녹음 — 아무 소스도 안 켜진 라이브 세션에서 한 번에 시작
        self._rec_start_btn = QPushButton("● 녹음")
        self._rec_start_btn.setProperty("cssClass", "primary")
        self._rec_start_btn.setCursor(Qt.PointingHandCursor)
        self._rec_start_btn.clicked.connect(self._on_record_clicked)
        self._rec_start_btn.hide()
        header_row.addWidget(self._rec_start_btn)

        self._updating_toggles = False
        self._live_visible = False
        self._live_started = False
        self._source_buttons: dict[AudioSource, QPushButton] = {}
        self._source_names = {AudioSource.MIC: "마이크", AudioSource.SYSTEM: "시스템"}
        self._source_icons = {AudioSource.MIC: "\U0001F3A4", AudioSource.SYSTEM: "\U0001F50A"}
        for source in (AudioSource.MIC, AudioSource.SYSTEM):
            button = QPushButton()
            button.setCheckable(True)
            button.setProperty("cssClass", "sourceToggle")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"{self._source_names[source]} 켜기/끄기 — 세션 중 언제든 전환")
            button.toggled.connect(
                lambda on, s=source: self._on_source_toggle(s, on)
            )
            button.hide()
            self._source_buttons[source] = button
            header_row.addWidget(button)
        self._sync_source_labels(set())

        from .icons import make_ui_icon

        self._stop_btn = QPushButton(" 정지")
        self._stop_btn.setIcon(make_ui_icon("stop", 13, "#e25757"))
        self._stop_btn.setProperty("cssClass", "danger")
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setToolTip("듣기·녹음을 끝냅니다 (노트는 계속 편집 가능)")
        self._stop_btn.clicked.connect(self.stop_requested)
        self._stop_btn.hide()
        header_row.addWidget(self._stop_btn)
        bar_layout.addLayout(header_row)

        # 2행: 재생 바(▶ · 탐색 · 시간 · 이어서 녹음) — 상단에 함께
        self.player_bar = PlayerBar()
        self.player_bar.position_changed.connect(self._on_play_position)
        bar_layout.addWidget(self.player_bar)

        layout.addWidget(control_bar)

        self._list = QListWidget()
        self._list.setWordWrap(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.installEventFilter(self)      # Ctrl+휠/±로 자막 크기 조절
        self._list.viewport().installEventFilter(self)
        layout.addWidget(self._list, stretch=1)

        # 대기 상태 배너 (모델 로딩 등)
        self._pending = QLabel()
        self._pending.setProperty("cssClass", "pendingBanner")
        self._pending.hide()
        layout.addWidget(self._pending)
        self._pending_base = ""
        self._dots = 0
        self._pending_timer = QTimer(self)
        self._pending_timer.timeout.connect(self._animate_pending)

        self._segments: list[TranscriptSegment] = []
        self._playing_row = -1
        self._caption_pt = 11  # 자막 글꼴 크기 (Ctrl +/- 로 조절)
        self._bookmarks: set[int] = set()  # 북마크된 t_start_ms

    # --- 자막 글꼴 크기 (Ctrl +/-, Ctrl+휠) ---

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            self._change_caption_font(1 if event.angleDelta().y() > 0 else -1)
            return True
        if event.type() == QEvent.KeyPress and event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Plus, Qt.Key_Equal):
                self._change_caption_font(1); return True
            if event.key() == Qt.Key_Minus:
                self._change_caption_font(-1); return True
        return super().eventFilter(obj, event)

    def _change_caption_font(self, delta: int) -> None:
        self._caption_pt = max(8, min(28, self._caption_pt + delta))
        width = self._list.viewport().width()
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = self._list.itemWidget(item)
            if row is not None:
                row.set_font_pt(self._caption_pt)
                item.setSizeHint(QSize(0, row.preferred_height(width)))

    # --- 파이프라인에서 (메인 스레드 경유) ---

    def add_segment(self, segment: TranscriptSegment) -> None:
        at_bottom = (
            self._list.verticalScrollBar().value()
            >= self._list.verticalScrollBar().maximum() - 4
        )
        index = len(self._segments)
        item = QListWidgetItem(self._list)
        row = _SegmentRow(
            segment,
            on_click=lambda i=index: self.row_activated.emit(self._segments[i]),
            on_correction=self.correction_requested.emit,
            bookmarked=segment.t_start_ms in self._bookmarks,
            on_bookmark=lambda on, s=segment: self._on_bookmark(s, on),
        )
        row.set_font_pt(self._caption_pt)
        item.setSizeHint(
            QSize(0, row.preferred_height(self._list.viewport().width()))
        )
        self._list.setItemWidget(item, row)
        self._segments.append(segment)
        if at_bottom:
            self._list.scrollToBottom()

    def update_last_segment(self, segment: TranscriptSegment) -> None:
        """마지막 자막 행의 텍스트를 교체 (이어붙이기)."""
        if not self._segments:
            self.add_segment(segment)
            return
        i = len(self._segments) - 1
        self._segments[i] = segment
        item = self._list.item(i)
        row = self._list.itemWidget(item)
        if row is not None:
            row.label.setText(segment.text)
            item.setSizeHint(
                QSize(0, row.preferred_height(self._list.viewport().width()))
            )

    def resizeEvent(self, event) -> None:
        """패널 폭이 바뀌면 줄바꿈이 달라지므로 행 높이를 다시 계산."""
        super().resizeEvent(event)
        width = self._list.viewport().width()
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = self._list.itemWidget(item)
            if row is not None:
                item.setSizeHint(QSize(0, row.preferred_height(width)))

    def set_bookmarks(self, t_ms_set: set[int]) -> None:
        """세션의 북마크 시각들 — load_segments 전에 불러야 행에 반영된다."""
        self._bookmarks = set(t_ms_set)

    def _on_bookmark(self, segment: TranscriptSegment, on: bool) -> None:
        if on:
            self._bookmarks.add(segment.t_start_ms)
        else:
            self._bookmarks.discard(segment.t_start_ms)
        self.bookmark_toggled.emit(segment, on)

    def load_segments(self, segments: list[TranscriptSegment]) -> None:
        """지난 세션을 열 때 저장된 자막 전체를 채운다."""
        self._list.clear()
        self._segments = []
        self._playing_row = -1
        for segment in segments:
            self.add_segment(segment)
        self._list.scrollToTop()

    # --- 대기 상태 배너 ---

    def show_pending(self, text: str) -> None:
        self._pending_base = text.rstrip("… .")
        self._dots = 0
        self._pending.setText(self._pending_base)
        self._pending.show()
        self._pending_timer.start(450)

    def clear_pending(self) -> None:
        self._pending_timer.stop()
        self._pending.hide()

    def _animate_pending(self) -> None:
        self._dots = (self._dots + 1) % 4
        self._pending.setText(self._pending_base + "." * self._dots)

    # --- 노트 쪽에서 (거터 클릭) ---

    def scroll_to_time(self, t_ms: int) -> None:
        """t_ms에 가장 가까운 자막 행으로 스크롤하고 잠깐 강조."""
        if not self._segments:
            return
        index = min(
            range(len(self._segments)),
            key=lambda i: abs(self._segments[i].t_start_ms - t_ms),
        )
        item = self._list.item(index)
        self._list.scrollToItem(item, QListWidget.PositionAtCenter)
        self._list.setCurrentItem(item)
        QTimer.singleShot(1400, self._list.clearSelection)

    # --- 라이브 세션 컨트롤 ---

    def set_live_controls(self, visible: bool, active: set | None = None) -> None:
        self._live_visible = visible
        self._live_started = bool(active)
        self._apply_live_visibility()
        if not visible:
            return
        if active is not None:
            self._updating_toggles = True
            for source, button in self._source_buttons.items():
                button.setChecked(source in active)
            self._updating_toggles = False
            self._sync_source_labels(active)

    def _apply_live_visibility(self) -> None:
        """시작 전엔 ● 녹음만, 시작 후엔 토글·경과·정지만."""
        visible = self._live_visible
        started = self._live_started
        for button in self._source_buttons.values():
            button.setVisible(visible and started)
        self._stop_btn.setVisible(visible and started)
        self._rec_label.setVisible(visible and started)
        self._rec_start_btn.setVisible(visible and not started)

    def update_recording_status(self, status: dict) -> None:
        """studio가 주기적으로 호출 — 로딩/경과 시간·소리 감지 표시."""
        if status.get("stopped"):
            return
        active = status.get("active", set())
        if status.get("loading"):
            text, state = "●  준비 중…", "loading"
        elif not active:
            text, state = "", ""  # 아무 소스도 안 켜짐 (일시정지)
        else:
            text = f"●  {format_ms(status.get('elapsed_ms', 0))} 녹음 중"
            state = "recording"
        if self._rec_label.text() != text:
            self._rec_label.setText(text)
        if self._rec_label.property("recState") != state:  # 리폴리시는 상태 변화 때만
            self._rec_label.setProperty("recState", state)
            self._rec_label.style().unpolish(self._rec_label)
            self._rec_label.style().polish(self._rec_label)
        self._sync_source_labels(active, status.get("heard", {}))

    def _sync_source_labels(self, active: set, heard: dict | None = None) -> None:
        """소스 버튼 상태를 색으로만 표시 (텍스트 폭 고정 — 바가 안 흔들리게).

        off=회색 / on=파랑 / 소리 감지=초록.
        """
        heard = heard or {}
        for source, button in self._source_buttons.items():
            on = source in active
            listening = on and heard.get(source)
            # 텍스트는 항상 동일 (폭 불변) — 켜짐 표시로 앞에 상태 점만
            button.setText(f"● {self._source_icons[source]} {self._source_names[source]}")
            state = "listening" if listening else ("on" if on else "off")
            if button.property("srcState") != state:
                button.setProperty("srcState", state)
                button.style().unpolish(button)
                button.style().polish(button)

    def _on_source_toggle(self, source: AudioSource, on: bool) -> None:
        if not self._updating_toggles:
            self.source_toggled.emit(source, on)

    def _on_record_clicked(self) -> None:
        self._live_started = True
        self._apply_live_visibility()
        for button in self._source_buttons.values():
            if not button.isChecked():
                button.setChecked(True)  # toggled 시그널이 소스를 켠다

    # --- 내부 ---

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.row_activated.emit(self._segments[self._list.row(item)])

    def _on_play_position(self, t_ms: int) -> None:
        """재생 위치가 가리키는 자막 행에 파스텔 배경."""
        index = -1
        if t_ms >= 0 and self._segments:
            from bisect import bisect_right

            starts = [seg.t_start_ms for seg in self._segments]
            index = bisect_right(starts, t_ms) - 1
        if index == self._playing_row:
            return
        self._set_row_playing(self._playing_row, False)
        self._set_row_playing(index, True)
        self._playing_row = index

    def _set_row_playing(self, index: int, on: bool) -> None:
        if not (0 <= index < self._list.count()):
            return
        row = self._list.itemWidget(self._list.item(index))
        if row is None:
            return
        row.setProperty("cssClass", "playingRow" if on else "")
        row.style().unpolish(row)
        row.style().polish(row)
