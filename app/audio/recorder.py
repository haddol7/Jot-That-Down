"""세션 녹음기 — 소스별 OGG 트랙 기록 (M5).

각 트랙은 세션 시계에 정렬된다: 캡처 공백만큼 무음을 채워 넣어
"파일에서의 위치 = 세션 경과 시간"이 항상 성립한다. 덕분에 재생 시
자막 타임스탬프를 그대로 파일 오프셋으로 쓸 수 있다.

16kHz 모노 Vorbis ≈ 시간당 10~15MB. 강의 다시 듣기 용도로 충분.
"""
import queue
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from ..core.clock import SessionClock
from ..core.models import AudioSource
from .capture import LoopbackCapture, MicCapture

RECORD_RATE = 16000


def audio_path(data_dir: Path, session_id: int, source: AudioSource) -> Path:
    return data_dir / "audio" / f"{session_id}_{source.value}.ogg"


def _resample_to(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """선형 보간 리샘플 — 음성 기록 용도로 충분."""
    if src_rate == dst_rate:
        return samples
    n_out = int(len(samples) * dst_rate / src_rate)
    positions = np.linspace(0, len(samples) - 1, n_out)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.int16)


class _TrackWriter:
    """한 소스의 청크를 받아 세션 시계에 정렬된 OGG로 기록."""

    # 이 이상 벌어지면 캡처 공백으로 보고 무음을 채운다
    _GAP_THRESHOLD_MS = 500

    def __init__(self, path: Path, clock: SessionClock, resume: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._queue: queue.Queue = queue.Queue()
        self._cursor = 0  # 지금까지 기록한 샘플 수

        # OGG는 이어쓰기가 안 되므로, 기존 녹음을 새 파일 앞에 복사한 뒤 계속 쓴다.
        # 복사가 끝날 때까지 원본은 .prev로 보존된다 (중간 크래시에도 유실 없음).
        previous = None
        if resume and path.exists():
            previous = path.with_name(path.stem + ".prev.ogg")
            if previous.exists():
                previous.unlink()
            path.rename(previous)

        self._file = sf.SoundFile(
            str(path), mode="w", samplerate=RECORD_RATE, channels=1,
            format="OGG", subtype="VORBIS",
        )
        if previous is not None:
            with sf.SoundFile(str(previous)) as old:
                while True:
                    block = old.read(65536, dtype="int16")
                    if len(block) == 0:
                        break
                    if old.samplerate != RECORD_RATE:
                        block = _resample_to(block, old.samplerate, RECORD_RATE)
                    self._file.write(block)
                    self._cursor += len(block)
            previous.unlink()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def feed(self, samples: np.ndarray, src_rate: int) -> None:
        """캡처 콜백 스레드에서 호출 — 큐잉만 하고 즉시 반환."""
        self._queue.put((self._clock.now_ms(), samples, src_rate))

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            arrived_ms, samples, src_rate = item
            chunk = _resample_to(samples, src_rate, RECORD_RATE)
            # 청크의 시작 시각 기준으로 공백을 무음으로 채워 시계와 정렬
            chunk_start_ms = arrived_ms - len(chunk) * 1000 // RECORD_RATE
            expected_cursor = chunk_start_ms * RECORD_RATE // 1000
            gap = expected_cursor - self._cursor
            if gap > self._GAP_THRESHOLD_MS * RECORD_RATE // 1000:
                self._write_silence(gap)
                self._cursor += gap
            self._file.write(chunk)
            self._cursor += len(chunk)
        self._file.close()

    def _write_silence(self, total: int) -> None:
        """무음 채우기 — 수 분치 공백을 한 번에 쓰면 libsndfile(vorbis)이
        스택 오버플로로 죽으므로 블록 단위로 나눠 쓴다."""
        block = np.zeros(65536, dtype=np.int16)
        remaining = total
        while remaining > 0:
            n = min(remaining, len(block))
            self._file.write(block[:n])
            remaining -= n


class SessionRecorder:
    """세션의 소스들을 각자 트랙으로 녹음한다. 소스는 세션 중 켜고 끌 수 있다.

    - 트랙(캡처+파일)은 소스를 처음 켤 때 만들어진다.
    - 끈 동안은 청크를 버리고, 다시 켜면 공백이 무음으로 채워져
      "파일 위치 = 세션 시간" 정렬이 유지된다.
    - STT 엔진과 완전히 독립 — WASAPI 공유 모드라 같은 장치를 STT와
      녹음기가 동시에 캡처해도 문제없다.
    """

    _CAPTURE_CLASSES = {
        AudioSource.MIC: MicCapture,
        AudioSource.SYSTEM: LoopbackCapture,
    }

    def __init__(
        self,
        data_dir: Path,
        session_id: int,
        clock: SessionClock,
        resume: bool = False,
    ) -> None:
        self._data_dir = data_dir
        self._session_id = session_id
        self._clock = clock
        self._resume = resume
        self._tracks: dict[AudioSource, tuple[object, _TrackWriter]] = {}
        self._active: dict[AudioSource, bool] = {}
        self._lock = threading.Lock()

    def set_active(self, source: AudioSource, active: bool) -> None:
        with self._lock:
            self._active[source] = active
            if active and source not in self._tracks:
                writer = _TrackWriter(
                    audio_path(self._data_dir, self._session_id, source),
                    self._clock,
                    resume=self._resume,
                )
                capture = self._CAPTURE_CLASSES[source](
                    on_chunk=lambda s, r, src=source, w=writer: self._feed(src, w, s, r)
                )
                capture.start()
                self._tracks[source] = (capture, writer)

    def stop(self) -> None:
        with self._lock:
            for capture, writer in self._tracks.values():
                capture.stop()
                writer.close()
            self._tracks.clear()
            self._active.clear()

    def _feed(self, source: AudioSource, writer: _TrackWriter, samples, rate) -> None:
        if self._active.get(source):
            writer.feed(samples, rate)
