"""데이터 폴더 이사 — 클라우드 동기화 폴더로 옮길 때 쓴다.

파일 복사만으로는 부족하다: 노트의 첨부 이미지 URL과 세션의 PDF 경로가
절대경로로 저장돼 있어서, 새 위치로 재작성해야 옮긴 뒤에도 보인다.
원본 폴더는 지우지 않는다 (문제 시 되돌릴 수 있게).
"""
import shutil
import sqlite3
from pathlib import Path


def migrate_data_dir(old_dir: Path, new_dir: Path) -> None:
    """old_dir의 데이터를 new_dir로 복사하고 내부 절대경로를 재작성한다."""
    old_dir = Path(old_dir)
    new_dir = Path(new_dir)
    new_dir.mkdir(parents=True, exist_ok=True)

    for sub in ("audio", "attachments", "pdf"):
        src = old_dir / sub
        if src.is_dir():
            shutil.copytree(src, new_dir / sub, dirs_exist_ok=True)

    src_db = old_dir / "jotthatdown.db"
    if not src_db.exists():
        return
    # 열려 있는 DB(WAL)도 안전하게 복제되도록 backup API 사용
    src = sqlite3.connect(str(src_db))
    dst = sqlite3.connect(str(new_dir / "jotthatdown.db"))
    try:
        src.backup(dst)
        old_att_uri = (old_dir / "attachments").as_uri()
        new_att_uri = (new_dir / "attachments").as_uri()
        for table in ("notes", "pages"):
            dst.execute(
                f"UPDATE {table} SET doc_json = replace(doc_json, ?, ?)"
                " WHERE doc_json IS NOT NULL",
                (old_att_uri, new_att_uri),
            )
        dst.execute(
            "UPDATE sessions SET pdf_path = replace(pdf_path, ?, ?)"
            " WHERE pdf_path IS NOT NULL",
            (str(old_dir / "pdf"), str(new_dir / "pdf")),
        )
        dst.commit()
    finally:
        dst.close()
        src.close()
