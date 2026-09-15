"""일회성 병합 — Drive 폴더의 데이터를 로컬 data/로 합친다.

배경: 예전 구조는 Drive 폴더를 데이터 원본으로 직접 썼다. 그래서 Drive를 끄면
로컬의 옛 데이터가 보였다. 로컬을 원본으로 되돌리기 전에, 두 갈래로 갈라진
DB를 하나로 합쳐야 한다.

두 DB는 공통 조상에서 갈라져 id 공간을 공유하므로(세션 9~17 vs 22~25) id를
재매핑하지 않고 그대로 옮길 수 있다. 겹치는 id가 발견되면 중단한다.

사용:  python scripts/merge_drive_into_local.py [--apply]
       (--apply 없으면 무엇을 할지만 보여준다)
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paths import app_root  # noqa: E402

# 세션에 딸린 행을 가진 테이블 — session_id로 따라온다
_SESSION_TABLES = (
    "segments",
    "notes",
    "block_times",
    "pages",
    "session_markers",
    "pdf_annotations",
)


def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _checkpoint(db: Path) -> None:
    """WAL에 남은 커밋을 본 파일로 합친다 — 안 하면 최근 변경을 놓친다."""
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _ids(conn: sqlite3.Connection, table: str, schema: str) -> set[int]:
    return {
        r[0] for r in conn.execute(f"SELECT id FROM {schema}.{table}")
    }


def _rewrite_doc(doc_json: str | None, src_att: str, dst_att: str) -> str | None:
    """첨부 이미지의 file:/// URI를 새 위치로. (URI는 doc_json 안에 문자열로 박혀 있다)"""
    if not doc_json:
        return doc_json
    return doc_json.replace(src_att, dst_att)


def merge(src_dir: Path, dst_dir: Path, apply: bool) -> int:
    src_db, dst_db = src_dir / "jotthatdown.db", dst_dir / "jotthatdown.db"
    if not src_db.exists():
        print(f"[!] Drive DB가 없습니다: {src_db}")
        return 1
    if not dst_db.exists():
        print(f"[!] 로컬 DB가 없습니다: {dst_db}")
        return 1

    _checkpoint(src_db)
    _checkpoint(dst_db)

    conn = sqlite3.connect(str(dst_db))
    conn.execute("ATTACH DATABASE ? AS src", (str(src_db),))

    # 1) id 충돌 검사 — 겹치면 재매핑이 필요하므로 사람이 봐야 한다
    conflicts = {}
    for table in ("sessions", "folders", "pages", "segments", "pdf_annotations"):
        try:
            overlap = _ids(conn, table, "main") & _ids(conn, table, "src")
        except sqlite3.OperationalError:
            continue
        if overlap:
            conflicts[table] = sorted(overlap)

    # folders는 양쪽이 같은 폴더(같은 id·이름)면 충돌이 아니라 '이미 같은 것'
    same_folders = set()
    if "folders" in conflicts:
        for folder_id in list(conflicts["folders"]):
            main_row = conn.execute(
                "SELECT name, color, emoji FROM main.folders WHERE id = ?", (folder_id,)
            ).fetchone()
            src_row = conn.execute(
                "SELECT name, color, emoji FROM src.folders WHERE id = ?", (folder_id,)
            ).fetchone()
            if main_row == src_row:
                same_folders.add(folder_id)
                conflicts["folders"].remove(folder_id)
        if not conflicts["folders"]:
            del conflicts["folders"]

    if conflicts:
        print("[!] id가 겹칩니다 — 자동 병합을 중단합니다:")
        for table, ids in conflicts.items():
            print(f"    {table}: {ids[:10]}{' …' if len(ids) > 10 else ''}")
        conn.close()
        return 2

    new_sessions = sorted(_ids(conn, "sessions", "src") - _ids(conn, "sessions", "main"))
    new_folders = sorted(_ids(conn, "folders", "src") - _ids(conn, "folders", "main"))
    print(f"로컬로 가져올 Drive 세션: {new_sessions}")
    for sid in new_sessions:
        title, started = conn.execute(
            "SELECT title, started_at FROM src.sessions WHERE id = ?", (sid,)
        ).fetchone()
        segs = conn.execute(
            "SELECT COUNT(*) FROM src.segments WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        print(f"    #{sid} {title!r}  {started}  자막 {segs}개")
    print(f"가져올 폴더: {new_folders or '(없음 — 이미 동일한 폴더 보유)'}")
    if same_folders:
        print(f"양쪽에 동일한 폴더(그대로 둠): {sorted(same_folders)}")

    if not apply:
        print("\n(미리보기입니다. 실제로 합치려면 --apply)")
        conn.close()
        return 0

    # 2) 백업 — 되돌릴 수 있게
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = dst_dir / f"jotthatdown.db.bak-{stamp}"
    shutil.copy2(dst_db, backup)
    print(f"\n로컬 DB 백업: {backup.name}")

    src_att = (src_dir / "attachments").as_uri()
    dst_att = (dst_dir / "attachments").as_uri()

    # 3) 폴더 → 세션 → 딸린 행 순서로 (FK 순서)
    for folder_id in new_folders:
        cols = _columns(conn, "folders")
        placeholders = ", ".join("?" * len(cols))
        row = conn.execute(
            f"SELECT {', '.join(cols)} FROM src.folders WHERE id = ?", (folder_id,)
        ).fetchone()
        conn.execute(
            f"INSERT INTO main.folders ({', '.join(cols)}) VALUES ({placeholders})", row
        )

    session_cols = _columns(conn, "sessions")
    for sid in new_sessions:
        row = list(
            conn.execute(
                f"SELECT {', '.join(session_cols)} FROM src.sessions WHERE id = ?",
                (sid,),
            ).fetchone()
        )
        # pdf_path는 절대경로 — 새 위치로 고쳐 준다
        if "pdf_path" in session_cols:
            i = session_cols.index("pdf_path")
            if row[i]:
                row[i] = str(dst_dir / "pdf" / Path(row[i]).name)
        conn.execute(
            f"INSERT INTO main.sessions ({', '.join(session_cols)})"
            f" VALUES ({', '.join('?' * len(session_cols))})",
            row,
        )

    moved = {}
    for table in _SESSION_TABLES:
        try:
            cols = _columns(conn, table)
        except sqlite3.OperationalError:
            continue
        if not cols:
            continue
        doc_i = cols.index("doc_json") if "doc_json" in cols else None
        count = 0
        for sid in new_sessions:
            rows = conn.execute(
                f"SELECT {', '.join(cols)} FROM src.{table} WHERE session_id = ?", (sid,)
            ).fetchall()
            for row in rows:
                row = list(row)
                if doc_i is not None:
                    row[doc_i] = _rewrite_doc(row[doc_i], src_att, dst_att)
                conn.execute(
                    f"INSERT INTO main.{table} ({', '.join(cols)})"
                    f" VALUES ({', '.join('?' * len(cols))})",
                    row,
                )
                count += 1
        moved[table] = count
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()
    print("옮긴 행:", ", ".join(f"{t}={n}" for t, n in moved.items() if n))

    # 4) 딸린 파일 — 이름이 겹치면 로컬 것을 남긴다 (로컬이 원본)
    copied = {}
    for sub in ("audio", "attachments", "pdf"):
        src_sub, dst_sub = src_dir / sub, dst_dir / sub
        if not src_sub.is_dir():
            continue
        dst_sub.mkdir(parents=True, exist_ok=True)
        n = 0
        for item in src_sub.iterdir():
            if item.is_file() and not (dst_sub / item.name).exists():
                shutil.copy2(item, dst_sub / item.name)
                n += 1
        copied[sub] = n
    print("복사한 파일:", ", ".join(f"{s}={n}" for s, n in copied.items()))
    print("\n병합 완료.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive", help="Drive의 JotThatDown 폴더 (생략 시 자동 탐지)")
    parser.add_argument("--apply", action="store_true", help="실제로 병합")
    args = parser.parse_args()

    if args.drive:
        src_dir = Path(args.drive)
    else:
        from app.gdrive import find_google_drive_root

        root = find_google_drive_root()
        if root is None:
            print("[!] 구글 드라이브를 찾지 못했습니다. --drive 로 경로를 지정하세요.")
            return 1
        src_dir = root / "JotThatDown"
    dst_dir = app_root() / "data"
    print(f"Drive: {src_dir}\n로컬 : {dst_dir}\n")
    return merge(src_dir, dst_dir, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
