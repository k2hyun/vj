"""Fold/collapse mixin for JsonEditor."""

from __future__ import annotations


class FoldMixin:
    """Fold and collapse related methods for JsonEditor."""

    def _adjust_line_indices(self, from_line: int, delta: int) -> None:
        """라인 삽입(delta>0)/삭제(delta<0) 후 fold/collapse 인덱스 조정."""
        if delta == 0:
            return
        if delta > 0:
            new_folds = {}
            for s, e in self._folds.items():
                ns = s + delta if s >= from_line else s
                ne = e + delta if e >= from_line else e
                new_folds[ns] = ne
            self._folds = new_folds
            self._collapsed_strings = {
                (i + delta if i >= from_line else i) for i in self._collapsed_strings
            }
        else:
            abs_d = abs(delta)
            del_end = from_line + abs_d
            new_folds = {}
            for s, e in self._folds.items():
                if e < from_line:
                    new_folds[s] = e
                elif s >= del_end:
                    new_folds[s - abs_d] = e - abs_d
                elif s >= from_line:
                    continue
                elif e < del_end:
                    if from_line - 1 > s:
                        new_folds[s] = from_line - 1
                else:
                    new_folds[s] = e - abs_d
            self._folds = new_folds
            self._collapsed_strings = {
                (i - abs_d if i >= del_end else i)
                for i in self._collapsed_strings
                if not (from_line <= i < del_end)
            }

    def _find_matching_bracket_forward(
        self, row: int, col: int
    ) -> tuple[int, int] | None:
        """_search_bracket_forward와 동일하나 커서를 변경하지 않고 위치만 반환."""
        line = self.lines[row]
        if col >= len(line):
            return None
        open_ch = line[col]
        close_ch = self._BRACKET_PAIRS.get(open_ch)
        if close_ch is None:
            return None
        depth = 1
        r, c = row, col + 1
        while r < len(self.lines):
            ln = self.lines[r]
            while c < len(ln):
                if ln[c] == open_ch:
                    depth += 1
                elif ln[c] == close_ch:
                    depth -= 1
                    if depth == 0:
                        return (r, c)
                c += 1
            r += 1
            c = 0
        return None

    def _find_foldable_at(self, line_idx: int) -> tuple[int, int] | None:
        """line_idx에서 시작하는 fold 가능 범위를 반환. 없으면 None."""
        line = self.lines[line_idx]
        stripped = line.rstrip()
        if not stripped:
            return None
        last_ch = stripped[-1]
        if last_ch in ("{", "["):
            col = len(stripped) - 1
            match = self._find_matching_bracket_forward(line_idx, col)
            if match and match[0] > line_idx:
                return (line_idx, match[0])
        return None

    def _find_enclosing_foldable(self, line_idx: int) -> tuple[int, int] | None:
        """line_idx를 감싸는 가장 가까운 foldable 블록의 시작줄을 찾는다."""
        for i in range(line_idx - 1, -1, -1):
            rng = self._find_foldable_at(i)
            if rng and rng[0] < line_idx <= rng[1]:
                return rng
        return None

    def _is_line_folded(self, line_idx: int) -> bool:
        """fold 안에 숨겨진 라인인지 확인."""
        for start, end in self._folds.items():
            if start < line_idx <= end:
                return True
        return False

    def _next_visible_line(self, line_idx: int, direction: int = 1) -> int:
        """다음/이전 보이는 라인 인덱스 반환."""
        idx = line_idx + direction
        while 0 <= idx < len(self.lines):
            if not self._is_line_folded(idx):
                return idx
            idx += direction
        return line_idx

    def _skip_visible_lines(self, line_idx: int, count: int, direction: int = 1) -> int:
        """보이는 라인 기준으로 count만큼 이동."""
        idx = line_idx
        for _ in range(count):
            nxt = self._next_visible_line(idx, direction)
            if nxt == idx:
                break
            idx = nxt
        return idx

    def _unfold_for_line(self, line_idx: int) -> None:
        """line_idx를 숨기고 있는 fold를 모두 해제."""
        to_remove = [s for s, e in self._folds.items() if s < line_idx <= e]
        for s in to_remove:
            del self._folds[s]

    def _find_long_string_at(self, line_idx: int) -> tuple[int, int, int] | None:
        """라인에서 긴 string value를 찾는다.

        Returns (quote_start, quote_end, str_len) 또는 None.
        """
        line = self.lines[line_idx]
        i = 0
        while i < len(line):
            if line[i] == '"':
                start = i
                i += 1
                while i < len(line):
                    if line[i] == '"' and line[i - 1] != "\\":
                        break
                    i += 1
                end = i + 1
                before = line[:start].rstrip()
                if before.endswith(":"):
                    str_len = end - start - 2
                    if str_len >= self._string_collapse_threshold:
                        return (start, end, str_len)
            i += 1
        return None

    def _toggle_fold(self, line_idx: int) -> None:
        """za: fold 토글."""
        if line_idx in self._folds:
            del self._folds[line_idx]
            return
        rng = self._find_foldable_at(line_idx)
        if rng:
            self._folds[rng[0]] = rng[1]
            return
        for start, end in list(self._folds.items()):
            if start < line_idx <= end:
                del self._folds[start]
                return
        if line_idx in self._collapsed_strings:
            self._collapsed_strings.discard(line_idx)
            return
        if self._find_long_string_at(line_idx):
            self._collapsed_strings.add(line_idx)

    def _open_fold(self, line_idx: int) -> None:
        """zo: fold 열기."""
        if line_idx in self._folds:
            del self._folds[line_idx]
        self._collapsed_strings.discard(line_idx)

    def _close_fold(self, line_idx: int) -> None:
        """zc: fold 접기."""
        rng = self._find_foldable_at(line_idx)
        if rng:
            self._folds[rng[0]] = rng[1]
            return
        if self._find_long_string_at(line_idx):
            self._collapsed_strings.add(line_idx)
            return
        enclosing = self._find_enclosing_foldable(line_idx)
        if enclosing:
            self._folds[enclosing[0]] = enclosing[1]
            self.cursor_row = enclosing[0]

    def _fold_all(self) -> None:
        """zM: 모든 top-level foldable 영역과 긴 string 접기."""
        self._folds.clear()
        self._collapsed_strings.clear()
        i = 0
        while i < len(self.lines):
            rng = self._find_foldable_at(i)
            if rng:
                self._folds[rng[0]] = rng[1]
                i = rng[1] + 1
            else:
                if self._find_long_string_at(i):
                    self._collapsed_strings.add(i)
                i += 1

    def _unfold_all(self) -> None:
        """zR: 모든 fold 해제."""
        self._folds.clear()
        self._collapsed_strings.clear()

    def _fold_all_nested(self) -> None:
        """모든 depth의 foldable 블록과 긴 string을 접기 (root 제외)."""
        self._folds.clear()
        self._collapsed_strings.clear()
        for i in range(len(self.lines)):
            rng = self._find_foldable_at(i)
            if rng:
                self._folds[rng[0]] = rng[1]
            elif self._find_long_string_at(i):
                self._collapsed_strings.add(i)
        if 0 in self._folds:
            del self._folds[0]

    def _fold_at_depth(self, depth: int) -> None:
        """지정된 depth의 foldable 블록과 긴 string을 접기."""
        self._folds.clear()
        self._collapsed_strings.clear()
        target_indent = depth * 4
        for i, line in enumerate(self.lines):
            stripped = line.lstrip()
            if not stripped:
                continue
            indent = len(line) - len(stripped)
            if indent == target_indent:
                rng = self._find_foldable_at(i)
                if rng:
                    self._folds[rng[0]] = rng[1]
                elif self._find_long_string_at(i):
                    self._collapsed_strings.add(i)
