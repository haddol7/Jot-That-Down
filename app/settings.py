"""앱 설정 — data/settings.json에 저장. 설정 다이얼로그(M6+)가 편집한다."""
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class AppSettings:
    theme: str = "light"          # light | dark
    model_mode: str = "auto"      # auto | large-v3 | large-v3-turbo | small
    silence_sec: float = 0.7      # 이만큼 조용하면 발화 확정
    editor_font_px: int = 16      # 에디터 본문 글꼴 크기
    panel_side: str = "right"     # 받아쓰기 패널 위치: left | right | top | bottom
    overlay_font_px: int = 20     # 실시간 자막(오버레이) 글자 크기
    overlay_lines: int = 2        # 오버레이에 유지할 자막 줄 수
    overlay_ttl_sec: int = 10     # 자막이 사라지기까지의 시간
    # 동기화 — 데이터는 항상 로컬(data_root())에 있고, 여기는 '사본을 두는 곳'이다.
    sync_dir: str = ""            # 구글 드라이브의 JotThatDown 폴더 (비면 동기화 끔)
    sync_revision: int = 0        # 마지막으로 맞춰 본 대상의 개정 번호
    sync_pushed_stamp: float = 0.0  # 그때의 로컬 데이터 변경 시각
    # PDF 도구별 스타일: {"underline": {"color": "#...", "width": 2.4}, ...}
    pdf_tool_styles: dict = field(default_factory=dict)


def settings_path(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def load_settings(data_dir: Path) -> AppSettings:
    try:
        raw = json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppSettings()
    raw = _upgrade(raw)
    known = {f.name for f in fields(AppSettings)}
    return AppSettings(**{k: v for k, v in raw.items() if k in known})


def _upgrade(raw: dict) -> dict:
    """구버전 설정 끌어올리기.

    예전에는 data_dir이 '데이터가 사는 곳'이라 드라이브 폴더를 직접 가리켰다.
    이제 데이터는 항상 로컬이고, 그 폴더는 '사본을 두는 곳'(sync_dir)이 된다.
    """
    legacy = raw.pop("data_dir", "")
    if legacy and not raw.get("sync_dir"):
        raw["sync_dir"] = legacy
    return raw


def save_settings(data_dir: Path, settings: AppSettings) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    settings_path(data_dir).write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
    )
