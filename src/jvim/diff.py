"""JSON-aware diff computation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum, auto


class DiffTag(Enum):
    EQUAL = auto()
    INSERT = auto()  # 우측에만 존재
    DELETE = auto()  # 좌측에만 존재
    REPLACE = auto()  # 양쪽 다르게 존재


@dataclass
class DiffHunk:
    """연속된 변경 블록."""

    left_start: int  # 정렬된 라인 배열에서의 시작 (0-based)
    left_count: int
    right_start: int
    right_count: int
    tag: DiffTag


@dataclass
class DiffResult:
    """Diff 결과: 정렬된 라인 배열과 태그."""

    left_lines: list[str] = field(default_factory=list)
    right_lines: list[str] = field(default_factory=list)
    left_line_tags: list[DiffTag] = field(default_factory=list)
    right_line_tags: list[DiffTag] = field(default_factory=list)
    hunks: list[DiffHunk] = field(default_factory=list)


def format_json(content: str) -> str:
    """JSON을 indent=4로 포맷팅. 파싱 실패 시 원본 반환."""
    try:
        parsed = json.loads(content)
        return json.dumps(parsed, indent=4, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return content


def normalize_json(content: str) -> str:
    """JSON을 indent=4 + sort_keys로 정규화. 파싱 실패 시 원본 반환."""
    try:
        parsed = json.loads(content)
        return json.dumps(parsed, indent=4, ensure_ascii=False, sort_keys=True)
    except (json.JSONDecodeError, ValueError):
        return content


def format_jsonl(content: str) -> str:
    """JSONL 레코드별 indent=4 포맷팅. 빈 줄로 구분."""
    blocks: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
            blocks.append(json.dumps(parsed, indent=4, ensure_ascii=False))
        except json.JSONDecodeError:
            blocks.append(stripped)
    return "\n\n".join(blocks)


def normalize_jsonl(content: str) -> str:
    """JSONL 레코드별 indent=4 + sort_keys 정규화. 빈 줄로 구분."""
    blocks: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
            blocks.append(
                json.dumps(parsed, indent=4, ensure_ascii=False, sort_keys=True)
            )
        except json.JSONDecodeError:
            blocks.append(stripped)
    return "\n\n".join(blocks)


def _parse_jsonl_records(content: str, normalize: bool) -> list[str]:
    """JSONL을 레코드별 포맷팅된 문자열 리스트로 변환."""
    records: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
            if normalize:
                records.append(
                    json.dumps(parsed, indent=4, ensure_ascii=False, sort_keys=True)
                )
            else:
                records.append(json.dumps(parsed, indent=4, ensure_ascii=False))
        except json.JSONDecodeError:
            records.append(stripped)
    return records


def _append_lines(
    result: DiffResult, left_lines: list[str], right_lines: list[str], tag: DiffTag
) -> None:
    """정렬된 라인 쌍을 result에 추가. 짧은 쪽은 filler로 패딩."""
    max_count = max(len(left_lines), len(right_lines))
    for k in range(max_count):
        result.left_lines.append(left_lines[k] if k < len(left_lines) else "")
        result.right_lines.append(right_lines[k] if k < len(right_lines) else "")
        result.left_line_tags.append(tag)
        result.right_line_tags.append(tag)
    return max_count


def _line_diff(
    result: DiffResult, left_lines: list[str], right_lines: list[str]
) -> None:
    """변경된 레코드 내부를 라인 단위 diff."""
    matcher = SequenceMatcher(None, left_lines, right_lines)
    hunk_start = len(result.left_lines)
    total = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        lc, rc = i2 - i1, j2 - j1
        if tag == "equal":
            for k in range(lc):
                result.left_lines.append(left_lines[i1 + k])
                result.right_lines.append(right_lines[j1 + k])
                result.left_line_tags.append(DiffTag.EQUAL)
                result.right_line_tags.append(DiffTag.EQUAL)
            total += lc
        else:
            dt = {
                "delete": DiffTag.DELETE,
                "insert": DiffTag.INSERT,
                "replace": DiffTag.REPLACE,
            }[tag]
            mc = max(lc, rc)
            for k in range(mc):
                result.left_lines.append(left_lines[i1 + k] if k < lc else "")
                result.right_lines.append(right_lines[j1 + k] if k < rc else "")
                result.left_line_tags.append(dt)
                result.right_line_tags.append(dt)
            total += mc
    if total:
        result.hunks.append(
            DiffHunk(
                left_start=hunk_start,
                left_count=total,
                right_start=hunk_start,
                right_count=total,
                tag=DiffTag.REPLACE,
            )
        )


def compute_json_diff(
    left: str,
    right: str,
    normalize: bool = True,
    jsonl: bool = False,
) -> DiffResult:
    """두 JSON 문자열의 diff를 계산하여 정렬된 결과를 반환."""
    if jsonl:
        return _compute_jsonl_diff(left, right, normalize)

    if normalize:
        left = normalize_json(left)
        right = normalize_json(right)
    else:
        left = format_json(left)
        right = format_json(right)
    return _compute_line_diff(left.split("\n"), right.split("\n"))


def _compute_line_diff(left_src: list[str], right_src: list[str]) -> DiffResult:
    """라인 배열의 diff를 계산."""
    matcher = SequenceMatcher(None, left_src, right_src)
    result = DiffResult()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_count = i2 - i1
        right_count = j2 - j1

        if tag == "equal":
            for k in range(left_count):
                result.left_lines.append(left_src[i1 + k])
                result.right_lines.append(right_src[j1 + k])
                result.left_line_tags.append(DiffTag.EQUAL)
                result.right_line_tags.append(DiffTag.EQUAL)

        elif tag == "delete":
            hunk_start = len(result.left_lines)
            for k in range(left_count):
                result.left_lines.append(left_src[i1 + k])
                result.right_lines.append("")
                result.left_line_tags.append(DiffTag.DELETE)
                result.right_line_tags.append(DiffTag.DELETE)
            result.hunks.append(
                DiffHunk(
                    left_start=hunk_start,
                    left_count=left_count,
                    right_start=hunk_start,
                    right_count=left_count,
                    tag=DiffTag.DELETE,
                )
            )

        elif tag == "insert":
            hunk_start = len(result.left_lines)
            for k in range(right_count):
                result.left_lines.append("")
                result.right_lines.append(right_src[j1 + k])
                result.left_line_tags.append(DiffTag.INSERT)
                result.right_line_tags.append(DiffTag.INSERT)
            result.hunks.append(
                DiffHunk(
                    left_start=hunk_start,
                    left_count=right_count,
                    right_start=hunk_start,
                    right_count=right_count,
                    tag=DiffTag.INSERT,
                )
            )

        elif tag == "replace":
            hunk_start = len(result.left_lines)
            max_count = max(left_count, right_count)
            for k in range(max_count):
                l_line = left_src[i1 + k] if k < left_count else ""
                r_line = right_src[j1 + k] if k < right_count else ""
                result.left_lines.append(l_line)
                result.right_lines.append(r_line)
                result.left_line_tags.append(DiffTag.REPLACE)
                result.right_line_tags.append(DiffTag.REPLACE)
            result.hunks.append(
                DiffHunk(
                    left_start=hunk_start,
                    left_count=max_count,
                    right_start=hunk_start,
                    right_count=max_count,
                    tag=DiffTag.REPLACE,
                )
            )

    return result


def _compute_jsonl_diff(left: str, right: str, normalize: bool) -> DiffResult:
    """JSONL 레코드 단위 diff: 레코드 매칭 후 변경분만 라인 diff."""
    left_records = _parse_jsonl_records(left, normalize)
    right_records = _parse_jsonl_records(right, normalize)

    # 레코드 단위 비교 (레코드 수만큼만 비교 → 빠름)
    matcher = SequenceMatcher(None, left_records, right_records)
    result = DiffResult()
    first = True

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                if not first:
                    # 레코드 구분 빈 줄
                    result.left_lines.append("")
                    result.right_lines.append("")
                    result.left_line_tags.append(DiffTag.EQUAL)
                    result.right_line_tags.append(DiffTag.EQUAL)
                first = False
                for line in left_records[i1 + k].split("\n"):
                    result.left_lines.append(line)
                    result.right_lines.append(line)
                    result.left_line_tags.append(DiffTag.EQUAL)
                    result.right_line_tags.append(DiffTag.EQUAL)

        elif tag == "delete":
            for k in range(i2 - i1):
                if not first:
                    result.left_lines.append("")
                    result.right_lines.append("")
                    result.left_line_tags.append(DiffTag.DELETE)
                    result.right_line_tags.append(DiffTag.DELETE)
                first = False
                hunk_start = len(result.left_lines)
                rec_lines = left_records[i1 + k].split("\n")
                cnt = _append_lines(result, rec_lines, [], DiffTag.DELETE)
                result.hunks.append(
                    DiffHunk(
                        left_start=hunk_start,
                        left_count=cnt,
                        right_start=hunk_start,
                        right_count=cnt,
                        tag=DiffTag.DELETE,
                    )
                )

        elif tag == "insert":
            for k in range(j2 - j1):
                if not first:
                    result.left_lines.append("")
                    result.right_lines.append("")
                    result.left_line_tags.append(DiffTag.INSERT)
                    result.right_line_tags.append(DiffTag.INSERT)
                first = False
                hunk_start = len(result.left_lines)
                rec_lines = right_records[j1 + k].split("\n")
                cnt = _append_lines(result, [], rec_lines, DiffTag.INSERT)
                result.hunks.append(
                    DiffHunk(
                        left_start=hunk_start,
                        left_count=cnt,
                        right_start=hunk_start,
                        right_count=cnt,
                        tag=DiffTag.INSERT,
                    )
                )

        elif tag == "replace":
            l_count = i2 - i1
            r_count = j2 - j1
            paired = min(l_count, r_count)

            # 위치별 매칭: 각 레코드 쌍을 개별 diff
            for k in range(paired):
                if not first:
                    result.left_lines.append("")
                    result.right_lines.append("")
                    result.left_line_tags.append(DiffTag.REPLACE)
                    result.right_line_tags.append(DiffTag.REPLACE)
                first = False
                l_lines = left_records[i1 + k].split("\n")
                r_lines = right_records[j1 + k].split("\n")
                if left_records[i1 + k] == right_records[j1 + k]:
                    for line in l_lines:
                        result.left_lines.append(line)
                        result.right_lines.append(line)
                        result.left_line_tags.append(DiffTag.EQUAL)
                        result.right_line_tags.append(DiffTag.EQUAL)
                else:
                    _line_diff(result, l_lines, r_lines)

            # 나머지: 좌측 초과분 → DELETE
            for k in range(paired, l_count):
                if not first:
                    result.left_lines.append("")
                    result.right_lines.append("")
                    result.left_line_tags.append(DiffTag.DELETE)
                    result.right_line_tags.append(DiffTag.DELETE)
                first = False
                hunk_start = len(result.left_lines)
                rec_lines = left_records[i1 + k].split("\n")
                cnt = _append_lines(result, rec_lines, [], DiffTag.DELETE)
                result.hunks.append(
                    DiffHunk(
                        left_start=hunk_start,
                        left_count=cnt,
                        right_start=hunk_start,
                        right_count=cnt,
                        tag=DiffTag.DELETE,
                    )
                )

            # 나머지: 우측 초과분 → INSERT
            for k in range(paired, r_count):
                if not first:
                    result.left_lines.append("")
                    result.right_lines.append("")
                    result.left_line_tags.append(DiffTag.INSERT)
                    result.right_line_tags.append(DiffTag.INSERT)
                first = False
                hunk_start = len(result.left_lines)
                rec_lines = right_records[j1 + k].split("\n")
                cnt = _append_lines(result, [], rec_lines, DiffTag.INSERT)
                result.hunks.append(
                    DiffHunk(
                        left_start=hunk_start,
                        left_count=cnt,
                        right_start=hunk_start,
                        right_count=cnt,
                        tag=DiffTag.INSERT,
                    )
                )

    return result
