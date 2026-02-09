"""Tests for jvimdiff diff computation and DiffEditor."""

from types import SimpleNamespace

from jvim.diff import (
    DiffResult,
    DiffTag,
    compute_json_diff,
    format_json,
    format_jsonl,
    normalize_json,
    normalize_jsonl,
)
from jvim.diff_app import DiffEditor


class TestFormatJson:
    """JSON 포맷팅 테스트 (키 순서 유지)."""

    def test_format_simple(self):
        result = format_json('{"a":1}')
        assert result == '{\n    "a": 1\n}'

    def test_format_preserves_key_order(self):
        result = format_json('{"b": 2, "a": 1}')
        assert result.index('"b"') < result.index('"a"')

    def test_format_invalid_json(self):
        assert format_json("not json") == "not json"


class TestNormalizeJson:
    """JSON 정규화 테스트 (키 정렬 포함)."""

    def test_normalize_simple(self):
        result = normalize_json('{"a":1}')
        assert result == '{\n    "a": 1\n}'

    def test_normalize_sorts_keys(self):
        result = normalize_json('{"b": 2, "a": 1}')
        assert '"a": 1' in result
        assert result.index('"a"') < result.index('"b"')

    def test_normalize_invalid_json(self):
        """잘못된 JSON은 원본 그대로 반환."""
        content = "not json {{"
        assert normalize_json(content) == content

    def test_normalize_preserves_unicode(self):
        result = normalize_json('{"name": "한글"}')
        assert "한글" in result

    def test_normalize_nested(self):
        result = normalize_json('{"a":{"b":1}}')
        assert '    "a": {' in result
        assert '        "b": 1' in result


class TestComputeJsonDiff:
    """Diff 계산 테스트."""

    def test_identical_files(self):
        content = '{"a": 1, "b": 2}'
        result = compute_json_diff(content, content)
        assert all(t == DiffTag.EQUAL for t in result.left_line_tags)
        assert all(t == DiffTag.EQUAL for t in result.right_line_tags)
        assert len(result.hunks) == 0

    def test_alignment_equal_length(self):
        """좌우 라인 수는 항상 동일해야 한다."""
        result = compute_json_diff('{"a": 1}', '{"a": 1, "b": 2}')
        assert len(result.left_lines) == len(result.right_lines)
        assert len(result.left_line_tags) == len(result.right_line_tags)

    def test_added_key(self):
        left = '{"a": 1}'
        right = '{"a": 1, "b": 2}'
        result = compute_json_diff(left, right)
        assert len(result.hunks) > 0
        # 우측에 INSERT 또는 REPLACE 태그가 존재해야 함
        has_change = any(
            t in (DiffTag.INSERT, DiffTag.REPLACE)
            for t in result.right_line_tags
        )
        assert has_change

    def test_removed_key(self):
        left = '{"a": 1, "b": 2}'
        right = '{"a": 1}'
        result = compute_json_diff(left, right)
        assert len(result.hunks) > 0
        has_change = any(
            t in (DiffTag.DELETE, DiffTag.REPLACE)
            for t in result.left_line_tags
        )
        assert has_change

    def test_changed_value(self):
        left = '{"a": 1}'
        right = '{"a": 2}'
        result = compute_json_diff(left, right)
        assert len(result.hunks) > 0
        has_replace = any(t == DiffTag.REPLACE for t in result.left_line_tags)
        assert has_replace

    def test_no_normalize_still_formats(self):
        """normalize=False여도 pretty formatting은 적용된다."""
        left = '{"a":1}'
        right = '{"a": 1}'
        result = compute_json_diff(left, right, normalize=False)
        # 포맷팅 후 동일하므로 diff 없음
        assert len(result.hunks) == 0
        # 표시되는 라인이 indent=4로 포맷팅됨
        assert any("    " in line for line in result.left_lines)

    def test_no_normalize_preserves_key_order(self):
        """normalize=False면 키 순서가 유지된다."""
        left = '{"b": 1, "a": 2}'
        right = '{"b": 1, "a": 2}'
        result = compute_json_diff(left, right, normalize=False)
        # 키 순서 유지: "b"가 "a"보다 먼저
        left_text = "\n".join(result.left_lines)
        assert left_text.index('"b"') < left_text.index('"a"')

    def test_normalize_sorts_keys_in_diff(self):
        """normalize=True면 키가 정렬되어 구조적으로 동일한 JSON은 diff 없음."""
        left = '{"b": 1, "a": 2}'
        right = '{"a": 2, "b": 1}'
        result = compute_json_diff(left, right, normalize=True)
        assert len(result.hunks) == 0

    def test_no_normalize_identical(self):
        content = '{"a":1}'
        result = compute_json_diff(content, content, normalize=False)
        assert len(result.hunks) == 0

    def test_empty_left(self):
        result = compute_json_diff("", '{"a": 1}')
        assert len(result.left_lines) == len(result.right_lines)
        assert len(result.hunks) > 0

    def test_empty_right(self):
        result = compute_json_diff('{"a": 1}', "")
        assert len(result.left_lines) == len(result.right_lines)
        assert len(result.hunks) > 0

    def test_both_empty(self):
        result = compute_json_diff("", "")
        assert len(result.hunks) == 0

    def test_completely_different(self):
        result = compute_json_diff('{"a": 1}', '{"z": 99}')
        assert len(result.hunks) > 0
        assert len(result.left_lines) == len(result.right_lines)

    def test_filler_lines_for_insert(self):
        """INSERT 시 좌측에 빈 filler 라인이 들어간다."""
        left = '{"a": 1}'
        right = '{"a": 1, "b": 2}'
        result = compute_json_diff(left, right)
        # INSERT 태그가 있는 행의 좌측은 빈 문자열 (filler)
        for i, tag in enumerate(result.left_line_tags):
            if tag == DiffTag.INSERT:
                assert result.left_lines[i] == ""

    def test_filler_lines_for_delete(self):
        """DELETE 시 우측에 빈 filler 라인이 들어간다."""
        left = '{"a": 1, "b": 2}'
        right = '{"a": 1}'
        result = compute_json_diff(left, right)
        for i, tag in enumerate(result.right_line_tags):
            if tag == DiffTag.DELETE:
                assert result.right_lines[i] == ""


class TestJsonlFormat:
    """JSONL 포맷팅/정규화 테스트."""

    def test_format_jsonl(self):
        content = '{"a":1}\n{"b":2}'
        result = format_jsonl(content)
        # 레코드별 pretty-print, 빈 줄로 구분
        assert "    " in result
        assert "\n\n" in result

    def test_format_jsonl_preserves_key_order(self):
        content = '{"b":1,"a":2}\n{"d":3,"c":4}'
        result = format_jsonl(content)
        assert result.index('"b"') < result.index('"a"')
        assert result.index('"d"') < result.index('"c"')

    def test_normalize_jsonl_sorts_keys(self):
        content = '{"b":1,"a":2}'
        result = normalize_jsonl(content)
        assert result.index('"a"') < result.index('"b"')

    def test_format_jsonl_skips_empty_lines(self):
        content = '{"a":1}\n\n{"b":2}\n'
        result = format_jsonl(content)
        blocks = result.split("\n\n")
        assert len(blocks) == 2

    def test_format_jsonl_invalid_record(self):
        content = '{"a":1}\nnot json\n{"b":2}'
        result = format_jsonl(content)
        assert "not json" in result


class TestComputeJsonDiffJsonl:
    """JSONL diff 계산 테스트."""

    def test_identical_jsonl(self):
        content = '{"a":1}\n{"b":2}'
        result = compute_json_diff(content, content, jsonl=True)
        assert len(result.hunks) == 0

    def test_jsonl_added_record(self):
        left = '{"a":1}'
        right = '{"a":1}\n{"b":2}'
        result = compute_json_diff(left, right, jsonl=True)
        assert len(result.hunks) > 0
        assert len(result.left_lines) == len(result.right_lines)

    def test_jsonl_changed_value(self):
        left = '{"a":1}\n{"b":2}'
        right = '{"a":1}\n{"b":99}'
        result = compute_json_diff(left, right, jsonl=True)
        assert len(result.hunks) > 0

    def test_jsonl_no_normalize_still_formats(self):
        """normalize=False여도 JSONL pretty formatting은 적용."""
        content = '{"a":1}\n{"b":2}'
        result = compute_json_diff(content, content, normalize=False, jsonl=True)
        assert len(result.hunks) == 0
        # 포맷팅이 적용되었는지 확인
        assert any("    " in line for line in result.left_lines)

    def test_jsonl_normalize_sorts_keys(self):
        """normalize=True면 JSONL 레코드 키도 정렬."""
        left = '{"b":1,"a":2}'
        right = '{"a":2,"b":1}'
        result = compute_json_diff(left, right, normalize=True, jsonl=True)
        assert len(result.hunks) == 0


class TestDiffEditor:
    """DiffEditor 위젯 테스트."""

    def test_init_readonly(self):
        editor = DiffEditor('{"a": 1}')
        assert editor.read_only is True

    def test_set_diff_data(self):
        editor = DiffEditor()
        lines = ["line1", "line2", "line3"]
        tags = [DiffTag.EQUAL, DiffTag.REPLACE, DiffTag.EQUAL]
        from jvim.diff import DiffHunk

        hunks = [DiffHunk(1, 1, 1, 1, DiffTag.REPLACE)]
        editor.set_diff_data(lines, tags, set(), hunks)
        assert editor.lines == lines
        assert editor._line_tags == tags
        assert len(editor._diff_hunks) == 1

    def test_line_background_equal(self):
        editor = DiffEditor()
        editor._line_tags = [DiffTag.EQUAL]
        assert editor._line_background(0) == ""

    def test_line_background_delete(self):
        editor = DiffEditor()
        editor._line_tags = [DiffTag.DELETE]
        assert "on" in editor._line_background(0)

    def test_line_background_insert(self):
        editor = DiffEditor()
        editor._line_tags = [DiffTag.INSERT]
        assert "on" in editor._line_background(0)

    def test_line_background_replace(self):
        editor = DiffEditor()
        editor._line_tags = [DiffTag.REPLACE]
        assert "on" in editor._line_background(0)

    def test_line_background_filler(self):
        editor = DiffEditor()
        editor._line_tags = [DiffTag.INSERT]
        editor._filler_rows = {0}
        bg = editor._line_background(0)
        assert bg == DiffEditor._FILLER_BG

    def test_line_background_out_of_range(self):
        editor = DiffEditor()
        editor._line_tags = [DiffTag.EQUAL]
        assert editor._line_background(99) == ""

    def test_hunk_navigation_next(self):
        editor = DiffEditor()
        from jvim.diff import DiffHunk

        hunks = [
            DiffHunk(5, 2, 5, 2, DiffTag.REPLACE),
            DiffHunk(15, 3, 15, 3, DiffTag.DELETE),
        ]
        lines = [f"line{i}" for i in range(20)]
        tags = [DiffTag.EQUAL] * 20
        editor.set_diff_data(lines, tags, set(), hunks)
        editor._visible_height = lambda: 30

        editor._goto_next_hunk()
        assert editor.cursor_row == 5
        assert editor._current_hunk == 0

        editor._goto_next_hunk()
        assert editor.cursor_row == 15
        assert editor._current_hunk == 1

        # 순환
        editor._goto_next_hunk()
        assert editor.cursor_row == 5
        assert editor._current_hunk == 0

    def test_hunk_navigation_prev(self):
        editor = DiffEditor()
        from jvim.diff import DiffHunk

        hunks = [
            DiffHunk(5, 2, 5, 2, DiffTag.REPLACE),
            DiffHunk(15, 3, 15, 3, DiffTag.DELETE),
        ]
        lines = [f"line{i}" for i in range(20)]
        tags = [DiffTag.EQUAL] * 20
        editor.set_diff_data(lines, tags, set(), hunks)
        editor._visible_height = lambda: 30

        editor._goto_prev_hunk()
        assert editor.cursor_row == 15
        assert editor._current_hunk == 1

        editor._goto_prev_hunk()
        assert editor.cursor_row == 5
        assert editor._current_hunk == 0

    def test_hunk_navigation_no_hunks(self):
        editor = DiffEditor()
        editor.set_diff_data(["line"], [DiffTag.EQUAL], set(), [])
        editor._goto_next_hunk()
        assert editor.status_msg == "No diffs"

    def test_pending_bracket_c(self):
        """']c' / '[c' 키 조합으로 hunk 네비게이션."""
        editor = DiffEditor()
        from jvim.diff import DiffHunk

        hunks = [DiffHunk(3, 1, 3, 1, DiffTag.REPLACE)]
        lines = [f"line{i}" for i in range(10)]
        tags = [DiffTag.EQUAL] * 10
        editor.set_diff_data(lines, tags, set(), hunks)
        editor._visible_height = lambda: 30

        # ']' sets pending
        event_bracket = SimpleNamespace(key="right_square_bracket", character="]")
        editor._handle_normal(event_bracket)
        assert editor.pending == "]"

        # 'c' triggers next hunk
        event_c = SimpleNamespace(key="c", character="c")
        editor._handle_normal(event_c)
        assert editor.cursor_row == 3
        assert editor.pending == ""

    def test_status_msg_hunk_count(self):
        editor = DiffEditor()
        from jvim.diff import DiffHunk

        hunks = [
            DiffHunk(1, 1, 1, 1, DiffTag.REPLACE),
            DiffHunk(5, 1, 5, 1, DiffTag.DELETE),
        ]
        editor._diff_hunks = hunks
        editor._update_hunk_status()
        assert "2 hunks" in editor.status_msg

    def test_status_msg_identical(self):
        editor = DiffEditor()
        editor._diff_hunks = []
        editor._update_hunk_status()
        assert "identical" in editor.status_msg.lower()
