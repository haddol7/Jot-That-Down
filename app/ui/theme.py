"""테마 토큰과 QSS 생성 — 노션의 웜 그레이 팔레트 기반.

레퍼런스: 본문 #37352F, 보조 #787774→#9B9A97, 종이색 #F7F6F3,
액센트 #2383E2, 다크 #191919/#202020. 웹 에디터(editor.css)의
CSS 변수와 같은 값을 쓴다 — 한쪽을 바꾸면 양쪽을 맞출 것.
"""

TOKENS = {
    "light": {
        "bg": "#ffffff",
        "surface": "#f7f6f3",     # 툴바·상태바 — 노션 종이색
        "text": "#37352f",
        "muted": "#787774",
        "faint": "#9b9a97",
        "border": "#e9e9e7",
        "hover": "#f1f1ef",
        "selection": "rgba(35, 131, 226, 0.15)",
        "accent": "#2383e2",
        "accent_hover": "#1b74c4",
        "playing_bg": "#fbf3db",   # 재생 중 자막 행 파스텔 배경
        "tooltip_bg": "#37352f",
        "tooltip_text": "#ffffff",
    },
    "dark": {
        "bg": "#191919",
        "surface": "#202020",
        "text": "#e8e8e6",
        "muted": "#9b9b98",
        "faint": "#6f6f6c",
        "border": "#2e2e2c",
        "hover": "#252525",
        "selection": "rgba(35, 131, 226, 0.30)",
        "accent": "#2383e2",
        "accent_hover": "#4a9aea",
        "playing_bg": "#39331f",   # 재생 중 자막 행 파스텔 배경 (다크)
        "tooltip_bg": "#e8e8e6",
        "tooltip_text": "#191919",
    },
}

_FONT_STACK = '"NanumSquare Neo", "NanumSquare", "Malgun Gothic", "Segoe UI", sans-serif'


def build_qss(theme: str) -> str:
    t = TOKENS.get(theme, TOKENS["light"])
    return f"""
QWidget {{
    color: {t['text']};
    font-family: {_FONT_STACK};
    font-size: 13px;
}}
QMainWindow, QDialog, QStackedWidget, QMessageBox,
#homePage, #sessionPage {{
    background: {t['bg']};
}}

QToolBar {{
    background: {t['surface']};
    border: none;
    border-bottom: 1px solid {t['border']};
    padding: 5px 8px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    color: {t['muted']};
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 600;
}}
QToolBar QToolButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
QToolBar QToolButton:checked {{ background: {t['selection']}; color: {t['accent']}; }}

QPushButton {{
    background: {t['bg']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton[cssClass="primary"] {{
    background: {t['accent']};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 700;
}}
QPushButton[cssClass="primary"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[cssClass="ghost"] {{
    background: transparent;
    border: none;
    color: {t['faint']};
    border-radius: 5px;
    padding: 2px 7px;
}}
QPushButton[cssClass="ghost"]:hover {{ background: {t['hover']}; color: {t['accent']}; }}

QLineEdit {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {t['selection']};
    selection-color: {t['text']};
}}
QLineEdit:focus {{ border: 1px solid {t['accent']}; }}

QComboBox {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 5px 10px;
}}
QComboBox:hover {{ background: {t['hover']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    selection-background-color: {t['hover']};
    selection-color: {t['text']};
    outline: none;
}}

QSpinBox, QDoubleSpinBox {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 5px 10px;
    selection-background-color: {t['selection']};
    selection-color: {t['text']};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {t['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 18px;
}}

/* 다이얼로그 하단 버튼(Save/Cancel 등) — 기본 네이티브 흰색 방지 */
QDialogButtonBox QPushButton {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 5px 18px;
    color: {t['text']};
}}
QDialogButtonBox QPushButton:hover {{ background: {t['hover']}; }}
QDialogButtonBox QPushButton:default {{
    border-color: {t['accent']}; color: {t['accent']}; font-weight: 700;
}}

QListWidget {{ background: {t['bg']}; border: none; outline: none; }}
QListWidget::item {{ border-radius: 8px; margin: 1px 6px; }}
QListWidget::item:hover {{ background: {t['hover']}; }}
QListWidget::item:selected {{ background: {t['selection']}; color: {t['text']}; }}

QScrollBar {{ border: none; background: transparent; }}
QScrollBar:vertical {{ width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {t['border']}; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {t['border']}; border-radius: 4px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t['faint']}; }}

QStatusBar {{
    background: {t['surface']};
    border-top: 1px solid {t['border']};
    color: {t['muted']};
}}
QStatusBar::item {{ border: none; }}  /* 위젯마다 그려지는 세로 구분선(|) 제거 */
QStatusBar QLabel {{ color: {t['muted']}; }}
QProgressBar {{
    border: none; background: {t['hover']}; border-radius: 2px;
    max-height: 4px; text-align: center;
}}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 2px; }}

QSplitter::handle {{ background: {t['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QSlider::groove:horizontal {{
    height: 4px; background: {t['hover']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 12px; height: 12px; margin: -4px 0;
    border-radius: 6px; background: {t['accent']};
}}
QSlider::handle:horizontal:hover {{ background: {t['accent_hover']}; }}

QTableWidget {{
    background: {t['bg']};
    color: {t['text']};
    gridline-color: {t['border']};
    border: 1px solid {t['border']};
    border-radius: 6px;
}}
QTableWidget::item {{ color: {t['text']}; }}
QTableWidget QLineEdit {{ background: {t['bg']}; color: {t['text']}; }}
QHeaderView {{ background: {t['surface']}; }}
QHeaderView::section {{
    background: {t['surface']};
    color: {t['muted']};
    border: none;
    border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border']};
    padding: 6px 8px;
}}
QTableCornerButton::section {{
    background: {t['surface']};
    border: none;
    border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border']};
}}

QMenu {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['hover']}; }}

QToolTip {{
    background: {t['tooltip_bg']};
    color: {t['tooltip_text']};
    border: none;
    padding: 5px 9px;
}}

QLabel[cssClass="pageTitle"] {{ font-size: 26px; font-weight: 800; }}
QLabel[cssClass="subtitle"] {{ color: {t['muted']}; font-size: 13px; }}
QLabel[cssClass="sectionLabel"] {{
    color: {t['faint']}; font-size: 12px; font-weight: 700;
}}
QLabel[cssClass="rowTitle"] {{ font-size: 14px; font-weight: 600; }}
QLabel[cssClass="rowMeta"] {{ color: {t['faint']}; font-size: 12px; }}
QLabel[cssClass="stamp"] {{ color: {t['faint']}; font-size: 11px; }}
QWidget[cssClass="playingRow"] {{ background: {t['playing_bg']}; border-radius: 8px; }}

#framelessDialog {{
    background: {t['bg']};
    border: 1px solid {t['border']};
}}
QLabel[cssClass="dialogTitle"] {{ font-size: 15px; font-weight: 700; }}

#stylePopover {{
    background: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}

#pageTabBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
#recordBar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
QPushButton[cssClass="danger"] {{
    background: transparent; border: 1px solid {t['border']};
    border-radius: 6px; padding: 4px 12px; color: #e25757; font-weight: 700;
}}
QPushButton[cssClass="danger"]:hover {{ background: rgba(226, 87, 87, 0.14); }}

QLabel[cssClass="recElapsed"] {{ color: #e25757; font-weight: 700; font-size: 12px; }}
QLabel[cssClass="debugInfo"] {{ color: {t['faint']}; font-size: 11px; }}
QLabel[cssClass="recElapsed"][recState="loading"] {{ color: {t['accent']}; }}

QPushButton[cssClass="sourceToggle"] {{
    border: 1px solid {t['border']}; border-radius: 6px;
    padding: 4px 10px; text-align: left;
}}
QPushButton[cssClass="sourceToggle"][srcState="off"] {{
    background: {t['hover']}; color: {t['faint']};
}}
QPushButton[cssClass="sourceToggle"][srcState="on"] {{
    background: {t['selection']}; border-color: {t['accent']};
    color: {t['accent']}; font-weight: 700;
}}
QPushButton[cssClass="sourceToggle"][srcState="listening"] {{
    background: rgba(64, 180, 90, 0.20); border-color: #40b45a;
    color: #2f9e4a; font-weight: 700;
}}
QPushButton[cssClass="toolBtn"] {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 4px 10px;
}}
QPushButton[cssClass="toolBtn"]:hover {{ background: {t['hover']}; }}
QPushButton[cssClass="toolBtn"]:checked {{
    background: {t['selection']}; border-color: {t['accent']};
}}
QPushButton[cssClass="pageTab"] {{
    background: transparent; border: none; border-radius: 6px;
    padding: 3px 12px; color: {t['muted']};
}}
QPushButton[cssClass="pageTab"]:hover {{ background: {t['hover']}; }}
QPushButton[cssClass="pageTab"]:checked {{
    background: {t['hover']}; color: {t['text']}; font-weight: 700;
}}

QPushButton[cssClass="folderChip"] {{
    background: transparent; border: 1px solid {t['border']};
    border-radius: 14px; padding: 4px 12px; color: {t['muted']};
}}
QPushButton[cssClass="folderChip"]:hover {{ background: {t['hover']}; }}
QPushButton[cssClass="folderChip"]:checked {{
    background: {t['selection']}; color: {t['text']};
    border-color: transparent; font-weight: 600;
}}
QLabel[cssClass="segMic"] {{ color: {t['accent']}; }}
QLabel[cssClass="segSys"] {{ color: {t['text']}; }}
QLabel[cssClass="pendingBanner"] {{
    color: {t['accent']}; font-size: 12px; font-weight: 600;
    padding: 2px 14px 8px;
}}
"""
