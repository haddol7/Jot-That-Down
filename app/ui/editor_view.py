"""Editor.js를 담는 QWebEngineView와 QWebChannel 브리지.

JS 쪽 진입점은 web/editor.js 참고. 이 모듈 밖에서는 웹 기술의 존재를
모르도록, 노출 API는 전부 파이썬 시그널/메서드다.
"""
import base64
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QFile, QIODevice, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..paths import data_root, resource_root

_WEB_DIR = resource_root() / "web"


def _attach_dir() -> Path:
    return data_root() / "attachments"


class EditorBridge(QObject):
    """JS가 호출하는 슬롯들 → 파이썬 시그널로 변환."""

    js_ready = Signal()
    block_added = Signal(str)              # blockId (에디터에서 새 블록 생성)
    block_stamp_forced = Signal(str, int)  # blockId, t_ms (인용 등 원본 시각 지정)
    doc_saved = Signal(int, str)           # 페이지 id, 문서 전체 JSON
    gutter_clicked = Signal(str)           # blockId
    page_open_requested = Signal(int)      # 페이지 블록 클릭 → 그 페이지로 진입

    # SessionPage가 주입 — 반환값이 필요한 호출들 (QWebChannel 동기 슬롯)
    create_page_handler = None  # (title) -> dict {id, title} | None
    page_title_handler = None   # (page_id) -> str | None

    @Slot()
    def jsReady(self) -> None:
        self.js_ready.emit()

    @Slot(str)
    def blockAdded(self, block_id: str) -> None:
        self.block_added.emit(block_id)

    @Slot(str, int)
    def stampBlock(self, block_id: str, t_ms: int) -> None:
        self.block_stamp_forced.emit(block_id, t_ms)

    @Slot(int, str)
    def docSaved(self, page_id: int, doc_json: str) -> None:
        self.doc_saved.emit(page_id, doc_json)

    @Slot(str)
    def gutterClicked(self, block_id: str) -> None:
        self.gutter_clicked.emit(block_id)

    @Slot(int)
    def openPage(self, page_id: int) -> None:
        self.page_open_requested.emit(page_id)

    @Slot(str, result=str)
    def createSubPage(self, title: str) -> str:
        if self.create_page_handler is None:
            return ""
        info = self.create_page_handler(title)
        return json.dumps(info, ensure_ascii=False) if info else ""

    @Slot(int, result=str)
    def pageTitle(self, page_id: int) -> str:
        if self.page_title_handler is None:
            return ""
        return self.page_title_handler(page_id) or ""

    @Slot(str, str, result=str)
    def saveImage(self, data_url: str, ext: str) -> str:
        """붙여넣은 이미지를 data/attachments에 저장하고 URL을 돌려준다."""
        try:
            _, _, b64 = data_url.partition(",")
            raw = base64.b64decode(b64)
            safe_ext = ext.lower() if re.fullmatch(r"[a-z0-9]{1,5}", ext.lower()) else "png"
            attach = _attach_dir()
            attach.mkdir(parents=True, exist_ok=True)
            path = attach / f"{uuid4().hex}.{safe_ext}"
            path.write_bytes(raw)
            return path.as_uri()
        except Exception:
            return ""


def _qwebchannel_js() -> str:
    """Qt 리소스에 내장된 qwebchannel.js 소스를 꺼낸다."""
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if not f.open(QIODevice.ReadOnly):
        raise RuntimeError("qwebchannel.js 리소스를 열 수 없습니다.")
    try:
        return bytes(f.readAll()).decode("utf-8")
    finally:
        f.close()


class EditorView(QWebEngineView):
    # 홈(스택에서 숨김) 상태에서 boot를 실행한 직후 화면에 표시되면
    # 크로뮴 렌더러가 네이티브 데드락으로 영구 정지한다 (CPU 100%,
    # "Compositor returned null texture"). 표시가 자리잡은 뒤에만 boot해야
    # 하므로, 표시 후 잠깐 지난 시점을 shown_settled 시그널로 알린다.
    shown_settled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.bridge = EditorBridge(self)
        self.settled = False  # 화면에 표시된 뒤 안정화됐는지 (boot 안전 시점)

        # qwebchannel.js를 문서 생성 시점에 주입 (file:// 페이지에서 qrc 접근 불가 대비)
        script = QWebEngineScript()
        script.setSourceCode(_qwebchannel_js())
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        self.page().scripts().insert(script)

        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self._channel)

        self.load(QUrl.fromLocalFile(str(_WEB_DIR / "editor.html")))

        # 렌더 프로세스가 죽으면 웹뷰가 앱 재시작 전까지 영구 공백이 된다 —
        # 감지 즉시 다시 로드해 자동 복구한다. 로드가 끝나면 editor.html이
        # jsReady를 다시 쏘고, SessionPage가 보던 페이지를 재부팅한다.
        self.page().renderProcessTerminated.connect(self._on_render_crash)

        # 창을 빠르게 늘렸다 줄이면 크로뮴이 마지막 크기를 놓쳐 본문이
        # 이전 크기 기준으로 잘려 보인다 (QtWebEngine 리사이즈 유실 버그).
        # 리사이즈가 잦아든 뒤 줌을 살짝 흔들어 뷰포트를 재동기화한다.
        self._resize_sync = QTimer(self)
        self._resize_sync.setSingleShot(True)
        self._resize_sync.setInterval(200)
        self._resize_sync.timeout.connect(self._sync_viewport)

        # 표시 안정화 타이머 — 반드시 멤버 하나로: showEvent마다 일회성
        # 타이머를 만들면 빠른 홈↔노트 왕복 때 이전 표시의 타이머가
        # 새 표시 직후 발화해 안정화 지연이 사실상 0이 된다 (데드락 재발)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(300)
        self._settle_timer.timeout.connect(self._mark_settled)

        # 부팅 워치독 — 크로뮴이 특정 타이밍(숨김 boot, GPU 경합 등)에서
        # 데드락/무응답에 빠지는 일이 있어, boot 뒤 응답이 없으면
        # ① 페이지 재로드 → ② 렌더러 프로세스 강제 재시작으로 자가 복구한다.
        self._boot_watchdog = QTimer(self)
        self._boot_watchdog.setSingleShot(True)
        self._boot_watchdog.setInterval(4000)
        self._boot_watchdog.timeout.connect(self._boot_stuck)
        self._boot_seq = 0
        self._stuck_stage = 0

    def _on_render_crash(self, status, exit_code) -> None:
        from .. import diag

        diag.log("editor", f"렌더 프로세스 종료 {status} code={exit_code} — 자동 재로드")
        QTimer.singleShot(0, self.reload)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_sync.start()

    def showEvent(self, event) -> None:
        # 홈 ↔ 노트 전환으로 다시 보일 때도 합성 서페이스를 재동기화
        super().showEvent(event)
        self._resize_sync.start()
        self._settle_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._settle_timer.stop()
        self.settled = False

    def _mark_settled(self) -> None:
        if not self.isVisible() or self.settled:
            return
        self.settled = True
        self.shown_settled.emit()

    def _sync_viewport(self) -> None:
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            return
        zoom = self.zoomFactor()
        kicked = zoom * 1.0001
        self.setZoomFactor(kicked)

        def restore() -> None:
            # 그 사이 사용자가 Ctrl+휠로 줌을 바꿨다면 건드리지 않는다
            if abs(self.zoomFactor() - kicked) < 1e-9:
                self.setZoomFactor(zoom)

        # 같은 이벤트 루프에서 되돌리면 크로뮴이 변경을 합쳐 무시한다
        QTimer.singleShot(30, restore)

    # --- 파이썬 → JS ---

    def boot(
        self, doc_json: str | None, allow_page: bool = True,
        page_id: int | None = None,
    ) -> None:
        doc = doc_json if doc_json else "null"
        flag = "true" if allow_page else "false"
        pid = "null" if page_id is None else str(int(page_id))
        self.page().runJavaScript(f"boot({doc}, {flag}, {pid});")
        # 부팅 액(ack) — 렌더러가 살아 있으면 boot 처리 직후 돌아온다
        self._boot_seq += 1
        seq = self._boot_seq
        self._boot_watchdog.start()
        self.page().runJavaScript("1", 0, lambda _r, s=seq: self._boot_ack(s))

    def _boot_ack(self, seq: int) -> None:
        if seq == self._boot_seq:
            self._boot_watchdog.stop()
            self._stuck_stage = 0

    def _boot_stuck(self) -> None:
        from .. import diag

        self._stuck_stage += 1
        if self._stuck_stage == 1:
            diag.log("editor", "부팅 무응답 — 페이지 재로드로 복구 시도")
            self.reload()  # 성공하면 jsReady 재발화 → SessionPage가 재부팅
            self._boot_watchdog.start()  # 재로드마저 무시되면 다음 단계
        else:
            diag.log("editor", "재로드도 무응답 — 렌더러 프로세스 강제 재시작")
            self._stuck_stage = 0
            self._kill_renderer()  # renderProcessTerminated → 자동 재로드 경로

    def _kill_renderer(self) -> None:
        """이 프로세스의 자식 QtWebEngineProcess를 전부 강제 종료한다.

        렌더러 메인 스레드가 네이티브 데드락이면 reload()도 전달되지 않아,
        프로세스를 죽여 renderProcessTerminated 복구 경로를 태우는 수밖에 없다.
        (GPU 프로세스가 같이 죽어도 크로뮴이 알아서 다시 띄운다)
        """
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32

        class _Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snap == -1:
            return
        me = os.getpid()
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        killed = 0
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            if (
                entry.th32ParentProcessID == me
                and entry.szExeFile.lower() == b"qtwebengineprocess.exe"
            ):
                handle = k32.OpenProcess(1, False, entry.th32ProcessID)  # TERMINATE
                if handle:
                    k32.TerminateProcess(handle, 1)
                    k32.CloseHandle(handle)
                    killed += 1
            ok = k32.Process32Next(snap, ctypes.byref(entry))
        k32.CloseHandle(snap)
        from .. import diag

        diag.log("editor", f"QtWebEngineProcess {killed}개 강제 종료")

    def set_block_time(self, block_id: str, label: str) -> None:
        self.page().runJavaScript(
            f"setBlockTime({json.dumps(block_id)}, {json.dumps(label)});"
        )

    def scroll_to_block(self, block_id: str) -> None:
        self.page().runJavaScript(f"scrollToBlock({json.dumps(block_id)});")

    def insert_quote(self, text: str, caption: str, t_ms: int) -> None:
        self.page().runJavaScript(
            f"insertQuote({json.dumps(text)}, {json.dumps(caption)}, {int(t_ms)});"
        )

    def request_save(self) -> None:
        """디바운스를 건너뛰고 즉시 저장 (페이지 전환 직전)."""
        self.page().runJavaScript("saveNow();")

    def set_theme(self, theme: str, font_px: int) -> None:
        # 페이지 로드/전환 시 흰 배경이 번쩍이지 않도록 네이티브 배경도 맞춘다
        from PySide6.QtGui import QColor

        self.page().setBackgroundColor(
            QColor("#191919" if theme == "dark" else "#ffffff")
        )
        self.page().runJavaScript(
            f"setTheme({json.dumps(theme)}, {int(font_px)});"
        )
