"""동기화 — 로컬이 원본, 구글 드라이브는 사본.

앱은 항상 로컬 data/ 폴더에서 읽고 쓴다. 드라이브는 올릴 때(push)·받을 때(pull)만
만지므로, 드라이브가 꺼져 있어도 앱은 그대로 동작한다.
"""
from .service import RemoteInfo, SyncAction, SyncService, SyncStatus
from .state import SyncState, SyncStateStore
from .target import (
    FolderTarget,
    GoogleDriveTarget,
    SyncTarget,
    google_drive_target,
    target_for,
)

__all__ = [
    "FolderTarget",
    "GoogleDriveTarget",
    "RemoteInfo",
    "SyncAction",
    "SyncService",
    "SyncState",
    "SyncStateStore",
    "SyncStatus",
    "SyncTarget",
    "google_drive_target",
    "target_for",
]
