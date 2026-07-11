"""공용 조립 로직 — 콘솔(main)과 오버레이(run_overlay) 엔트리가 공유한다.

설정 결정, 소스별 엔진 생성, 교정 사전 로딩의 단일 출처.
"""
from .config import SttConfig, cpu_fallback
from .core.clock import SessionClock
from .core.ports import TranscriptionEngine
from .paths import app_root
from .stt.local_engine import (
    MicTranscriptionEngine,
    SystemTranscriptionEngine,
)
from .stt.shared_whisper import SharedWhisper
from .text.corrections import FileBackedCorrections
from .text.hallucinations import HallucinationFilter

PROJECT_ROOT = app_root()  # 소스: 프로젝트 루트 / exe: 실행 파일 옆

_DEFAULT_CORRECTIONS = """# 인식 교정 사전 — 형식:  잘못 인식된 표현 -> 올바른 표현
# 앱 실행 중에도 저장하면 다음 자막부터 즉시 반영됩니다.
"""

ENGINE_CLASSES = {
    "mic": [MicTranscriptionEngine],
    "system": [SystemTranscriptionEngine],
    "both": [MicTranscriptionEngine, SystemTranscriptionEngine],
}
SOURCES = tuple(ENGINE_CLASSES)


# 모델별 대략적 다운로드 용량 (안내 표시용)
_MODEL_SIZES = {"large-v3": "약 3GB", "large-v3-turbo": "약 1.6GB", "small": "약 0.5GB"}


def model_download_notice(model: str) -> str | None:
    """모델이 캐시에 없으면 '내려받는 중' 안내문(용량 포함), 있으면 None."""
    import os
    from pathlib import Path

    cache = Path(os.path.expanduser("~")) / ".cache" / "huggingface" / "hub"
    for entry in cache.glob(f"models--*faster-whisper-{model}*"):
        if any((entry / "snapshots").glob("*/*")):
            return None  # 이미 받아둠
    size = _MODEL_SIZES.get(model, "수 GB")
    return f"음성 인식 모델 내려받는 중… ({model} · {size} · 최초 1회)"


def cuda_available() -> bool:
    import ctranslate2

    return ctranslate2.get_cuda_device_count() > 0


def _vram_total_gb() -> float:
    """GPU 총 VRAM(GB). 조회 실패 시 0."""
    try:
        import pynvml

        pynvml.nvmlInit()
        info = pynvml.nvmlDeviceGetMemoryInfo(
            pynvml.nvmlDeviceGetHandleByIndex(0)
        )
        return info.total / (1024 ** 3)
    except Exception:
        return 0.0


# 인스턴스당 필요 VRAM(GB, int8_float16 근사치).
# auto는 turbo를 쓴다: large-v3보다 2~3배 빨라 GPU 점유 시간이 짧고
# (에디터 웹뷰와의 GPU 경합 → 녹음 중 타이핑 지연 완화) VRAM도 절반이다.
# 최고 정확도가 필요하면 설정에서 large-v3를 수동 선택.
_MODEL_TIERS = [(1.2, "large-v3-turbo")]
_VRAM_RESERVE_GB = 1.5  # 데스크톱 컴포지터 등 상시 사용분


def resolve_config(source: str, settings=None) -> tuple[SttConfig, str]:
    """하드웨어·소스 수·사용자 설정에 맞는 STT 설정. 반환: (설정, 선택 사유).

    설정에서 모델을 수동 지정하면 그대로 따르고(GPU 없으면 CPU 폴백),
    자동이면: 이 데스크톱(8GB)은 large-v3, 작은 노트북은 turbo,
    GPU가 없으면 CPU + small.
    """
    from dataclasses import replace

    base = SttConfig()
    if settings is not None:
        base = replace(base, post_speech_silence_sec=settings.silence_sec)

    if not cuda_available():
        return cpu_fallback(base), "GPU 없음 → CPU, small 모델"

    if settings is not None and settings.model_mode != "auto":
        return (
            replace(base, model=settings.model_mode),
            f"수동 선택: {settings.model_mode}",
        )

    # 모델은 소스 수와 무관하게 항상 1개 (SharedWhisper가 공유)
    available = _vram_total_gb() - _VRAM_RESERVE_GB
    for need_gb, model in _MODEL_TIERS:
        if available >= need_gb:
            return replace(base, model=model), f"GPU {_vram_total_gb():.0f}GB → {model}"
    return cpu_fallback(base), "GPU VRAM 부족 → CPU, small 모델"


def build_engines(
    source: str, config: SttConfig, clock: SessionClock
) -> list[TranscriptionEngine]:
    shared = SharedWhisper(config)  # 모든 소스가 모델 하나를 공유
    return [cls(config, clock, shared) for cls in ENGINE_CLASSES[source]]


def corrections_path():
    """교정 사전 파일 경로 — 없으면 기본 템플릿을 만들어 준다 (exe 첫 실행)."""
    path = PROJECT_ROOT / "corrections.txt"
    if not path.exists():
        try:
            path.write_text(_DEFAULT_CORRECTIONS, encoding="utf-8")
        except OSError:
            pass
    return path


def build_corrections() -> FileBackedCorrections:
    return FileBackedCorrections(corrections_path())


def build_transforms() -> list:
    """표준 변환 체인: 환각 제거 → 교정 사전."""
    return [HallucinationFilter(), build_corrections()]
