"""복사 원시 연산 — DB 스냅샷, 폴더 미러링, 변경 시각 스탬프.

DB는 그냥 파일 복사하면 안 된다: WAL 모드라 최근 커밋이 -wal에만 있을 수 있고,
앱이 열어 둔 채로 복사하면 찢어진 파일이 나온다. sqlite의 backup API는 열려
있는 DB도 일관된 스냅샷으로 떠 준다.
"""
import shutil
import sqlite3
from pathlib import Path

DB_NAME = "jotthatdown.db"
DATA_DIRS = ("audio", "attachments", "pdf")


def snapshot_db(src: Path, dst: Path) -> None:
    """열려 있어도 안전하게 DB를 dst로 복제한다 (WAL 포함, 단일 파일)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    target = sqlite3.connect(str(dst))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    # 스냅샷은 WAL 없이 파일 하나로 — 받는 쪽이 파일 하나만 옮기면 되게
    for leftover in (dst.with_name(dst.name + "-wal"), dst.with_name(dst.name + "-shm")):
        leftover.unlink(missing_ok=True)


def mirror_dir(src: Path, dst: Path, *, prune: bool = True) -> tuple[int, int]:
    """src의 파일을 dst로 맞춘다. (복사한 수, 지운 수)

    같은 이름·같은 크기·같은 시각이면 건너뛴다 — 녹음 파일이 커서 매번
    다시 올리면 느리다. prune이면 src에 없는 dst 파일은 지운다(미러).
    """
    copied = removed = 0
    dst.mkdir(parents=True, exist_ok=True)
    src_names = set()
    if src.is_dir():
        for item in src.iterdir():
            if not item.is_file():
                continue
            src_names.add(item.name)
            mate = dst / item.name
            if _same(item, mate):
                continue
            shutil.copy2(item, mate)
            copied += 1
    if prune:
        for item in dst.iterdir():
            if item.is_file() and item.name not in src_names:
                try:
                    item.unlink()
                    removed += 1
                except OSError:
                    pass  # 잠긴 파일은 다음 기회에
    return copied, removed


def _same(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    return sa.st_size == sb.st_size and abs(sa.st_mtime - sb.st_mtime) < 2


def content_stamp(root: Path) -> float:
    """데이터가 마지막으로 바뀐 시각. 로컬에 새 변경이 있는지 판단하는 기준.

    WAL 때문에 DB 본체의 mtime만 보면 안 된다 (커밋이 -wal에만 있을 수 있다).
    딸린 파일(녹음·첨부·PDF)까지 통틀어 가장 최근 시각을 쓴다.
    """
    newest = 0.0
    candidates = [
        root / DB_NAME,
        root / f"{DB_NAME}-wal",
    ]
    for sub in DATA_DIRS:
        directory = root / sub
        if directory.is_dir():
            candidates.extend(p for p in directory.iterdir() if p.is_file())
    for path in candidates:
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest
