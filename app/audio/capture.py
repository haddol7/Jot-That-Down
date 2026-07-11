"""WASAPI 오디오 캡처 — 마이크 입력과 시스템 재생음(루프백)을 공통 계약으로.

캡처한 청크는 모노 int16으로 다운믹스해 주입된 콜백에 넘긴다.
소비자(STT 엔진, 녹음기)는 PyAudio의 존재를 모른다.
WASAPI 공유 모드라 같은 장치를 여러 캡처가 동시에 열 수 있다
(STT와 녹음기가 각자 캡처를 가져도 충돌하지 않음).
"""
import threading
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio

# (모노 int16 샘플, 원본 샘플레이트) 를 받는 소비자
ChunkHandler = Callable[[np.ndarray, int], None]


class CaptureError(RuntimeError):
    pass


class _DeviceCapture:
    """장치 선택만 하위 클래스에 맡기는 공통 캡처 골격."""

    def __init__(self, on_chunk: ChunkHandler, frames_per_buffer: int = 1024) -> None:
        self._on_chunk = on_chunk
        self._frames_per_buffer = frames_per_buffer
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self._channels = 1
        self._rate = 48000
        self._lock = threading.Lock()

    def _find_device(self, pa: pyaudio.PyAudio) -> dict:
        raise NotImplementedError

    def start(self) -> None:
        with self._lock:
            self._pa = pyaudio.PyAudio()
            device = self._find_device(self._pa)
            self._channels = max(1, int(device["maxInputChannels"]))
            self._rate = int(device["defaultSampleRate"])
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._channels,
                rate=self._rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=self._frames_per_buffer,
                stream_callback=self._callback,
            )

    def stop(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None
            if self._pa is not None:
                self._pa.terminate()
                self._pa = None

    def _callback(self, in_data, frame_count, time_info, status):
        samples = np.frombuffer(in_data, dtype=np.int16)
        if self._channels > 1:
            samples = (
                samples.reshape(-1, self._channels).mean(axis=1).astype(np.int16)
            )
        self._on_chunk(samples, self._rate)
        return (None, pyaudio.paContinue)


class MicCapture(_DeviceCapture):
    """기본 입력 장치(마이크) 캡처."""

    def _find_device(self, pa: pyaudio.PyAudio) -> dict:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        return pa.get_device_info_by_index(wasapi["defaultInputDevice"])


class LoopbackCapture(_DeviceCapture):
    """기본 출력 장치(스피커)의 루프백 쌍둥이 캡처 — 시스템 재생음."""

    def _find_device(self, pa: pyaudio.PyAudio) -> dict:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if speakers.get("isLoopbackDevice"):
            return speakers
        for loopback in pa.get_loopback_device_info_generator():
            if speakers["name"] in loopback["name"]:
                return loopback
        raise CaptureError(
            f"기본 출력 장치 '{speakers['name']}'의 루프백 장치를 찾지 못했습니다."
        )
