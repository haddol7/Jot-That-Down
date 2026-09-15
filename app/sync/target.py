"""동기화 대상 — 데이터를 백업/공유할 '저 너머'의 장소.

서비스는 이 프로토콜에만 의존한다. 구글 드라이브 대신 OneDrive나 임의의
폴더를 붙여도 SyncService는 바뀌지 않는다.
"""
from pathlib import Path
from typing import Protocol

_APP_FOLDER = "JotThatDown"


class SyncTarget(Protocol):
    """동기화 대상. 지금은 '마운트된 폴더' 계열만 있다."""

    @property
    def label(self) -> str:
        """사용자에게 보여줄 이름 (예: '구글 드라이브')."""
        ...

    def is_available(self) -> bool:
        """지금 쓸 수 있는가. (드라이브가 꺼져 있으면 False)"""
        ...

    def root(self) -> Path:
        """데이터를 두는 폴더. 없으면 만든다. is_available()일 때만 호출."""
        ...


class FolderTarget:
    """이미 정해진 폴더 하나를 대상으로 삼는다 (드라이브 앱이 마운트한 폴더 등).

    폴더가 사라지면(드라이브 종료·로그아웃) is_available()이 False가 되고,
    앱은 조용히 로컬로만 동작한다.
    """

    def __init__(self, path: Path | str, label: str = "동기화 폴더") -> None:
        self._path = Path(path)
        self._label = label

    @property
    def label(self) -> str:
        return self._label

    @property
    def path(self) -> Path:
        return self._path

    def is_available(self) -> bool:
        # 폴더 자체가 있거나, 최소한 부모(마운트 지점)가 살아 있어 만들 수 있으면 OK
        try:
            return self._path.is_dir() or self._path.parent.is_dir()
        except OSError:
            return False

    def root(self) -> Path:
        self._path.mkdir(parents=True, exist_ok=True)
        return self._path


class GoogleDriveTarget:
    """구글 드라이브의 앱 폴더.

    설정에 적어 둔 경로를 먼저 쓰되, 그 경로가 죽어 있으면 드라이브를 다시 찾는다.
    드라이브 문자는 고정이 아니다 (USB를 꽂으면 G: → H:로 밀린다). 저장된 경로만
    믿으면 드라이브가 멀쩡히 켜져 있는데도 영영 '꺼짐'으로 보인다.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path else None

    @property
    def label(self) -> str:
        return "구글 드라이브"

    @property
    def path(self) -> Path | None:
        return self._path

    def is_available(self) -> bool:
        if self._path is not None and _mounted(self._path):
            return True
        from ..gdrive import find_google_drive_root

        root = find_google_drive_root()  # 문자가 바뀌었을 수도 있으니 다시 찾는다
        if root is None:
            return False
        self._path = root / _APP_FOLDER
        return True

    def root(self) -> Path:
        if not self.is_available():
            raise OSError("구글 드라이브를 찾을 수 없습니다.")
        self._path.mkdir(parents=True, exist_ok=True)
        return self._path


def _mounted(path: Path) -> bool:
    """폴더가 있거나, 최소한 부모(마운트 지점)가 살아 있어 만들 수 있는가."""
    try:
        return path.is_dir() or path.parent.is_dir()
    except OSError:
        return False


def google_drive_target() -> GoogleDriveTarget | None:
    """지금 마운트된 드라이브에서 앱 폴더를 잡는다. 드라이브가 없으면 None."""
    target = GoogleDriveTarget()
    return target if target.is_available() else None


def target_for(sync_dir: str) -> GoogleDriveTarget | None:
    """설정에 저장된 폴더로 대상을 복원한다. 설정이 비었으면 None(동기화 끔)."""
    if not sync_dir:
        return None
    return GoogleDriveTarget(sync_dir)
