"""포트(추상 인터페이스) — 구현체가 아닌 이 계약에만 의존한다 (DIP).

새 엔진(예: 시스템 사운드)이나 새 싱크(오버레이, DB 저장)는
이 인터페이스를 구현해 추가하며, 기존 코드는 수정하지 않는다 (OCP).
"""
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from .models import TranscriptSegment


@runtime_checkable
class TranscriptSink(Protocol):
    """확정된 세그먼트를 받는 소비자 (콘솔, 오버레이, DB 등)."""

    def on_segment(self, segment: TranscriptSegment) -> None: ...


@runtime_checkable
class SegmentTransform(Protocol):
    """세그먼트를 싱크에 전달하기 전에 가공하는 단계 (교정 사전 등).

    None을 반환하면 그 세그먼트는 버려진다 (환각 필터 등).
    """

    def apply(self, segment: TranscriptSegment) -> TranscriptSegment | None: ...


class TranscriptionEngine(ABC):
    """오디오를 듣고 세그먼트를 발행하는 엔진의 공통 계약."""

    @abstractmethod
    def add_sink(self, sink: TranscriptSink) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
