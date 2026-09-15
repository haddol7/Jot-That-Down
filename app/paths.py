"""경로 해석 — 소스 실행과 패키징(exe) 실행 양쪽에서 올바른 위치를 준다.

- app_root(): 쓰기 가능한 앱 홈. data/, corrections.txt가 여기 산다.
  (소스: 프로젝트 루트 / exe: 실행 파일 옆)
- resource_root(): 읽기 전용 번들 자원(web/ 등).
  (소스: 프로젝트 루트 / exe: PyInstaller가 푼 _internal)
- data_root(): 데이터 원본. 항상 로컬 — 클라우드 폴더로 바뀌지 않는다.
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


def data_root() -> Path:
    """데이터(DB·녹음·첨부·PDF)는 언제나 여기. 로컬이 원본이다.

    구글 드라이브는 app/sync가 이 폴더를 올리고 받는 '사본'일 뿐이다 —
    드라이브 폴더를 직접 데이터 위치로 쓰지 않는다. 그랬다가는 드라이브가
    꺼졌을 때 데이터가 통째로 사라진 것처럼 보인다.
    """
    return app_root() / "data"


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
