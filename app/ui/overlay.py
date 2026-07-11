"""컴팩트 오버레이 자막 창 — 창을 최소화하면 나타나는 실시간 자막.

디자인 레퍼런스(라이브 캡션 UX 통설, Smashing/CapCut 등):
- 반투명 검정 배경(불투명 ~80%) + 큰 라운드 — 어떤 배경 위에서도 읽힘
- 흰 글씨, 산세리프, 18~22px — 가독성 최우선
- 화면 하단 중앙, 최근 2줄만. 현재 발화만 강조.
- 드래그 이동, 우측 상단에 복원 버튼.
"""
import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import AudioSource, TranscriptSegment

_DOT = {AudioSource.MIC: "#5aa9ff", AudioSource.SYSTEM: "#9be36b"}  # 출처 색점


class OverlayWindow(QWidget):
    restore_requested = Signal()

    def __init__(self, settings=None) -> None:
        super().__init__()
        self._settings = settings
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 반투명 검정 라운드 카드 (레퍼런스: 어떤 배경에서도 읽히는 gold standard)
        self._card = QWidget(self)
        self._card.setObjectName("overlayCard")
        self._card.setStyleSheet(
            "#overlayCard {"
            "  background: rgba(18, 18, 20, 214);"
            "  border-radius: 16px;"
            "}"
        )
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(18, 12, 12, 14)
        card_layout.setSpacing(4)

        # 상단 바: 복원 버튼만 (우측)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch()
        from .icons import make_ui_icon

        restore = QPushButton()
        restore.setIcon(make_ui_icon("restore", 14, "#dddddd"))
        restore.setCursor(Qt.PointingHandCursor)
        restore.setFixedSize(22, 22)
        restore.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 5px; }"
            "QPushButton:hover { background: rgba(255,255,255,40); }"
        )
        restore.clicked.connect(self.restore_requested)
        top.addWidget(restore)
        card_layout.addLayout(top)

        self._lines_box = QVBoxLayout()
        self._lines_box.setContentsMargins(0, 0, 0, 0)
        self._lines_box.setSpacing(3)
        card_layout.addLayout(self._lines_box)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._card)

        self._lines: list[tuple[float, QLabel, tuple]] = []  # (시각, 라벨, 발화 키)
        self._drag_offset: QPoint | None = None

        # 폭·아래 변 고정, 높이는 내용만큼 (위로만 자란다 — 위 여백 없음)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self._width = min(760, int(screen.width() * 0.55))
        self.setFixedWidth(self._width)
        self._anchor_bottom = screen.bottom() - 70
        self.move(screen.center().x() - self._width // 2, self._anchor_bottom)
        self._refit()

        self._expire_timer = QTimer(self)
        self._expire_timer.timeout.connect(self._expire_old_lines)
        self._expire_timer.start(1000)

    # --- 설정 (없으면 기본값) ---

    @property
    def _font_px(self) -> int:
        return getattr(self._settings, "overlay_font_px", 20) if self._settings else 20

    @property
    def _max_lines(self) -> int:
        return getattr(self._settings, "overlay_lines", 2) if self._settings else 2

    @property
    def _ttl_sec(self) -> float:
        return getattr(self._settings, "overlay_ttl_sec", 10) if self._settings else 10

    # --- 슬롯 (브리지 시그널과 연결) ---

    _CAPTION_QSS = (
        "color: #ffffff; line-height: 1.35;"
        "border-left: 3px solid {dot}; padding-left: 10px;"
    )

    def _caption_font(self) -> QFont:
        font = QFont("NanumSquare Neo")
        font.setPixelSize(self._font_px)
        return font

    def _refit(self) -> None:
        """내용에 맞춰 높이 조절 — 아래 변은 고정, 위로만 늘고 준다."""
        # 레이아웃 sizeHint는 워드랩 줄바꿈을 반영하지 못하므로
        # 자막 라벨들의 실제 높이(heightForWidth)를 직접 합산한다
        inner_w = self._width - 18 - 12  # 카드 좌우 여백
        lines_h = 0
        for _, label, _ in self._lines:
            h = label.heightForWidth(inner_w)
            lines_h += min(h, label.maximumHeight())
        lines_h += max(0, len(self._lines) - 1) * 3  # 줄 간격
        height = 12 + 22 + 4 + lines_h + 14  # 상하 여백 + 상단바 + 간격
        self.setFixedHeight(max(height, 52))
        self.move(self.x(), self._anchor_bottom - self.height())

    def _make_caption(self, text: str, dot_color: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(self._caption_font())
        label.setStyleSheet(self._CAPTION_QSS.format(dot=dot_color))
        return label

    def _tail_fit(self, text: str) -> tuple[str, int]:
        """2줄에 들어가게 앞부분을 '…'로 생략 — 최신 내용(끝)이 항상 보이게.

        표시 라벨과 완전히 같은 조건(폰트+스타일시트)의 프로브로 실측 판정.
        반환: (잘린 텍스트, 2줄 높이). 스타일시트가 줄바꿈 계산을 바꾸므로
        메트릭 예측 대신 이 방식이어야 렌더링과 일치한다.
        """
        probe = self._make_caption("가\n가", "#ffffff")  # 정확한 2줄 높이 기준
        width = self._width - 18 - 12  # 카드 좌우 여백만 뺀 라벨 폭
        max_h = probe.heightForWidth(width)

        def fits(t: str) -> bool:
            probe.setText(t)
            return probe.heightForWidth(width) <= max_h

        if fits(text):
            return text, max_h
        lo, hi = 0, len(text)
        while lo < hi:  # 잘라낼 앞부분 길이를 이진 탐색
            mid = (lo + hi) // 2
            if fits("…" + text[mid:]):
                hi = mid
            else:
                lo = mid + 1
        return "…" + text[lo:], max_h

    def show_segment(self, segment: TranscriptSegment) -> None:
        text, max_h = self._tail_fit(segment.text)
        key = (segment.source, segment.t_start_ms)
        # 이어붙는 문장(같은 발화)은 새 줄 대신 현재 줄을 제자리에서 갱신 —
        # 안 그러면 문장이 자랄 때마다 이전 버전이 흐린 줄로 남아 겹쳐 보인다
        if self._lines and self._lines[-1][2] == key:
            stamp, label, _ = self._lines[-1]
            label.setText(text)
            self._lines[-1] = (time.monotonic(), label, key)
            self._refit()
            return
        label = self._make_caption(text, _DOT[segment.source])
        label.setMaximumHeight(max_h)  # 겹침 방지 안전장치
        # 이전 줄은 흐리게 (현재 발화만 또렷)
        for _, old, _ in self._lines:
            old.setStyleSheet(
                "color: rgba(255,255,255,120); line-height: 1.3;"
                "border-left: 3px solid rgba(255,255,255,60); padding-left: 10px;"
            )
        self._lines_box.addWidget(label)
        self._lines.append((time.monotonic(), label, key))
        while len(self._lines) > self._max_lines:
            self._remove_oldest()
        self._refit()

    def set_click_through(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowTransparentForInput, enabled)
        self.show()

    # --- 내부 ---

    def _remove_oldest(self) -> None:
        _, label, _ = self._lines.pop(0)
        self._lines_box.removeWidget(label)
        label.deleteLater()

    def _expire_old_lines(self) -> None:
        now = time.monotonic()
        removed = False
        while self._lines and now - self._lines[0][0] > self._ttl_sec:
            self._remove_oldest()
            removed = True
        if removed:
            self._refit()

    # --- 드래그 이동 ---

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._anchor_bottom = self.y() + self.height()  # 새 위치에 다시 고정

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
