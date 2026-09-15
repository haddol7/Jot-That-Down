"""DB 안에 박힌 절대경로 고치기.

노트의 첨부 이미지는 file:/// URI로, 세션의 PDF는 절대경로로 저장돼 있다.
다른 기기가 올린 데이터를 받아오면 그 기기의 경로가 들어 있으므로, 이 기기의
데이터 폴더를 가리키도록 재작성해야 이미지와 PDF가 보인다.
"""
import sqlite3
from pathlib import Path


def rewrite_paths(db_path: Path, old_root: Path, new_root: Path) -> None:
    """db_path 안의 old_root 참조를 new_root로 바꾼다 (멱등)."""
    old_root, new_root = Path(old_root), Path(new_root)
    if old_root == new_root:
        return
    conn = sqlite3.connect(str(db_path))
    try:
        old_att = (old_root / "attachments").as_uri()
        new_att = (new_root / "attachments").as_uri()
        for table in ("notes", "pages"):
            try:
                conn.execute(
                    f"UPDATE {table} SET doc_json = replace(doc_json, ?, ?)"
                    " WHERE doc_json IS NOT NULL",
                    (old_att, new_att),
                )
            except sqlite3.OperationalError:
                continue  # 구버전 DB에는 없는 테이블
        conn.execute(
            "UPDATE sessions SET pdf_path = replace(pdf_path, ?, ?)"
            " WHERE pdf_path IS NOT NULL",
            (str(old_root / "pdf"), str(new_root / "pdf")),
        )
        conn.commit()
    finally:
        conn.close()
