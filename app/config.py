"""앱 설정 — 생성자 주입으로 전달한다. 전역 상태 없음."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SttConfig:
    model: str = "large-v3"
    device: str = "cuda"              # GPU 불가 시 "cpu" + small 모델로 폴백
    compute_type: str = "int8_float16"
    # "ko" 고정: 자동 감지("")는 99개 언어 전체가 대상이라 소음/음악에서
    # 제3언어 오감지가 발생한다. ko 모드도 문장 속 영어는 영문으로 받아쓰므로
    # 한영 혼용 요구를 충족한다. (사용자 결정 2026-07-09)
    language: str = "ko"
    post_speech_silence_sec: float = 0.7  # 이만큼 조용하면 발화 확정
    initial_prompt: str | None = None     # 용어집 힌트 (M6에서 파일 연동)


def cpu_fallback(config: SttConfig) -> SttConfig:
    """GPU를 못 쓸 때의 대체 설정."""
    return SttConfig(
        model="small",
        device="cpu",
        compute_type="int8",
        language=config.language,
        post_speech_silence_sec=config.post_speech_silence_sec,
        initial_prompt=config.initial_prompt,
    )
