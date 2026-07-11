"""그려서 만드는 아이콘들 — 파일 리소스 없이 QPainter로.

폴더 아이콘: 선택한 색의 폴더 모양 안에 이모지를 렌더링한다.
PDF 도구 아이콘: 글자 없이 도구 모양만 또렷하게.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

FOLDER_COLORS = [
    "#e57373", "#f2a860", "#e8c34e", "#7cb342",
    "#4db6ac", "#2383e2", "#9575cd", "#8d8d8d",
]

_INK = "#9a9a97"  # 라이트/다크 어디서든 보이는 중간 회색


def _lighten(color: QColor, factor: float) -> QColor:
    return QColor(
        min(255, int(color.red() + (255 - color.red()) * factor)),
        min(255, int(color.green() + (255 - color.green()) * factor)),
        min(255, int(color.blue() + (255 - color.blue()) * factor)),
    )


def make_folder_icon(color: str, emoji: str = "", size: int = 20) -> QIcon:
    from PySide6.QtGui import QLinearGradient

    scale = 4  # 고해상도로 그려서 축소 (또렷하게)
    px = size * scale
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    base = QColor(color)
    # 뒷면 탭 (조금 진하게)
    painter.setBrush(QBrush(base.darker(112)))
    tab = QPainterPath()
    tab.addRoundedRect(QRectF(px * 0.08, px * 0.20, px * 0.46, px * 0.30), px * 0.06, px * 0.06)
    painter.drawPath(tab.simplified())

    # 몸통 (세로 그라데이션)
    gradient = QLinearGradient(0, px * 0.30, 0, px * 0.86)
    gradient.setColorAt(0, _lighten(base, 0.12))
    gradient.setColorAt(1, base)
    painter.setBrush(QBrush(gradient))
    body = QPainterPath()
    body.addRoundedRect(QRectF(px * 0.06, px * 0.32, px * 0.88, px * 0.54), px * 0.09, px * 0.09)
    painter.drawPath(body.simplified())

    if emoji:
        font = QFont()
        font.setPixelSize(int(px * 0.36))
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRectF(0, px * 0.34, px, px * 0.52), Qt.AlignCenter, emoji
        )
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def make_ui_icon(kind: str, size: int = 18, color: str = _INK) -> QIcon:
    """UI 글리프 아이콘 — ←/+/◀▶/■/▢ 등을 또렷한 벡터로."""
    scale = 4
    px = size * scale
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), px * 0.11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    c = px / 2

    if kind == "back":
        p.drawLine(QPointF(px * 0.62, px * 0.24), QPointF(px * 0.34, c))
        p.drawLine(QPointF(px * 0.34, c), QPointF(px * 0.62, px * 0.76))
    elif kind == "plus":
        p.drawLine(QPointF(c, px * 0.22), QPointF(c, px * 0.78))
        p.drawLine(QPointF(px * 0.22, c), QPointF(px * 0.78, c))
    elif kind in ("prev", "next", "play"):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        from PySide6.QtGui import QPolygonF

        if kind == "prev":
            tri = [QPointF(px * 0.64, px * 0.26), QPointF(px * 0.64, px * 0.74),
                   QPointF(px * 0.34, c)]
        else:  # next / play (오른쪽 삼각형)
            tri = [QPointF(px * 0.36, px * 0.24), QPointF(px * 0.36, px * 0.76),
                   QPointF(px * 0.72, c)]
        p.drawPolygon(QPolygonF(tri))
    elif kind == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(px * 0.30, px * 0.30, px * 0.40, px * 0.40),
                          px * 0.06, px * 0.06)
    elif kind == "restore":
        p.drawRoundedRect(QRectF(px * 0.26, px * 0.26, px * 0.48, px * 0.48),
                          px * 0.06, px * 0.06)
    elif kind in ("undo", "redo"):
        if kind == "redo":  # 좌우 반전
            p.translate(px, 0)
            p.scale(-1, 1)
        curve = QPainterPath(QPointF(px * 0.76, px * 0.64))
        curve.cubicTo(
            QPointF(px * 0.80, px * 0.28),
            QPointF(px * 0.30, px * 0.22),
            QPointF(px * 0.27, px * 0.54),
        )
        p.drawPath(curve)
        # 화살촉 (곡선 끝, 아래 방향)
        p.drawLine(QPointF(px * 0.27, px * 0.58), QPointF(px * 0.16, px * 0.48))
        p.drawLine(QPointF(px * 0.27, px * 0.58), QPointF(px * 0.38, px * 0.48))
    elif kind.startswith("dock_"):
        # 패널 위치 아이콘 — 사각 틀 + 해당 변에 두꺼운 막대
        p.drawRoundedRect(QRectF(px * 0.16, px * 0.16, px * 0.68, px * 0.68),
                          px * 0.08, px * 0.08)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        side = kind[5:]
        bar = px * 0.22
        if side == "left":
            p.drawRect(QRectF(px * 0.16, px * 0.16, bar, px * 0.68))
        elif side == "right":
            p.drawRect(QRectF(px * 0.84 - bar, px * 0.16, bar, px * 0.68))
        elif side == "top":
            p.drawRect(QRectF(px * 0.16, px * 0.16, px * 0.68, bar))
        else:  # bottom
            p.drawRect(QRectF(px * 0.16, px * 0.84 - bar, px * 0.68, bar))
    elif kind in ("bookmark", "bookmark_on"):
        ribbon = QPainterPath()
        ribbon.moveTo(px * 0.30, px * 0.16)
        ribbon.lineTo(px * 0.70, px * 0.16)
        ribbon.lineTo(px * 0.70, px * 0.84)
        ribbon.lineTo(px * 0.50, px * 0.66)
        ribbon.lineTo(px * 0.30, px * 0.84)
        ribbon.closeSubpath()
        if kind == "bookmark_on":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
        p.drawPath(ribbon)
    elif kind == "trash":
        p.drawLine(QPointF(px * 0.20, px * 0.30), QPointF(px * 0.80, px * 0.30))  # 뚜껑
        handle = QPainterPath()
        handle.moveTo(px * 0.40, px * 0.30)
        handle.lineTo(px * 0.40, px * 0.19)
        handle.lineTo(px * 0.60, px * 0.19)
        handle.lineTo(px * 0.60, px * 0.30)
        p.drawPath(handle)
        body = QPainterPath()
        body.moveTo(px * 0.27, px * 0.40)
        body.lineTo(px * 0.31, px * 0.80)
        body.lineTo(px * 0.69, px * 0.80)
        body.lineTo(px * 0.73, px * 0.40)
        p.drawPath(body)
        p.drawLine(QPointF(c, px * 0.48), QPointF(c, px * 0.70))

    p.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def make_note_icon(is_pdf: bool = False, size: int = 20) -> QIcon:
    """문서(노트) 아이콘 — 접힌 모서리가 있는 종이. PDF면 붉은 배지."""
    scale = 4
    px = size * scale
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    fold = px * 0.24
    left, top, right, bottom = px * 0.20, px * 0.10, px * 0.80, px * 0.90
    page = QPainterPath()
    page.moveTo(left, top)
    page.lineTo(right - fold, top)
    page.lineTo(right, top + fold)
    page.lineTo(right, bottom)
    page.lineTo(left, bottom)
    page.closeSubpath()
    painter.setPen(QPen(QColor("#c7c7c4"), px * 0.03))
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawPath(page)

    # 접힌 모서리
    corner = QPainterPath()
    corner.moveTo(right - fold, top)
    corner.lineTo(right - fold, top + fold)
    corner.lineTo(right, top + fold)
    corner.closeSubpath()
    painter.setBrush(QBrush(QColor("#e4e4e1")))
    painter.drawPath(corner)

    # 본문 줄
    painter.setPen(QPen(QColor("#b8b8b5"), px * 0.028, Qt.SolidLine, Qt.RoundCap))
    for i, frac in enumerate((0.42, 0.55, 0.68, 0.81)):
        end = right - px * 0.12 if i % 2 == 0 else right - px * 0.28
        painter.drawLine(QPointF(left + px * 0.10, bottom * frac + top * (1 - frac)),
                         QPointF(end, bottom * frac + top * (1 - frac)))

    if is_pdf:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#e2453d")))
        painter.drawRoundedRect(QRectF(px * 0.30, px * 0.60, px * 0.44, px * 0.22),
                                px * 0.04, px * 0.04)
        font = QFont()
        font.setPixelSize(int(px * 0.13))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(px * 0.30, px * 0.60, px * 0.44, px * 0.22),
                         Qt.AlignCenter, "PDF")
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def make_tool_icon(kind: str, size: int = 20) -> QIcon:
    """PDF 도구 버튼 아이콘 — 글자 없이 모양으로."""
    scale = 4
    px = size * scale
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    ink = QPen(QColor(_INK), px * 0.085, Qt.SolidLine, Qt.RoundCap)

    if kind == "underline":
        painter.setPen(ink)
        painter.drawLine(QPointF(px * 0.14, px * 0.72), QPointF(px * 0.86, px * 0.40))
    elif kind == "highlight":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 212, 0, 210))
        painter.drawRoundedRect(
            QRectF(px * 0.10, px * 0.38, px * 0.80, px * 0.30), px * 0.06, px * 0.06
        )
        thin = QPen(QColor("#6f6f6c"), px * 0.05, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(thin)
        painter.drawLine(QPointF(px * 0.16, px * 0.53), QPointF(px * 0.84, px * 0.53))
    elif kind == "rect":
        painter.setPen(ink)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(px * 0.16, px * 0.26, px * 0.68, px * 0.48))
    elif kind == "ellipse":
        painter.setPen(ink)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(px * 0.14, px * 0.26, px * 0.72, px * 0.48))
    elif kind == "eraser":
        painter.save()
        painter.translate(px * 0.5, px * 0.55)
        painter.rotate(-35)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e58f8f"))
        painter.drawRoundedRect(
            QRectF(-px * 0.30, -px * 0.16, px * 0.60, px * 0.32), px * 0.06, px * 0.06
        )
        painter.setBrush(QColor(_INK))
        painter.drawRoundedRect(
            QRectF(-px * 0.30, -px * 0.16, px * 0.24, px * 0.32), px * 0.06, px * 0.06
        )
        painter.restore()
    elif kind in ("fit_width", "fit_height"):
        painter.setPen(ink)
        if kind == "fit_height":
            painter.translate(px * 0.5, px * 0.5)
            painter.rotate(90)
            painter.translate(-px * 0.5, -px * 0.5)
        # |←→| : 두 경계선 사이 양방향 화살표
        painter.drawLine(QPointF(px * 0.12, px * 0.22), QPointF(px * 0.12, px * 0.78))
        painter.drawLine(QPointF(px * 0.88, px * 0.22), QPointF(px * 0.88, px * 0.78))
        painter.drawLine(QPointF(px * 0.24, px * 0.50), QPointF(px * 0.76, px * 0.50))
        painter.drawLine(QPointF(px * 0.24, px * 0.50), QPointF(px * 0.36, px * 0.38))
        painter.drawLine(QPointF(px * 0.24, px * 0.50), QPointF(px * 0.36, px * 0.62))
        painter.drawLine(QPointF(px * 0.76, px * 0.50), QPointF(px * 0.64, px * 0.38))
        painter.drawLine(QPointF(px * 0.76, px * 0.50), QPointF(px * 0.64, px * 0.62))

    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)
