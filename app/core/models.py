"""도메인 모델 — 앱 전체가 공유하는 불변 데이터 타입."""
from dataclasses import dataclass
from enum import Enum


class AudioSource(str, Enum):
    MIC = "mic"
    SYSTEM = "system"


@dataclass(frozen=True)
class TranscriptSegment:
    """확정된 발화 한 조각. 시각은 세션 시작 기준 경과 밀리초."""

    source: AudioSource
    text: str
    t_start_ms: int
    t_end_ms: int
    db_id: int | None = None  # 저장 후 부여 — 자막 수정 시 필요
    partial: bool = False      # 무음이 아니라 길이 제한으로 강제로 잘린 조각
                               # (다음 세그먼트가 이어붙는다)
