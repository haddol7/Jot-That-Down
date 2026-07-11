"""스타일 팝오버 — 도구 버튼 아래에 뜨는지, 값 선택 시 콜백 되는지 확인."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.settings import AppSettings
from app.store.db import SessionStore
from app.ui.pdf_view import PdfAnnotationView
from app.ui.theme import build_qss
import tempfile


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss("dark"))
    store = SessionStore(Path(tempfile.mkdtemp()) / "t.db")
    settings = AppSettings()
    view = PdfAnnotationView(store, settings)
    view.resize(700, 200)
    view.show()

    button = view._tool_buttons["ellipse"]
    view._edit_style("ellipse")
    popover = view._style_popover
    app.processEvents()

    btn_bottom = button.mapToGlobal(button.rect().bottomLeft())
    pop_pos = popover.mapToGlobal(popover.rect().topLeft())
    print(f"button bottom-left: {btn_bottom.x()},{btn_bottom.y()}")
    print(f"popover top-left  : {pop_pos.x()},{pop_pos.y()}")
    assert popover.isVisible(), "팝오버 안 보임"
    assert abs(pop_pos.x() - btn_bottom.x()) < 4, "가로 위치 안 맞음"
    assert 0 < pop_pos.y() - btn_bottom.y() < 12, "버튼 바로 아래 아님"
    print(f"popover size: {popover.width()}x{popover.height()}")
    assert popover.width() > popover.height() * 2, "가로로 길쭉해야 함"

    # 빨강·굵게 선택 → 설정 반영 + 팝오버 닫힘
    view._edit_style("ellipse")
    view._style_popover._pick_width(4.0)
    assert settings.pdf_tool_styles["ellipse"]["width"] == 4.0
    view._edit_style("ellipse")
    view._style_popover._pick_color("#e25757")
    assert settings.pdf_tool_styles["ellipse"]["color"] == "#e25757"
    assert not view._style_popover.isVisible(), "선택 후 닫혀야 함"
    print("RESULT: OK — 버튼 아래 가로 팝오버, 선택 즉시 반영·닫힘")

    if "--show" in sys.argv:
        view._edit_style("ellipse")
        out = Path(sys.argv[sys.argv.index("--show") + 1])
        QTimer.singleShot(400, lambda: (view.grab().save(str(out)), app.quit()))
        app.exec()


if __name__ == "__main__":
    main()
