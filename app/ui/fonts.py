"""나눔스퀘어 네오 폰트 로딩 — 앱 전역 기본 글꼴로 등록한다.

네오는 구버전과 달리 한글 11,172자를 전부 실제 글리프로 갖고 있고
(구버전은 2,479자 + 빈 글리프), 작은 크기에서 획이 훨씬 또렷하다.
구버전도 폴백으로 함께 등록한다.
"""
from PySide6.QtGui import QFontDatabase

from ..paths import resource_root

FAMILY = "NanumSquare Neo"
_loaded = False

_FILES = (
    "NanumSquareNeo.ttf", "NanumSquareNeoB.ttf", "NanumSquareNeoEB.ttf",
    "NanumSquareR.ttf", "NanumSquareB.ttf", "NanumSquareEB.ttf",  # 폴백
)


def load_fonts() -> str:
    """번들된 나눔스퀘어 TTF들을 등록하고 패밀리명을 돌려준다 (한 번만)."""
    global _loaded
    if _loaded:
        return FAMILY
    font_dir = resource_root() / "assets" / "fonts"
    for name in _FILES:
        path = font_dir / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    _loaded = True
    return FAMILY
