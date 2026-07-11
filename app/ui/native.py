"""Windows 네이티브 창 꾸미기 — 타이틀바 색을 테마와 맞춘다 (DWM, Win11).

theme.py의 surface/text 토큰과 같은 색. COLORREF는 0x00BBGGRR 순서.
"""
import ctypes
import sys

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

# theme.py TOKENS의 surface / text 를 COLORREF(BGR)로 변환한 값
_TITLEBAR = {
    "light": {"caption": 0x00F3F6F7, "text": 0x002F3537},
    "dark": {"caption": 0x00202020, "text": 0x00E6E8E8},
}


def style_titlebar(widget, theme: str) -> None:
    if sys.platform != "win32":
        return
    colors = _TITLEBAR.get(theme, _TITLEBAR["light"])
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if theme == "dark" else 0)
        dwm.DwmSetWindowAttribute(
            hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark), 4
        )
        for attr, value in (
            (_DWMWA_CAPTION_COLOR, colors["caption"]),
            (_DWMWA_TEXT_COLOR, colors["text"]),
        ):
            color = ctypes.c_uint(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(color), 4)
    except Exception:
        pass  # 구버전 Windows 등 — 타이틀바 색은 장식이므로 조용히 넘어간다
