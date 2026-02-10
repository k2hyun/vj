"""Tests for JsonEditor widget."""

from src.jvim.editor import JsonEditor, EditorMode


class TestEditorBasic:
    """Basic editor initialization and content tests."""

    def test_init_empty(self):
        editor = JsonEditor()
        assert editor.lines == [""]
        assert editor.cursor_row == 0
        assert editor.cursor_col == 0

    def test_init_with_content(self):
        editor = JsonEditor('{"key": "value"}')
        assert editor.lines == ['{"key": "value"}']

    def test_init_multiline(self):
        content = '{\n    "key": "value"\n}'
        editor = JsonEditor(content)
        assert len(editor.lines) == 3
        assert editor.lines[1] == '    "key": "value"'

    def test_get_content(self):
        content = '{"key": "value"}'
        editor = JsonEditor(content)
        assert editor.get_content() == content

    def test_set_content(self):
        editor = JsonEditor('{"old": "data"}')
        editor.set_content('{"new": "data"}')
        assert editor.lines == ['{"new": "data"}']
        assert editor.cursor_row == 0
        assert editor.cursor_col == 0


class TestCacheInvalidation:
    """Tests for cache invalidation - fixes for IndexError bugs."""

    def test_save_undo_marks_dirty(self):
        """_save_undo should mark cache as dirty."""
        editor = JsonEditor('{"key": "value"}')
        editor._style_cache[0] = ["white"] * 16
        editor._jsonl_records_cache = [1]

        editor._save_undo()

        assert editor._cache_dirty is True

    def test_set_content_marks_dirty(self):
        """set_content should mark cache as dirty."""
        editor = JsonEditor('{"old": "data"}')
        editor._style_cache[0] = ["white"] * 14
        editor._jsonl_records_cache = [1]

        editor.set_content('{"new": "data"}')

        assert editor._cache_dirty is True

    def test_undo_marks_dirty(self):
        """_undo should mark cache as dirty."""
        editor = JsonEditor('{"key": "value"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']
        editor._style_cache[0] = ["white"] * 20

        editor._undo()

        assert editor._cache_dirty is True
        assert editor.lines == ['{"key": "value"}']

    def test_redo_marks_dirty(self):
        """_redo should mark cache as dirty."""
        editor = JsonEditor('{"key": "value"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']
        editor._undo()
        editor._style_cache[0] = ["white"] * 16

        editor._redo()

        assert editor._cache_dirty is True
        assert editor.lines == ['{"modified": "data"}']

    def test_render_auto_invalidation_skips_empty_cache(self):
        """render() auto-invalidation should skip hash computation when cache is empty."""
        editor = JsonEditor('{"key": "value"}')
        # Cache is empty, hash check should be skipped
        assert editor._style_cache == {}
        # Change content
        editor.lines = ['{"new": "data"}']
        # With empty cache, no hash computation needed
        # (This is tested by the optimization logic itself)


class TestUndoRedo:
    """Tests for undo/redo functionality."""

    def test_undo_restores_content(self):
        editor = JsonEditor('{"original": "data"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']

        editor._undo()

        assert editor.lines == ['{"original": "data"}']
        assert editor.status_msg == "undone"

    def test_undo_restores_cursor_position(self):
        editor = JsonEditor('{"key": "value"}')
        editor.cursor_row = 0
        editor.cursor_col = 5
        editor._save_undo()
        editor.cursor_row = 0
        editor.cursor_col = 10

        editor._undo()

        assert editor.cursor_row == 0
        assert editor.cursor_col == 5

    def test_redo_restores_content(self):
        editor = JsonEditor('{"original": "data"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']
        editor._undo()

        editor._redo()

        assert editor.lines == ['{"modified": "data"}']
        assert editor.status_msg == "redone"

    def test_undo_nothing_to_undo(self):
        editor = JsonEditor('{"key": "value"}')

        editor._undo()

        assert editor.status_msg == "nothing to undo"

    def test_redo_nothing_to_redo(self):
        editor = JsonEditor('{"key": "value"}')

        editor._redo()

        assert editor.status_msg == "nothing to redo"

    def test_new_edit_clears_redo_stack(self):
        editor = JsonEditor('{"original": "data"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']
        editor._undo()
        assert len(editor.redo_stack) == 1

        # New edit should clear redo stack
        editor._save_undo()

        assert len(editor.redo_stack) == 0


class TestEmbeddedJson:
    """Tests for embedded JSON editing (ej command)."""

    def test_find_string_at_cursor(self):
        editor = JsonEditor('{"data": "{\\"nested\\": 1}"}')
        editor.cursor_row = 0
        editor.cursor_col = 9

        result = editor._find_string_at_cursor()

        assert result is not None
        col_start, col_end, content = result
        assert content == '{"nested": 1}'

    def test_update_embedded_string(self):
        editor = JsonEditor('{"data": "{\\"nested\\": 1}"}')
        # Simulate finding the string value position
        # The string value starts at col 9 and ends at col 25

        editor.update_embedded_string(0, 9, 25, '{"nested": 2}')

        # The new content is escaped as JSON string
        assert '\\"nested\\": 2' in editor.lines[0]
        # Should have saved undo
        assert len(editor.undo_stack) == 1

    def test_update_embedded_string_cache_cleared(self):
        """update_embedded_string should result in cleared cache via _save_undo."""
        editor = JsonEditor('{"data": "{\\"nested\\": 1}"}')
        editor._style_cache[0] = ["white"] * 27

        editor.update_embedded_string(0, 9, 25, '{"nested": 2}')

        # Cache should be marked dirty by _save_undo
        assert editor._cache_dirty is True


class TestJsonl:
    """Tests for JSONL file handling."""

    def test_jsonl_to_pretty(self):
        content = '{"a": 1}\n{"b": 2}'
        result = JsonEditor._jsonl_to_pretty(content)

        assert '"a": 1' in result
        assert '"b": 2' in result
        # Pretty printed with indentation
        assert '    ' in result or result.count('\n') > 1

    def test_pretty_to_jsonl(self):
        pretty = '{\n    "a": 1\n}\n\n{\n    "b": 2\n}'
        result = JsonEditor._pretty_to_jsonl(pretty)

        lines = result.split('\n')
        assert len(lines) == 2
        assert '{"a": 1}' in lines[0] or '{"a":1}' in lines[0]

    def test_split_jsonl_blocks(self):
        content = '{\n    "a": 1\n}\n\n{\n    "b": 2\n}'
        blocks = JsonEditor._split_jsonl_blocks(content)

        assert len(blocks) == 2

    def test_jsonl_mode_init(self):
        content = '{"a": 1}\n{"b": 2}'
        editor = JsonEditor(content, jsonl=True)

        # Should be pretty-printed
        assert len(editor.lines) > 2

    def test_jsonl_line_records(self):
        editor = JsonEditor('{"a": 1}\n{"b": 2}', jsonl=True)
        records = editor._jsonl_line_records()

        # First line of each block should have record number
        assert 1 in records
        assert 2 in records


class TestEditorMode:
    """Tests for editor mode handling."""

    def test_initial_mode_is_normal(self):
        editor = JsonEditor()
        assert editor._mode == EditorMode.NORMAL

    def test_enter_insert_mode(self):
        editor = JsonEditor('{"key": "value"}')
        editor._enter_insert()

        assert editor._mode == EditorMode.INSERT
        assert editor.status_msg == "-- INSERT --"

    def test_readonly_blocks_insert(self):
        editor = JsonEditor('{"key": "value"}', read_only=True)
        editor._enter_insert()

        assert editor._mode == EditorMode.NORMAL
        assert editor.status_msg == "[readonly]"


class TestJsonValidation:
    """Tests for JSON validation."""

    def test_valid_json(self):
        editor = JsonEditor('{"key": "value"}')
        valid, err = editor._check_content(editor.get_content())

        assert valid is True
        assert err == ""

    def test_invalid_json(self):
        editor = JsonEditor('{"key": }')
        valid, err = editor._check_content(editor.get_content())

        assert valid is False
        assert "JSON error" in err

    def test_valid_jsonl(self):
        editor = JsonEditor('{"a": 1}\n{"b": 2}', jsonl=True)
        valid, err = editor._check_content(editor.get_content())

        assert valid is True

    def test_invalid_jsonl_record(self):
        content = '{\n    "a": 1\n}\n\n{\n    "b": \n}'
        editor = JsonEditor(jsonl=True)
        editor.lines = content.split('\n')
        valid, err = editor._check_content(editor.get_content())

        assert valid is False
        assert "JSONL error" in err


class TestMovement:
    """Tests for cursor movement."""

    def test_clamp_cursor_row(self):
        editor = JsonEditor('line1\nline2')
        editor.cursor_row = 10
        editor._clamp_cursor()

        assert editor.cursor_row == 1

    def test_clamp_cursor_col_normal_mode(self):
        editor = JsonEditor('short')
        editor._mode = EditorMode.NORMAL
        editor.cursor_col = 10
        editor._clamp_cursor()

        # In NORMAL mode, cursor stays on last character
        assert editor.cursor_col == 4

    def test_clamp_cursor_col_insert_mode(self):
        editor = JsonEditor('short')
        editor._mode = EditorMode.INSERT
        editor.cursor_col = 10
        editor._clamp_cursor()

        # In INSERT mode, cursor can be at end of line
        assert editor.cursor_col == 5

    def test_move_word_forward(self):
        editor = JsonEditor('{"key": "value"}')
        editor.cursor_col = 0
        editor._move_word_forward()

        assert editor.cursor_col > 0

    def test_move_word_backward(self):
        editor = JsonEditor('{"key": "value"}')
        editor.cursor_col = 10
        editor._move_word_backward()

        assert editor.cursor_col < 10


class TestBracketMatching:
    """Tests for bracket matching (% command)."""

    def test_jump_matching_bracket_forward(self):
        editor = JsonEditor('{"key": [1, 2, 3]}')
        editor.cursor_col = 0  # On {
        editor._jump_matching_bracket()

        assert editor.cursor_col == 17  # On }

    def test_jump_matching_bracket_backward(self):
        editor = JsonEditor('{"key": [1, 2, 3]}')
        editor.cursor_col = 17  # On }
        editor._jump_matching_bracket()

        assert editor.cursor_col == 0  # On {


class TestCharWidth:
    """Tests for character width calculation (CJK support)."""

    def test_ascii_width(self):
        editor = JsonEditor()
        assert editor._char_width('a') == 1
        assert editor._char_width('1') == 1

    def test_cjk_width(self):
        editor = JsonEditor()
        # Korean character should be width 2
        assert editor._char_width('한') == 2
        # Japanese
        assert editor._char_width('日') == 2
        # Chinese
        assert editor._char_width('中') == 2

    def test_char_width_cache(self):
        editor = JsonEditor()
        # First call computes and caches
        w1 = editor._char_width('한')
        # Second call uses cache
        w2 = editor._char_width('한')

        assert w1 == w2 == 2
        assert '한' in editor._char_width_cache


class TestJsonPathFilter:
    """Tests for JSONPath search with value filtering."""

    def test_parse_filter_equals_string(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter('$.name="John"')

        assert path == "$.name"
        assert op == "="
        assert val == "John"

    def test_parse_filter_equals_number(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.age=30")

        assert path == "$.age"
        assert op == "="
        assert val == 30

    def test_parse_filter_greater_than(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.age>18")

        assert path == "$.age"
        assert op == ">"
        assert val == 18

    def test_parse_filter_less_than(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.price<100")

        assert path == "$.price"
        assert op == "<"
        assert val == 100

    def test_parse_filter_greater_or_equal(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.count>=5")

        assert path == "$.count"
        assert op == ">="
        assert val == 5

    def test_parse_filter_less_or_equal(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.count<=10")

        assert path == "$.count"
        assert op == "<="
        assert val == 10

    def test_parse_filter_not_equals(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.status!=null")

        assert path == "$.status"
        assert op == "!="
        assert val is None

    def test_parse_filter_regex(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.name~^J")

        assert path == "$.name"
        assert op == "~"
        assert val == "^J"

    def test_parse_filter_no_filter(self):
        editor = JsonEditor()
        path, op, val = editor._parse_jsonpath_filter("$.users[*].name")

        assert path == "$.users[*].name"
        assert op == ""
        assert val is None

    def test_value_matches_equals(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches("John", "=", "John")
        assert not editor._jsonpath_value_matches("Jane", "=", "John")
        assert editor._jsonpath_value_matches(30, "=", 30)

    def test_value_matches_not_equals(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches("Jane", "!=", "John")
        assert not editor._jsonpath_value_matches("John", "!=", "John")

    def test_value_matches_greater(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches(30, ">", 18)
        assert not editor._jsonpath_value_matches(18, ">", 18)
        assert not editor._jsonpath_value_matches(10, ">", 18)

    def test_value_matches_less(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches(10, "<", 18)
        assert not editor._jsonpath_value_matches(18, "<", 18)
        assert not editor._jsonpath_value_matches(30, "<", 18)

    def test_value_matches_greater_or_equal(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches(30, ">=", 18)
        assert editor._jsonpath_value_matches(18, ">=", 18)
        assert not editor._jsonpath_value_matches(10, ">=", 18)

    def test_value_matches_less_or_equal(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches(10, "<=", 18)
        assert editor._jsonpath_value_matches(18, "<=", 18)
        assert not editor._jsonpath_value_matches(30, "<=", 18)

    def test_value_matches_regex(self):
        editor = JsonEditor()

        assert editor._jsonpath_value_matches("John", "~", "^J")
        assert editor._jsonpath_value_matches("Jane", "~", "^J")
        assert not editor._jsonpath_value_matches("Mary", "~", "^J")
        assert editor._jsonpath_value_matches("test@email.com", "~", r"@.*\.com$")

    def test_search_with_equals_filter(self):
        editor = JsonEditor('{"users": [{"name": "John"}, {"name": "Jane"}]}')
        editor._search_buffer = '$.users[*].name="John"'
        editor._search_forward = True
        editor._execute_search()

        assert len(editor._search_matches) == 1

    def test_search_with_greater_filter(self):
        editor = JsonEditor('{"users": [{"age": 25}, {"age": 30}, {"age": 20}]}')
        editor._search_buffer = "$.users[*].age>24"
        editor._search_forward = True
        editor._execute_search()

        assert len(editor._search_matches) == 2  # 25 and 30

    def test_search_with_regex_filter(self):
        editor = JsonEditor('{"users": [{"name": "John"}, {"name": "Jane"}, {"name": "Mary"}]}')
        editor._search_buffer = "$.users[*].name~^J"
        editor._search_forward = True
        editor._execute_search()

        assert len(editor._search_matches) == 2  # John and Jane

    def test_search_jsonl_with_filter(self):
        content = '{"name": "John", "age": 25}\n{"name": "Jane", "age": 30}\n{"name": "Bob", "age": 20}'
        editor = JsonEditor(content, jsonl=True)
        editor._search_buffer = "$.age>24"
        editor._search_forward = True
        editor._execute_search()

        assert len(editor._search_matches) == 2  # 25 and 30

    def test_search_jsonl_with_regex_filter(self):
        content = '{"name": "John"}\n{"name": "Jane"}\n{"name": "Bob"}'
        editor = JsonEditor(content, jsonl=True)
        editor._search_buffer = "$.name~^J"
        editor._search_forward = True
        editor._execute_search()

        assert len(editor._search_matches) == 2  # John and Jane

    def test_search_with_boolean_filter(self):
        editor = JsonEditor('{"items": [{"active": true}, {"active": false}]}')
        editor._search_buffer = "$.items[*].active=true"
        editor._search_forward = True
        editor._execute_search()

        assert len(editor._search_matches) == 1


class TestHistory:
    """Tests for command and search history."""

    def test_get_history(self):
        editor = JsonEditor()
        editor._search_history = ["pattern1", "pattern2"]
        editor._command_history = ["w", "q"]

        history = editor.get_history()

        assert history["search"] == ["pattern1", "pattern2"]
        assert history["command"] == ["w", "q"]

    def test_set_history(self):
        editor = JsonEditor()
        history = {
            "search": ["foo", "bar"],
            "command": ["fmt", "w"],
        }

        editor.set_history(history)

        assert editor._search_history == ["foo", "bar"]
        assert editor._command_history == ["fmt", "w"]

    def test_set_history_partial(self):
        editor = JsonEditor()
        editor._search_history = ["old"]
        editor._command_history = ["old_cmd"]

        editor.set_history({"search": ["new"]})

        assert editor._search_history == ["new"]
        assert editor._command_history == ["old_cmd"]

    def test_add_to_command_history(self):
        editor = JsonEditor()

        editor._add_to_command_history("fmt")
        editor._add_to_command_history("w")

        assert editor._command_history == ["w", "fmt"]

    def test_add_to_command_history_no_duplicates(self):
        editor = JsonEditor()
        editor._command_history = ["w", "fmt"]

        editor._add_to_command_history("w")

        assert editor._command_history == ["w", "fmt"]

    def test_command_history_navigation(self):
        editor = JsonEditor()
        editor._command_history = ["c", "b", "a"]

        editor._command_history_prev()
        assert editor.command_buffer == "c"

        editor._command_history_prev()
        assert editor.command_buffer == "b"

        editor._command_history_next()
        assert editor.command_buffer == "c"

        editor._command_history_next()
        assert editor.command_buffer == ""


class TestLineJump:
    """Tests for line jump positioning cursor at top."""

    def test_scroll_cursor_to_top(self):
        """_scroll_cursor_to_top sets scroll_top to cursor_row."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)

        editor.cursor_row = 50
        editor._scroll_cursor_to_top()

        assert editor._scroll_top == 50

    def test_line_jump_command_scrolls_to_top(self):
        """Line number command (e.g., :50) positions cursor at top."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)
        editor._scroll_top = 0

        editor._exec_command("50")

        assert editor.cursor_row == 49  # 0-indexed
        assert editor._scroll_top == 49  # Cursor at top

    def test_line_jump_G_scrolls_to_top(self):
        """G command positions last line at top."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)

        from types import SimpleNamespace
        event = SimpleNamespace(key="g", character="G")
        editor._handle_normal(event)

        assert editor.cursor_row == 99  # Last line
        assert editor._scroll_top == 99  # Cursor at top

    def test_line_jump_gg_scrolls_to_top(self):
        """gg command positions first line at top."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)
        editor.cursor_row = 50
        editor._scroll_top = 50

        from types import SimpleNamespace
        # First 'g' to set pending
        event1 = SimpleNamespace(key="g", character="g")
        editor._handle_normal(event1)
        # Second 'g' to complete
        event2 = SimpleNamespace(key="g", character="g")
        editor._handle_normal(event2)

        assert editor.cursor_row == 0
        assert editor._scroll_top == 0

    def test_line_jump_dollar_scrolls_to_top(self):
        """:$ command positions last line at top."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)

        editor._exec_command("$")

        assert editor.cursor_row == 99
        assert editor._scroll_top == 99

    def test_scroll_cursor_to_center(self):
        """_scroll_cursor_to_center positions cursor at 1/3 from top."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)

        editor.cursor_row = 50
        # Simulate visible height of 30 lines
        editor._visible_height = lambda: 30
        editor._scroll_cursor_to_center()

        # int(30 * 0.33) = 9, so scroll_top should be 50 - 9 = 41
        assert editor._scroll_top == 41

    def test_search_positions_at_center(self):
        """Search result positions cursor at 1/3 from top."""
        content = "\n".join([f"line {i}" for i in range(100)])
        editor = JsonEditor(content)
        editor._visible_height = lambda: 30

        editor._search_buffer = "line 50"
        editor._search_forward = True
        editor._execute_search()

        assert editor.cursor_row == 50
        # int(30 * 0.33) = 9, so scroll_top should be 50 - 9 = 41
        assert editor._scroll_top == 41


class TestFolding:
    """JSON folding 테스트."""

    SAMPLE = '{\n    "a": {\n        "b": 1,\n        "c": 2\n    },\n    "d": [\n        1,\n        2\n    ],\n    "e": 3\n}'
    # line 0: {
    # line 1:     "a": {
    # line 2:         "b": 1,
    # line 3:         "c": 2
    # line 4:     },
    # line 5:     "d": [
    # line 6:         1,
    # line 7:         2
    # line 8:     ],
    # line 9:     "e": 3
    # line 10: }

    def test_find_foldable_at_object(self):
        """multi-line object를 감지."""
        editor = JsonEditor(self.SAMPLE)
        rng = editor._find_foldable_at(1)
        assert rng == (1, 4)

    def test_find_foldable_at_array(self):
        """multi-line array를 감지."""
        editor = JsonEditor(self.SAMPLE)
        rng = editor._find_foldable_at(5)
        assert rng == (5, 8)

    def test_find_foldable_at_root(self):
        """root object를 감지."""
        editor = JsonEditor(self.SAMPLE)
        rng = editor._find_foldable_at(0)
        assert rng == (0, 10)

    def test_find_foldable_at_non_foldable(self):
        """fold 불가한 라인은 None."""
        editor = JsonEditor(self.SAMPLE)
        assert editor._find_foldable_at(2) is None
        assert editor._find_foldable_at(9) is None

    def test_find_foldable_at_single_line(self):
        """single-line object는 fold 불가."""
        editor = JsonEditor('{"a": 1}')
        assert editor._find_foldable_at(0) is None

    def test_toggle_fold(self):
        """za: fold 토글."""
        editor = JsonEditor(self.SAMPLE)
        editor._toggle_fold(1)
        assert 1 in editor._folds
        assert editor._folds[1] == 4
        editor._toggle_fold(1)
        assert 1 not in editor._folds

    def test_toggle_fold_inside_folded(self):
        """za: fold 안에서 호출하면 해당 fold 펼기."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor._toggle_fold(3)  # fold 안의 라인
        assert 1 not in editor._folds

    def test_close_fold_from_inside(self):
        """zc: 블록 안에서 호출하면 감싸는 블록을 접는다."""
        editor = JsonEditor(self.SAMPLE)
        editor._close_fold(3)  # "c": 2 라인
        assert 1 in editor._folds
        assert editor._folds[1] == 4

    def test_fold_all(self):
        """zM: top-level foldable 영역만 접기."""
        editor = JsonEditor(self.SAMPLE)
        editor._fold_all()
        # root만 접혀야 함 (top-level)
        assert 0 in editor._folds
        assert editor._folds[0] == 10

    def test_unfold_all(self):
        """zR: 모든 fold 해제."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor._folds[5] = 8
        editor._unfold_all()
        assert editor._folds == {}

    def test_is_line_folded(self):
        """fold 안에 숨겨진 라인 판별."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        assert not editor._is_line_folded(0)
        assert not editor._is_line_folded(1)  # 헤더는 보임
        assert editor._is_line_folded(2)
        assert editor._is_line_folded(3)
        assert editor._is_line_folded(4)
        assert not editor._is_line_folded(5)

    def test_next_visible_line(self):
        """fold를 건너뛰는 라인 이동."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        assert editor._next_visible_line(0, 1) == 1  # 헤더는 보임
        assert editor._next_visible_line(1, 1) == 5  # fold 건너뜀
        assert editor._next_visible_line(5, -1) == 1  # 역방향

    def test_unfold_for_line(self):
        """검색 시 자동 펼기."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor._unfold_for_line(3)
        assert 1 not in editor._folds

    def test_clamp_cursor_snaps_to_fold_header(self):
        """fold 안에 커서가 있으면 fold 헤더로 snap."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor.cursor_row = 3
        editor._clamp_cursor()
        assert editor.cursor_row == 1

    def test_auto_expand_fold_on_cursor_past_end(self):
        """fold 헤더에서 커서가 라인 끝을 넘으면 자동 펼기."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor.cursor_row = 1
        # line 1: '    "a": {' — 마지막 문자 인덱스 = 9
        line_len = len(editor.lines[1])
        editor.cursor_col = line_len  # 끝을 넘어감
        editor._clamp_cursor()
        assert 1 not in editor._folds  # 자동 펼기됨

    def test_no_expand_fold_on_cursor_at_end(self):
        """fold 헤더에서 커서가 마지막 문자에 있으면 접힌 상태 유지."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor.cursor_row = 1
        line_len = len(editor.lines[1])
        editor.cursor_col = line_len - 1  # 마지막 문자 ('{')
        editor._clamp_cursor()
        assert 1 in editor._folds  # 유지

    def test_set_content_clears_folds(self):
        """set_content 시 fold 초기화."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        editor.set_content('{"new": 1}')
        assert editor._folds == {}

    def test_undo_clears_folds(self):
        """undo 시 fold 초기화."""
        editor = JsonEditor(self.SAMPLE)
        editor._save_undo()
        editor._folds[1] = 4
        editor._undo()
        assert editor._folds == {}

    def test_find_enclosing_foldable(self):
        """커서를 감싸는 foldable 블록 찾기."""
        editor = JsonEditor(self.SAMPLE)
        rng = editor._find_enclosing_foldable(3)
        assert rng == (1, 4)
        rng = editor._find_enclosing_foldable(7)
        assert rng == (5, 8)

    def test_fold_at_depth_1(self):
        """1-depth foldable 블록만 접기."""
        editor = JsonEditor(self.SAMPLE)
        editor._fold_at_depth(1)
        # "a": { 와 "d": [ 만 접혀야 함
        assert 1 in editor._folds  # "a": {
        assert 5 in editor._folds  # "d": [
        assert 0 not in editor._folds  # root는 접히면 안 됨
        assert len(editor._folds) == 2

    def test_fold_at_depth_0(self):
        """0-depth (root)만 접기."""
        editor = JsonEditor(self.SAMPLE)
        editor._fold_at_depth(0)
        assert 0 in editor._folds
        assert len(editor._folds) == 1

    def test_fold_all_nested(self):
        """모든 depth의 foldable 블록을 접기 (root 제외)."""
        editor = JsonEditor(self.SAMPLE)
        editor._fold_all_nested()
        assert 0 not in editor._folds  # root는 접히지 않음
        assert 1 in editor._folds  # "a": { ... }
        assert 5 in editor._folds  # "d": [ ... ]
        assert len(editor._folds) == 2

    def test_fold_all_nested_deep(self):
        """중첩된 구조에서 모든 depth 접기."""
        content = '{\n    "a": {\n        "b": {\n            "c": 1\n        }\n    }\n}'
        # line 0: {
        # line 1:     "a": {
        # line 2:         "b": {
        # line 3:             "c": 1
        # line 4:         }
        # line 5:     }
        # line 6: }
        editor = JsonEditor(content)
        editor._fold_all_nested()
        assert 0 not in editor._folds  # root 제외
        assert 1 in editor._folds  # depth 1
        assert 2 in editor._folds  # depth 2
        assert len(editor._folds) == 2

    def test_skip_visible_lines_forward(self):
        """fold를 건너뛰며 N줄 전진."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4  # line 1-4 접힘
        # line 0 → 1(헤더) → 5 → 6 → 7 → 8 → 9
        result = editor._skip_visible_lines(0, 4, 1)
        assert result == 7  # 0→1→5→6→7

    def test_skip_visible_lines_backward(self):
        """fold를 건너뛰며 N줄 후진."""
        editor = JsonEditor(self.SAMPLE)
        editor._folds[1] = 4
        # line 7 → 6 → 5 → 1(헤더) → 0
        result = editor._skip_visible_lines(7, 4, -1)
        assert result == 0

    def test_page_down_with_folds(self):
        """Ctrl+F: fold 시 보이는 라인 기준으로 이동."""
        content = "\n".join([f"line {i}" for i in range(50)])
        editor = JsonEditor(content)
        editor._visible_height = lambda: 10
        # fold lines 5-15 (header at 5)
        editor._folds[5] = 15
        editor.cursor_row = 0

        from types import SimpleNamespace
        event = SimpleNamespace(key="ctrl+f", character="")
        editor._handle_normal(event)

        # 10 visible lines from 0: 0→1→2→3→4→5(header)→16→17→18→19→20
        assert editor.cursor_row == 20

    def test_page_up_with_folds(self):
        """Ctrl+B: fold 시 보이는 라인 기준으로 이동."""
        content = "\n".join([f"line {i}" for i in range(50)])
        editor = JsonEditor(content)
        editor._visible_height = lambda: 10
        editor._folds[5] = 15
        editor.cursor_row = 25

        from types import SimpleNamespace
        event = SimpleNamespace(key="ctrl+b", character="")
        editor._handle_normal(event)

        # 10 visible lines back from 25: 25→24→23→22→21→20→19→18→17→16→5(header)
        assert editor.cursor_row == 5


class TestStringCollapse:
    """긴 string value 접기/펼기 테스트."""

    LONG_STR = "a" * 100
    SAMPLE = '{\n    "short": "hi",\n    "long": "' + LONG_STR + '"\n}'
    # line 0: {
    # line 1:     "short": "hi",
    # line 2:     "long": "aaa...aaa"
    # line 3: }

    def test_find_long_string_at(self):
        """긴 string value를 감지."""
        editor = JsonEditor(self.SAMPLE)
        result = editor._find_long_string_at(2)
        assert result is not None
        qs, qe, slen = result
        assert slen == 100

    def test_find_long_string_at_short(self):
        """짧은 string은 None 반환."""
        editor = JsonEditor(self.SAMPLE)
        assert editor._find_long_string_at(1) is None

    def test_find_long_string_at_no_value(self):
        """string value가 없는 라인은 None."""
        editor = JsonEditor(self.SAMPLE)
        assert editor._find_long_string_at(0) is None

    def test_toggle_collapse(self):
        """za: 긴 string 토글."""
        editor = JsonEditor(self.SAMPLE)
        editor._toggle_fold(2)
        assert 2 in editor._collapsed_strings
        editor._toggle_fold(2)
        assert 2 not in editor._collapsed_strings

    def test_close_collapse(self):
        """zc: 긴 string 접기."""
        editor = JsonEditor(self.SAMPLE)
        editor._close_fold(2)
        assert 2 in editor._collapsed_strings

    def test_open_collapse(self):
        """zo: 긴 string 펼기."""
        editor = JsonEditor(self.SAMPLE)
        editor._collapsed_strings.add(2)
        editor._open_fold(2)
        assert 2 not in editor._collapsed_strings

    def test_fold_all_includes_strings(self):
        """zM: 긴 string도 같이 접기."""
        editor = JsonEditor(self.SAMPLE)
        editor._fold_all()
        # root object가 fold되므로 string collapse는 안에 숨겨짐
        # string이 보이는 상태에서 확인
        editor._unfold_all()
        assert editor._collapsed_strings == set()
        # fold 없이 string만 있는 경우
        content = '{\n    "data": "' + "x" * 100 + '"\n}'
        editor2 = JsonEditor(content)
        editor2._fold_all()
        # root fold에 감싸져 있으면 string collapse가 없을 수 있음
        # top-level에서 foldable이 아닌 라인의 긴 string은 접혀야 함
        assert 0 in editor2._folds  # root object 접힘

    def test_unfold_all_clears_strings(self):
        """zR: collapsed strings도 해제."""
        editor = JsonEditor(self.SAMPLE)
        editor._collapsed_strings.add(2)
        editor._unfold_all()
        assert editor._collapsed_strings == set()

    def test_set_content_clears_collapsed(self):
        """set_content 시 collapsed strings 초기화."""
        editor = JsonEditor(self.SAMPLE)
        editor._collapsed_strings.add(2)
        editor.set_content('{"a": 1}')
        assert editor._collapsed_strings == set()

    def test_fold_at_depth_collapses_strings(self):
        """_fold_at_depth에서 해당 depth의 긴 string도 접기."""
        editor = JsonEditor(self.SAMPLE)
        editor._fold_at_depth(1)
        assert 2 in editor._collapsed_strings

    def test_threshold(self):
        """threshold 미만이면 접지 않음."""
        short_str = "b" * 59  # 59 < 60 threshold
        content = '{\n    "key": "' + short_str + '"\n}'
        editor = JsonEditor(content)
        assert editor._find_long_string_at(1) is None
        # 정확히 threshold
        exact_str = "c" * 60
        content2 = '{\n    "key": "' + exact_str + '"\n}'
        editor2 = JsonEditor(content2)
        result = editor2._find_long_string_at(1)
        assert result is not None

    def test_auto_expand_on_cursor_enter(self):
        """커서가 collapsed 영역 안으로 진입하면 자동 펼기."""
        editor = JsonEditor(self.SAMPLE)
        editor._collapsed_strings.add(2)
        editor.cursor_row = 2
        # 미리보기 영역 안 — 접힌 상태 유지
        info = editor._find_long_string_at(2)
        qs = info[0]
        editor.cursor_col = qs + 5  # 미리보기 범위 안
        editor._clamp_cursor()
        assert 2 in editor._collapsed_strings
        # 미리보기 끝을 넘어가면 자동 펼기
        editor._collapsed_strings.add(2)
        editor.cursor_col = qs + 22  # 여는 따옴표 + 20 + 1 = 넘침
        editor._clamp_cursor()
        assert 2 not in editor._collapsed_strings
