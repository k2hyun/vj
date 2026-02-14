"""Visual mode mixin for JsonEditor."""

from __future__ import annotations


class VisualMixin:
    """Visual mode related methods for JsonEditor."""

    def _visual_selection_range(self) -> tuple[int, int, int, int]:
        """선택 범위 반환: (start_row, start_col, end_row, end_col)."""
        ar, ac = self._visual_anchor_row, self._visual_anchor_col
        cr, cc = self.cursor_row, self.cursor_col
        if self._visual_mode == "V":
            if ar <= cr:
                return (ar, 0, cr, len(self.lines[cr]))
            else:
                return (cr, 0, ar, len(self.lines[ar]))
        if (ar, ac) <= (cr, cc):
            return (ar, ac, cr, cc)
        else:
            return (cr, cc, ar, ac)

    def _execute_visual_operator(self, op: str) -> None:
        """Visual 선택에 대해 d/y/c 연산자 실행."""
        if op in ("d", "c") and self._check_readonly():
            self._visual_mode = ""
            return
        if self._visual_mode == "V":
            self._execute_visual_linewise(op)
        else:
            self._execute_visual_charwise(op)
        self._visual_mode = ""

    def _execute_visual_linewise(self, op: str) -> None:
        """Line-wise visual 연산자 (V 모드)."""
        sr, _sc, er, _ec = self._visual_selection_range()
        selected = self.lines[sr : er + 1]
        self._yank_type = "line"
        if op == "y":
            self.yank_buffer = selected[:]
            self.cursor_row = sr
            self.cursor_col = 0
            self.status_msg = f"{len(selected)} lines yanked"
            return
        self._save_undo()
        self.yank_buffer = selected[:]
        deleted_count = er - sr + 1
        if er < len(self.lines) - 1 or sr > 0:
            self.lines[sr : er + 1] = []
            self._adjust_line_indices(sr, -deleted_count)
            if not self.lines:
                self.lines = [""]
        else:
            self.lines[sr : er + 1] = [""]
            self._folds.clear()
            self._collapsed_strings.clear()
        self.cursor_row = min(sr, len(self.lines) - 1)
        self.cursor_col = 0
        if op == "c":
            indent = (
                len(selected[0]) - len(selected[0].lstrip())
                if selected[0].strip()
                else 0
            )
            if len(self.lines) == 1 and self.lines[0] == "":
                self.lines[0] = " " * indent
            else:
                self.lines.insert(self.cursor_row, " " * indent)
                self._adjust_line_indices(self.cursor_row, 1)
            self.cursor_col = indent
            self._enter_insert()
        else:
            self.status_msg = f"{len(selected)} lines deleted"

    def _execute_visual_charwise(self, op: str) -> None:
        """Char-wise visual 연산자 (v 모드)."""
        sr, sc, er, ec = self._visual_selection_range()
        self._yank_type = "char"
        if sr == er:
            text = self.lines[sr][sc : ec + 1]
        else:
            parts = [self.lines[sr][sc:]]
            for r in range(sr + 1, er):
                parts.append(self.lines[r])
            parts.append(self.lines[er][: ec + 1])
            text = "\n".join(parts)
        if op == "y":
            self.yank_buffer = [text]
            self.cursor_row = sr
            self.cursor_col = sc
            self.status_msg = "yanked"
            return
        self._save_undo()
        self.yank_buffer = [text]
        if sr == er:
            line = self.lines[sr]
            self.lines[sr] = line[:sc] + line[ec + 1 :]
        else:
            before = self.lines[sr][:sc]
            after = self.lines[er][ec + 1 :]
            self.lines[sr] = before + after
            deleted_count = er - sr
            del self.lines[sr + 1 : er + 1]
            self._adjust_line_indices(sr + 1, -deleted_count)
        self.cursor_row = sr
        self.cursor_col = sc
        if op == "c":
            self._enter_insert()
        else:
            self.status_msg = "deleted"
