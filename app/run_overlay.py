"""오버레이 자막 엔트리포인트 (M2): 마이크/시스템 사운드 → 화면 위 자막.

실행:  python -m app.run_overlay [mic|system|both]   (기본: both)
종료:  트레이 아이콘 우클릭 → 종료
"""
import sys
import threading

# ctranslate2가 로드되기 전에 CUDA DLL 경로를 등록해야 하므로 가장 먼저 실행
from app.cuda_dlls import register_cuda_dlls

register_cuda_dlls()

from PySide6.QtWidgets import QApplication

from app import bootstrap
from app.core.clock import SessionClock
from app.sinks.console import ConsoleSink
from app.sinks.transforming import TransformingSink
from app.ui.overlay import OverlayWindow
from app.ui.qt_bridge import SegmentBridge
from app.ui.tray import create_tray


def main() -> None:
    from app.paths import ensure_std_streams

    ensure_std_streams()

    source = sys.argv[1] if len(sys.argv) > 1 else "both"
    if source not in bootstrap.SOURCES:
        print(f"사용법: python -m app.run_overlay [{'|'.join(bootstrap.SOURCES)}]")
        raise SystemExit(1)

    from app.settings import load_settings

    config, reason = bootstrap.resolve_config(
        source, load_settings(bootstrap.PROJECT_ROOT / "data")
    )
    print(f"모델 선택: {reason}")

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)  # 창이 없어도 트레이로 상주

    overlay = OverlayWindow()
    bridge = SegmentBridge()
    bridge.segment_received.connect(overlay.show_segment)
    bridge.status_changed.connect(overlay.show_status)
    overlay.show()

    clock = SessionClock()
    sink = TransformingSink(
        bootstrap.build_transforms(), [ConsoleSink(), bridge]
    )
    engines = bootstrap.build_engines(source, config, clock)
    for engine in engines:
        engine.add_sink(sink)

    def start_engines() -> None:
        """모델 로딩(수십 초)이 UI를 얼리지 않도록 워커 스레드에서 시작."""
        for engine in engines:
            engine.start()
        labels = {"mic": "\U0001F3A4 마이크", "system": "\U0001F50A 시스템",
                  "both": "\U0001F3A4+\U0001F50A 동시"}
        bridge.status_changed.emit(f"듣는 중 · {labels[source]}")

    threading.Thread(target=start_engines, name="engine-start", daemon=True).start()

    def quit_app() -> None:
        for engine in engines:
            engine.stop()
        qt_app.quit()

    tray = create_tray(overlay, quit_app)  # noqa: F841 — GC 방지로 참조 유지

    qt_app.exec()


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()  # Windows 패키징(exe) 대비 안전장치
    main()
