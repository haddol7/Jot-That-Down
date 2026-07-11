"""SQLite 세션 저장소 — 자막 세그먼트, 노트 문서, 블록 타임스탬프.

모든 호출은 Qt 메인 스레드에서 일어난다 (세그먼트는 SegmentBridge를
거쳐 메인 스레드로 넘어온 뒤 저장되므로 별도 락이 필요 없다).
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from ..core.models import TranscriptSegment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    t_start_ms INTEGER NOT NULL,
    t_end_ms INTEGER NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    session_id INTEGER PRIMARY KEY REFERENCES sessions(id),
    doc_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS block_times (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    block_id TEXT NOT NULL,
    t_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, block_id)
);
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#2383e2',
    emoji TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    title TEXT NOT NULL,
    doc_json TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS session_markers (
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    t_ms INTEGER NOT NULL,
    kind TEXT NOT NULL  -- 'resume': 이어서 녹음 시작 지점
);
CREATE TABLE IF NOT EXISTS pdf_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    page INTEGER NOT NULL,
    kind TEXT NOT NULL,      -- underline | highlight | rect | ellipse
    x0 REAL NOT NULL, y0 REAL NOT NULL,  -- 페이지 정규화 좌표 (0~1)
    x1 REAL NOT NULL, y1 REAL NOT NULL,
    color TEXT NOT NULL,
    t_ms INTEGER             -- 라이브 세션이면 그은 시각
);
"""


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        # 커밋마다 fsync로 메인 스레드가 멈칫하지 않게 (녹음 중 타이핑 지연 방지)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """구버전 DB를 폴더·페이지 구조로 끌어올린다 (멱등)."""
        import json

        session_cols = [r[1] for r in self._conn.execute("PRAGMA table_info(sessions)")]
        if "folder_id" not in session_cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN folder_id INTEGER REFERENCES folders(id)"
            )
        if "pdf_path" not in session_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN pdf_path TEXT")
        if "deleted_at" not in session_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN deleted_at TEXT")
        annotation_cols = [
            r[1] for r in self._conn.execute("PRAGMA table_info(pdf_annotations)")
        ]
        if "width" not in annotation_cols:
            self._conn.execute(
                "ALTER TABLE pdf_annotations ADD COLUMN width REAL NOT NULL DEFAULT 2.4"
            )
        bt_cols = [r[1] for r in self._conn.execute("PRAGMA table_info(block_times)")]
        if "page_id" not in bt_cols:
            self._conn.execute(
                "ALTER TABLE block_times ADD COLUMN page_id INTEGER REFERENCES pages(id)"
            )
        page_cols = [r[1] for r in self._conn.execute("PRAGMA table_info(pages)")]
        if "parent_page_id" not in page_cols:
            self._conn.execute(
                "ALTER TABLE pages ADD COLUMN parent_page_id INTEGER REFERENCES pages(id)"
            )
        if "pdf_page" not in page_cols:
            self._conn.execute("ALTER TABLE pages ADD COLUMN pdf_page INTEGER")
        # 탭 시절에 만들어진 여분의 루트 페이지 → 첫 페이지의 하위로 이관하고
        # 첫 페이지 문서에 페이지 링크 블록을 붙여 접근을 보존한다
        # (PDF 페이지 노트는 의도된 다중 루트이므로 제외)
        multi_roots = self._conn.execute(
            "SELECT session_id FROM pages"
            " WHERE parent_page_id IS NULL AND pdf_page IS NULL"
            " GROUP BY session_id HAVING COUNT(*) > 1"
        ).fetchall()
        for (session_id,) in multi_roots:
            roots = self._conn.execute(
                "SELECT id, title, doc_json FROM pages"
                " WHERE session_id = ? AND parent_page_id IS NULL AND pdf_page IS NULL"
                " ORDER BY position, id",
                (session_id,),
            ).fetchall()
            first_id, _, first_doc = roots[0]
            try:
                doc = json.loads(first_doc) if first_doc else {"blocks": []}
            except ValueError:
                doc = {"blocks": []}
            for page_id, title, _ in roots[1:]:
                self._conn.execute(
                    "UPDATE pages SET parent_page_id = ? WHERE id = ?",
                    (first_id, page_id),
                )
                doc.setdefault("blocks", []).append(
                    {"type": "pageLink", "data": {"pageId": page_id, "title": title}}
                )
            self._conn.execute(
                "UPDATE pages SET doc_json = ? WHERE id = ?",
                (json.dumps(doc, ensure_ascii=False), first_id),
            )
        # notes(세션당 문서 1개) → pages(세션당 여러 페이지)의 첫 페이지로 이관
        rows = self._conn.execute(
            "SELECT n.session_id, n.doc_json, n.updated_at FROM notes n"
            " WHERE NOT EXISTS (SELECT 1 FROM pages p WHERE p.session_id = n.session_id)"
        ).fetchall()
        for session_id, doc_json, updated_at in rows:
            cur = self._conn.execute(
                "INSERT INTO pages (session_id, title, doc_json, position, updated_at)"
                " VALUES (?, '노트', ?, 0, ?)",
                (session_id, doc_json, updated_at),
            )
            self._conn.execute(
                "UPDATE block_times SET page_id = ? WHERE session_id = ? AND page_id IS NULL",
                (cur.lastrowid, session_id),
            )

    def close(self) -> None:
        try:  # WAL을 본 파일로 합쳐 동기화(클라우드 폴더)가 파일 하나만 옮기게
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self._conn.close()

    # --- 세션 ---

    def create_session(self, title: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (title, started_at) VALUES (?, ?)",
            (title, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), session_id),
        )
        self._conn.commit()

    def trash_session(self, session_id: int) -> None:
        """휴지통으로 이동 — 목록에서만 숨기고 데이터·파일은 그대로 둔다."""
        self._conn.execute(
            "UPDATE sessions SET deleted_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), session_id),
        )
        self._conn.commit()

    def restore_session(self, session_id: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET deleted_at = NULL WHERE id = ?", (session_id,)
        )
        self._conn.commit()

    def trashed_sessions(self) -> list[tuple]:
        """휴지통 목록 (최근 삭제순): (id, title, started_at, 자막 수)."""
        return self._conn.execute(
            "SELECT s.id, s.title, s.started_at,"
            " (SELECT COUNT(*) FROM segments g WHERE g.session_id = s.id)"
            " FROM sessions s WHERE s.deleted_at IS NOT NULL"
            " ORDER BY s.deleted_at DESC, s.id DESC"
        ).fetchall()

    def delete_session(self, session_id: int) -> None:
        """세션과 딸린 모든 데이터 영구 삭제 (파일 정리는 호출 쪽 책임)."""
        for table in (
            "segments", "block_times", "pdf_annotations",
            "session_markers", "pages", "notes",
        ):
            self._conn.execute(
                f"DELETE FROM {table} WHERE session_id = ?", (session_id,)
            )
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    def cleanup_orphan_attachments(self, attach_dir: Path) -> int:
        """어떤 노트에서도 참조되지 않는 첨부(붙여넣은 이미지) 파일 삭제.

        노트/세션을 지워도 이미지 파일은 남으므로 시작 시·영구 삭제 후에
        쓸어낸다. 반환: 지운 파일 수.
        """
        import re

        if not attach_dir.is_dir():
            return 0
        referenced: set[str] = set()
        pattern = re.compile(r"attachments/([0-9a-f]{32}\.[a-z0-9]{1,5})")
        for table in ("notes", "pages"):
            for (doc,) in self._conn.execute(
                f"SELECT doc_json FROM {table} WHERE doc_json IS NOT NULL"
            ):
                if doc:
                    referenced.update(pattern.findall(doc))
        removed = 0
        for path in attach_dir.iterdir():
            if path.is_file() and path.name not in referenced:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def rename_session(self, session_id: int, title: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id)
        )
        self._conn.commit()

    def get_session(self, session_id: int) -> tuple | None:
        return self._conn.execute(
            "SELECT id, title, started_at, ended_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

    def list_sessions(
        self, search: str = "", folder_id: int | None = None,
        only_folderless: bool = False,
    ) -> list[tuple]:
        """세션 목록 (최신순): (id, title, started_at, 자막 수).

        search가 있으면 제목·자막·페이지 본문에서 부분 일치 검색.
        folder_id가 주어지면 해당 폴더의 세션만.
        only_folderless=True면 어떤 폴더에도 없는 세션만.
        """
        conditions, params = ["s.deleted_at IS NULL"], []
        if only_folderless:
            conditions.append("s.folder_id IS NULL")
        elif folder_id is not None:
            conditions.append("s.folder_id = ?")
            params.append(folder_id)
        if search:
            like = f"%{search}%"
            conditions.append(
                "(s.title LIKE ?"
                " OR EXISTS (SELECT 1 FROM segments g WHERE g.session_id = s.id"
                "            AND g.text LIKE ?)"
                " OR EXISTS (SELECT 1 FROM pages p WHERE p.session_id = s.id"
                "            AND p.doc_json LIKE ?))"
            )
            params += [like, like, like]
        sql = (
            "SELECT s.id, s.title, s.started_at,"
            " (SELECT COUNT(*) FROM segments g WHERE g.session_id = s.id)"
            " FROM sessions s"
        )
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        return self._conn.execute(sql + " ORDER BY s.id DESC", params).fetchall()

    # --- PDF (세션당 1개) 와 주석 ---

    def set_session_pdf(self, session_id: int, path: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET pdf_path = ? WHERE id = ?", (path, session_id)
        )
        self._conn.commit()

    def get_session_pdf(self, session_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT pdf_path FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row[0] if row and row[0] else None

    def add_pdf_annotation(
        self,
        session_id: int,
        page: int,
        kind: str,
        rect: tuple[float, float, float, float],
        color: str,
        width: float = 2.4,
        t_ms: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO pdf_annotations"
            " (session_id, page, kind, x0, y0, x1, y1, color, width, t_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, page, kind, *rect, color, width, t_ms),
        )
        self._conn.commit()
        return cur.lastrowid

    def pdf_annotations_for(self, session_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, page, kind, x0, y0, x1, y1, color, width, t_ms"
            " FROM pdf_annotations WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [
            {
                "id": r[0], "page": r[1], "kind": r[2],
                "rect": (r[3], r[4], r[5], r[6]), "color": r[7], "width": r[8],
                "t_ms": r[9],
            }
            for r in rows
        ]

    def delete_pdf_annotation(self, annotation_id: int) -> None:
        self._conn.execute(
            "DELETE FROM pdf_annotations WHERE id = ?", (annotation_id,)
        )
        self._conn.commit()

    # --- 세션 마커 (이어서 녹음 지점 등) ---

    def add_marker(self, session_id: int, t_ms: int, kind: str = "resume") -> None:
        self._conn.execute(
            "INSERT INTO session_markers (session_id, t_ms, kind) VALUES (?, ?, ?)",
            (session_id, t_ms, kind),
        )
        self._conn.commit()

    def remove_marker(self, session_id: int, t_ms: int, kind: str) -> None:
        self._conn.execute(
            "DELETE FROM session_markers"
            " WHERE session_id = ? AND t_ms = ? AND kind = ?",
            (session_id, t_ms, kind),
        )
        self._conn.commit()

    def markers_for(self, session_id: int, kind: str = "resume") -> list[int]:
        return [
            row[0]
            for row in self._conn.execute(
                "SELECT t_ms FROM session_markers WHERE session_id = ? AND kind = ?"
                " ORDER BY t_ms",
                (session_id, kind),
            )
        ]

    # --- 폴더 ---

    def folders(self) -> list[tuple]:
        """(id, name, color, emoji) 목록."""
        return self._conn.execute(
            "SELECT id, name, color, emoji FROM folders ORDER BY name"
        ).fetchall()

    def create_folder(self, name: str, color: str, emoji: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO folders (name, color, emoji) VALUES (?, ?, ?)",
            (name, color, emoji),
        )
        self._conn.commit()
        return cur.lastrowid

    def delete_folder(self, folder_id: int) -> None:
        """폴더 삭제 — 안의 세션은 폴더 없음으로 이동."""
        self._conn.execute(
            "UPDATE sessions SET folder_id = NULL WHERE folder_id = ?", (folder_id,)
        )
        self._conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        self._conn.commit()

    def set_session_folder(self, session_id: int, folder_id: int | None) -> None:
        self._conn.execute(
            "UPDATE sessions SET folder_id = ? WHERE id = ?", (folder_id, session_id)
        )
        self._conn.commit()

    # --- 페이지 (세션 안의 중첩 노트 문서들) ---

    def root_page(self, session_id: int) -> tuple:
        """(id, title). 없으면 기본 루트 페이지를 만들어 돌려준다.

        PDF 페이지 노트(pdf_page 지정)는 별도 루트라 여기서 제외한다.
        """
        row = self._conn.execute(
            "SELECT id, title FROM pages"
            " WHERE session_id = ? AND parent_page_id IS NULL AND pdf_page IS NULL"
            " ORDER BY position, id LIMIT 1",
            (session_id,),
        ).fetchone()
        if row:
            return row
        page_id = self.create_page(session_id, "노트")
        return (page_id, "노트")

    def page_for_pdf(self, session_id: int, pdf_page: int) -> int:
        """PDF 페이지 전용 노트 페이지 id. 없으면 'p.N'으로 만든다."""
        row = self._conn.execute(
            "SELECT id FROM pages WHERE session_id = ? AND pdf_page = ?",
            (session_id, pdf_page),
        ).fetchone()
        if row:
            return row[0]
        cur = self._conn.execute(
            "INSERT INTO pages (session_id, title, position, updated_at, pdf_page)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                session_id, f"p.{pdf_page + 1}", 1000 + pdf_page,
                datetime.now().isoformat(timespec="seconds"), pdf_page,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_page(self, page_id: int) -> tuple | None:
        """(id, title, parent_page_id)."""
        return self._conn.execute(
            "SELECT id, title, parent_page_id FROM pages WHERE id = ?", (page_id,)
        ).fetchone()

    def child_pages(self, page_id: int) -> list[tuple]:
        """(id, title) — 이 페이지의 하위 페이지들."""
        return self._conn.execute(
            "SELECT id, title FROM pages WHERE parent_page_id = ?"
            " ORDER BY position, id",
            (page_id,),
        ).fetchall()

    def create_page(
        self, session_id: int, title: str, parent_page_id: int | None = None
    ) -> int:
        position = self._conn.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM pages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        cur = self._conn.execute(
            "INSERT INTO pages (session_id, title, position, updated_at, parent_page_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                session_id, title, position,
                datetime.now().isoformat(timespec="seconds"), parent_page_id,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def rename_page(self, page_id: int, title: str) -> None:
        self._conn.execute("UPDATE pages SET title = ? WHERE id = ?", (title, page_id))
        self._conn.commit()

    def save_page_doc(self, page_id: int, doc_json: str) -> None:
        self._conn.execute(
            "UPDATE pages SET doc_json = ?, updated_at = ? WHERE id = ?",
            (doc_json, datetime.now().isoformat(timespec="seconds"), page_id),
        )
        self._conn.commit()

    def load_page_doc(self, page_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT doc_json FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
        return row[0] if row else None

    def pages_tree(self, session_id: int) -> list[tuple]:
        """MD 내보내기용: (깊이, title, doc_json) — 루트들부터 깊이 우선.

        루트 순서: 일반 노트 먼저, 그다음 PDF 페이지 노트(p.1, p.2 …).
        """
        result: list[tuple] = []

        def walk(page_id: int, title: str, depth: int) -> None:
            doc = self.load_page_doc(page_id)
            result.append((depth, title, doc))
            for child_id, child_title in self.child_pages(page_id):
                walk(child_id, child_title, depth + 1)

        roots = self._conn.execute(
            "SELECT id, title FROM pages"
            " WHERE session_id = ? AND parent_page_id IS NULL"
            " ORDER BY (pdf_page IS NOT NULL), pdf_page, position, id",
            (session_id,),
        ).fetchall()
        if not roots:
            roots = [self.root_page(session_id)]
        for root_id, root_title in roots:
            walk(root_id, root_title, 0)
        return result

    # --- 자막 세그먼트 ---

    def add_segment(self, session_id: int, seg: TranscriptSegment) -> int:
        cur = self._conn.execute(
            "INSERT INTO segments (session_id, t_start_ms, t_end_ms, source, text)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, seg.t_start_ms, seg.t_end_ms, seg.source.value, seg.text),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_segment_text(self, segment_id: int, text: str) -> None:
        self._conn.execute(
            "UPDATE segments SET text = ? WHERE id = ?", (text, segment_id)
        )
        self._conn.commit()

    def get_segments(self, session_id: int) -> list[TranscriptSegment]:
        rows = self._conn.execute(
            "SELECT id, source, text, t_start_ms, t_end_ms FROM segments"
            " WHERE session_id = ? ORDER BY t_start_ms",
            (session_id,),
        ).fetchall()
        from ..core.models import AudioSource

        return [
            TranscriptSegment(
                source=AudioSource(source), text=text,
                t_start_ms=t_start, t_end_ms=t_end, db_id=row_id,
            )
            for row_id, source, text, t_start, t_end in rows
        ]

    def max_time_ms(self, session_id: int) -> int:
        """세션에 기록된 가장 늦은 시각 — 이어서 녹음할 때 시계 오프셋 계산용."""
        seg = self._conn.execute(
            "SELECT MAX(t_end_ms) FROM segments WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        blk = self._conn.execute(
            "SELECT MAX(t_ms) FROM block_times WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        return max(seg or 0, blk or 0)

    # --- 노트 문서 ---

    def save_doc(self, session_id: int, doc_json: str) -> None:
        self._conn.execute(
            "INSERT INTO notes (session_id, doc_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET doc_json = excluded.doc_json,"
            " updated_at = excluded.updated_at",
            (session_id, doc_json, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def load_doc(self, session_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT doc_json FROM notes WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row[0] if row else None

    # --- 블록 타임스탬프 ---

    def stamp_block(
        self,
        session_id: int,
        block_id: str,
        t_ms: int,
        force: bool = False,
        page_id: int | None = None,
    ) -> bool:
        """블록 시각 기록. 이미 있으면 force일 때만 덮어씀. 반환: 기록 여부."""
        if force:
            self._conn.execute(
                "INSERT INTO block_times (session_id, block_id, t_ms, page_id)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_id, block_id) DO UPDATE SET"
                " t_ms = excluded.t_ms, page_id = excluded.page_id",
                (session_id, block_id, t_ms, page_id),
            )
        else:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO block_times (session_id, block_id, t_ms, page_id)"
                " VALUES (?, ?, ?, ?)",
                (session_id, block_id, t_ms, page_id),
            )
            if cur.rowcount == 0:
                return False
        self._conn.commit()
        return True

    def block_times_for_page(self, session_id: int, page_id: int) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT block_id, t_ms FROM block_times"
            " WHERE session_id = ? AND (page_id = ? OR page_id IS NULL)",
            (session_id, page_id),
        ).fetchall()
        return dict(rows)

    def block_time(self, session_id: int, block_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT t_ms FROM block_times WHERE session_id = ? AND block_id = ?",
            (session_id, block_id),
        ).fetchone()
        return row[0] if row else None

    def block_times_for(self, session_id: int) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT block_id, t_ms FROM block_times WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        return dict(rows)
