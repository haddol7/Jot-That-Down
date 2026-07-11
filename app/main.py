"""콘솔 자막 엔트리포인트: 마이크/시스템 사운드 → 자체 STT 파이프라인 → 콘솔.

실행:  python -m app.main [mic|system|both]   (기본: both)
종료:  Ctrl+C
"""
import sys
import time

# ctranslate2가 로드되기 전에 CUDA DLL 경로를 등록해야 하므로 가장 먼저 실행
from app.cuda_dlls import register_cuda_dlls

register_cuda_dlls()

from app import bootstrap
from app.core.clock import SessionClock
from app.sinks.console import ConsoleSink
from app.sinks.transforming import TransformingSink


def main() -> None:
    from app.paths import ensure_std_streams

    ensure_std_streams()

    source = sys.argv[1] if len(sys.argv) > 1 else "both"
    if source not in bootstrap.SOURCES:
        print(f"사용법: python -m app.main [{'|'.join(bootstrap.SOURCES)}]")
        raise SystemExit(1)

    from app.settings import load_settings

    config, reason = bootstrap.resolve_config(
        source, load_settings(bootstrap.PROJECT_ROOT / "data")
    )
    print(f"모델 선택: {reason}")

    clock = SessionClock()
    sink = TransformingSink(bootstrap.build_transforms(), [ConsoleSink()])
    engines = bootstrap.build_engines(source, config, clock)
    for engine in engines:
        engine.add_sink(sink)

    print(f"모델 로딩 중... ({config.model}, {config.device}, 소스: {source})")
    for engine in engines:
        engine.start()
    print("듣는 중 — [MIC]=마이크, [SYS]=시스템 사운드. 종료: Ctrl+C")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n종료 중...")
        for engine in engines:
            engine.stop()


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()  # Windows 패키징(exe) 대비 안전장치
    main()
