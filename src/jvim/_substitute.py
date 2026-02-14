"""Substitute mixin for JsonEditor."""

from __future__ import annotations

import json
import re

from jvim._jsonpath import (
    get_value_at_path,
    jsonpath_find,
    jsonpath_value_matches,
    parse_jsonpath_filter,
)


class SubstituteMixin:
    """Substitute-related methods for JsonEditor."""

    def _execute_substitute(self, cmd: str) -> None:
        """치환 명령 실행: s/old/new/flags, %s/old/new/flags, N,Ms/old/new/flags"""
        if self.read_only:
            self.status_msg = "[readonly]"
            return

        range_match = re.match(r"^(%|(\d+),(\d+))?s(.)(.*)$", cmd)
        if not range_match:
            self.status_msg = "invalid substitute command"
            return

        range_spec = range_match.group(1)
        range_start_s = range_match.group(2)
        range_end_s = range_match.group(3)
        delim = range_match.group(4)
        rest = range_match.group(5)

        parts: list[str] = []
        current: list[str] = []
        i = 0
        while i < len(rest):
            if rest[i] == "\\" and i + 1 < len(rest) and rest[i + 1] == delim:
                current.append(delim)
                i += 2
            elif rest[i] == delim:
                parts.append("".join(current))
                current = []
                i += 1
            else:
                current.append(rest[i])
                i += 1
        parts.append("".join(current))

        if len(parts) < 2:
            self.status_msg = "invalid substitute command"
            return

        pattern = parts[0]
        replacement = parts[1]
        flags_str = parts[2] if len(parts) > 2 else ""

        if not pattern:
            self.status_msg = "empty pattern"
            return

        if pattern.startswith("$.") or pattern.startswith("$["):
            self._execute_substitute_jsonpath(pattern, replacement, flags_str)
            return

        global_flag = "g" in flags_str
        re_flags = 0
        if "i" in flags_str:
            re_flags |= re.IGNORECASE

        try:
            regex = re.compile(pattern, re_flags)
        except re.error as e:
            self.status_msg = f"invalid regex: {e}"
            return

        if range_spec == "%":
            start, end = 0, len(self.lines) - 1
        elif range_start_s and range_end_s:
            start = max(0, int(range_start_s) - 1)
            end = min(len(self.lines) - 1, int(range_end_s) - 1)
        else:
            start = end = self.cursor_row

        if start > end:
            self.status_msg = "invalid range"
            return

        self._save_undo()

        total_count = 0
        for row in range(start, end + 1):
            line = self.lines[row]
            if global_flag:
                new_line, count = regex.subn(replacement, line)
            else:
                new_line, count = regex.subn(replacement, line, count=1)
            if count > 0:
                self.lines[row] = new_line
                total_count += count

        if total_count == 0:
            self.undo_stack.pop()
            self.status_msg = f"Pattern not found: {pattern}"
        else:
            self.status_msg = f"{total_count} substitution(s)"
            self._invalidate_caches()

    @staticmethod
    def _json_encode_replacement(value: str) -> str:
        """replacement 값을 JSON 값으로 자동 변환."""
        if value in ("true", "false", "null"):
            return value
        try:
            float(value)
            return value
        except ValueError:
            pass
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            return value
        return json.dumps(value, ensure_ascii=False)

    def _execute_substitute_jsonpath(
        self, pattern: str, replacement: str, flags_str: str
    ) -> None:
        """JSONPath 패턴으로 JSON 키 또는 값을 치환."""
        global_flag = "g" in flags_str

        jsonpath, op, filter_value = parse_jsonpath_filter(pattern)

        key_rename = not op
        unconditional_value = op == "=" and filter_value is None

        content = self.get_content()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            self.status_msg = f"Invalid JSON: {e.msg} (line {e.lineno})"
            return

        if self.jsonl:
            self._execute_substitute_jsonpath_jsonl(
                jsonpath,
                op,
                filter_value,
                replacement,
                global_flag,
                key_rename,
                unconditional_value,
            )
            return

        try:
            results = jsonpath_find(data, jsonpath)
        except ValueError as e:
            self.status_msg = f"Invalid JSONPath: {e}"
            return

        if op and not unconditional_value:
            results = [
                p
                for p in results
                if jsonpath_value_matches(get_value_at_path(data, p), op, filter_value)
            ]

        if not results:
            self.status_msg = f"JSONPath not found: {pattern}"
            return

        if key_rename:
            key_results = [p for p in results if p and isinstance(p[-1], str)]
            if not key_results:
                self.status_msg = "No renamable keys found"
                return
            if not global_flag:
                key_results = key_results[:1]

            key_index = self._build_key_index()
            positions: list[tuple[int, int, int]] = []
            used: set[tuple[int, int]] = set()
            for json_path in key_results:
                pos = self._find_json_value_position_fast(
                    data, json_path, key_index, return_key=True
                )
                while pos and (pos[0], pos[1]) in used:
                    pos = self._find_json_value_position_fast(
                        data, json_path, key_index, pos[0], pos[1] + 1, return_key=True
                    )
                if pos:
                    used.add((pos[0], pos[1]))
                    positions.append(pos)

            if not positions:
                self.status_msg = "JSONPath matched but key positions not found"
                return

            encoded = json.dumps(replacement, ensure_ascii=False)
        else:
            leaf_results = [
                p
                for p in results
                if not isinstance(get_value_at_path(data, p), (dict, list))
            ]
            if not leaf_results:
                self.status_msg = (
                    "JSONPath matches only objects/arrays (not substitutable)"
                )
                return
            if not global_flag:
                leaf_results = leaf_results[:1]

            key_index = self._build_key_index()
            positions = []
            used = set()
            for json_path in leaf_results:
                pos = self._find_json_value_position_fast(data, json_path, key_index)
                while pos and (pos[0], pos[1]) in used:
                    pos = self._find_json_value_position_fast(
                        data, json_path, key_index, pos[0], pos[1] + 1
                    )
                if pos:
                    used.add((pos[0], pos[1]))
                    positions.append(pos)

            if not positions:
                self.status_msg = "JSONPath matched but positions not found"
                return

            encoded = self._json_encode_replacement(replacement)

        self._save_undo()

        positions.sort(key=lambda p: (p[0], p[1]), reverse=True)
        for row, col_start, col_end in positions:
            line = self.lines[row]
            self.lines[row] = line[:col_start] + encoded + line[col_end:]

        self.status_msg = f"{len(positions)} substitution(s)"
        self._invalidate_caches()

    def _execute_substitute_jsonpath_jsonl(
        self,
        jsonpath: str,
        op: str,
        filter_value: object,
        replacement: str,
        global_flag: bool,
        key_rename: bool = False,
        unconditional_value: bool = False,
    ) -> None:
        """JSONL 모드에서 JSONPath 치환."""
        blocks = self._split_jsonl_blocks(self.get_content())
        if not blocks:
            self.status_msg = "No JSONL records found"
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
                    if op and not unconditional_value:
                        actual = get_value_at_path(data, json_path)
                        if not jsonpath_value_matches(actual, op, filter_value):
                            continue
                    if key_rename:
                        if json_path and isinstance(json_path[-1], str):
                            all_results.append((block_idx, data, json_path))
                    else:
                        val = get_value_at_path(data, json_path)
                        if not isinstance(val, (dict, list)):
                            all_results.append((block_idx, data, json_path))
            except ValueError as e:
                if block_idx == 0:
                    self.status_msg = f"Invalid JSONPath: {e}"
                    return

        if not all_results:
            self.status_msg = f"JSONPath not found: {jsonpath}"
            return

        if not global_flag:
            all_results = all_results[:1]

        key_index = self._build_key_index()
        positions: list[tuple[int, int, int]] = []
        for block_idx, data, json_path in all_results:
            start_line = block_start_lines.get(block_idx, 0)
            pos = self._find_json_value_position_fast(
                data, json_path, key_index, start_line, return_key=key_rename
            )
            if pos:
                positions.append(pos)

        if not positions:
            self.status_msg = "JSONPath matched but positions not found"
            return

        encoded = (
            json.dumps(replacement, ensure_ascii=False)
            if key_rename
            else self._json_encode_replacement(replacement)
        )

        self._save_undo()

        positions.sort(key=lambda p: (p[0], p[1]), reverse=True)
        for row, col_start, col_end in positions:
            line = self.lines[row]
            self.lines[row] = line[:col_start] + encoded + line[col_end:]

        self.status_msg = f"{len(positions)} substitution(s)"
        self._invalidate_caches()
