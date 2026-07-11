"""UI 스타일 프리뷰 — 최신 세션을 아카이브 모드로 열어 렌더링만 확인.

엔진·녹음 없이 창만 띄운다. 사용: python scripts/preview_ui.py [light|dark]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cuda_dlls import register_cuda_dlls

register_cuda_dlls()

from PySide6.QtWidgets import QApplication

from app import bootstrap
from app.settings import AppSettings
from app.store.db import SessionStore
from app.ui.studio_window import StudioWindow
from app.ui.theme import build_qss


def main() -> None:
    theme = sys.argv[1] if len(sys.argv) > 1 else "light"
    qt_app = QApplication(sys.argv)
    from app.ui.fonts import load_fonts
    from PySide6.QtGui import QFont

    qt_app.setFont(QFont(load_fonts(), 10))
    settings = AppSettings(theme=theme)
    qt_app.setStyleSheet(build_qss(theme))

    store = SessionStore(bootstrap.PROJECT_ROOT / "data" / "jotthatdown.db")
    window = StudioWindow(store, bootstrap.PROJECT_ROOT / "corrections.txt", settings)
    window.setWindowTitle(f"JotThatDown-preview-{theme}")

    sessions = store.list_sessions()
    if "--home" in sys.argv:
        sessions = []  # 홈 화면 확인용
    if sessions:
        from app.audio.recorder import audio_path
        from app.core.models import AudioSource

        sid, title = sessions[0][0], sessions[0][1]
        window.show_session(sid, title, clock=None)
        paths = [
            audio_path(bootstrap.PROJECT_ROOT / "data", sid, s) for s in AudioSource
        ]
        window.set_playback(paths, offer_resume=True)
    if "--probe" in sys.argv:
        from PySide6.QtCore import QTimer

        def probe() -> None:
            window.session_page.editor.page().runJavaScript(
                "(() => {"
                " const child = document.querySelector('.cdx-list__item-children .cdx-list__item');"
                " if (!child) return 'no nested list in doc';"
                " const parts = [];"
                " let el = child;"
                " const parent = child.closest('.cdx-list__item-children').closest('.cdx-list__item');"
                " while (el && el !== parent) {"
                "   const cs = getComputedStyle(el);"
                "   parts.push(`${el.className.split(' ')[0]}: ml=${cs.marginLeft} pl=${cs.paddingLeft} left=${Math.round(el.getBoundingClientRect().left)}`);"
                "   el = el.parentElement;"
                " }"
                " parts.push(`PARENT left=${Math.round(parent.getBoundingClientRect().left)}`);"
                " return parts.join(' | '); })()",
                0,
                lambda result: print(f"PROBE: {result}", flush=True),
            )

        QTimer.singleShot(4000, probe)

    window.show()
    window.apply_window_theme()

    if "--dialog" in sys.argv:  # 새 폴더 다이얼로그 스타일 확인용
        from app.ui.home_page import _FolderDialog

        dialog = _FolderDialog(window)
        dialog.show()

    qt_app.exec()


if __name__ == "__main__":
    main()
