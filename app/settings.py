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
    data_dir: str = ""            # 데이터 폴더 (비면 기본 위치) — 클라우드 동기화용
    # PDF 도구별 스타일: {"underline": {"color": "#...", "width": 2.4}, ...}
    pdf_tool_styles: dict = field(default_factory=dict)


def settings_path(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def load_settings(data_dir: Path) -> AppSettings:
    try:
        raw = json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppSettings()
    known = {f.name for f in fields(AppSettings)}
    return AppSettings(**{k: v for k, v in raw.items() if k in known})


def save_settings(data_dir: Path, settings: AppSettings) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    settings_path(data_dir).write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
    )
