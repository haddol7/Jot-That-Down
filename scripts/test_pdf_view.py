"""PDF 필기 뷰 스모크 테스트 — 생성한 PDF에 주석 4종을 긋고 렌더 확인."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from app.store.db import SessionStore
from app.ui.pdf_view import PdfAnnotationView
from app.ui.theme import build_qss


def make_test_pdf(path: Path) -> None:
    """선택 가능한 텍스트 레이어가 있는 최소 PDF를 손으로 만든다.

    (QPdfWriter 산출물은 QtPdf가 텍스트를 추출하지 못해 테스트 불가)
    """
    def page_stream(lines: list[str]) -> bytes:
        ops = ["BT /F1 24 Tf"]
        y = 770
        for line in lines:
            ops.append(f"1 0 0 1 72 {y} Tm ({line}) Tj")
            y -= 40
        ops.append("ET")
        return " ".join(ops).encode()

    streams = [
        page_stream(["Virtual Memory and the TLB cache", "Paging works per frame"]),
        page_stream(["Page replacement algorithms"]),
    ]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 5 0 R"
        b" /Resources << /Font << /F1 7 0 R >> >> >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 6 0 R"
        b" /Resources << /Font << /F1 7 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(streams[0]) + streams[0] + b"\nendstream",
        b"<< /Length %d >>\nstream\n" % len(streams[1]) + streams[1] + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_pos)
    )
    path.write_bytes(bytes(out))


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss("dark"))

    tmp = Path(tempfile.mkdtemp())
    pdf_path = tmp / "lecture.pdf"
    make_test_pdf(pdf_path)

    store = SessionStore(tmp / "t.db")
    sid = store.create_session("PDF 테스트")
    store.set_session_pdf(sid, str(pdf_path))
    assert store.get_session_pdf(sid) == str(pdf_path)

    view = PdfAnnotationView(store)
    view.resize(700, 900)
    view.open(sid, str(pdf_path), clock=None)

    # 형광펜 글자 스냅: 상단 텍스트 줄을 가로지르는 드래그 → 글자 영역으로 스냅
    drag = (0.0, 0.01, 0.9, 0.10)
    snapped = view._canvas.highlight_rects(drag)
    assert snapped, "텍스트 스냅 결과 없음"
    drag_height = drag[3] - drag[1]
    assert all((r[3] - r[1]) < drag_height for r in snapped), snapped  # 글줄만큼만
    # 글자 없는 빈 영역 → 아무것도 칠하지 않음
    assert view._canvas.highlight_rects((0.1, 0.85, 0.6, 0.95)) == []

    # 주석 4종을 저장 경로로 직접 추가 (마우스 드래그와 같은 코드 경로)
    view._add_annotation(0, "underline", (0.2, 0.30, 0.7, 0.31))
    view._add_annotation(0, "highlight", snapped[0])
    view._add_annotation(0, "rect", (0.15, 0.25, 0.8, 0.6))
    view._add_annotation(1, "ellipse", (0.3, 0.2, 0.6, 0.4))
    assert len(store.pdf_annotations_for(sid)) == 4

    # 지우개: 사각형 내부 점 → 최근 것부터 하나 삭제
    view._erase_at(0, 0.5, 0.53)  # 형광펜/사각형 겹침 — 마지막(rect) 삭제
    assert len(store.pdf_annotations_for(sid)) == 3

    # 페이지 이동 + 페이지별 노트 매핑
    changes: list[int] = []
    view.page_changed.connect(changes.append)
    view._go(1)
    assert view.current_page == 1 and changes == [1]
    view._go(1)  # 마지막 페이지에서 더 못 감
    assert view.current_page == 1 and changes == [1]
    view._go(-1)
    assert view.current_page == 0 and changes == [1, 0]

    note_p1 = store.page_for_pdf(sid, 0)
    assert store.page_for_pdf(sid, 0) == note_p1          # 같은 페이지 재사용
    note_p2 = store.page_for_pdf(sid, 1)
    assert note_p1 != note_p2
    assert store.get_page(note_p1)[1] == "p.1"
    assert store.root_page(sid)[1] == "노트"              # 일반 루트는 그대로
    titles = [t for _, t, _ in store.pages_tree(sid)]
    assert titles == ["노트", "p.1", "p.2"], titles       # 내보내기 순서

    view.show()
    app.processEvents()
    pixmap = view.grab()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else tmp / "pdf_view.png"
    pixmap.save(str(out))
    print(f"pdf view: OK (주석 3개 렌더, 캡처 {out})")


if __name__ == "__main__":
    main()
