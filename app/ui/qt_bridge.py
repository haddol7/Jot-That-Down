"""워커 스레드 → Qt 메인 스레드 다리.

TranscriptSink 포트의 Qt 구현체. 엔진(워커 스레드)이 on_segment를 호출하면
시그널로 변환되어 Qt가 메인 스레드 큐로 안전하게 전달한다.
"""
from PySide6.QtCore import QObject, Signal

from ..core.models import TranscriptSegment


class SegmentBridge(QObject):
    segment_received = Signal(object)  # TranscriptSegment
    status_changed = Signal(str)       # "로딩 중", "듣는 중" 등

    def on_segment(self, segment: TranscriptSegment) -> None:
        self.segment_received.emit(segment)
