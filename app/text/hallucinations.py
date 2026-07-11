"""Whisper 무음 환각 + 무의미 감탄사 필터 — SegmentTransform 구현체.

- 환각: Whisper가 무음·잡음에서 지어내는 학습데이터 문구. 전체 일치만 버린다.
- 감탄사: "어", "음" 같은 의미 없는 채움말은 버리고, "네"·"아니요" 같은
  실제 답변은 남긴다. (세그먼트 전체가 감탄사(들)로만 이뤄졌을 때만)
"""
import re

from ..core.models import TranscriptSegment

_KNOWN_HALLUCINATIONS = {
    "시청해주셔서 감사합니다",
    "시청해 주셔서 감사합니다",
    "구독과 좋아요 부탁드립니다",
    "구독과 좋아요 눌러주세요",
    "다음 영상에서 만나요",
    "MBC 뉴스 이덕영입니다",
    "감사합니다. 시청해주셔서 감사합니다",
}

# 의미 없는 채움말(감탄사) — 세그먼트가 이것들로만 이뤄지면 버린다.
# "네·아니요·응·예" 같은 실제 답변은 포함하지 않는다 (남긴다).
_FILLERS = {
    "어", "음", "으", "아", "에", "그", "저", "뭐", "이", "오",
    "어어", "음음", "그그", "에에", "아아", "으음", "어음", "흠", "허",
}


class HallucinationFilter:
    def apply(self, segment: TranscriptSegment) -> TranscriptSegment | None:
        text = segment.text.strip()
        normalized = text.rstrip(".!?~ ").strip()
        if normalized in _KNOWN_HALLUCINATIONS:
            return None
        if self._is_only_fillers(normalized):
            return None
        return segment

    @staticmethod
    def _is_only_fillers(text: str) -> bool:
        """구두점·공백을 뺀 토큰이 전부 채움말이면 True."""
        tokens = [t for t in re.split(r"[\s,./!?~…·]+", text) if t]
        if not tokens:
            return False
        return all(t in _FILLERS for t in tokens)
