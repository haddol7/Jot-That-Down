"""재생기 — 녹음 트랙 재생 (M5+).

QMediaPlayer 대신 soundfile+PyAudio로 직접 PCM을 재생한다:
Windows 미디어 코덱 의존성이 없고, 트랙이 세션 시계에 정렬되어
있으므로 t_ms → 프레임 오프셋 변환이 단순 곱셈이다.

- SnippetPlayer: 자막 한 구간 다시 듣기 (단일 트랙)
- MixPlayer: 세션 전체 재생 — 마이크·시스템 트랙을 실시간 믹스,
  탐색(seek)과 진행 위치(position_ms) 제공
"""
import threading
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
import soundfile as sf


class SnippetPlayer:
    """한 번에 하나의 구간만 재생. 새 재생 요청이 오면 기존 것을 멈춘다."""

    def __init__(self) -> None:
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None

    def play(self, path: Path, start_ms: int, end_ms: int) -> None:
        self.stop()
        self._stop_flag = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            args=(path, start_ms, end_ms, self._stop_flag),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @staticmethod
    def _run(path: Path, start_ms: int, end_ms: int, stop_flag: threading.Event) -> None:  # noqa: C901
        try:
            file = sf.SoundFile(str(path))
        except Exception:
            return  # 트랙 없음(녹음 이전 세션 등) — 조용히 무시
        pa = pyaudio.PyAudio()
        try:
            rate = file.samplerate
            start = min(int(start_ms * rate / 1000), max(file.frames - 1, 0))
            remaining = max(int((end_ms - start_ms) * rate / 1000), 0)
            file.seek(start)
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, output=True)
            while remaining > 0 and not stop_flag.is_set():
                block = file.read(min(2048, remaining), dtype="int16")
                if len(block) == 0:
                    break
                stream.write(block.tobytes())
                remaining -= len(block)
            stream.stop_stream()
            stream.close()
        finally:
            file.close()
            pa.terminate()


class MixPlayer:
    """세션 전체 재생 — 여러 트랙을 프레임 단위로 합산해 하나로 재생.

    트랙들은 모두 세션 시계에 정렬되어 있으므로(무음 패딩) 같은
    프레임 인덱스 = 같은 세션 시각이다. position_ms는 UI가 폴링한다.
    """

    def __init__(self) -> None:
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self.position_ms = 0
        self.playing = False

    @staticmethod
    def total_ms(paths: list[Path]) -> int:
        total = 0
        for path in paths:
            try:
                info = sf.info(str(path))
                total = max(total, int(info.frames * 1000 / info.samplerate))
            except Exception:
                continue
        return total

    def play(self, paths: list[Path], start_ms: int = 0) -> None:
        self.stop()
        self._stop_flag = threading.Event()
        self.playing = True
        self.position_ms = start_ms
        self._thread = threading.Thread(
            target=self._run, args=(list(paths), start_ms, self._stop_flag), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self.playing = False

    def _run(self, paths: list[Path], start_ms: int, stop_flag: threading.Event) -> None:
        files = []
        for path in paths:
            try:
                files.append(sf.SoundFile(str(path)))
            except Exception:
                continue
        if not files:
            self.playing = False
            return
        pa = pyaudio.PyAudio()
        try:
            rate = files[0].samplerate
            for file in files:
                file.seek(min(int(start_ms * rate / 1000), file.frames))
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, output=True)
            position = start_ms
            while not stop_flag.is_set():
                blocks = [file.read(2048, dtype="int16") for file in files]
                length = max((len(b) for b in blocks), default=0)
                if length == 0:
                    break
                mixed = np.zeros(length, dtype=np.int32)
                for block in blocks:
                    mixed[: len(block)] += block.astype(np.int32)
                stream.write(np.clip(mixed, -32768, 32767).astype(np.int16).tobytes())
                position += length * 1000 // rate
                self.position_ms = position
            stream.stop_stream()
            stream.close()
        finally:
            for file in files:
                file.close()
            pa.terminate()
            self.playing = False
