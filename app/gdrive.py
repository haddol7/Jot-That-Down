"""구글 드라이브(데스크톱) 감지 — 로그인은 구글 클라이언트가 담당하므로
앱은 마운트된 '내 드라이브' 위치만 찾아 폴더를 만들어 쓴다."""
import os
import string
from pathlib import Path

_DRIVE_FOLDER_NAMES = ("내 드라이브", "My Drive")


def find_google_drive_root() -> Path | None:
    """마운트된 구글 드라이브의 '내 드라이브' 경로. 없으면 None."""
    for letter in string.ascii_uppercase:
        base = Path(f"{letter}:/")
        if not base.exists():
            continue
        for name in _DRIVE_FOLDER_NAMES:
            candidate = base / name
            try:
                if candidate.is_dir():
                    return candidate
            except OSError:
                continue
    # 구버전(백업 및 동기화) 기본 위치
    legacy = Path(os.path.expanduser("~")) / "Google Drive"
    if legacy.is_dir():
        return legacy
    return None
