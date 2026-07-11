"""공유 Whisper 워커 — faster-whisper 모델 하나를 모든 소스가 함께 쓴다.

경량화의 핵심: RealtimeSTT는 인식기마다 별도 프로세스+모델을 띄웠지만
(동시 모드 = 모델 2개), 이 워커는 프로세스 없이 스레드 하나 + 모델 하나다.
"""
import queue
import threading
import time
from typing import Callable

import numpy as np

from ..config import SttConfig


class SharedWhisper:
    def __init__(self, config: SttConfig) -> None:
        self._config = config
        self._model = None
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """모델 로딩 (여러 엔진이 불러도 한 번만). 로딩 완료까지 블록."""
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            cfg = self._config
            self._model = WhisperModel(
                cfg.model, device=cfg.device, compute_type=cfg.compute_type
            )
            self._thread = threading.Thread(
                target=self._run, name="whisper-worker", daemon=True
            )
            self._thread.start()

    def submit(self, audio_f32: np.ndarray, on_text: Callable[[str], None]) -> None:
        self._queue.put((audio_f32, on_text))

    def stop(self) -> None:
        with self._lock:
            if self._model is None:
                return
            # 대기 중인 발화는 버린다 — 종료가 인식 백로그에 막혀
            # 수십 초씩 걸리지 않게 (소리는 녹음 파일에 남아 있다)
            try:
                while True:
                    self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put(None)
            if self._thread is not None:
                self._thread.join(timeout=10)
            self._model = None
            # ctranslate2 모델은 참조 해제 시 VRAM을 반환한다 (torch 불필요)
            import gc

            gc.collect()

    # --- 내부 ---

    def _run(self) -> None:
        from .. import diag

        cfg = self._config
        while True:
            item = self._queue.get()
            if item is None:
                break
            audio, on_text = item
            backlog = self._queue.qsize()
            started = time.monotonic()
            try:
                segments, _ = self._model.transcribe(
                    audio,
                    language=cfg.language or None,
                    initial_prompt=cfg.initial_prompt,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
            except Exception as error:  # 한 발화의 실패가 파이프라인을 죽이지 않게
                diag.log("whisper", f"인식 실패! {type(error).__name__}: {error}")
                continue
            took = time.monotonic() - started
            if text:
                diag.log(
                    "whisper",
                    f"{took:.1f}s, 대기 {backlog}건, 결과 {len(text)}자: {text[:40]}",
                )
                on_text(text)
            else:
                diag.log("whisper", f"{took:.1f}s, 결과 비어 있음 (무음/잡음 판정)")
