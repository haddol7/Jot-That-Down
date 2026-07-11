"""경로 해석 — 소스 실행과 패키징(exe) 실행 양쪽에서 올바른 위치를 준다.

- app_root(): 쓰기 가능한 앱 홈. data/, corrections.txt가 여기 산다.
  (소스: 프로젝트 루트 / exe: 실행 파일 옆)
- resource_root(): 읽기 전용 번들 자원(web/ 등).
  (소스: 프로젝트 루트 / exe: PyInstaller가 푼 _internal)
"""
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_root()))
    return app_root()


# 데이터 폴더(DB·녹음·첨부·PDF) — 설정에서 클라우드 동기화 폴더로 바꿀 수 있다.
# 설정 파일 자체는 항상 기본 위치(app_root()/data)에 남는다.
_data_root: Path | None = None


def set_data_root(path: Path | str) -> None:
    global _data_root
    _data_root = Path(path)


def data_root() -> Path:
    return _data_root if _data_root is not None else app_root() / "data"


def ensure_std_streams() -> None:
    """windowed exe에서는 sys.stdout/stderr가 None이라 print()가 크래시한다.

    콘솔이 없으면 표준 스트림을 무해한 sink로 대체하고, 있으면 UTF-8로.
    """
    import os

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            # StringIO는 긴 세션에서 무한히 쌓이므로 그냥 버린다
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        else:
            try:
                if stream.encoding and stream.encoding.lower() != "utf-8":
                    stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
