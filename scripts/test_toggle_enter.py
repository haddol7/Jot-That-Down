"""토글 제목에서 Enter → 내용으로 커서 이동 검증 (합성 키 이벤트)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cuda_dlls import register_cuda_dlls

register_cuda_dlls()

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.ui.editor_view import EditorView

DOC = json.dumps({
    "blocks": [
        {"id": "t1", "type": "toggle", "data": {"text": "토글 제목", "status": "open"}},
    ]
})

DISPATCH = """
(function() {
  const input = document.querySelector('.toggle-block__input');
  if (!input) return 'NO_INPUT';
  input.focus();
  const sel = window.getSelection();
  sel.selectAllChildren(input);
  sel.collapseToEnd();
  const ev = new KeyboardEvent('keydown',
    {code: 'Enter', key: 'Enter', bubbles: true, cancelable: true});
  input.dispatchEvent(ev);
  return 'DISPATCHED';
})()
"""

INSPECT = """
(function() {
  const items = document.querySelectorAll('.toggle-block__item');
  const active = document.activeElement;
  return JSON.stringify({
    items: items.length,
    blocks: editor.blocks.getBlocksCount(),
    activeInItem: !!(active && active.closest && active.closest('.toggle-block__item')),
    activeClass: active ? String(active.className) : null,
  });
})()
"""


def main() -> None:
    app = QApplication(sys.argv)
    view = EditorView()
    view.resize(800, 600)

    results = {}

    def on_ready() -> None:
        view.boot(DOC)
        QTimer.singleShot(900, baseline)

    def baseline() -> None:
        view.page().runJavaScript(INSPECT, 0, lambda r: step_dispatch(r))

    def step_dispatch(before) -> None:
        results["before"] = before
        view.page().runJavaScript(DISPATCH, 0, lambda r: results.update(dispatch=r))
        QTimer.singleShot(600, check)

    def check() -> None:
        view.page().runJavaScript(INSPECT, 0, finish)

    def finish(after) -> None:
        print("before :", results.get("before"))
        print("dispatch:", results.get("dispatch"))
        print("after  :", after)
        try:
            b = json.loads(results["before"])
            a = json.loads(after)
            ok = a["items"] > b["items"] or (a["activeInItem"] and a["items"] > 0)
            print("RESULT:", "OK — 커서가 토글 안으로" if ok else "FAIL — 자식 생성/이동 안 됨")
        except Exception as exc:
            print("RESULT: PARSE_ERROR", exc)
        app.quit()

    view.bridge.js_ready.connect(on_ready)
    view.show()
    app.exec()


if __name__ == "__main__":
    main()
