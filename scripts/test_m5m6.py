"""M5/M6 단위 테스트 — MD 내보내기, DB 쿼리, 녹음 트랙 시계 정렬."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

import numpy as np
import soundfile as sf

from app.audio.recorder import RECORD_RATE, _TrackWriter
from app.core.clock import SessionClock
from app.core.models import AudioSource, TranscriptSegment
from app.store.db import SessionStore
from app.store.export import export_markdown

tmp = Path(tempfile.mkdtemp())


def test_export() -> None:
    doc = json.dumps({
        "blocks": [
            {"id": "b1", "type": "header", "data": {"level": 2, "text": "가상 <b>메모리</b>"}},
            {"id": "b2", "type": "paragraph", "data": {"text": "페이징은 <code class=\"inline-code\">frame</code> 단위"}},
            {"id": "b3", "type": "list", "data": {"style": "ordered", "items": [
                {"content": "TLB는 캐시", "items": []},
                {"content": "미스 나면 페이지 테이블", "items": []},
            ]}},
            {"id": "b4", "type": "checklist", "data": {"items": [
                {"text": "복습하기", "checked": True},
            ]}},
            {"id": "b5", "type": "quote", "data": {"text": "시험에 나옵니다", "caption": "🔊 00:42"}},
            {"id": "b6", "type": "code", "data": {"code": "malloc(4096);"}},
            {"id": "b7", "type": "toggle", "data": {"text": "심화 내용", "status": "open"}},
            {"id": "b8", "type": "image", "data": {"file": {"url": "file:///img.png"}, "caption": "TLB 구조"}},
            {"id": "b9", "type": "paragraph", "data": {"text": "이건 <mark class=\"cdx-marker\">시험 범위</mark>다"}},
        ]
    })
    segs = [TranscriptSegment(AudioSource.SYSTEM, "시험에 나옵니다", 42000, 44000)]
    md = export_markdown(
        "운영체제 7주차", [(0, "노트", doc)], {"b1": 30000, "b5": 42000}, segs
    )
    for expected in [
        "# 운영체제 7주차",
        "`[00:30]`\n## 가상 **메모리**",
        "페이징은 `frame` 단위",
        "1. TLB는 캐시",
        "2. 미스 나면",
        "- [x] 복습하기",
        "> 시험에 나옵니다\n> — 🔊 00:42",
        "```\nmalloc(4096);\n```",
        "**▸ 심화 내용**",
        "![TLB 구조](file:///img.png)",
        "이건 ==시험 범위==다",
        "## 자막 기록",
        "- `[00:42]` (재생) 시험에 나옵니다",
    ]:
        assert expected in md, f"누락: {expected!r}\n---\n{md}"
    print("export: OK")


def test_db() -> None:
    store = SessionStore(tmp / "t.db")
    s1 = store.create_session("운영체제 7주차")
    s2 = store.create_session("자료구조 3주차")
    store.add_segment(s1, TranscriptSegment(AudioSource.SYSTEM, "TLB 캐시", 1000, 2000))
    store.add_segment(s1, TranscriptSegment(AudioSource.MIC, "질문 있어요", 3000, 4000))

    sessions = store.list_sessions()
    assert [row[0] for row in sessions] == [s2, s1]          # 최신순
    assert sessions[1][3] == 2                               # s1 자막 수
    assert [row[0] for row in store.list_sessions("TLB")] == [s1]   # 자막 검색
    assert [row[0] for row in store.list_sessions("자료구조")] == [s2]  # 제목 검색
    assert store.list_sessions("없는말") == []

    segs = store.get_segments(s1)
    assert len(segs) == 2 and segs[0].text == "TLB 캐시" and segs[0].source == AudioSource.SYSTEM

    store.rename_session(s1, "운영체제 7주차 (기말범위)")
    assert store.get_session(s1)[1] == "운영체제 7주차 (기말범위)"

    # 폴더
    f1 = store.create_folder("전공", "#2383e2", "💻")
    store.set_session_folder(s1, f1)
    assert [r[0] for r in store.list_sessions(folder_id=f1)] == [s1]
    assert len(store.list_sessions()) == 2          # 전체 보기는 그대로
    store.delete_folder(f1)
    assert store.list_sessions(folder_id=f1) == []
    assert len(store.list_sessions()) == 2          # 세션은 유지

    # 페이지 (중첩)
    root_id, root_title = store.root_page(s1)       # 기본 루트 자동 생성
    assert root_title == "노트"
    child = store.create_page(s1, "요약", parent_page_id=root_id)
    grandchild = store.create_page(s1, "심화", parent_page_id=child)
    store.save_page_doc(child, '{"blocks":[]}')
    assert store.load_page_doc(child) == '{"blocks":[]}'
    store.rename_page(child, "시험 대비")
    assert store.get_page(child)[1] == "시험 대비"
    assert store.get_page(grandchild)[2] == child   # 부모 관계
    assert [c[0] for c in store.child_pages(root_id)] == [child]
    store.stamp_block(s1, "blk1", 1000, page_id=child)
    assert store.block_times_for_page(s1, child) == {"blk1": 1000}
    assert store.block_times_for_page(s1, root_id) == {}
    tree = store.pages_tree(s1)                      # 깊이 우선
    assert [(d, t) for d, t, _ in tree] == [(0, "노트"), (1, "시험 대비"), (2, "심화")]
    store.close()
    print("db: OK (folders/nested pages 포함)")


def test_track_writer_alignment() -> None:
    """캡처 공백이 무음으로 채워져 '파일 위치 = 세션 시간'이 유지되는가."""
    clock = SessionClock()
    path = tmp / "track.ogg"
    writer = _TrackWriter(path, clock)
    tone = (np.sin(np.linspace(0, 200 * np.pi, RECORD_RATE // 5)) * 8000).astype(np.int16)

    writer.feed(tone, RECORD_RATE)      # 0.2초 분량
    time.sleep(1.2)                     # 1초 이상 캡처 공백
    writer.feed(tone, RECORD_RATE)
    elapsed_at_close = clock.now_ms()
    writer.close()

    info = sf.info(str(path))
    file_ms = info.frames * 1000 / info.samplerate
    # 파일 길이가 세션 경과 시간과 대략 일치해야 함 (공백이 채워졌다는 뜻)
    assert abs(file_ms - elapsed_at_close) < 600, (file_ms, elapsed_at_close)
    # 뒷부분에 실제 소리(무음이 아닌 샘플)가 존재해야 함
    data, _ = sf.read(str(path), dtype="int16")
    assert np.abs(data[-len(tone):]).max() > 500
    print(f"track writer: OK (파일 {file_ms:.0f}ms ≈ 세션 {elapsed_at_close}ms)")


def test_resume_appends() -> None:
    """이어서 녹음: 기존 오디오 보존 + 오프셋 시계 기준 정렬."""
    from app.audio.player import MixPlayer

    assert SessionClock(offset_ms=60000).now_ms() >= 60000

    tone = (np.sin(np.linspace(0, 200 * np.pi, RECORD_RATE // 5)) * 8000).astype(np.int16)
    path = tmp / "resume.ogg"

    first = _TrackWriter(path, SessionClock())
    first.feed(tone, RECORD_RATE)
    first.close()
    frames_before = sf.info(str(path)).frames

    # 5초 지점부터 이어서 녹음
    second = _TrackWriter(path, SessionClock(offset_ms=5000), resume=True)
    second.feed(tone, RECORD_RATE)
    second.close()

    info = sf.info(str(path))
    total_ms = info.frames * 1000 / info.samplerate
    assert info.frames > frames_before                    # 뒤에 덧붙었음
    assert 4700 < total_ms < 6000, total_ms               # 5초 오프셋 정렬
    data, _ = sf.read(str(path), dtype="int16")
    assert np.abs(data[: len(tone)]).max() > 500          # 기존 녹음 보존
    assert np.abs(data[-len(tone):]).max() > 500          # 새 녹음 존재
    assert not path.with_name(path.stem + ".prev.ogg").exists()  # 임시본 정리됨
    assert MixPlayer.total_ms([path]) == int(total_ms)


if __name__ == "__main__":
    test_export()
    test_db()
    test_track_writer_alignment()
    test_resume_appends()
    print("M5/M6 tests: all OK")
