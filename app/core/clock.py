"""세션 시계 — 모든 타임스탬프(자막·노트 블록·녹음)의 단일 기준."""
import time


class SessionClock:
    def __init__(self, offset_ms: int = 0) -> None:
        """offset_ms: 지난 세션을 이어서 녹음할 때 기존 세션의 끝 시각."""
        self._t0 = time.monotonic()
        self._offset_ms = offset_ms

    def now_ms(self) -> int:
        """세션 시작 이후 경과 밀리초 (이어 녹음이면 기존 시간 뒤에서 계속)."""
        return self._offset_ms + int((time.monotonic() - self._t0) * 1000)


def format_ms(t_ms: int) -> str:
    """14:23 또는 1:02:03 형태로 표시."""
    total_sec = t_ms // 1000
    h, rem = divmod(total_sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
