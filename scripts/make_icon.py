"""앱 아이콘 생성 — 자막 바 + 펜 모티브를 그려 assets/app.ico 저장."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication(sys.argv)
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # 바탕: 노션풍 다크 라운드 사각형
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("#202020")))
    painter.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)

    # 자막 바 두 줄
    painter.setBrush(QBrush(QColor("#2383e2")))
    painter.drawRoundedRect(QRectF(48, 150, 112, 26), 13, 13)
    painter.setBrush(QBrush(QColor("#e8e8e6")))
    painter.drawRoundedRect(QRectF(172, 150, 36, 26), 13, 13)
    painter.setBrush(QBrush(QColor("#6f6f6c")))
    painter.drawRoundedRect(QRectF(48, 190, 90, 20), 10, 10)

    # 상단: J 워드마크
    font = QFont("Segoe UI", 84)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#f7f6f3"))
    painter.drawText(QRectF(0, 20, 256, 120), Qt.AlignCenter, "J")
    painter.end()

    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    pixmap.save(str(out / "app.png"))
    pixmap.scaled(256, 256).save(str(out / "app.ico"))
    print("saved:", out / "app.ico")


if __name__ == "__main__":
    main()
