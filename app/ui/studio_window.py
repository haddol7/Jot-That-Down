"""스튜디오 메인 창 — 홈(세션 목록)과 세션 페이지(에디터+자막)의 스택.

세션 페이지 동기화 규칙(SessionPage가 유일한 조율자):
- 새 블록 생성 → 세션 시각 기록 + 거터 표시 (라이브 세션만)
- 거터 시각 클릭 → 자막 패널 스크롤 / 자막 행 클릭 → 노트 블록 점프
- 자막 [인용] → 인용 블록 삽입 (블록 시각 = 자막 원본 시각)
- 자막 [▶] → play_requested (재생은 조립 루트가 담당)

엔진·녹음기 등 런타임 수명은 이 모듈 밖(studio.py)에서 관리한다.
"""
import shutil
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
    QVBoxLayout,
)

from ..core.clock import SessionClock, format_ms
from ..core.models import AudioSource, TranscriptSegment
from ..settings import AppSettings
from ..store.db import SessionStore
from ..store.export import export_markdown
from .corrections_dialog import CorrectionsDialog
from .editor_view import EditorView
from .home_page import HomePage
from .pdf_view import PdfAnnotationView
from .settings_dialog import SettingsDialog
from .transcript_panel import TranscriptPanel

_ICONS = {"mic": "\U0001F3A4", "system": "\U0001F50A"}


class _ThemeSwitch(QWidget):
    """라이트/다크 토글 스위치 — 손잡이에 ☀/🌙."""

    def __init__(self, on_toggle) -> None:
        super().__init__()
        self.setFixedSize(48, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("테마 전환")
        self._dark = False
        self._on_toggle = on_toggle

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._on_toggle()

    def paintEvent(self, event) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3f3f46") if self._dark else QColor("#d9d9d4"))
        p.drawRoundedRect(QRectF(0, 3, w, h - 6), (h - 6) / 2, (h - 6) / 2)
        knob = h - 4
        x = w - knob - 2 if self._dark else 2
        p.setBrush(QColor("#27272b") if self._dark else QColor("#ffffff"))
        p.drawEllipse(QRectF(x, 2, knob, knob))
        font = QFont()
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(QColor("#f4b03e"))
        p.drawText(QRectF(x, 2, knob, knob), Qt.AlignCenter,
                   "\U0001F319" if self._dark else "☀")
        p.end()


def _process_rss_mb() -> int:
    """현재 프로세스의 물리 메모리(MB). 실패 시 0."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return round(counters.WorkingSetSize / (1024 * 1024))
    except Exception:
        pass
    return 0


_NVML_HANDLE = None


def _gpu_mem_mb() -> tuple[int, int]:
    """GPU 사용/총 VRAM(MB). 실패 시 (0, 0).

    NVML을 프로세스 안에서 직접 호출 — nvidia-smi 프로세스 스폰(회당
    수십 ms)보다 훨씬 싸다.
    """
    global _NVML_HANDLE
    try:
        import pynvml

        if _NVML_HANDLE is None:
            pynvml.nvmlInit()
            _NVML_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(_NVML_HANDLE)
        return int(info.used // 1048576), int(info.total // 1048576)
    except Exception:
        return (0, 0)


class _PageTab(QPushButton):
    """페이지 탭 — 더블클릭으로 이름 변경."""

    def __init__(self, title: str, on_rename) -> None:
        super().__init__(title)
        self.setCheckable(True)
        self.setProperty("cssClass", "pageTab")
        self.setCursor(Qt.PointingHandCursor)
        self._on_rename = on_rename

    def mouseDoubleClickEvent(self, event) -> None:
        self._on_rename()


class SessionPage(QWidget):
    panel_collapsed = Signal(bool)  # 자막 패널이 스플리터로 완전히 접혔는지
    layout_changed = Signal()       # 패널 도킹 위치 변경 → 설정 저장은 조립 루트가

    def __init__(self, store: SessionStore, settings: AppSettings) -> None:
        super().__init__()
        self.setObjectName("sessionPage")
        self._store = store
        self._settings = settings
        self._session_id: int | None = None
        self._page_id: int | None = None
        self._clock: SessionClock | None = None  # None = 아카이브(스탬프 없음)
        self._js_ready = False
        self._pending_open = False
        self._pending_partial: dict = {}  # 소스별 이어붙이는 중인 조각

        self.editor = EditorView()
        self.panel = TranscriptPanel()

        # 왼쪽 아래: [브레드크럼: 노트 › 하위 페이지 › …] + [에디터]
        note_area = QWidget()
        note_layout = QVBoxLayout(note_area)
        note_layout.setContentsMargins(0, 0, 0, 0)
        note_layout.setSpacing(0)
        crumb_bar = QWidget()
        crumb_bar.setObjectName("pageTabBar")
        crumb_bar.setAttribute(Qt.WA_StyledBackground, True)
        self._crumbs_layout = QHBoxLayout(crumb_bar)
        self._crumbs_layout.setContentsMargins(10, 6, 10, 6)
        self._crumbs_layout.setSpacing(2)
        note_layout.addWidget(crumb_bar, stretch=0)
        note_layout.addWidget(self.editor, stretch=1)

        # 왼쪽: [PDF 필기 (import 시)] 위 / [노트] 아래 (GoodNotes 모티브)
        self.pdf_view = PdfAnnotationView(store, settings)
        left_split = QSplitter(Qt.Vertical)
        left_split.addWidget(self.pdf_view)
        left_split.addWidget(note_area)
        left_split.setSizes([420, 380])

        self._content = left_split  # PDF+노트 묶음 (패널 반대편)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_split)
        splitter.addWidget(self.panel)
        splitter.splitterMoved.connect(
            lambda *_: self.panel_collapsed.emit(self._panel_size() == 0)
        )
        self._main_split = splitter
        self.set_panel_dock(getattr(settings, "panel_side", "right"), save=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.editor.bridge.js_ready.connect(self._on_js_ready)
        self.editor.shown_settled.connect(self._on_editor_settled)
        self.editor.bridge.block_added.connect(self._on_block_added)
        self.editor.bridge.block_stamp_forced.connect(self._on_block_stamp_forced)
        self.editor.bridge.doc_saved.connect(self._on_doc_saved)
        self.editor.bridge.gutter_clicked.connect(self._on_gutter_clicked)
        self.editor.bridge.page_open_requested.connect(self._switch_page)
        self.editor.bridge.create_page_handler = self._create_sub_page
        self.editor.bridge.page_title_handler = self._page_title
        self.panel.row_activated.connect(self._on_row_activated)
        self.pdf_view.page_changed.connect(self._on_pdf_page_changed)

    @property
    def session_id(self) -> int | None:
        return self._session_id

    def open_session(self, session_id: int, clock: SessionClock | None) -> None:
        self._session_id = session_id
        self._clock = clock
        self._page_id = None
        self._pending_partial = {}
        self.panel.player_bar.clear()  # 재생 UI는 조립 루트가 아카이브일 때만 켠다
        self.panel.set_bookmarks(set(self._store.markers_for(session_id, "bookmark")))
        self.panel.load_segments(self._store.get_segments(session_id))
        pdf_path = self._store.get_session_pdf(session_id)
        if pdf_path and Path(pdf_path).exists():
            self.pdf_view.open(session_id, pdf_path, clock)
        else:
            self.pdf_view.clear()
        # 에디터가 아직 화면에 없으면(홈에서 전환 중) 표시 후로 미룬다 —
        # 숨겨진 웹뷰에 boot를 실행하면 크로뮴 렌더러가 데드락된다
        if self._js_ready and self.editor.settled:
            self._boot_editor()
        else:
            self._pending_open = True

    def import_pdf(self, source_path: str) -> None:
        """PDF를 앱 데이터로 복사해 이 세션에 붙인다."""
        if self._session_id is None:
            return
        from ..paths import data_root

        target_dir = data_root() / "pdf"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{self._session_id}.pdf"
        shutil.copyfile(source_path, target)
        self._store.set_session_pdf(self._session_id, str(target))
        self.pdf_view.open(self._session_id, str(target), self._clock)
        # 붙이자마자 1페이지 전용 노트로 전환
        self._switch_page(self._store.page_for_pdf(self._session_id, 0))

    # --- 페이지 (노트 안에 중첩되는 하위 페이지) ---

    def _rebuild_breadcrumb(self) -> None:
        while self._crumbs_layout.count():
            item = self._crumbs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 현재 페이지에서 루트까지 부모를 거슬러 올라가 경로를 만든다
        chain = []
        page_id = self._page_id
        while page_id is not None:
            row = self._store.get_page(page_id)
            if row is None:
                break
            chain.append((row[0], row[1]))
            page_id = row[2]
        chain.reverse()

        for i, (pid, title) in enumerate(chain):
            if i:
                sep = QLabel("›")
                sep.setProperty("cssClass", "rowMeta")
                self._crumbs_layout.addWidget(sep)
            is_current = pid == self._page_id
            crumb = _PageTab(
                title,
                on_rename=(lambda p=pid: self._rename_page(p)) if is_current else (lambda: None),
            )
            crumb.setChecked(is_current)
            if not is_current:
                crumb.clicked.connect(lambda _, p=pid: self._switch_page(p))
            else:
                crumb.setToolTip("더블클릭으로 이름 변경")
            self._crumbs_layout.addWidget(crumb)
        self._crumbs_layout.addStretch()

    def _switch_page(self, page_id: int) -> None:
        if page_id == self._page_id:
            self._rebuild_breadcrumb()
            return
        self.editor.request_save()  # 현재 페이지 즉시 저장 후 전환
        QTimer.singleShot(200, lambda: self._open_page(page_id))

    def _open_page(self, page_id: int) -> None:
        self._page_id = page_id
        self._rebuild_breadcrumb()
        # 페이지 깊이는 1단계까지 — 하위 페이지 안에서는 페이지 생성 금지
        row = self._store.get_page(page_id)
        is_root = row is None or row[2] is None
        self.editor.boot(
            self._store.load_page_doc(page_id), allow_page=is_root, page_id=page_id
        )
        for block_id, t_ms in self._store.block_times_for_page(
            self._session_id, page_id
        ).items():
            self.editor.set_block_time(block_id, format_ms(t_ms))

    def _create_sub_page(self, title: str) -> dict | None:
        """에디터의 페이지 블록이 만들어질 때 호출된다 (부모 = 현재 페이지)."""
        if self._session_id is None or self._page_id is None:
            return None
        row = self._store.get_page(self._page_id)
        if row is not None and row[2] is not None:
            return None  # 하위 페이지 안에서는 더 못 만든다 (깊이 1 제한)
        page_id = self._store.create_page(
            self._session_id, title or "새 페이지", parent_page_id=self._page_id
        )
        return {"id": page_id, "title": title or "새 페이지"}

    def _page_title(self, page_id: int) -> str | None:
        row = self._store.get_page(page_id)
        return row[1] if row else None

    def _rename_page(self, page_id: int) -> None:
        row = self._store.get_page(page_id)
        title, ok = QInputDialog.getText(
            self, "페이지 이름", "이름:", text=row[1] if row else ""
        )
        title = title.strip()
        if ok and title:
            self._store.rename_page(page_id, title)
            self._rebuild_breadcrumb()

    def _panel_size(self) -> int:
        index = self._main_split.indexOf(self.panel)
        sizes = self._main_split.sizes()
        return sizes[index] if 0 <= index < len(sizes) else 1

    def set_panel_dock(self, side: str, save: bool = True) -> None:
        """받아쓰기 패널을 노트 기준 좌/우/상/하로 옮긴다.

        PDF 세션에서도 동일: 위 = PDF 칸 위, 아래 = 노트 칸 아래.
        """
        if side not in ("left", "right", "top", "bottom"):
            side = "right"
        horizontal = side in ("left", "right")
        self._main_split.setOrientation(
            Qt.Horizontal if horizontal else Qt.Vertical
        )
        panel_first = side in ("left", "top")
        self._main_split.insertWidget(0 if panel_first else 1, self.panel)
        total = 1200 if horizontal else 760
        panel_px = 420 if horizontal else 250
        sizes = [panel_px, total - panel_px] if panel_first else [total - panel_px, panel_px]
        self._main_split.setSizes(sizes)
        self._settings.panel_side = side
        self.panel_collapsed.emit(False)
        if save:
            self.layout_changed.emit()

    def expand_panel(self) -> None:
        """스플리터로 접힌 자막 패널을 다시 편다 (오버레이 복원 등)."""
        if self._panel_size() == 0:
            index = self._main_split.indexOf(self.panel)
            sizes = self._main_split.sizes()
            total = max(sum(sizes), 10)
            sizes = [int(total * 0.35) if i == index else int(total * 0.65)
                     for i in range(len(sizes))]
            self._main_split.setSizes(sizes)
            self.panel_collapsed.emit(False)

    def attach_clock(self, clock: SessionClock) -> None:
        """지난 세션에 이어서 녹음을 시작할 때 — 스탬프가 다시 흐른다."""
        self._clock = clock
        self.pdf_view.attach_clock(clock)

    def detach_live(self) -> None:
        """라이브 세션 정지 후에도 노트 편집은 계속되지만 스탬프는 멈춘다."""
        self._clock = None
        self.pdf_view.attach_clock(None)

    # --- 파이프라인 (라이브 세션만 호출됨) ---

    def on_segment(self, segment: TranscriptSegment) -> None:
        if self._session_id is None:
            return
        # 직전 조각이 길이 제한으로 잘린(partial) 같은 소스면 이어붙인다
        prev = self._pending_partial.get(segment.source)
        if prev is not None and segment.t_start_ms - prev.t_end_ms < 1500:
            merged_text = (prev.text.rstrip() + " " + segment.text.lstrip()).strip()
            self._store.update_segment_text(prev.db_id, merged_text)
            updated = replace(
                prev, text=merged_text, t_end_ms=segment.t_end_ms,
                partial=segment.partial,
            )
            self.panel.update_last_segment(updated)
        else:
            db_id = self._store.add_segment(self._session_id, segment)
            updated = replace(segment, db_id=db_id)
            self.panel.add_segment(updated)
        # partial이면 다음 조각을 기다리고, 아니면 이어붙이기 종료
        if segment.partial:
            self._pending_partial[segment.source] = updated
        else:
            self._pending_partial.pop(segment.source, None)

    # --- 에디터 ↔ 저장소/자막 ---

    def _on_js_ready(self) -> None:
        self._js_ready = True
        self.apply_theme()
        # 크래시 후 자동 재로드도 여기로 온다 — 세션이 열려 있으면 재부팅 대상
        if not (self._pending_open or self._session_id is not None):
            return
        if self.editor.settled:
            self._pending_open = False
            self._boot_current()
        else:
            self._pending_open = True

    def _on_editor_settled(self) -> None:
        """에디터가 화면에 표시되어 안정된 시점 — 미뤄둔 boot를 실행한다."""
        if self._js_ready and self._pending_open:
            self._pending_open = False
            self._boot_current()

    def _boot_current(self) -> None:
        if self._page_id is not None:
            self._open_page(self._page_id)  # 보던 하위 페이지 유지 (크래시 복구)
        else:
            self._boot_editor()

    def apply_theme(self) -> None:
        self.editor.set_theme(self._settings.theme, self._settings.editor_font_px)

    def _boot_editor(self) -> None:
        if self.pdf_view.isVisible():
            # PDF 세션: 현재 PDF 페이지의 전용 노트로
            self._open_page(
                self._store.page_for_pdf(self._session_id, self.pdf_view.current_page)
            )
        else:
            self._open_page(self._store.root_page(self._session_id)[0])

    def _on_pdf_page_changed(self, pdf_page: int) -> None:
        """PDF 페이지를 넘기면 그 페이지 전용 노트로 아래 에디터가 전환된다."""
        if self._session_id is None:
            return
        self._switch_page(self._store.page_for_pdf(self._session_id, pdf_page))

    def _on_block_added(self, block_id: str) -> None:
        if self._clock is None or self._session_id is None:
            return
        t_ms = self._clock.now_ms()
        if self._store.stamp_block(
            self._session_id, block_id, t_ms, page_id=self._page_id
        ):
            self.editor.set_block_time(block_id, format_ms(t_ms))

    def _on_block_stamp_forced(self, block_id: str, t_ms: int) -> None:
        if self._session_id is None:
            return
        self._store.stamp_block(
            self._session_id, block_id, t_ms, force=True, page_id=self._page_id
        )
        self.editor.set_block_time(block_id, format_ms(t_ms))

    def _on_doc_saved(self, page_id: int, doc_json: str) -> None:
        # JS가 boot 시점의 페이지 id를 스탬프해 보낸다 — 세션을 빠르게 오가면
        # 이전 페이지의 저장이 늦게 도착할 수 있는데, 현재 페이지가 아니라
        # '그 내용이 속한' 페이지에 기록해야 한다 (교차 오염 방지)
        if page_id >= 0:
            self._store.save_page_doc(page_id, doc_json)
        elif self._page_id is not None:  # 스탬프 없는 옛 경로 대비
            self._store.save_page_doc(self._page_id, doc_json)

    def _on_gutter_clicked(self, block_id: str) -> None:
        t_ms = self._store.block_time(self._session_id, block_id)
        if t_ms is not None:
            self.panel.scroll_to_time(t_ms)

    def _on_row_activated(self, segment: TranscriptSegment) -> None:
        """자막 클릭: 녹음이 있으면 그 시각부터 리플레이, 없으면 노트로 점프."""
        if self.panel.player_bar.has_audio:
            self.panel.player_bar.play_from(segment.t_start_ms)
            return
        block_times = self._store.block_times_for(self._session_id)
        if block_times:
            nearest = min(
                block_times, key=lambda b: abs(block_times[b] - segment.t_start_ms)
            )
            self.editor.scroll_to_block(nearest)


class StudioWindow(QMainWindow):
    new_session_requested = Signal(str)   # source
    archive_open_requested = Signal(int)  # session_id
    stop_requested = Signal()
    went_home = Signal()
    settings_changed = Signal()           # 저장/재적용은 조립 루트 담당
    source_toggled = Signal(object, bool)  # AudioSource, 켜짐 여부
    resume_requested = Signal()           # 지난 세션에 이어서 녹음

    def __init__(
        self, store: SessionStore, corrections_path, settings: AppSettings
    ) -> None:
        super().__init__()
        self._store = store
        self._corrections_path = corrections_path
        self._settings = settings
        self.setWindowTitle("JotThatDown")
        self.resize(1280, 800)

        self.home = HomePage(store)
        self.session_page = SessionPage(store, settings)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.home)
        self._stack.addWidget(self.session_page)
        self.setCentralWidget(self._stack)

        # 최소화 시 뜨는 실시간 자막 오버레이 (녹음 중일 때만)
        from .overlay import OverlayWindow

        self._overlay = OverlayWindow(settings)
        self._overlay.restore_requested.connect(self._restore_from_overlay)
        self._recording = False
        self._panel_hidden = False  # 자막 패널이 스플리터로 접힌 상태

        self._build_toolbar()

        # 하단 바: 왼쪽 디버그(메모리·오디오 파일 크기) · 오른쪽 테마 스위치
        self._debug = QLabel("")
        self._debug.setProperty("cssClass", "debugInfo")
        self._theme_switch = _ThemeSwitch(self._toggle_theme)
        switch_wrap = QWidget()  # 창 모서리에 붙지 않게 여백
        wrap_layout = QHBoxLayout(switch_wrap)
        wrap_layout.setContentsMargins(6, 4, 14, 4)
        wrap_layout.addWidget(self._theme_switch)
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        bar.addWidget(self._debug)
        bar.addPermanentWidget(switch_wrap)
        self.setStatusBar(bar)

        # 마우스 옆 버튼(XButton1/2)으로 뒤로/앞으로 — 앱 전역에서
        self._nav_fwd: list[tuple] = []
        QApplication.instance().installEventFilter(self)

        self.home.new_session_requested.connect(self.new_session_requested)
        self.home.session_opened.connect(self.archive_open_requested)
        self.session_page.panel.player_bar.resume_requested.connect(self.resume_requested)
        self.session_page.panel.correction_requested.connect(self._on_correction_from_transcript)
        self.session_page.panel.source_toggled.connect(self.source_toggled)
        self.session_page.panel.stop_requested.connect(self.stop_requested)
        self.session_page.panel.bookmark_toggled.connect(self._on_bookmark_toggled)
        self.session_page.panel.dock_requested.connect(self.session_page.set_panel_dock)
        self.session_page.layout_changed.connect(self.settings_changed)
        self.session_page.pdf_view.style_saved.connect(self.settings_changed)
        self.session_page.panel_collapsed.connect(self._on_panel_collapsed)

        self.show_home()

    def _build_toolbar(self) -> None:
        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)

        from .icons import make_ui_icon

        self._home_action = QAction(make_ui_icon("back", 16), " 홈", self)
        self._home_action.triggered.connect(self.show_home)
        self._toolbar.addAction(self._home_action)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("세션 제목")
        self._title_edit.setFixedWidth(340)
        self._title_edit.editingFinished.connect(self._on_title_edited)
        # QToolBar 위젯은 addWidget이 돌려주는 QAction으로만 숨길 수 있다
        self._title_action = self._toolbar.addWidget(self._title_edit)

        self._export_action = QAction("MD 내보내기", self)
        self._export_action.triggered.connect(self._on_export)
        self._toolbar.addAction(self._export_action)

        self._export_txt_action = QAction("받아쓰기 내보내기", self)
        self._export_txt_action.triggered.connect(self._on_export_transcript)
        self._toolbar.addAction(self._export_txt_action)

        settings_action = QAction("설정", self)
        settings_action.triggered.connect(self._open_settings)
        self._toolbar.addAction(settings_action)

    # --- 페이지 전환 ---

    def show_home(self) -> None:
        # 편집 중 뒤로 나가는 경우 — 디바운스를 기다리지 않고 즉시 저장해
        # 마지막 타이핑이 유실되거나 저장이 홈에서 늦게 떠다니지 않게 한다
        if self._stack.currentWidget() is self.session_page:
            self.session_page.editor.request_save()
        self.went_home.emit()
        self.home.refresh()
        self._stack.setCurrentWidget(self.home)
        self._title_action.setVisible(False)
        self._export_action.setVisible(False)
        self._export_txt_action.setVisible(False)
        self._home_action.setVisible(False)
        self.session_page.panel.set_live_controls(False)

    def show_session(
        self,
        session_id: int,
        title: str,
        clock: SessionClock | None,
        active_sources: set | None = None,
    ) -> None:
        self.session_page.open_session(session_id, clock)
        self._stack.setCurrentWidget(self.session_page)
        self._title_edit.setText(title)
        self._title_action.setVisible(True)
        self._export_action.setVisible(True)
        self._export_txt_action.setVisible(True)
        self._home_action.setVisible(True)
        self.session_page.panel.set_live_controls(
            clock is not None, active_sources or set()
        )
        self._recording = clock is not None
        self._update_overlay()
        if clock is None:
            self.show_status("")

    def set_live_stopped(self) -> None:
        self.session_page.detach_live()
        self.session_page.panel.set_live_controls(False)
        self._recording = False
        self._overlay.hide()
        self.show_status("")

    def set_playback(self, paths: list, offer_resume: bool) -> None:
        """아카이브(또는 정지된) 세션의 재생/이어녹음 바를 켠다.

        슬라이더 눈금: 자막 위치(흐린 |)와 이어녹음 지점(주황 |).
        """
        sid = self.session_page.session_id
        segment_ticks = (
            [seg.t_start_ms for seg in self._store.get_segments(sid)] if sid else []
        )
        resume_ticks = self._store.markers_for(sid) if sid else []
        bookmark_ticks = self._store.markers_for(sid, "bookmark") if sid else []
        self.session_page.panel.player_bar.configure(
            paths, offer_resume, segment_ticks, resume_ticks, bookmark_ticks
        )

    def attach_live(self, clock: SessionClock, active_sources: set) -> None:
        """지난 세션에 이어서 녹음 시작 — 페이지 리로드 없이 라이브 모드로 전환."""
        self.session_page.attach_clock(clock)
        self.session_page.panel.player_bar.clear()
        self.session_page.panel.set_live_controls(True, active_sources)
        self._recording = True
        self._update_overlay()

    # --- 마우스 옆 버튼 내비게이션 ---

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.XButton1:
                self._nav_back()
                return True
            if event.button() == Qt.XButton2:
                self._nav_go_forward()
                return True
        return super().eventFilter(obj, event)

    def _nav_back(self) -> None:
        if self._stack.currentWidget() is self.session_page:
            sid = self.session_page.session_id
            if sid is not None:
                self._nav_fwd.append(("session", sid))
            self.show_home()
        else:
            state = self.home.nav_state()
            if self.home.go_up():
                self._nav_fwd.append(state)

    def _nav_go_forward(self) -> None:
        if not self._nav_fwd:
            return
        kind, value = self._nav_fwd.pop()
        if kind == "session":
            self.archive_open_requested.emit(value)
        elif self._stack.currentWidget() is self.home:
            self.home.open_view((kind, value))
        else:
            self._nav_fwd.append((kind, value))  # 홈이 아니면 보류

    # --- 최소화 오버레이 ---

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.WindowStateChange:
            self._update_overlay()
        super().changeEvent(event)

    def _on_panel_collapsed(self, hidden: bool) -> None:
        self._panel_hidden = hidden
        self._update_overlay()

    def _update_overlay(self) -> None:
        """녹음 중 자막이 안 보이는 상황(최소화·패널 접힘)에만 오버레이."""
        self._overlay.setVisible(
            self._recording and (self.isMinimized() or self._panel_hidden)
        )

    def _restore_from_overlay(self) -> None:
        self._overlay.hide()
        self.session_page.expand_panel()  # 패널이 접혀 있었으면 다시 편다
        self.setWindowState(
            self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
        )
        self.show()
        self.raise_()
        self.activateWindow()

    # --- 파이프라인 위임 ---

    def on_segment(self, segment: TranscriptSegment) -> None:
        self.session_page.on_segment(segment)
        if self._overlay.isVisible():
            self._overlay.show_segment(segment)

    def set_debug_info(self, audio_bytes: int = 0) -> None:
        """우측 하단 디버그 표시 — 프로세스 메모리·VRAM·오디오 파일 크기."""
        parts = []
        rss = _process_rss_mb()
        if rss:
            parts.append(f"RAM {rss:,}MB")
        # GPU 조회(nvidia-smi)는 비싸므로 ~3초마다 워커 스레드에서 갱신하고 캐시
        self._gpu_tick = getattr(self, "_gpu_tick", 0) + 1
        if self._gpu_tick % 10 == 1 and not getattr(self, "_gpu_busy", False):
            self._gpu_busy = True

            def refresh() -> None:
                self._gpu_cache = _gpu_mem_mb()
                self._gpu_busy = False

            threading.Thread(target=refresh, name="gpu-query", daemon=True).start()
        used, total = getattr(self, "_gpu_cache", (0, 0))
        if total:
            parts.append(f"VRAM {used:,}/{total:,}MB")
        if audio_bytes:
            parts.append(f"녹음 {audio_bytes / (1024 * 1024):.1f}MB")
        text = "   ·   ".join(parts)
        if self._debug.text() != text:  # 바뀔 때만 다시 그림
            self._debug.setText(text)

    def show_status(self, text: str) -> None:
        """대기 상태(모델 로딩·다운로드)는 자막 타임라인 배너로만 보여준다."""
        if "로딩" in text or "내려받는" in text:
            self.session_page.panel.show_pending(text)
        else:
            self.session_page.panel.clear_pending()

    # --- 내부 ---

    def _open_settings(self) -> None:
        SettingsDialog(
            self._settings,
            on_apply=self.settings_changed.emit,
            corrections_path=self._corrections_path,
            parent=self,
        ).exec()

    def _toggle_theme(self) -> None:
        self._settings.theme = "dark" if self._settings.theme == "light" else "light"
        self.settings_changed.emit()

    def _on_correction_from_transcript(self, selected_text: str) -> None:
        CorrectionsDialog(self._corrections_path, self, prefill=selected_text).exec()

    def _on_bookmark_toggled(self, segment: TranscriptSegment, on: bool) -> None:
        sid = self.session_page.session_id
        if sid is None:
            return
        if on:
            self._store.add_marker(sid, segment.t_start_ms, "bookmark")
        else:
            self._store.remove_marker(sid, segment.t_start_ms, "bookmark")
        self.session_page.panel.player_bar.set_bookmark_ticks(
            self._store.markers_for(sid, "bookmark")
        )

    def apply_window_theme(self) -> None:
        """타이틀바 색·테마 스위치를 현재 테마에 맞춘다."""
        from .native import style_titlebar

        style_titlebar(self, self._settings.theme)
        self._theme_switch.set_dark(self._settings.theme == "dark")

    def _on_title_edited(self) -> None:
        sid = self.session_page.session_id
        title = self._title_edit.text().strip()
        if sid is not None and title:
            self._store.rename_session(sid, title)

    def _on_export(self) -> None:
        sid = self.session_page.session_id
        if sid is None:
            return
        title = self._title_edit.text().strip() or "세션"
        path, _ = QFileDialog.getSaveFileName(
            self, "마크다운으로 내보내기", f"{title}.md", "Markdown (*.md)"
        )
        if not path:
            return
        self.session_page.editor.request_save()  # 마지막 입력까지 반영
        md = export_markdown(
            title,
            self._store.pages_tree(sid),
            self._store.block_times_for(sid),
            self._store.get_segments(sid),
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        QMessageBox.information(self, "내보내기 완료", f"저장됨:\n{path}")

    def _on_export_transcript(self) -> None:
        sid = self.session_page.session_id
        if sid is None:
            return
        segments = self._store.get_segments(sid)
        if not segments:
            QMessageBox.information(self, "받아쓰기 내보내기", "받아쓰기가 없습니다.")
            return
        title = self._title_edit.text().strip() or "세션"
        path, _ = QFileDialog.getSaveFileName(
            self, "받아쓰기 내보내기", f"{title} 받아쓰기.txt", "텍스트 (*.txt)"
        )
        if not path:
            return
        lines = [
            f"[{format_ms(seg.t_start_ms)}] {seg.text}" for seg in segments
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        QMessageBox.information(self, "내보내기 완료", f"저장됨:\n{path}")
