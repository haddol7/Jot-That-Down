"""Editor.js를 담는 QWebEngineView와 QWebChannel 브리지.

JS 쪽 진입점은 web/editor.js 참고. 이 모듈 밖에서는 웹 기술의 존재를
모르도록, 노출 API는 전부 파이썬 시그널/메서드다.
"""
import base64
import json
import re
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal, Slot
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
    doc_saved = Signal(str)                # 문서 전체 JSON
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

    @Slot(str)
    def docSaved(self, doc_json: str) -> None:
        self.doc_saved.emit(doc_json)

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
    def __init__(self) -> None:
        super().__init__()
        self.bridge = EditorBridge(self)

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

    # --- 파이썬 → JS ---

    def boot(self, doc_json: str | None, allow_page: bool = True) -> None:
        doc = doc_json if doc_json else "null"
        flag = "true" if allow_page else "false"
        self.page().runJavaScript(f"boot({doc}, {flag});")

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
