"""세션 오디오 내보내기.

마이크·시스템 트랙은 세션 시계에 맞춰 각각 저장된다. 이 모듈은 그
트랙들을 같은 프레임끼리 합쳐, 앱 밖에서 바로 들을 수 있는 MP3 또는
OGG 하나로 만든다. 캡처/재생/UI와 분리해 파일 변환 책임만 맡는다.
"""
from pathlib import Path
import shutil
import tempfile

import numpy as np
import soundfile as sf


class AudioExportError(Exception):
    """세션 오디오를 내보낼 수 없을 때 발생한다."""


def export_session_audio(source_paths: list[Path], target_path: Path) -> Path:
    """존재하는 소스 트랙을 MP3/OGG 하나로 내보내고 최종 경로를 반환한다.

    OGG 트랙이 하나뿐이고 OGG로 내보내면 원본을 그대로 복사한다. 그 외에는
    세션 타임라인상 같은 프레임을 더하고 int16 범위로 제한해 인코딩한다.
    """
    candidates = [Path(path) for path in source_paths if Path(path).is_file()]
    if not candidates:
        raise AudioExportError("내보낼 녹음이 없습니다.")

    target = Path(target_path)
    extension = target.suffix.lower()
    if extension not in {".mp3", ".ogg"}:
        raise AudioExportError("MP3 또는 OGG 파일로만 내보낼 수 있습니다.")
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    if any(path.resolve() == resolved_target for path in candidates):
        raise AudioExportError("앱이 보관 중인 원본 녹음에는 덮어쓸 수 없습니다.")

    sources = []
    for path in candidates:
        try:
            if sf.info(str(path)).frames > 0:
                sources.append(path)
        except Exception as exc:
            raise AudioExportError(f"녹음 파일을 읽을 수 없습니다: {path.name}") from exc
    if not sources:
        raise AudioExportError("내보낼 녹음이 비어 있습니다.")

    handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-", suffix=extension, dir=target.parent, delete=False
    )
    temp_path = Path(handle.name)
    handle.close()

    try:
        if len(sources) == 1 and extension == ".ogg":
            shutil.copyfile(sources[0], temp_path)
        else:
            _mix_tracks(sources, temp_path, extension)
        temp_path.replace(target)
    except AudioExportError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise AudioExportError(f"음성 파일을 만들지 못했습니다: {exc}") from exc
    return target


def _mix_tracks(source_paths: list[Path], target_path: Path, extension: str) -> None:
    files: list[sf.SoundFile] = []
    try:
        files = [sf.SoundFile(str(path)) for path in source_paths]
        if not files or max(file.frames for file in files) == 0:
            raise AudioExportError("내보낼 녹음이 비어 있습니다.")

        sample_rate = files[0].samplerate
        if any(file.channels != 1 for file in files):
            raise AudioExportError("모노 녹음 트랙만 내보낼 수 있습니다.")
        if any(file.samplerate != sample_rate for file in files):
            raise AudioExportError("녹음 트랙의 샘플레이트가 서로 다릅니다.")

        output_format, output_subtype = (
            ("MP3", "MPEG_LAYER_III") if extension == ".mp3"
            else ("OGG", "VORBIS")
        )
        with sf.SoundFile(
            str(target_path), mode="w", samplerate=sample_rate, channels=1,
            format=output_format, subtype=output_subtype,
        ) as output:
            while True:
                blocks = [file.read(65536, dtype="int16") for file in files]
                length = max((len(block) for block in blocks), default=0)
                if length == 0:
                    break
                mixed = np.zeros(length, dtype=np.int32)
                for block in blocks:
                    mixed[: len(block)] += block.astype(np.int32)
                output.write(np.clip(mixed, -32768, 32767).astype(np.int16))
    finally:
        for file in files:
            file.close()
