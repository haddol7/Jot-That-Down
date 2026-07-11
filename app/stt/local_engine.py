"""자체 경량 STT 엔진 — TranscriptionEngine 포트 구현 (RealtimeSTT 대체).

캡처(우리 것) → 16kHz 리샘플 → Silero VAD 세그먼터 → 공유 Whisper 워커.
프로세스를 만들지 않고, 모델은 SharedWhisper 하나를 모든 소스가 공유한다.
"""
import queue
import threading
import time

import numpy as np

from ..audio.capture import LoopbackCapture, MicCapture
from ..config import SttConfig
from ..core.clock import SessionClock
from ..core.models import AudioSource, TranscriptSegment
from ..core.ports import TranscriptionEngine, TranscriptSink
from .segmenter import SAMPLE_RATE, UtteranceSegmenter
from .shared_whisper import SharedWhisper


def _to_16k_float(samples: np.ndarray, src_rate: int) -> np.ndarray:
    audio = samples.astype(np.float32) / 32768.0
    if src_rate == SAMPLE_RATE:
        return audio
    n_out = int(len(audio) * SAMPLE_RATE / src_rate)
    positions = np.linspace(0, len(audio) - 1, n_out)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)


class _LocalEngineBase(TranscriptionEngine):
    SOURCE: AudioSource
    CAPTURE_CLS: type

    def __init__(
        self, config: SttConfig, clock: SessionClock, shared: SharedWhisper
    ) -> None:
        self._config = config
        self._clock = clock
        self._shared = shared
        self._sinks: list[TranscriptSink] = []
        self._capture = self.CAPTURE_CLS(on_chunk=self._on_chunk)
        self._chunks: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._active = threading.Event()
        self._active.set()
        self._last_sound_ms = -100000  # 마지막으로 소리가 감지된 세션 시각

    def add_sink(self, sink: TranscriptSink) -> None:
        self._sinks.append(sink)

    def heard_recently(self, within_ms: int = 500) -> bool:
        """최근 within_ms 안에 유의미한 소리가 들어왔는가 (활동 표시용)."""
        return self._active.is_set() and (
            self._clock.now_ms() - self._last_sound_ms <= within_ms
        )

    def start(self) -> None:
        self._shared.start()  # 여러 엔진이 불러도 모델은 한 번만 로딩
        self._segmenter = UtteranceSegmenter(
            self._config.post_speech_silence_sec, self._on_utterance
        )
        self._running.set()
        self._thread = threading.Thread(
            target=self._pump, name=f"{self.SOURCE.value}-segmenter", daemon=True
        )
        self._thread.start()
        self._capture.start()

    def stop(self) -> None:
        self._running.clear()
        self._capture.stop()
        self._chunks.put(None)

    def set_active(self, active: bool) -> None:
        """세션 중 음소거/해제 — 캡처는 유지하고 주입만 차단한다."""
        if active:
            self._active.set()
        else:
            self._active.clear()

    # --- 내부 ---

    def _on_chunk(self, samples: np.ndarray, sample_rate: int) -> None:
        if not self._active.is_set():
            return
        # 대략적인 크기(RMS)로 "소리 들어오는 중" 표시 — 잡음 바닥 위면 활동으로
        if samples.size:
            rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2)))
            if rms > 0.01:
                self._last_sound_ms = self._clock.now_ms()
        self._chunks.put((samples, sample_rate))

    def _pump(self) -> None:
        from .. import diag

        last_beat = time.monotonic()
        chunk_count = 0
        while self._running.is_set():
            try:
                item = self._chunks.get(timeout=3.0)
            except queue.Empty:
                # 캡처가 끊겼다 — 장치 변경(헤드폰 연결 등)이 흔한 원인
                if self._active.is_set():
                    diag.log("capture", f"{self.SOURCE.value}: 3초간 오디오 없음 (장치 끊김?)")
                continue
            if item is None:
                break
            samples, rate = item
            chunk_count += 1
            now = time.monotonic()
            if now - last_beat >= 10.0:  # 10초마다 하트비트
                diag.log(
                    "capture",
                    f"{self.SOURCE.value}: {chunk_count}청크/10s, "
                    f"최근소리 {self._clock.now_ms() - self._last_sound_ms}ms 전",
                )
                last_beat = now
                chunk_count = 0
            self._segmenter.feed(_to_16k_float(samples, rate))

    def _on_utterance(
        self, audio: np.ndarray, duration_ms: int, tail_ms: int, partial: bool
    ) -> None:
        from .. import diag

        t_end = self._clock.now_ms() - tail_ms
        t_start = max(0, t_end - (duration_ms - tail_ms))
        diag.log(
            "utterance",
            f"{self.SOURCE.value}: {duration_ms}ms 발화 확정 → 인식 큐"
            f"{' (강제컷)' if partial else ''}",
        )
        self._shared.submit(
            audio, lambda text: self._dispatch(text, t_start, t_end, partial)
        )

    def _dispatch(self, text: str, t_start: int, t_end: int, partial: bool) -> None:
        segment = TranscriptSegment(
            source=self.SOURCE, text=text, t_start_ms=t_start, t_end_ms=t_end,
            partial=partial,
        )
        for sink in self._sinks:
            sink.on_segment(segment)


class MicTranscriptionEngine(_LocalEngineBase):
    SOURCE = AudioSource.MIC
    CAPTURE_CLS = MicCapture


class SystemTranscriptionEngine(_LocalEngineBase):
    SOURCE = AudioSource.SYSTEM
    CAPTURE_CLS = LoopbackCapture
