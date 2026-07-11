"""pip로 설치한 NVIDIA cuBLAS/cuDNN DLL을 ctranslate2가 찾을 수 있게 등록.

ctranslate2를 import 하기 전에 호출해야 한다.
패키징(exe)에서는 PyInstaller가 수집한 _internal/nvidia/ 폴더를 찾는다.
"""
import os
from pathlib import Path


def register_cuda_dlls() -> None:
    roots: list[Path] = []
    try:
        import nvidia

        roots += [Path(p) for p in nvidia.__path__]
    except ImportError:
        pass
    from .paths import resource_root

    roots.append(resource_root() / "nvidia")

    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for pkg_dir in root.iterdir():
            bin_dir = pkg_dir / "bin"
            key = str(bin_dir).lower()
            if bin_dir.is_dir() and key not in seen:
                seen.add(key)
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
