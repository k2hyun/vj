"""Search mixin for JsonEditor."""

from __future__ import annotations

import json
import re

from jvim._jsonpath import (
    get_value_at_path,
    jsonpath_find,
    jsonpath_value_matches,
    parse_jsonpath_filter,
)


class SearchMixin:
    """Search-related methods for JsonEditor."""

    def _handle_search(self, event) -> None:
        key = event.key
        char = event.character

        if key == "escape":
            from jvim.widget import EditorMode

            self._mode = EditorMode.NORMAL
            self._search_buffer = ""
            self._search_history_idx = -1
            self.status_msg = ""
            return

        if key == "enter":
            from jvim.widget import EditorMode

            if self._search_buffer:
                self._add_to_search_history(self._search_buffer)
                self._execute_search()
            self._mode = EditorMode.NORMAL
            self._search_history_idx = -1
            return

        if key == "backspace":
            if self._search_buffer:
                self._search_buffer = self._search_buffer[:-1]
                self._search_history_idx = -1
            else:
                from jvim.widget import EditorMode

                self._mode = EditorMode.NORMAL
                self._search_history_idx = -1
            return

        if key == "up":
            self._search_history_prev()
            return
        if key == "down":
            self._search_history_next()
            return

        if char and char.isprintable():
            self._search_buffer += char
            self._search_history_idx = -1

    def _add_to_search_history(self, pattern: str) -> None:
        """Add pattern to search history, avoiding duplicates."""
        if not pattern:
            return
        if pattern in self._search_history:
            self._search_history.remove(pattern)
        self._search_history.insert(0, pattern)
        if len(self._search_history) > self._search_history_max:
            self._search_history.pop()

    def _search_history_prev(self) -> None:
        """Navigate to previous search in history."""
        if not self._search_history:
            return
        if self._search_history_idx < len(self._search_history) - 1:
            self._search_history_idx += 1
            self._search_buffer = self._search_history[self._search_history_idx]

    def _search_history_next(self) -> None:
        """Navigate to next search in history."""
        if self._search_history_idx > 0:
            self._search_history_idx -= 1
            self._search_buffer = self._search_history[self._search_history_idx]
        elif self._search_history_idx == 0:
            self._search_history_idx = -1
            self._search_buffer = ""

    def _build_search_row_index(self) -> None:
        """Build row-indexed lookup for search matches."""
        self._search_match_by_row = {}
        for mi, (row, start, end) in enumerate(self._search_matches):
            if row not in self._search_match_by_row:
                self._search_match_by_row[row] = []
            self._search_match_by_row[row].append((start, end, mi))

    def _execute_search(self) -> None:
        """Execute search and find all matches."""
        pattern = self._search_buffer
        self._search_pattern = pattern

        if pattern.endswith("\\j"):
            self._execute_jsonpath_search(pattern[:-2])
            return
        if pattern.startswith("$.") or pattern.startswith("$["):
            self._execute_jsonpath_search(pattern)
            return

        flags = 0
        if pattern.endswith("\\c"):
            pattern = pattern[:-2]
            flags = re.IGNORECASE
        elif pattern.endswith("\\C"):
            pattern = pattern[:-2]
        elif pattern.islower():
            flags = re.IGNORECASE

        self._search_matches = []
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            self.status_msg = f"Invalid pattern: {e}"
            self._search_match_by_row = {}
            self._current_match = -1
            return

        for row, line in enumerate(self.lines):
            for match in regex.finditer(line):
                self._search_matches.append((row, match.start(), match.end()))
        self._build_search_row_index()

        if not self._search_matches:
            self.status_msg = f"Pattern not found: {self._search_pattern}"
            self._current_match = -1
            return

        self._current_match = self._find_match_near_cursor()
        self._goto_current_match()

    def _execute_jsonpath_search(self, path: str) -> None:
        """Execute JSONPath search and find all matches."""
        if self.jsonl:
            self._execute_jsonpath_search_jsonl(path)
            return

        jsonpath, op, filter_value = parse_jsonpath_filter(path)

        content = self.get_content()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            self.status_msg = f"Invalid JSON: {e.msg} (line {e.lineno})"
            return

        try:
            results = jsonpath_find(data, jsonpath)
        except ValueError as e:
            self.status_msg = f"Invalid JSONPath: {e}"
            return

        if op:
            results = [
                p
                for p in results
                if jsonpath_value_matches(get_value_at_path(data, p), op, filter_value)
            ]

        if not results:
            self.status_msg = f"JSONPath not found: {path}"
            self._search_matches = []
            self._search_match_by_row = {}
            self._current_match = -1
            return

        key_index = self._build_key_index()

        self._search_matches = []
        for json_path in results:
            pos = self._find_json_value_position_fast(data, json_path, key_index)
            if pos:
                self._search_matches.append(pos)
        self._build_search_row_index()

        if not self._search_matches:
            self.status_msg = "JSONPath matched but positions not found"
            self._current_match = -1
            return

        self._current_match = self._find_match_near_cursor()
        self._goto_current_match()

    def _execute_jsonpath_search_jsonl(self, path: str) -> None:
        """Execute JSONPath search across JSONL records."""
        jsonpath, op, filter_value = parse_jsonpath_filter(path)

        blocks = self._split_jsonl_blocks(self.get_content())

        if not blocks:
            self.status_msg = "No JSONL records found"
            self._search_matches = []
            self._current_match = -1
            return

        block_start_lines = self._compute_block_start_lines()

        all_results: list[tuple[int, object, list[str | int]]] = []
        for block_idx, block in enumerate(blocks):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue

            try:
                results = jsonpath_find(data, jsonpath)
                for json_path in results:
                    if op:
                        actual = get_value_at_path(data, json_path)
                        if not jsonpath_value_matches(actual, op, filter_value):
                            continue
                    all_results.append((block_idx, data, json_path))
            except ValueError:
                if block_idx == 0:
                    self.status_msg = f"Invalid JSONPath: {jsonpath}"
                    self._search_matches = []
                    self._current_match = -1
                    return

        if not all_results:
            self.status_msg = f"JSONPath not found: {path}"
            self._search_matches = []
            self._search_match_by_row = {}
            self._current_match = -1
            return

        key_index = self._build_key_index()

        self._search_matches = []
        for block_idx, data, json_path in all_results:
            start_line = block_start_lines.get(block_idx, 0)
            pos = self._find_json_value_position_fast(
                data, json_path, key_index, start_line
            )
            if pos:
                self._search_matches.append(pos)
        self._build_search_row_index()

        if not self._search_matches:
            self.status_msg = "JSONPath matched but positions not found"
            self._current_match = -1
            return

        self._current_match = self._find_match_near_cursor()
        self._goto_current_match()

    def _build_key_index(self) -> dict[str, list[tuple[int, int]]]:
        """Build an index of JSON keys to their (row, col) positions."""
        index: dict[str, list[tuple[int, int]]] = {}
        for row, line in enumerate(self.lines):
            col = 0
            while col < len(line):
                quote_pos = line.find('"', col)
                if quote_pos == -1:
                    break
                end_pos = quote_pos + 1
                while end_pos < len(line):
                    if line[end_pos] == '"' and line[end_pos - 1] != "\\":
                        break
                    end_pos += 1
                if end_pos >= len(line):
                    break
                after = end_pos + 1
                while after < len(line) and line[after] in " \t":
                    after += 1
                if after < len(line) and line[after] == ":":
                    key = line[quote_pos : end_pos + 1]
                    if key not in index:
                        index[key] = []
                    index[key].append((row, quote_pos))
                col = end_pos + 1
        return index

    def _compute_block_start_lines(self) -> dict[int, int]:
        """Compute the starting line number for each JSONL block."""
        result: dict[int, int] = {}
        block_idx = 0
        in_block = False
        for i, line in enumerate(self.lines):
            if line.strip():
                if not in_block:
                    result[block_idx] = i
                    block_idx += 1
                    in_block = True
            else:
                in_block = False
        return result

    def _find_json_value_position_fast(
        self,
        data: object,
        path: list[str | int],
        key_index: dict[str, list[tuple[int, int]]],
        start_line: int = 0,
        min_col: int = 0,
        return_key: bool = False,
    ) -> tuple[int, int, int] | None:
        """Find text position using pre-built key index.

        return_key=True이면 값 대신 키 위치를 반환.
        """
        current = data
        for key in path:
            if isinstance(current, dict):
                if key not in current:
                    return None
                current = current[key]
            elif isinstance(current, list) and isinstance(key, int):
                if 0 <= key < len(current):
                    current = current[key]
                else:
                    return None
            else:
                return None

        is_complex = isinstance(current, (dict, list))

        if path:
            last_key = path[-1]
            if isinstance(last_key, str):
                key_pattern = json.dumps(last_key, ensure_ascii=False)
                positions = key_index.get(key_pattern, [])

                for row, col in positions:
                    if row > start_line or (row == start_line and col >= min_col):
                        if return_key:
                            return (row, col, col + len(key_pattern))
                        if is_complex:
                            return (row, col, col + len(key_pattern))
                        else:
                            line = self.lines[row]
                            value_start = col + len(key_pattern)
                            while (
                                value_start < len(line) and line[value_start] in ": \t"
                            ):
                                value_start += 1
                            target_str = json.dumps(current, ensure_ascii=False)
                            if line[value_start:].startswith(target_str):
                                return (row, value_start, value_start + len(target_str))
                            value_end = self._find_value_end(line, value_start)
                            if value_end > value_start:
                                return (row, value_start, value_end)
                return None
            else:
                if is_complex:
                    return None
                target_str = json.dumps(current, ensure_ascii=False)
                for row in range(start_line, len(self.lines)):
                    line = self.lines[row]
                    search_start = min_col if row == start_line else 0
                    pos = line.find(target_str, search_start)
                    if pos >= 0:
                        return (row, pos, pos + len(target_str))
                return None
        return None

    @staticmethod
    def _find_value_end(line: str, start: int) -> int:
        """Find the end position of a JSON value starting at start."""
        if start >= len(line):
            return start
        ch = line[start]
        if ch == '"':
            i = start + 1
            while i < len(line):
                if line[i] == '"' and line[i - 1] != "\\":
                    return i + 1
                i += 1
            return len(line)
        elif ch in "-0123456789":
            i = start + 1
            while i < len(line) and line[i] in "0123456789.eE+-":
                i += 1
            return i
        elif line[start : start + 4] == "true":
            return start + 4
        elif line[start : start + 5] == "false":
            return start + 5
        elif line[start : start + 4] == "null":
            return start + 4
        return start

    def _find_match_near_cursor(self) -> int:
        """Find the index of the match nearest to cursor in search direction."""
        if not self._search_matches:
            return -1

        cursor_pos = (self.cursor_row, self.cursor_col)

        if self._search_forward:
            for i, (row, col_start, _) in enumerate(self._search_matches):
                if (row, col_start) >= cursor_pos:
                    return i
            return 0
        else:
            for i in range(len(self._search_matches) - 1, -1, -1):
                row, col_start, _ = self._search_matches[i]
                if (row, col_start) <= cursor_pos:
                    return i
            return len(self._search_matches) - 1

    def _goto_current_match(self) -> None:
        """Move cursor to the current match and update status."""
        if not self._search_matches or self._current_match < 0:
            return

        row, col_start, _ = self._search_matches[self._current_match]
        self._unfold_for_line(row)
        self.cursor_row = row
        self.cursor_col = col_start
        self._scroll_cursor_to_center()
        total = len(self._search_matches)
        self.status_msg = (
            f"/{self._search_pattern}  [{self._current_match + 1}/{total}]"
        )

    def _goto_next_match(self) -> None:
        """Go to the next search match."""
        if not self._search_matches:
            if self._search_pattern:
                self.status_msg = f"Pattern not found: {self._search_pattern}"
            else:
                self.status_msg = "No previous search"
            return

        self.cursor_col += 1
        self._current_match = self._find_match_near_cursor()
        self._goto_current_match()

    def _goto_prev_match(self) -> None:
        """Go to the previous search match."""
        if not self._search_matches:
            if self._search_pattern:
                self.status_msg = f"Pattern not found: {self._search_pattern}"
            else:
                self.status_msg = "No previous search"
            return

        self.cursor_col -= 1
        if self.cursor_col < 0:
            self.cursor_row -= 1
            if self.cursor_row < 0:
                self.cursor_row = len(self.lines) - 1
            self.cursor_col = len(self.lines[self.cursor_row])

        cursor_pos = (self.cursor_row, self.cursor_col)
        found = -1
        for i in range(len(self._search_matches) - 1, -1, -1):
            row, col_start, _ = self._search_matches[i]
            if (row, col_start) <= cursor_pos:
                found = i
                break

        if found >= 0:
            self._current_match = found
        else:
            self._current_match = len(self._search_matches) - 1

        self._goto_current_match()
