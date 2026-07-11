"""발화 세그먼터 — 16kHz float32 스트림에서 Silero VAD로 발화 단위를 잘라낸다.

RealtimeSTT를 대체하는 자체 경량 파이프라인의 앞단. 소스(마이크/시스템)마다
인스턴스 하나씩. 무거운 인식 모델은 SharedWhisper 하나를 공유한다.
"""
from collections import deque
from typing import Callable

import numpy as np

SAMPLE_RATE = 16000
_WINDOW = 512  # Silero v5는 16kHz에서 정확히 512샘플(32ms) 단위

_START_PROB = 0.5     # 이 이상이면 발화 시작
_END_PROB = 0.35      # 이 미만이 이어지면 발화 종료 판정
_PRE_ROLL_SEC = 0.32  # 발화 시작 직전 오디오를 함께 포함 (첫 음절 보존)
_MIN_UTTERANCE_SEC = 0.25
# 말이 계속 이어지면 여기서 강제로 잘라 중간 인식(가독성). 이렇게 잘린 조각은
# partial로 표시되어 다음 조각과 이어붙는다.
_MAX_UTTERANCE_SEC = 11.0
# 강제 컷 전, 이만큼이라도 조용해지면(약한 쉼) 거기서 자연스럽게 끊는다
_SOFT_SILENCE_WINDOWS = 3  # ~0.1초의 짧은 쉼


class _StreamingVad:
    """faster-whisper에 내장된 Silero ONNX를 스트리밍으로 구동.

    torch 없이 onnxruntime(CPU)만 사용 — torch CUDA 런타임(~1GB RAM)을
    통째로 덜어내는 것이 경량화의 두 번째 축이다.
    faster-whisper 버전에 따라 v5(인코더/디코더 분리)와 v6(단일 세션,
    h/c 상태) 두 구조가 있어 둘 다 지원한다. 모델 세션은 lru_cache로
    전 소스가 공유하고, 스트리밍 상태만 인스턴스별로 가진다.
    """

    _CONTEXT = 64  # Silero는 직전 윈도의 마지막 64샘플을 함께 받는다

    def __init__(self) -> None:
        from faster_whisper.vad import get_vad_model

        self._model = get_vad_model()
        self._context = np.zeros((1, self._CONTEXT), dtype=np.float32)
        if hasattr(self._model, "session"):  # v6: 단일 세션 + h/c 상태
            self._h = np.zeros((1, 1, 128), dtype=np.float32)
            self._c = np.zeros((1, 1, 128), dtype=np.float32)
            self._run = self._run_v6
        else:  # v5: 인코더/디코더 분리 + state
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._run = self._run_v5

    def prob(self, window: np.ndarray) -> float:
        """512샘플(16kHz) 윈도의 음성 확률."""
        x = np.concatenate(
            [self._context, window[None, :].astype(np.float32)], axis=1
        )
        result = self._run(x)
        self._context = window[None, -self._CONTEXT:].astype(np.float32)
        return result

    def _run_v6(self, x: np.ndarray) -> float:
        out, self._h, self._c = self._model.session.run(
            None, {"input": x, "h": self._h, "c": self._c}
        )
        return float(np.asarray(out).reshape(-1)[0])

    def _run_v5(self, x: np.ndarray) -> float:
        encoded = self._model.encoder_session.run(None, {"input": x})[0]
        out, self._state = self._model.decoder_session.run(
            None, {"input": encoded.reshape(1, 128), "state": self._state}
        )
        return float(np.asarray(out).reshape(-1)[0])


class UtteranceSegmenter:
    """feed()로 오디오를 밀어 넣으면 발화가 끝날 때 on_utterance가 불린다.

    on_utterance(audio_f32, duration_ms, tail_silence_ms, partial):
      tail_silence_ms는 발화 끝 판정에 쓰인 꼬리 무음 길이 — 호출 시점에서
      빼면 실제 발화가 끝난 시각이 된다.
      partial=True면 무음이 아니라 길이 제한으로 잘린 조각(다음과 이어짐).
    """

    def __init__(
        self,
        silence_sec: float,
        on_utterance: Callable[[np.ndarray, int, int, bool], None],
    ) -> None:
        self._vad = _StreamingVad()
        self._silence_windows = max(1, int(silence_sec * SAMPLE_RATE / _WINDOW))
        self._on_utterance = on_utterance

        self._buffer = np.empty(0, dtype=np.float32)
        self._pre_roll: deque = deque(maxlen=int(_PRE_ROLL_SEC * SAMPLE_RATE / _WINDOW))
        self._speech: list[np.ndarray] = []
        self._speaking = False
        self._silent_count = 0

    def feed(self, samples_f32: np.ndarray) -> None:
        self._buffer = np.concatenate([self._buffer, samples_f32])
        while len(self._buffer) >= _WINDOW:
            window = self._buffer[:_WINDOW]
            self._buffer = self._buffer[_WINDOW:]
            self._process(window)

    # --- 내부 ---

    def _process(self, window: np.ndarray) -> None:
        prob = self._vad.prob(window)

        if not self._speaking:
            if prob >= _START_PROB:
                self._speaking = True
                self._silent_count = 0
                self._speech = list(self._pre_roll)
                self._speech.append(window)
            else:
                self._pre_roll.append(window)
            return

        self._speech.append(window)
        self._silent_count = self._silent_count + 1 if prob < _END_PROB else 0

        duration_sec = len(self._speech) * _WINDOW / SAMPLE_RATE
        if self._silent_count >= self._silence_windows:
            # 진짜 문장 끝 (충분한 무음)
            self._finalize(tail_windows=self._silent_count, partial=False)
        elif duration_sec >= _MAX_UTTERANCE_SEC:
            # 너무 길다 → 강제로 자른다. 짧은 쉼 지점이면 그때 끊고,
            # 아니면 그냥 잘라 partial 표시 (다음 조각과 이어붙는다)
            soft = self._silent_count >= _SOFT_SILENCE_WINDOWS
            self._finalize(tail_windows=self._silent_count if soft else 0, partial=True)

    def _finalize(self, tail_windows: int, partial: bool) -> None:
        audio = np.concatenate(self._speech)
        # partial(강제 컷)이면 다음 발화가 바로 이어지도록 상태를 유지한 채 계속 듣는다
        if partial:
            self._speech = []
            self._silent_count = 0
        else:
            self._speaking = False
            self._speech = []
            self._silent_count = 0
            self._pre_roll.clear()
        if len(audio) / SAMPLE_RATE >= _MIN_UTTERANCE_SEC:
            duration_ms = int(len(audio) * 1000 / SAMPLE_RATE)
            tail_ms = int(tail_windows * _WINDOW * 1000 / SAMPLE_RATE)
            self._on_utterance(audio, duration_ms, tail_ms, partial)
