"""교정 사전 — 자주 틀리는 인식 결과를 결정적으로 치환한다.

SegmentTransform 포트 구현체. 규칙 파일은 앱 실행 중에 수정해도
다음 세그먼트부터 즉시 반영된다 (mtime 감지 재로딩).
M6에서 이 파일을 편집하는 UI가 붙는다.
"""
from dataclasses import replace
from pathlib import Path

from ..core.models import TranscriptSegment

Rule = tuple[str, str]  # (잘못 인식된 표현, 올바른 표현)


def parse_rules(content: str) -> list[Rule]:
    """"잘못된 표현 -> 올바른 표현" 형식의 줄들을 규칙 목록으로 변환."""
    rules: list[Rule] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "->" not in line:
            continue
        wrong, _, right = line.partition("->")
        wrong, right = wrong.strip(), right.strip()
        if wrong:
            rules.append((wrong, right))
    # 긴 패턴을 먼저 적용해 부분 문자열 규칙이 가로채는 것을 방지
    rules.sort(key=lambda rule: len(rule[0]), reverse=True)
    return rules


class FileBackedCorrections:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float | None = None
        self._rules: list[Rule] = []

    def apply(self, segment: TranscriptSegment) -> TranscriptSegment:
        self._reload_if_changed()
        text = segment.text
        for wrong, right in self._rules:
            text = text.replace(wrong, right)
        if text == segment.text:
            return segment
        return replace(segment, text=text)

    def _reload_if_changed(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            self._mtime, self._rules = None, []
            return
        if mtime != self._mtime:
            self._mtime = mtime
            self._rules = parse_rules(self._path.read_text(encoding="utf-8"))
