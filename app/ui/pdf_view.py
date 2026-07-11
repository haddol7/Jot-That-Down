"""PDF 필기 뷰 (GoodNotes 모티브) — 한 페이지씩 넘기며 주석을 긋는다.

- 도구(아이콘 버튼): 밑줄(자유 직선) · 형광펜(글자 인식 — 글자 없으면 안 그림) · 사각형 · 타원 · 지우개(드래그로 연속 삭제)
  같은 버튼을 다시 클릭하면 해제되어 스크롤 모드. 밑줄/사각형/타원은 더블클릭으로 색·굵기 설정.
- 확대/축소: Ctrl+휠, Ctrl+(+/-). 좌우 맞춤/위아래 맞춤 버튼.
- 페이지 이동: ◀ ▶, ←/→/PgUp/PgDn — page_changed(pdf_page) 발행 → 페이지별 노트 전환.
- 주석은 페이지 정규화 좌표(0~1)로 SQLite에 저장.
"""
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .icons import make_tool_icon, make_ui_icon

_TOOLS = [
    ("underline", "밑줄 — 드래그한 그대로 선 (대각선 가능) · 더블클릭: 색/굵기"),
    ("highlight", "형광펜 — 글씨 위를 드래그하면 글줄에 맞춰 칠해짐 · 더블클릭: 색/두께"),
    ("rect", "사각형 · 더블클릭: 색/굵기"),
    ("ellipse", "타원 · 더블클릭: 색/굵기"),
    ("eraser", "지우개 — 누른 채 드래그하면 지나가는 주석이 지워짐"),
]
_TOOL_COLORS = {
    "underline": "#e25757",
    "highlight": "#ffd43b",
    "rect": "#2383e2",
    "ellipse": "#2383e2",
}
_TOOL_WIDTHS = {"underline": 2.4, "highlight": 1.0, "rect": 2.0, "ellipse": 2.0}
_STYLABLE = {"underline", "highlight", "rect", "ellipse"}
_MARGIN = 12

_STYLE_COLORS = [("검정", "#1f1f1f"), ("파랑", "#2383e2"), ("빨강", "#e25757")]
_STYLE_WIDTHS = [("얇게", 1.2), ("중간", 2.4), ("굵게", 4.0)]
# 형광펜 전용: 파스텔 3색 + 띠 두께(글줄 높이 배율)
_HL_COLORS = [("옐로우", "#ffd43b"), ("블루", "#74c0fc"), ("그린", "#69db7c")]
_HL_WIDTHS = [("얇게", 0.6), ("중간", 1.0), ("굵게", 1.4)]


class _StylePopover(QWidget):
    """도구 버튼 아래에 뜨는 가로 팝오버 — 색 3개 · 굵기 3개.

    고르는 즉시 on_change(color, width)가 불리고, 바깥 클릭/포커스 이탈 시 사라진다.
    """

    def __init__(
        self, color: str, width: float, on_change,
        colors=None, widths=None,
    ) -> None:
        super().__init__(None, Qt.Popup)
        self.setObjectName("stylePopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._on_change = on_change
        self._color = color
        self._width = width

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(4)

        for _, value in (colors or _STYLE_COLORS):
            dot = QPushButton()
            dot.setCheckable(True)
            dot.setFixedSize(22, 22)
            dot.setCursor(Qt.PointingHandCursor)
            selected = "#ffffff" if value.lower() == color.lower() else value
            dot.setStyleSheet(
                f"QPushButton {{ background: {value}; border-radius: 11px;"
                f" border: 2px solid {selected}; }}"
            )
            dot.clicked.connect(lambda _, v=value: self._pick_color(v))
            row.addWidget(dot)

        sep = QLabel("│")
        sep.setProperty("cssClass", "rowMeta")
        row.addWidget(sep)

        self._width_buttons = []
        for name, value in (widths or _STYLE_WIDTHS):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("cssClass", "pageTab")
            button.setChecked(abs(value - width) < 0.15)
            button.clicked.connect(lambda _, v=value: self._pick_width(v))
            self._width_buttons.append((value, button))
            row.addWidget(button)

    def show_under(self, button) -> None:
        pos = button.mapToGlobal(button.rect().bottomLeft())
        self.adjustSize()
        self.move(pos.x(), pos.y() + 4)
        self.show()

    def _pick_color(self, value: str) -> None:
        self._color = value
        self._on_change(self._color, self._width)
        self.close()

    def _pick_width(self, value: float) -> None:
        self._width = value
        for v, button in self._width_buttons:
            button.setChecked(v == value)
        self._on_change(self._color, self._width)
        self.close()


class _ToolButton(QPushButton):
    def __init__(self, on_double_click) -> None:
        super().__init__()
        self._on_double_click = on_double_click

    def mouseDoubleClickEvent(self, event) -> None:
        self._on_double_click()


class _PdfCanvas(QWidget):
    """현재 페이지 하나를 그리는 캔버스 + 주석 오버레이."""

    def __init__(
        self,
        on_annotation: Callable[[int, str, tuple], None],
        on_erase: Callable[[int, float, float], None],
        on_zoom: Callable[[int], None],
    ) -> None:
        super().__init__()
        self._doc: QPdfDocument | None = None
        self._on_annotation = on_annotation
        self._on_erase = on_erase
        self._on_zoom = on_zoom
        self._annotations: list[dict] = []
        self.tool: str | None = None
        self.drag_style: tuple[str, float] = ("#e25757", 2.4)  # 미리보기용
        self.page_index = 0

        self._render_width: int | None = None  # None = 좌우 맞춤
        self._pixmaps: dict[tuple[int, int], QPixmap] = {}
        self._text_line_cache: dict[int, list[tuple]] = {}  # 페이지 → 글줄 영역들
        self._drag: tuple | None = None  # (x0, y0, x1, y1) 정규화
        self._drag_highlights: list[tuple] = []  # 형광펜 미리보기 (텍스트 스냅)
        self._erasing = False

        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout)

        # 직선 도구: 드래그 중 1초 멈추면 수평/수직으로 스냅
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(1000)
        self._hold_timer.timeout.connect(self._snap_line)
        self._snap_axis: str | None = None  # None | "h" | "v"
        self._last_move = None

    # --- 외부 API ---

    def set_document(self, doc: QPdfDocument | None) -> None:
        self._doc = doc
        self.page_index = 0
        self._render_width = None
        self._pixmaps.clear()
        self._text_line_cache.clear()
        self.setMinimumWidth(0)
        self._relayout()

    def set_page(self, index: int) -> None:
        self.page_index = index
        self._drag = None
        self._relayout()

    def set_render_width(self, width: int | None) -> None:
        """None = 좌우 맞춤, 값 = 그 픽셀 폭으로 (줌)."""
        self._render_width = width
        self.setMinimumWidth(0 if width is None else width + 2 * _MARGIN)
        self._relayout()

    def set_annotations(self, annotations: list[dict]) -> None:
        self._annotations = annotations
        self.update()

    # --- 레이아웃/렌더 ---

    def page_width_px(self) -> int:
        if self._render_width is not None:
            return self._render_width
        return max(50, self.width() - 2 * _MARGIN)

    def _origin_x(self) -> int:
        """페이지가 캔버스보다 좁으면 가로 중앙 정렬 (위아래 맞춤 등)."""
        return max(_MARGIN, (self.width() - self.page_width_px()) // 2)

    def page_ratio(self) -> float:
        size = self._doc.pagePointSize(self.page_index)
        return size.height() / max(size.width(), 1)

    def _page_height(self) -> float:
        return self.page_width_px() * self.page_ratio()

    def _relayout(self) -> None:
        if self._doc is None or self._doc.pageCount() == 0:
            self.setMinimumHeight(0)
            self.update()
            return
        self.setMinimumHeight(int(self._page_height() + 2 * _MARGIN))
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_timer.start(150)

    _CACHE_BYTES = 150 * 1024 * 1024  # 렌더 캐시 총량 상한

    def _pixmap(self) -> QPixmap:
        width = self.page_width_px()
        key = (self.page_index, width)
        if key not in self._pixmaps:
            # 표시 크기의 2배 해상도로 렌더 후 devicePixelRatio를 걸어
            # 부드럽게 축소 — 계단현상(에일리어싱)이 크게 줄어든다.
            # 이미 크게 확대된 상태에서는 원본 해상도로도 충분해 배율을 줄인다
            # (4000px 페이지를 2배 렌더하면 장당 360MB가 된다)
            ss = 2 if width < 2000 else 1
            image = self._doc.render(
                self.page_index,
                QSize(width * ss, int(self._page_height()) * ss),
            )
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(ss)
            self._pixmaps[key] = pixmap
            self._trim_cache(keep_key=key)
        return self._pixmaps[key]

    def _trim_cache(self, keep_key: tuple) -> None:
        """캐시를 개수가 아니라 총 바이트로 제한 — 줌 몇 번에 수백 MB가
        쌓이는 것을 막는다. 오래된 항목부터 버린다."""
        def nbytes(pm: QPixmap) -> int:
            return pm.width() * pm.height() * 4

        total = sum(nbytes(p) for p in self._pixmaps.values())
        for old in list(self._pixmaps):
            if total <= self._CACHE_BYTES:
                break
            if old == keep_key:
                continue
            total -= nbytes(self._pixmaps.pop(old))

    def paintEvent(self, event) -> None:
        if self._doc is None or self._doc.pageCount() == 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        width = self.page_width_px()
        height = self._page_height()
        origin_x = self._origin_x()
        painter.fillRect(
            QRectF(origin_x - 1, _MARGIN - 1, width + 2, height + 2),
            QColor("#00000030"),
        )
        painter.drawPixmap(origin_x, _MARGIN, self._pixmap())
        for annotation in self._annotations:
            if annotation["page"] == self.page_index:
                self._draw(painter, annotation["kind"], annotation["rect"],
                           annotation["color"], annotation.get("width", 2.4))
        if self._drag is not None:
            color, pen_width = self.drag_style
            if self.tool == "highlight":
                # 드래그 영역 자체를 옅게 — 어디를 지나는지 항상 보이게
                x0, y0, x1, y1 = self._drag
                band = QRectF(
                    origin_x + min(x0, x1) * width,
                    _MARGIN + min(y0, y1) * height,
                    abs(x1 - x0) * width,
                    abs(y1 - y0) * height,
                )
                faint = QColor(color)
                faint.setAlpha(34)
                painter.fillRect(band, faint)
                for rect in self._drag_highlights:  # 글자 스냅 미리보기
                    self._draw(painter, "highlight", rect, color, pen_width)
            else:
                self._draw(painter, self.tool, self._drag, color, pen_width)
        painter.end()

    def _text_lines(self) -> list[tuple]:
        """이 페이지 글줄들의 정규화 영역 (페이지별 캐시)."""
        if self.page_index in self._text_line_cache:
            return self._text_line_cache[self.page_index]
        size = self._doc.pagePointSize(self.page_index)
        rects: list[tuple] = []
        for polygon in self._doc.getAllText(self.page_index).bounds():
            bounds = polygon.boundingRect()
            if bounds.width() <= 0 or bounds.height() <= 0:
                continue
            rects.append((
                bounds.left() / size.width(),
                bounds.top() / size.height(),
                bounds.right() / size.width(),
                bounds.bottom() / size.height(),
            ))
        lines = self._merge_line_rects(rects)
        self._text_line_cache[self.page_index] = lines
        return lines

    def highlight_rects(self, rect: tuple) -> list[tuple]:
        """드래그 영역과 겹치는 글줄 부분들 (정규화 좌표).

        글자를 지나지 않은 드래그는 빈 목록 — 아무것도 칠하지 않는다.
        """
        rx0, ry0 = min(rect[0], rect[2]), min(rect[1], rect[3])
        rx1, ry1 = max(rect[0], rect[2]), max(rect[1], rect[3])
        result: list[tuple] = []
        for lx0, ly0, lx1, ly1 in self._text_lines():
            line_height = ly1 - ly0
            overlap_y = min(ly1, ry1) - max(ly0, ry0)
            if overlap_y < 0.12 * line_height:  # 살짝만 걸쳐도 칠해지게 (느슨하게)
                continue
            x0 = max(lx0, rx0)
            x1 = min(lx1, rx1)
            if x1 - x0 > 0.005:
                result.append((x0, ly0, x1, ly1))
        return result

    @staticmethod
    def _merge_line_rects(rects: list[tuple]) -> list[tuple]:
        """같은 글줄의 조각들을 하나로 — 단어 사이 공백도 이어서 칠해지게."""
        lines: list[list[float]] = []
        for r in sorted(rects, key=lambda r: (r[1], r[0])):
            for line in lines:
                overlap = min(line[3], r[3]) - max(line[1], r[1])
                shorter = min(line[3] - line[1], r[3] - r[1])
                if shorter > 0 and overlap > 0.5 * shorter:  # 세로로 겹침 = 같은 줄
                    line[0] = min(line[0], r[0])
                    line[1] = min(line[1], r[1])
                    line[2] = max(line[2], r[2])
                    line[3] = max(line[3], r[3])
                    break
            else:
                lines.append(list(r))
        return [tuple(line) for line in lines]

    def _draw(
        self, painter: QPainter, kind: str, rect, color: str, pen_width: float = 2.4
    ) -> None:
        # rect는 이미 최종 좌표 (형광펜은 글자 스냅/띠 변환이 끝난 상태)
        x0, y0, x1, y1 = rect
        width = self.page_width_px()
        height = self._page_height()
        origin_x = self._origin_x()
        px = QRectF(
            origin_x + min(x0, x1) * width,
            _MARGIN + min(y0, y1) * height,
            abs(x1 - x0) * width,
            abs(y1 - y0) * height,
        )
        if kind == "highlight":
            # 형광펜의 width는 띠 두께(글줄 높이 배율). 예전 주석은 펜 굵기
            # 값(2.4)이 들어 있으므로 배율 범위 밖이면 1.0으로 취급한다.
            scale = pen_width if 0.0 < pen_width <= 2.0 else 1.0
            if scale != 1.0:
                delta = px.height() * (1 - scale) / 2
                px = px.adjusted(0, delta, 0, -delta)
            fill = QColor(color)
            fill.setAlpha(90)
            painter.fillRect(px, fill)
        elif kind == "underline":
            # 드래그한 그대로의 직선 — 대각선도 가능
            painter.setPen(QPen(QColor(color), pen_width))
            painter.drawLine(
                int(origin_x + x0 * width), int(_MARGIN + y0 * height),
                int(origin_x + x1 * width), int(_MARGIN + y1 * height),
            )
        elif kind == "rect":
            painter.setPen(QPen(QColor(color), pen_width))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(px)
        elif kind == "ellipse":
            painter.setPen(QPen(QColor(color), pen_width))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(px)

    # --- 마우스 (주석 긋기/지우기) ---

    def _hit(self, pos) -> tuple[float, float] | None:
        width = self.page_width_px()
        height = self._page_height()
        origin_x = self._origin_x()
        if (origin_x <= pos.x() <= origin_x + width
                and _MARGIN <= pos.y() <= _MARGIN + height):
            return ((pos.x() - origin_x) / width, (pos.y() - _MARGIN) / height)
        return None

    def mousePressEvent(self, event) -> None:
        if self.tool is None or event.button() != Qt.LeftButton:
            return
        hit = self._hit(event.position())
        if hit is None:
            return
        x, y = hit
        if self.tool == "eraser":
            self._erasing = True  # 누른 채 드래그하면 연속으로 지운다
            self._on_erase(self.page_index, x, y)
            return
        self._drag = (x, y, x, y)
        if self.tool == "underline":
            self._snap_axis = None
            self._last_move = event.position()
            self._hold_timer.start()

    def mouseMoveEvent(self, event) -> None:
        if self._erasing:
            hit = self._hit(event.position())
            if hit:
                self._on_erase(self.page_index, hit[0], hit[1])
            return
        if self._drag is None:
            return
        hit = self._hit(event.position())
        if hit:
            x, y = hit
            if self._snap_axis == "h":    # 스냅 후에는 축을 유지한 채 이동
                y = self._drag[1]
            elif self._snap_axis == "v":
                x = self._drag[0]
            self._drag = (self._drag[0], self._drag[1], x, y)
            if self.tool == "highlight":
                self._drag_highlights = self.highlight_rects(self._drag)
            self.update()
        if self.tool == "underline" and self._last_move is not None:
            # 3px 이상 움직였을 때만 '멈춤' 타이머를 다시 잰다
            delta = event.position() - self._last_move
            if abs(delta.x()) + abs(delta.y()) > 3:
                self._last_move = event.position()
                if self._snap_axis is None:
                    self._hold_timer.start()

    def _snap_line(self) -> None:
        """드래그 중 1초 멈춤 — 직선을 수평/수직 중 가까운 쪽으로 스냅."""
        if self._drag is None or self.tool != "underline":
            return
        x0, y0, x1, y1 = self._drag
        dx = abs(x1 - x0) * self.page_width_px()
        dy = abs(y1 - y0) * self._page_height()
        self._snap_axis = "h" if dx >= dy else "v"
        if self._snap_axis == "h":
            self._drag = (x0, y0, x1, y0)
        else:
            self._drag = (x0, y0, x0, y1)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._erasing = False
        self._hold_timer.stop()
        self._snap_axis = None
        self._last_move = None
        if self._drag is None:
            return
        x0, y0, x1, y1 = self._drag
        self._drag = None
        self._drag_highlights = []
        self.update()
        if abs(x1 - x0) < 0.004 and abs(y1 - y0) < 0.004:
            return  # 실수 클릭
        if self.tool == "highlight":
            # 글자 인식: 드래그 구간의 글줄들을 각각 하나의 형광펜으로
            for rect in self.highlight_rects((x0, y0, x1, y1)):
                self._on_annotation(self.page_index, "highlight", rect)
        else:
            self._on_annotation(self.page_index, self.tool, (x0, y0, x1, y1))

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            self._on_zoom(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        else:
            event.ignore()  # 스크롤 영역이 처리


class PdfAnnotationView(QWidget):
    """도구 줄(아이콘) + 줌/맞춤 + 페이지 내비게이션 + 캔버스."""

    page_changed = Signal(int)  # 사용자가 페이지를 넘김 → 노트도 전환
    style_saved = Signal()      # 도구 스타일 변경 → 설정 저장은 조립 루트가

    def __init__(self, store, settings=None) -> None:
        super().__init__()
        self._store = store
        self._settings = settings
        self._session_id: int | None = None
        self._clock = None
        self._doc: QPdfDocument | None = None
        self.setFocusPolicy(Qt.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tools_bar = QWidget()
        tools_bar.setObjectName("pageTabBar")
        tools_bar.setAttribute(Qt.WA_StyledBackground, True)
        tools_layout = QHBoxLayout(tools_bar)
        tools_layout.setContentsMargins(10, 4, 10, 4)
        tools_layout.setSpacing(4)

        self._tool_buttons: dict[str, QPushButton] = {}
        for tool, tip in _TOOLS:
            button = _ToolButton(
                on_double_click=(
                    (lambda t=tool: self._edit_style(t))
                    if tool in _STYLABLE else (lambda: None)
                ),
            )
            button.setIcon(make_tool_icon(tool))
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.setProperty("cssClass", "toolBtn")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tip)
            button.clicked.connect(lambda _, t=tool: self._on_tool_clicked(t))
            self._tool_buttons[tool] = button
            tools_layout.addWidget(button)

        # 주석 실행 취소/다시 실행
        self._undo_stack: list[tuple] = []
        self._redo_stack: list[tuple] = []
        for kind, tip, handler in [
            ("undo", "실행 취소 (Ctrl+Z)", self._undo),
            ("redo", "다시 실행 (Ctrl+Y)", self._redo),
        ]:
            button = QPushButton()
            button.setIcon(make_ui_icon(kind, 18))
            button.setIconSize(QSize(20, 20))
            button.setProperty("cssClass", "ghost")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tip)
            button.clicked.connect(handler)
            tools_layout.addWidget(button)
        tools_layout.addStretch()

        for kind, tip, handler in [
            ("fit_width", "좌우 맞춤", self.fit_width),
            ("fit_height", "위아래 맞춤", self.fit_height),
        ]:
            button = QPushButton()
            button.setIcon(make_tool_icon(kind))
            button.setIconSize(QSize(20, 20))
            button.setProperty("cssClass", "ghost")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tip + " (확대/축소: Ctrl+휠, Ctrl+±)")
            button.clicked.connect(handler)
            tools_layout.addWidget(button)

        prev_btn = QPushButton()
        prev_btn.setIcon(make_ui_icon("prev", 16))
        prev_btn.setIconSize(QSize(18, 18))
        prev_btn.setProperty("cssClass", "ghost")
        prev_btn.setCursor(Qt.PointingHandCursor)
        prev_btn.setToolTip("이전 페이지 (←)")
        prev_btn.clicked.connect(lambda: self._go(-1))
        tools_layout.addWidget(prev_btn)
        self._nav_label = QLabel("1 / 1")
        self._nav_label.setProperty("cssClass", "rowMeta")
        tools_layout.addWidget(self._nav_label)
        next_btn = QPushButton()
        next_btn.setIcon(make_ui_icon("next", 16))
        next_btn.setIconSize(QSize(18, 18))
        next_btn.setProperty("cssClass", "ghost")
        next_btn.setCursor(Qt.PointingHandCursor)
        next_btn.setToolTip("다음 페이지 (→)")
        next_btn.clicked.connect(lambda: self._go(1))
        tools_layout.addWidget(next_btn)
        layout.addWidget(tools_bar)

        self._canvas = _PdfCanvas(self._add_annotation, self._erase_at, self.zoom_step)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._canvas)
        # 방향키를 스크롤이 가로채지 않고 페이지 이동에 쓰도록
        self._scroll.setFocusPolicy(Qt.NoFocus)
        self._scroll.viewport().installEventFilter(self)
        layout.addWidget(self._scroll)
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        # PDF 영역을 클릭하면 이 뷰가 포커스를 가져가 ←/→ 페이지 이동이 먹는다
        if event.type() == QEvent.MouseButtonPress:
            self.setFocus()
        return super().eventFilter(obj, event)

    # --- SessionPage에서 ---

    @property
    def current_page(self) -> int:
        return self._canvas.page_index

    def open(self, session_id: int, pdf_path: str, clock) -> None:
        self._session_id = session_id
        self._clock = clock
        self._doc = QPdfDocument(self)
        self._doc.load(pdf_path)
        self._canvas.set_document(self._doc)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_nav()
        self._refresh_annotations()
        self.show()

    def attach_clock(self, clock) -> None:
        self._clock = clock

    def clear(self) -> None:
        self._session_id = None
        self._doc = None
        self._canvas.set_document(None)
        self._canvas.set_annotations([])
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.hide()

    # --- 확대/축소 ---

    def zoom_step(self, direction: int) -> None:
        current = self._canvas.page_width_px()
        factor = 1.15 if direction > 0 else 1 / 1.15
        self._canvas.set_render_width(int(max(120, min(4000, current * factor))))

    def fit_width(self) -> None:
        self._canvas.set_render_width(None)

    def fit_height(self) -> None:
        if self._doc is None:
            return
        available = self._scroll.viewport().height() - 2 * _MARGIN
        self._canvas.set_render_width(
            int(max(120, available / self._canvas.page_ratio()))
        )

    # --- 페이지 이동 ---

    def _go(self, delta: int) -> None:
        if self._doc is None:
            return
        target = max(0, min(self._doc.pageCount() - 1,
                            self._canvas.page_index + delta))
        if target == self._canvas.page_index:
            return
        self._canvas.set_page(target)
        self._scroll.verticalScrollBar().setValue(0)
        self._update_nav()
        self.page_changed.emit(target)

    def keyPressEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Z:
            self._undo()
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Y:
            self._redo()
        elif event.modifiers() & Qt.ControlModifier and event.key() in (
            Qt.Key_Plus, Qt.Key_Equal
        ):
            self.zoom_step(1)
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Minus:
            self.zoom_step(-1)
        elif event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self._go(-1)
        elif event.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self._go(1)
        else:
            super().keyPressEvent(event)

    def _update_nav(self) -> None:
        total = self._doc.pageCount() if self._doc else 0
        self._nav_label.setText(f"{self._canvas.page_index + 1} / {max(total, 1)}")

    # --- 도구 ---

    def _tool_style(self, tool: str) -> tuple[str, float]:
        styles = (self._settings.pdf_tool_styles if self._settings else {}) or {}
        style = styles.get(tool, {})
        return (
            style.get("color", _TOOL_COLORS[tool]),
            style.get("width", _TOOL_WIDTHS[tool]),
        )

    def _on_tool_clicked(self, tool: str) -> None:
        if self._canvas.tool == tool:  # 같은 버튼 재클릭 → 해제 (스크롤 모드)
            self._tool_buttons[tool].setChecked(False)
            self._set_tool(None)
            return
        for name, button in self._tool_buttons.items():
            button.setChecked(name == tool)
        self._set_tool(tool)

    def _set_tool(self, tool: str | None) -> None:
        self._canvas.tool = tool
        if tool and tool != "eraser":
            self._canvas.drag_style = self._tool_style(tool)
        self._canvas.setCursor(
            Qt.ArrowCursor if tool is None else Qt.CrossCursor
        )

    def _edit_style(self, tool: str) -> None:
        # 더블클릭의 첫 클릭이 이미 켜진 도구를 꺼버릴 수 있으므로 항상 다시 선택
        # (안 그러면 굵기를 바꾼 직후 그려도 아무것도 안 보인다)
        for name, button in self._tool_buttons.items():
            button.setChecked(name == tool)
        self._set_tool(tool)
        colors = _HL_COLORS if tool == "highlight" else None
        widths = _HL_WIDTHS if tool == "highlight" else None
        color, width = self._tool_style(tool)

        def apply(new_color: str, new_width: float) -> None:
            if self._settings is not None:
                self._settings.pdf_tool_styles[tool] = {
                    "color": new_color, "width": new_width
                }
                self.style_saved.emit()
            if self._canvas.tool == tool:
                self._canvas.drag_style = (new_color, new_width)

        self._style_popover = _StylePopover(
            color, width, apply, colors=colors, widths=widths
        )  # 참조 유지
        self._style_popover.show_under(self._tool_buttons[tool])

    # --- 주석 ---

    def _refresh_annotations(self) -> None:
        if self._session_id is not None:
            self._canvas.set_annotations(
                self._store.pdf_annotations_for(self._session_id)
            )

    def _add_annotation(self, page: int, kind: str, rect: tuple) -> None:
        if self._session_id is None:
            return
        color, width = self._tool_style(kind) if kind in _STYLABLE else (
            _TOOL_COLORS[kind], _TOOL_WIDTHS[kind]
        )
        t_ms = self._clock.now_ms() if self._clock is not None else None
        # 형광펜은 캔버스가 글자 영역으로 스냅한 rect를 이미 넘겨준다
        new_id = self._store.add_pdf_annotation(
            self._session_id, page, kind, rect, color, width, t_ms
        )
        self._push_undo(("add", {
            "id": new_id, "page": page, "kind": kind, "rect": rect,
            "color": color, "width": width, "t_ms": t_ms,
        }))
        self._refresh_annotations()

    def _erase_at(self, page: int, x: float, y: float) -> None:
        if self._session_id is None:
            return
        tolerance = 0.012
        for annotation in reversed(self._store.pdf_annotations_for(self._session_id)):
            if annotation["page"] != page:
                continue
            x0, y0, x1, y1 = annotation["rect"]
            if (min(x0, x1) - tolerance <= x <= max(x0, x1) + tolerance
                    and min(y0, y1) - tolerance <= y <= max(y0, y1) + tolerance):
                self._store.delete_pdf_annotation(annotation["id"])
                self._push_undo(("del", annotation))
                self._refresh_annotations()
                return

    # --- 실행 취소/다시 실행 (주석 단위) ---

    def _push_undo(self, op: tuple) -> None:
        self._undo_stack.append(op)
        self._redo_stack.clear()

    def _restore(self, ann: dict) -> None:
        """지워졌던 주석을 다시 넣는다 (새 id로 갱신)."""
        ann["id"] = self._store.add_pdf_annotation(
            self._session_id, ann["page"], ann["kind"], ann["rect"],
            ann["color"], ann.get("width", 2.4), ann.get("t_ms"),
        )

    def _undo(self) -> None:
        if not self._undo_stack or self._session_id is None:
            return
        op, ann = self._undo_stack.pop()
        if op == "add":
            self._store.delete_pdf_annotation(ann["id"])
        else:
            self._restore(ann)
        self._redo_stack.append((op, ann))
        self._refresh_annotations()

    def _redo(self) -> None:
        if not self._redo_stack or self._session_id is None:
            return
        op, ann = self._redo_stack.pop()
        if op == "add":
            self._restore(ann)
        else:
            self._store.delete_pdf_annotation(ann["id"])
        self._undo_stack.append((op, ann))
        self._refresh_annotations()
