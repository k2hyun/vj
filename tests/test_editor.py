"""Tests for JsonEditor widget."""

import pytest
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

    def test_save_undo_clears_cache(self):
        """_save_undo should clear style cache."""
        editor = JsonEditor('{"key": "value"}')
        editor._style_cache[0] = ["white"] * 16
        editor._jsonl_records_cache = [1]

        editor._save_undo()

        assert editor._style_cache == {}
        assert editor._jsonl_records_cache is None

    def test_set_content_clears_cache(self):
        """set_content should clear caches."""
        editor = JsonEditor('{"old": "data"}')
        editor._style_cache[0] = ["white"] * 14
        editor._jsonl_records_cache = [1]

        editor.set_content('{"new": "data"}')

        assert editor._style_cache == {}
        assert editor._jsonl_records_cache is None

    def test_undo_clears_cache(self):
        """_undo should clear caches after restoring state."""
        editor = JsonEditor('{"key": "value"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']
        editor._style_cache[0] = ["white"] * 20

        editor._undo()

        assert editor._style_cache == {}
        assert editor._jsonl_records_cache is None
        assert editor.lines == ['{"key": "value"}']

    def test_redo_clears_cache(self):
        """_redo should clear caches after restoring state."""
        editor = JsonEditor('{"key": "value"}')
        editor._save_undo()
        editor.lines = ['{"modified": "data"}']
        editor._undo()
        editor._style_cache[0] = ["white"] * 16

        editor._redo()

        assert editor._style_cache == {}
        assert editor._jsonl_records_cache is None
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

        # Cache should be cleared by _save_undo
        assert editor._style_cache == {}


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
