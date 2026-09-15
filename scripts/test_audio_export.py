"""세션 음성 내보내기 스모크 테스트."""
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audio.exporter import AudioExportError, export_session_audio


def _write_ogg(path: Path, samples: np.ndarray, rate: int = 16000) -> None:
    sf.write(str(path), samples, rate, format="OGG", subtype="VORBIS")


def test_single_track_is_exported_to_mp3() -> None:
    root = Path(tempfile.mkdtemp())
    source = root / "1_mic.ogg"
    target = root / "lecture.mp3"
    tone = (np.sin(np.linspace(0, 20 * np.pi, 3200)) * 5000).astype(np.int16)
    _write_ogg(source, tone)

    assert export_session_audio([source], target) == target
    exported, rate = sf.read(str(target), dtype="int16")
    assert sf.info(str(target)).format == "MP3"
    assert rate == 16000
    assert len(exported) == len(tone)
    assert np.max(np.abs(exported)) > 1000


def test_tracks_are_mixed_on_the_session_timeline() -> None:
    root = Path(tempfile.mkdtemp())
    mic = root / "2_mic.ogg"
    system = root / "2_system.ogg"
    target = root / "mixed.mp3"
    tone = (np.sin(np.linspace(0, 40 * np.pi, 6400)) * 4000).astype(np.int16)
    _write_ogg(mic, tone)
    _write_ogg(system, tone[:3200])

    export_session_audio([mic, system], target)
    mixed, rate = sf.read(str(target), dtype="int16")
    mic_decoded, _ = sf.read(str(mic), dtype="int16")

    assert rate == 16000
    assert len(mixed) == len(tone)
    assert np.max(np.abs(mixed[:3000])) > np.max(np.abs(mic_decoded[:3000])) * 1.5
    assert np.max(np.abs(mixed[4000:])) > 1000


def test_missing_audio_is_rejected() -> None:
    root = Path(tempfile.mkdtemp())
    try:
        export_session_audio([root / "missing.ogg"], root / "out.ogg")
    except AudioExportError as exc:
        assert "없습니다" in str(exc)
    else:
        raise AssertionError("빈 세션이 내보내졌습니다.")


def test_empty_audio_is_rejected() -> None:
    root = Path(tempfile.mkdtemp())
    source = root / "empty.ogg"
    _write_ogg(source, np.array([], dtype=np.int16))
    try:
        export_session_audio([source], root / "out.ogg")
    except AudioExportError as exc:
        assert "비어" in str(exc)
    else:
        raise AssertionError("빈 녹음 파일이 내보내졌습니다.")


if __name__ == "__main__":
    test_single_track_is_exported_to_mp3()
    test_tracks_are_mixed_on_the_session_timeline()
    test_missing_audio_is_rejected()
    test_empty_audio_is_rejected()
    print("audio export: all OK")
