# -*- mode: python ; coding: utf-8 -*-
"""JotThatDown 패키징 스펙 (PyInstaller onedir).

빌드:  .venv\\Scripts\\python.exe -m PyInstaller packaging\\JotThatDown.spec --noconfirm
산출:  dist\\JotThatDown\\JotThatDown.exe
- web/ 에디터 번들, faster-whisper 자산(Silero ONNX) 포함
- GPU용 cuBLAS/cuDNN DLL(pip nvidia 패키지)을 함께 동봉
- Whisper 모델은 포함하지 않음 — 첫 실행 때 자동 다운로드
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent

datas = [(str(root / "web"), "web"), (str(root / "assets" / "fonts"), "assets/fonts")]
datas += collect_data_files("faster_whisper")

# NVIDIA cuBLAS/cuDNN — datas로 nvidia/<pkg>/bin 구조 그대로 한 벌만 포함
# (binaries로 넣으면 루트에 복제되어 1GB 중복이 생긴다)
# app/cuda_dlls.py가 _internal/nvidia/*/bin 을 DLL 검색 경로로 등록한다.
try:
    import nvidia

    for ns_path in nvidia.__path__:
        for bin_dir in Path(ns_path).glob("*/bin"):
            package = bin_dir.parent.name
            for dll in bin_dir.glob("*.dll"):
                datas.append((str(dll), f"nvidia/{package}/bin"))
except ImportError:
    pass

binaries = []

a = Analysis(
    [str(root / "run_app.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JotThatDown",
    icon=str(root / "assets" / "app.ico"),
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="JotThatDown",
)
