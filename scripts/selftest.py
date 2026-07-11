"""M1 셀프테스트 — 마이크 없이 파이프라인 핵심을 검증한다.

1. CUDA(GPU) 인식 확인
2. WAV 파일(TTS로 생성)을 faster-whisper large-v3로 인식해 결과 출력

실행: python scripts/selftest.py <wav 경로>
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cuda_dlls import register_cuda_dlls

register_cuda_dlls()

import ctranslate2
from faster_whisper import WhisperModel

from app.config import SttConfig, cpu_fallback


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    wav_path = sys.argv[1]

    gpu_count = ctranslate2.get_cuda_device_count()
    print(f"[1/2] CUDA 디바이스: {gpu_count}개 {'OK' if gpu_count else '-> CPU 폴백'}")

    config = SttConfig()
    if gpu_count == 0:
        config = cpu_fallback(config)

    print(f"[2/2] 모델 로딩: {config.model} ({config.device}, {config.compute_type})")
    t0 = time.perf_counter()
    model = WhisperModel(config.model, device=config.device, compute_type=config.compute_type)
    print(f"      로딩 완료 ({time.perf_counter() - t0:.1f}초)")

    t0 = time.perf_counter()
    segments, info = model.transcribe(wav_path, language=config.language or None)
    texts = [seg.text.strip() for seg in segments]
    elapsed = time.perf_counter() - t0

    print(f"      감지 언어: {info.language} (확률 {info.language_probability:.2f})")
    print(f"      인식 시간: {elapsed:.1f}초 (오디오 {info.duration:.1f}초)")
    print("--- 인식 결과 ---")
    for text in texts:
        print(text)


if __name__ == "__main__":
    main()
