"""동기화 상태 — '어디까지 맞춰 봤는가'를 기억한다.

서비스는 이 상태를 어디에 적는지 모른다 (설정 파일이든 무엇이든).
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SyncState:
    revision: int = 0        # 마지막으로 맞춰 본 대상의 개정 번호
    pushed_stamp: float = 0.0  # 그때의 로컬 데이터 변경 시각


class SyncStateStore(Protocol):
    def load(self) -> SyncState:
        ...

    def save(self, state: SyncState) -> None:
        ...
