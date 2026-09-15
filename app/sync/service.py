"""동기화 서비스 — 로컬이 원본, 대상(드라이브)은 사본.

앱은 언제나 로컬 데이터만 읽고 쓴다. 드라이브는 저장(push)·읽기(pull)·새로고침
때만 만진다. 드라이브가 꺼져 있으면 status().available이 False가 되고 앱은
평소대로 로컬로 동작한다 — 오프라인이 정상 경로다.

충돌 판단은 파일 시각이 아니라 '개정 번호'로 한다. 드라이브가 파일 mtime을
보존한다는 보장이 없고 기기 간 시계도 어긋나기 때문이다.
- 대상의 sync_meta.json에 revision이 있다. push할 때마다 1 오른다.
- 우리가 마지막으로 맞춰 본 revision을 로컬 상태에 적어 둔다.
- 대상 revision > 내가 아는 revision  → 저쪽에 새 게 있다 (pull 필요)
- 로컬 데이터가 마지막 동기화 이후 바뀜 → 이쪽에 새 게 있다 (push 필요)
- 둘 다면 충돌 — 서비스는 판정만 하고, 어느 쪽을 쓸지는 호출자가 정한다.
"""
import json
import socket
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..store.data_move import rewrite_paths
from .mirror import DATA_DIRS, DB_NAME, content_stamp, mirror_dir, snapshot_db
from .state import SyncState, SyncStateStore
from .target import SyncTarget

_META = "sync_meta.json"
_BACKUP_DIR = "backups"
_KEEP_BACKUPS = 5


class SyncAction(Enum):
    """지금 무엇을 해야 하는가."""

    NONE = "none"            # 이미 같다
    PUSH = "push"            # 이쪽 변경을 올린다
    PULL = "pull"            # 저쪽 변경을 받는다
    CONFLICT = "conflict"    # 양쪽 다 바뀜 — 사람이 골라야 한다
    UNAVAILABLE = "off"      # 드라이브가 꺼짐/설정 안 됨


@dataclass(frozen=True)
class RemoteInfo:
    """대상에 마지막으로 올린 사람의 흔적."""

    revision: int = 0
    device: str = ""
    pushed_at: str = ""
    data_root: str = ""

    @property
    def when(self) -> str:
        try:
            dt = datetime.fromisoformat(self.pushed_at)
        except ValueError:
            return self.pushed_at or "알 수 없음"
        return f"{dt.month}월 {dt.day}일 {dt:%H:%M}"


@dataclass(frozen=True)
class SyncStatus:
    action: SyncAction
    remote: RemoteInfo | None = None
    local_changed_at: float = 0.0

    @property
    def available(self) -> bool:
        return self.action is not SyncAction.UNAVAILABLE

    @property
    def local_when(self) -> str:
        if not self.local_changed_at:
            return "알 수 없음"
        dt = datetime.fromtimestamp(self.local_changed_at)
        return f"{dt.month}월 {dt.day}일 {dt:%H:%M}"


class SyncService:
    """로컬 폴더 ↔ 동기화 대상. Qt를 모른다 (백그라운드 스레드에서 돌 수 있게)."""

    def __init__(
        self,
        data_dir: Path,
        target: SyncTarget | None,
        state_store: SyncStateStore,
        device: str | None = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._target = target
        self._state_store = state_store
        self._device = device or socket.gethostname()

    @property
    def target(self) -> SyncTarget | None:
        return self._target

    # --- 판단 ---

    def status(self) -> SyncStatus:
        if self._target is None or not self._target.is_available():
            return SyncStatus(SyncAction.UNAVAILABLE)
        state = self._state_store.load()
        stamp = content_stamp(self._data_dir)
        try:
            remote = self._read_meta()
        except OSError:
            return SyncStatus(SyncAction.UNAVAILABLE)

        remote_ahead = remote.revision > state.revision
        # 1초 여유: 복사 직후의 미세한 시각 차를 변경으로 오인하지 않게
        local_ahead = stamp > state.pushed_stamp + 1.0

        if remote_ahead and local_ahead:
            action = SyncAction.CONFLICT
        elif remote_ahead:
            action = SyncAction.PULL
        elif local_ahead:
            action = SyncAction.PUSH
        else:
            action = SyncAction.NONE
        return SyncStatus(action, remote, stamp)

    # --- 동작 ---

    def push(self) -> RemoteInfo:
        """로컬 → 대상. 대상을 로컬과 똑같이 맞춘다."""
        root = self._require_root()
        remote = self._read_meta()

        snapshot_db(self._data_dir / DB_NAME, root / DB_NAME)
        for sub in DATA_DIRS:
            mirror_dir(self._data_dir / sub, root / sub)

        info = RemoteInfo(
            revision=remote.revision + 1,
            device=self._device,
            pushed_at=datetime.now().isoformat(timespec="seconds"),
            data_root=str(self._data_dir),
        )
        self._write_meta(root, info)
        self._state_store.save(
            SyncState(revision=info.revision, pushed_stamp=content_stamp(self._data_dir))
        )
        return info

    def pull(self) -> RemoteInfo:
        """대상 → 로컬. 호출 전에 DB 연결을 닫아야 한다 (파일을 갈아끼운다)."""
        root = self._require_root()
        remote = self._read_meta()
        remote_db = root / DB_NAME
        if not remote_db.exists():
            raise FileNotFoundError("동기화 폴더에 데이터가 없습니다.")

        self.backup_local("pull-전")

        snapshot_db(remote_db, self._data_dir / DB_NAME)
        # 로컬에만 있던 -wal/-shm은 새 DB와 짝이 안 맞는다 — 버려야 한다
        for suffix in ("-wal", "-shm"):
            (self._data_dir / f"{DB_NAME}{suffix}").unlink(missing_ok=True)
        for sub in DATA_DIRS:
            mirror_dir(root / sub, self._data_dir / sub)

        # 올린 기기의 경로가 박혀 있으면 이 기기 경로로 고친다
        if remote.data_root and Path(remote.data_root) != self._data_dir:
            rewrite_paths(
                self._data_dir / DB_NAME, Path(remote.data_root), self._data_dir
            )
        self._state_store.save(
            SyncState(
                revision=remote.revision, pushed_stamp=content_stamp(self._data_dir)
            )
        )
        return remote

    def backup_local(self, why: str) -> Path:
        """덮어쓰기 전에 지금 로컬 DB를 보관해 둔다 — 되돌릴 수 있게."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = self._data_dir / _BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = backup_dir / f"{stamp}-{why}.db"
        source = self._data_dir / DB_NAME
        if source.exists():
            snapshot_db(source, path)
        self._prune_backups(backup_dir)
        return path

    def adopt_remote_revision(self) -> None:
        """대상의 변경을 '봤다'고 표시만 한다 (내 것으로 덮어쓰기로 결정했을 때)."""
        remote = self._read_meta()
        self._state_store.save(
            SyncState(revision=remote.revision, pushed_stamp=0.0)  # 로컬은 여전히 새것
        )

    # --- 내부 ---

    def _require_root(self) -> Path:
        if self._target is None or not self._target.is_available():
            raise OSError("동기화 폴더를 쓸 수 없습니다 (드라이브가 꺼져 있나요?)")
        return self._target.root()

    def _read_meta(self) -> RemoteInfo:
        if self._target is None:
            return RemoteInfo()
        path = self._target.root() / _META
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return RemoteInfo()
        known = RemoteInfo.__dataclass_fields__
        return RemoteInfo(**{k: v for k, v in raw.items() if k in known})

    def _write_meta(self, root: Path, info: RemoteInfo) -> None:
        (root / _META).write_text(
            json.dumps(info.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _prune_backups(self, backup_dir: Path) -> None:
        backups = sorted(backup_dir.glob("*.db"), reverse=True)
        for old in backups[_KEEP_BACKUPS:]:
            try:
                old.unlink()
            except OSError:
                pass
