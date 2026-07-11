"""마크다운 내보내기 — Editor.js 문서 + 블록 타임스탬프 + 자막 기록.

데이터가 앱 형식에 갇히지 않게 하는 출구. 타임스탬프는 `[14:23]`
형태로 블록 앞에 붙는다.
"""
import html
import json
import re

from ..core.clock import format_ms
from ..core.models import AudioSource, TranscriptSegment

_SOURCE_LABEL = {AudioSource.MIC: "말함", AudioSource.SYSTEM: "재생"}


def _inline(text: str) -> str:
    """Editor.js 인라인 HTML → 마크다운."""
    text = re.sub(r"</?b>|</?strong>", "**", text)
    text = re.sub(r"</?i>|</?em>", "*", text)
    text = re.sub(r'<code[^>]*>|</code>', "`", text)
    text = re.sub(r"<mark[^>]*>(.*?)</mark>", r"==\1==", text)  # 형광펜
    text = re.sub(r'<a href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)  # 나머지 태그 제거
    return html.unescape(text)


def _list_items(items: list, ordered: bool, checked_style: bool, depth: int = 0) -> list[str]:
    lines = []
    for i, item in enumerate(items, start=1):
        content = _inline(item.get("content", item.get("text", "")))
        indent = "    " * depth
        if checked_style or (item.get("meta") or {}).get("checked") is not None:
            mark = "x" if (item.get("meta") or {}).get("checked") or item.get("checked") else " "
            lines.append(f"{indent}- [{mark}] {content}")
        elif ordered:
            lines.append(f"{indent}{i}. {content}")
        else:
            lines.append(f"{indent}- {content}")
        if item.get("items"):
            lines.extend(_list_items(item["items"], ordered, checked_style, depth + 1))
    return lines


def _block_to_md(block: dict) -> str:
    kind, data = block.get("type"), block.get("data", {})
    if kind == "header":
        return "#" * int(data.get("level", 2)) + " " + _inline(data.get("text", ""))
    if kind == "list":
        ordered = data.get("style") == "ordered"
        checklist = data.get("style") == "checklist"
        return "\n".join(_list_items(data.get("items", []), ordered, checklist))
    if kind == "checklist":
        return "\n".join(_list_items(data.get("items", []), False, True))
    if kind == "quote":
        quote = "> " + _inline(data.get("text", "")).replace("\n", "\n> ")
        caption = _inline(data.get("caption", ""))
        return f"{quote}\n> — {caption}" if caption else quote
    if kind == "code":
        return "```\n" + data.get("code", "") + "\n```"
    if kind == "image":
        url = (data.get("file") or {}).get("url", "")
        return f"![{_inline(data.get('caption', ''))}]({url})"
    if kind == "toggle":
        # 토글의 자식 블록들은 별도 블록으로 이어서 내보내진다
        return f"**▸ {_inline(data.get('text', ''))}**"
    if kind == "pageLink":
        # 하위 페이지 본문은 트리 순회로 뒤에 이어진다 — 여기는 참조만
        return f"\U0001F4C4 **{data.get('title', '페이지')}** (하위 페이지)"
    return _inline(data.get("text", ""))  # paragraph 및 기타


def export_markdown(
    title: str,
    pages: list[tuple],  # (깊이, 페이지 제목, doc_json) — 루트부터 깊이 우선
    block_times: dict[str, int],
    segments: list[TranscriptSegment],
) -> str:
    lines = [f"# {title}", ""]

    multi_page = len(pages) > 1
    for depth, page_title, doc_json in pages:
        if multi_page and depth > 0:
            level = "#" * min(2 + depth, 6)
            lines += [f"{level} \U0001F4C4 {page_title}", ""]
        blocks = json.loads(doc_json).get("blocks", []) if doc_json else []
        for block in blocks:
            md = _block_to_md(block)
            if not md.strip():
                continue
            t_ms = block_times.get(block.get("id"))
            if t_ms is not None:
                lines.append(f"`[{format_ms(t_ms)}]`")
            lines.append(md)
            lines.append("")

    if segments:
        lines += ["---", "", "## 자막 기록", ""]
        for seg in segments:
            label = _SOURCE_LABEL[seg.source]
            lines.append(f"- `[{format_ms(seg.t_start_ms)}]` ({label}) {seg.text}")

    return "\n".join(lines).rstrip() + "\n"
