"""Tests for jvimdiff diff computation and DiffEditor."""

import json
from types import SimpleNamespace

from jvim.diff import (
    DiffTag,
    compute_json_diff,
    format_json,
    format_jsonl,
    normalize_json,
    normalize_jsonl,
)
from jvim.differ import DiffEditor, JsonDiffApp, SyncJsonEditor


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


class TestDiffEditorEmbeddedJson:
    """DiffEditor EJ 기능 테스트."""

    def _make_editor_with_embedded(self) -> DiffEditor:
        """임베디드 JSON이 포함된 DiffEditor 생성."""
        inner = json.dumps({"nested": 1}, ensure_ascii=False)
        escaped = json.dumps(inner, ensure_ascii=False)
        content = f'{{"data": {escaped}}}'
        editor = DiffEditor(content)
        return editor

    def test_find_string_at_cursor(self):
        """DiffEditor에서 임베디드 JSON 문자열을 찾을 수 있다."""
        editor = self._make_editor_with_embedded()
        # 포맷팅되지 않은 한 줄 JSON
        editor.cursor_row = 0
        editor.cursor_col = 9
        result = editor._find_string_at_cursor()
        assert result is not None
        _, _, content = result
        parsed = json.loads(content)
        assert parsed == {"nested": 1}

    def test_ej_on_diff_editor_is_readonly(self):
        """DiffEditor는 항상 read_only."""
        editor = self._make_editor_with_embedded()
        assert editor.read_only is True

    def test_ej_stack_push_pop(self):
        """EJ 스택 기반 중첩 네비게이션 로직 검증."""
        # 스택 동작은 App 레벨이므로 여기서는 스택 자체만 테스트
        stack: list[str] = []
        content1 = '{"level": 1}'
        content2 = '{"level": 2}'

        # 첫 번째 ej: 스택 비어있음
        stack.append(content1)
        assert len(stack) == 1

        # 중첩 ej
        stack.append(content2)
        assert len(stack) == 2

        # pop (닫기)
        restored = stack.pop()
        assert restored == content2
        assert len(stack) == 1

        restored = stack.pop()
        assert restored == content1
        assert len(stack) == 0

    def test_ej_editor_inherits_read_only(self):
        """EJ 패널에 사용될 DiffEditor도 read_only."""
        ej_editor = DiffEditor("")
        assert ej_editor.read_only is True

    def test_ej_diff_editor_set_diff_data(self):
        """EJ DiffEditor에 diff 데이터를 설정할 수 있다."""
        ej = DiffEditor("")
        lines = ['    "a": 1,', '    "b": 2']
        tags = [DiffTag.EQUAL, DiffTag.REPLACE]
        from jvim.diff import DiffHunk

        hunks = [DiffHunk(1, 1, 1, 1, DiffTag.REPLACE)]
        ej.set_diff_data(lines, tags, set(), hunks)
        assert ej.lines == lines
        assert ej._line_tags == tags
        assert len(ej._diff_hunks) == 1
        # REPLACE 행에는 배경색이 있어야 함
        assert ej._line_background(1) == DiffEditor._DIFF_BG[DiffTag.REPLACE]

    def test_ej_diff_both_sides(self):
        """양쪽 임베디드 JSON의 diff 계산 검증."""
        left_ej = '{\n    "key": "old_value"\n}'
        right_ej = '{\n    "key": "new_value"\n}'
        result = compute_json_diff(left_ej, right_ej, normalize=False)
        # 차이가 있어야 함
        assert len(result.hunks) > 0
        assert len(result.left_lines) == len(result.right_lines)
        has_change = any(
            t in (DiffTag.REPLACE, DiffTag.DELETE, DiffTag.INSERT)
            for t in result.left_line_tags
        )
        assert has_change

    def test_ej_diff_identical(self):
        """동일한 임베디드 JSON은 diff 없음."""
        content = '{\n    "key": "value"\n}'
        result = compute_json_diff(content, content, normalize=False)
        assert len(result.hunks) == 0


class TestDiffFoldSync:
    """diff 뷰어에서 fold 동기화 테스트."""

    SAMPLE = '{\n    "a": {\n        "b": 1\n    },\n    "c": 2\n}'

    def test_sync_toggle_fold(self):
        """한쪽에서 fold하면 다른 쪽도 동기화."""
        left = SyncJsonEditor(self.SAMPLE)
        right = SyncJsonEditor(self.SAMPLE)
        left._sync_target = right
        right._sync_target = left

        left._toggle_fold(1)
        assert 1 in left._folds
        assert 1 in right._folds
        assert right._folds[1] == left._folds[1]

    def test_sync_unfold_all(self):
        """전체 펼기 동기화."""
        left = SyncJsonEditor(self.SAMPLE)
        right = SyncJsonEditor(self.SAMPLE)
        left._sync_target = right
        right._sync_target = left

        left._fold_all()
        assert len(right._folds) > 0
        left._unfold_all()
        assert right._folds == {}

    def test_set_diff_data_clears_folds(self):
        """set_diff_data 시 fold 초기화."""
        editor = DiffEditor(self.SAMPLE)
        editor._folds[1] = 3
        editor.set_diff_data(
            lines=["a", "b"],
            tags=[DiffTag.EQUAL, DiffTag.EQUAL],
            filler_rows=set(),
            hunks=[],
        )
        assert editor._folds == {}

    def test_unfold_diff_regions(self):
        """diff가 있는 fold 영역만 자동으로 unfold."""
        content = json.dumps({"a": {"x": 1}, "b": {"y": 2}, "c": {"z": 3}}, indent=4)
        editor = DiffEditor(content)
        # EQUAL 태그로 초기화하되 b 블록에 REPLACE 태그 삽입
        lines = content.split("\n")
        tags = [DiffTag.EQUAL] * len(lines)
        # "b" 블록의 라인을 찾아서 REPLACE 태그 설정
        for i, line in enumerate(lines):
            if '"b"' in line or '"y"' in line:
                tags[i] = DiffTag.REPLACE
        editor._line_tags = tags
        # 전체 fold
        editor._fold_all()
        folded_before = dict(editor._folds)
        assert len(folded_before) > 0

        # diff 영역 unfold
        JsonDiffApp._unfold_diff_regions(editor)

        # b 블록의 fold는 제거되어야 함
        for start, end in folded_before.items():
            has_diff = any(
                tags[i] != DiffTag.EQUAL for i in range(start, end + 1) if i < len(tags)
            )
            if has_diff:
                assert start not in editor._folds, f"fold at {start} should be unfolded (has diff)"
            else:
                assert start in editor._folds, f"fold at {start} should remain folded"

    def test_unfold_diff_regions_all_equal(self):
        """모든 라인이 EQUAL이면 fold 유지."""
        content = json.dumps({"a": {"x": 1}, "b": {"y": 2}}, indent=4)
        editor = DiffEditor(content)
        tags = [DiffTag.EQUAL] * len(content.split("\n"))
        editor._line_tags = tags
        editor._fold_all()
        folds_before = dict(editor._folds)
        JsonDiffApp._unfold_diff_regions(editor)
        assert editor._folds == folds_before

    def test_nested_fold_preserves_clean_siblings(self):
        """diff가 있는 depth-1 블록을 열어도, 안쪽 diff 없는 블록은 접힌 상태 유지."""
        # "a" 블록에 diff가 있지만 "a.inner"에는 없음
        content = json.dumps({
            "a": {"inner": {"x": 1, "y": 2}, "changed": "val"},
            "b": {"clean": {"z": 3}},
        }, indent=4)
        lines = content.split("\n")
        tags = [DiffTag.EQUAL] * len(lines)
        # "changed" 라인에만 REPLACE
        for i, line in enumerate(lines):
            if '"changed"' in line:
                tags[i] = DiffTag.REPLACE
        editor = DiffEditor(content)
        editor._line_tags = tags
        # 모든 depth fold
        editor._fold_all_nested()
        # "a"의 inner 블록과 "b"의 clean 블록도 접혀 있어야 함
        inner_folds = {s for s in editor._folds if s > 0}
        assert len(inner_folds) >= 2  # 최소 depth-1 2개 + depth-2 블록들

        # diff unfold
        JsonDiffApp._unfold_diff_regions(editor)

        # "b" 블록은 diff 없으므로 접힌 상태
        b_start = None
        for i, line in enumerate(lines):
            if '"b"' in line and '{' in line:
                b_start = i
                break
        assert b_start is not None
        assert b_start in editor._folds, "diff 없는 b 블록은 접힌 상태 유지"

        # "a.inner" 블록도 diff 없으므로 접힌 상태
        inner_start = None
        for i, line in enumerate(lines):
            if '"inner"' in line and '{' in line:
                inner_start = i
                break
        assert inner_start is not None
        assert inner_start in editor._folds, "diff 없는 inner 블록은 접힌 상태 유지"

    def test_unfold_diff_expands_collapsed_strings(self):
        """diff가 있는 collapsed string은 자동 펼기."""
        long_str = "a" * 100
        content = '{\n    "data": "' + long_str + '"\n}'
        editor = DiffEditor(content)
        lines = content.split("\n")
        tags = [DiffTag.EQUAL] * len(lines)
        tags[1] = DiffTag.REPLACE  # "data" 라인에 diff
        editor._line_tags = tags
        editor._collapsed_strings.add(1)

        JsonDiffApp._unfold_diff_regions(editor)
        assert 1 not in editor._collapsed_strings

    def test_unfold_diff_keeps_clean_collapsed_strings(self):
        """diff가 없는 collapsed string은 접힌 상태 유지."""
        long_str = "a" * 100
        content = '{\n    "data": "' + long_str + '"\n}'
        editor = DiffEditor(content)
        lines = content.split("\n")
        tags = [DiffTag.EQUAL] * len(lines)
        editor._line_tags = tags
        editor._collapsed_strings.add(1)

        JsonDiffApp._unfold_diff_regions(editor)
        assert 1 in editor._collapsed_strings
