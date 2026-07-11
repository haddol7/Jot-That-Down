"""콘솔 싱크 — M1 검증용. TranscriptSink 프로토콜 구현."""
from ..core.clock import format_ms
from ..core.models import AudioSource, TranscriptSegment

_LABELS = {AudioSource.MIC: "MIC", AudioSource.SYSTEM: "SYS"}


class ConsoleSink:
    def on_segment(self, segment: TranscriptSegment) -> None:
        stamp = format_ms(segment.t_start_ms)
        label = _LABELS[segment.source]
        print(f"[{stamp}] [{label}] {segment.text}", flush=True)
