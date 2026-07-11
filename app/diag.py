"""STT 진단 로그 — 자막이 간헐적으로 안 나올 때 어느 단계에서 끊기는지 추적.

data/stt.log 에 기록된다 (세션 시작 시 초기화, 오버헤드 무시 가능 수준).
단계: capture(캡처 하트비트) → utterance(발화 확정) → whisper(인식) →
filter(환각/감탄사 드랍) → ui(패널 도착)
"""
import threading
import time

from .paths import data_root

_lock = threading.Lock()
_enabled = True


def log_path():
    return data_root() / "stt.log"


def reset() -> None:
    """세션 시작 시 호출 — 이전 로그를 비운다."""
    try:
        with _lock:
            log_path().write_text(
                time.strftime("%Y-%m-%d %H:%M:%S 세션 시작\n"), encoding="utf-8"
            )
    except OSError:
        pass


def log(tag: str, message: str) -> None:
    if not _enabled:
        return
    line = f"{time.strftime('%H:%M:%S')} [{tag}] {message}\n"
    try:
        with _lock:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(line)
    except OSError:
        pass
