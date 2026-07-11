"""변환 체인을 거쳐 하류 싱크로 전달하는 데코레이터 싱크.

엔진은 이 싱크 하나만 알면 되고, 변환(교정 등)과 실제 소비자(콘솔,
오버레이, DB)는 조립 시점(main)에 자유롭게 구성한다.
"""
from typing import Sequence

from ..core.models import TranscriptSegment
from ..core.ports import SegmentTransform, TranscriptSink


class TransformingSink:
    def __init__(
        self,
        transforms: Sequence[SegmentTransform],
        downstream: Sequence[TranscriptSink],
    ) -> None:
        self._transforms = list(transforms)
        self._downstream = list(downstream)

    def on_segment(self, segment: TranscriptSegment) -> None:
        for transform in self._transforms:
            segment = transform.apply(segment)
            if segment is None:  # 변환 단계가 세그먼트를 버림 (환각 필터 등)
                return
        for sink in self._downstream:
            sink.on_segment(segment)
