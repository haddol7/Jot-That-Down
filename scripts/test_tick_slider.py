"""_TickSlider 눈금 페인팅 검증 — 합성 마크로 렌더링해 픽셀 확인."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from app.ui.player_bar import _TickSlider
from app.ui.theme import build_qss


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss("dark"))
    slider = _TickSlider()
    slider.setRange(0, 100)
    slider.setFixedSize(400, 24)
    slider.set_marks([20, 40, 60], [80])
    pixmap = slider.grab()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tick_slider.png")
    pixmap.save(str(out))

    image = pixmap.toImage()
    # 80% 지점(주황 이어녹음 눈금) 근처에서 주황 픽셀을 찾는다
    found_orange = False
    for x in range(int(400 * 0.76), int(400 * 0.84)):
        for y in range(24):
            color = image.pixelColor(x, y)
            if color.red() > 200 and 120 < color.green() < 200 and color.blue() < 120:
                found_orange = True
    print("orange resume tick:", "OK" if found_orange else "MISSING")


if __name__ == "__main__":
    main()
