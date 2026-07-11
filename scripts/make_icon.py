"""앱 아이콘 생성 — 자막 바 + J 워드마크를 그려 assets/app.ico(멀티사이즈) 저장.

실행: .venv\\Scripts\\python.exe scripts\\make_icon.py
"""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


def draw(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256  # 256 기준 좌표 스케일

    # 바탕: 다크 라운드 사각형 + 미묘한 세로 그라데이션
    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0, QColor("#2b2b30"))
    gradient.setColorAt(1, QColor("#1b1b1f"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(gradient))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)

    # 아래: 자막 바 두 줄 (파랑 = 현재 발화, 회색 = 지난 줄)
    p.setBrush(QBrush(QColor("#2383e2")))
    p.drawRoundedRect(QRectF(48 * s, 148 * s, 116 * s, 30 * s), 15 * s, 15 * s)
    p.setBrush(QBrush(QColor("#f2f2ef")))
    p.drawRoundedRect(QRectF(176 * s, 148 * s, 32 * s, 30 * s), 15 * s, 15 * s)
    p.setBrush(QBrush(QColor("#5c5c62")))
    p.drawRoundedRect(QRectF(48 * s, 192 * s, 96 * s, 22 * s), 11 * s, 11 * s)

    # 위: J 워드마크
    font = QFont("NanumSquare Neo")
    if "NanumSquare Neo" not in QFontDatabase.families():
        font = QFont("Segoe UI")
    font.setPixelSize(int(112 * s))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#f7f6f3"))
    p.drawText(QRectF(0, 18 * s, size, 120 * s), Qt.AlignCenter, "J")
    p.end()
    return pixmap


def main() -> None:
    QApplication(sys.argv)
    # 폰트 등록 (있으면 J를 나눔스퀘어 네오로)
    for name in ("NanumSquareNeoEB.ttf", "NanumSquareNeoB.ttf"):
        path = ROOT / "assets" / "fonts" / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))

    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    for size in sizes:
        draw(size).save(str(out / f"_icon_{size}.png"))
    draw(256).save(str(out / "app.png"))

    # 멀티사이즈 ICO 합성 (작은 크기에서도 또렷하게)
    from PIL import Image

    largest = Image.open(out / "_icon_256.png")
    largest.save(
        out / "app.ico",
        sizes=[(s, s) for s in sizes],
        append_images=[Image.open(out / f"_icon_{s}.png") for s in sizes[:-1]],
    )
    for size in sizes:
        (out / f"_icon_{size}.png").unlink()
    print("saved:", out / "app.ico")


if __name__ == "__main__":
    main()
