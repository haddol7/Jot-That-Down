"""교정 사전(FileBackedCorrections)과 TransformingSink 단위 테스트."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import AudioSource, TranscriptSegment
from app.sinks.transforming import TransformingSink
from app.text.corrections import FileBackedCorrections, parse_rules


def main() -> None:
    # 1) 파싱: 주석/빈 줄/형식 오류 무시, 긴 패턴 우선 정렬
    rules = parse_rules("# c\n\n노선 -> 노션\n노선 앱 -> 노션 앱\nbad line\n")
    assert rules == [("노선 앱", "노션 앱"), ("노선", "노션")], rules

    # 2) 파일 기반 치환 + 교정 없으면 동일 객체 반환
    d = Path(tempfile.mkdtemp())
    f = d / "corr.txt"
    f.write_text("노선 앱 -> 노션 앱\n큐버네티스 -> 쿠버네티스\n", encoding="utf-8")
    c = FileBackedCorrections(f)
    seg = TranscriptSegment(AudioSource.MIC, "노선 앱에 큐버네티스 정리했어", 0, 1000)
    out = c.apply(seg)
    assert out.text == "노션 앱에 쿠버네티스 정리했어", out.text
    assert out.t_start_ms == 0 and out.source == AudioSource.MIC
    same = TranscriptSegment(AudioSource.MIC, "교정할 것 없음", 0, 1)
    assert c.apply(same) is same

    # 3) 실행 중 파일 수정 → 재로딩
    time.sleep(0.05)
    f.write_text("다 있소 -> 다이소\n", encoding="utf-8")
    out2 = c.apply(TranscriptSegment(AudioSource.MIC, "다 있소에서 샀어", 0, 1))
    assert out2.text == "다이소에서 샀어", out2.text

    # 4) TransformingSink 체인 통과
    received: list[str] = []

    class Probe:
        def on_segment(self, s: TranscriptSegment) -> None:
            received.append(s.text)

    TransformingSink([c], [Probe()]).on_segment(
        TranscriptSegment(AudioSource.MIC, "다 있소 최고", 0, 1)
    )
    assert received == ["다이소 최고"], received

    # 5) 파일 삭제 시 규칙 비움 (크래시 없음)
    f.unlink()
    assert c.apply(same) is same

    print("corrections: 5/5 tests OK")


if __name__ == "__main__":
    main()
