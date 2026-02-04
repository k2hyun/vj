"""Modal JSON editor widget."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto

from rich.text import Text
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget


class EditorMode(Enum):
    NORMAL = auto()
    INSERT = auto()
    COMMAND = auto()


class JsonEditor(Widget, can_focus=True):
    """A modal JSON editor Textual widget.

    Supported commands:
      NORMAL: h j k l  w b  0 $ ^  gg G  %  i I a A o O
              x  dd dw d$  cw cc  r{c}  J  yy p P  u
      INSERT: typing / Backspace / Enter / Tab / Escape
      COMMAND: :w :q :wq :fmt
    """

    DEFAULT_CSS = """
    JsonEditor {
        height: 1fr;
        background: $surface;
        padding: 0 1;
    }
    """

    mode: reactive[EditorMode] = reactive(EditorMode.NORMAL)

    # -- Messages ----------------------------------------------------------

    @dataclass
    class JsonValidated(Message):
        content: str
        valid: bool
        error: str = ""

    @dataclass
    class Quit(Message):
        pass

    # -- Init --------------------------------------------------------------

    def __init__(
        self,
        initial_content: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.lines: list[str] = (
            initial_content.split("\n") if initial_content else [""]
        )
        self.cursor_row: int = 0
        self.cursor_col: int = 0
        self._mode: EditorMode = EditorMode.NORMAL
        self.command_buffer: str = ""
        self.pending: str = ""
        self.status_msg: str = ""
        self.undo_stack: list[tuple[list[str], int, int]] = []
        self.yank_buffer: list[str] = []
        self.scroll_offset: int = 0

    # -- Helpers -----------------------------------------------------------

    def _save_undo(self) -> None:
        self.undo_stack.append(
            ([line for line in self.lines], self.cursor_row, self.cursor_col)
        )
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)

    def _clamp_cursor(self) -> None:
        self.cursor_row = max(0, min(self.cursor_row, len(self.lines) - 1))
        line_len = len(self.lines[self.cursor_row])
        if self._mode == EditorMode.NORMAL:
            max_col = max(0, line_len - 1) if line_len else 0
        else:
            max_col = line_len
        self.cursor_col = max(0, min(self.cursor_col, max_col))

    def _visible_height(self) -> int:
        return max(1, self.size.height - 2)

    def _ensure_cursor_visible(self) -> None:
        vh = self._visible_height()
        if self.cursor_row < self.scroll_offset:
            self.scroll_offset = self.cursor_row
        elif self.cursor_row >= self.scroll_offset + vh:
            self.scroll_offset = self.cursor_row - vh + 1

    # -- Public API --------------------------------------------------------

    def get_content(self) -> str:
        return "\n".join(self.lines)

    def set_content(self, content: str) -> None:
        self.lines = content.split("\n") if content else [""]
        self.cursor_row = 0
        self.cursor_col = 0
        self.refresh()

    # =====================================================================
    # Rendering
    # =====================================================================

    def render(self) -> Text:
        width = self.size.width - 2
        height = self.size.height
        if height < 3 or width < 10:
            return Text("(too small)")

        content_height = height - 2
        self._ensure_cursor_visible()

        result = Text()
        ln_width = max(3, len(str(len(self.lines))))

        for i in range(content_height):
            line_idx = self.scroll_offset + i
            if line_idx < len(self.lines):
                line = self.lines[line_idx]
                result.append(f"{line_idx + 1:>{ln_width}} ", style="dim cyan")
                if line_idx == self.cursor_row:
                    self._render_cursor_line(result, line)
                else:
                    self._render_line(result, line)
            else:
                result.append(f"{'~':>{ln_width}} \n", style="dim blue")

        # status bar
        mode_style = {
            EditorMode.NORMAL: "bold white on dark_green",
            EditorMode.INSERT: "bold white on dark_blue",
            EditorMode.COMMAND: "bold white on dark_red",
        }
        mode_label = f" {self._mode.name} "
        result.append(mode_label, style=mode_style[self._mode])

        if self.pending:
            result.append(f"  {self.pending}", style="bold yellow")

        pos = f" Ln {self.cursor_row + 1}/{len(self.lines)}, Col {self.cursor_col + 1} "
        spacer = max(
            0, width - len(mode_label) - len(pos) - len(self.status_msg) - 4
        )
        result.append(f"  {self.status_msg}")
        result.append(" " * spacer)
        result.append(pos, style="bold")

        if self._mode == EditorMode.COMMAND:
            result.append(f"\n:{self.command_buffer}", style="bold yellow")
        else:
            result.append("\n")

        return result

    # -- Syntax colouring helpers ------------------------------------------

    _BRACKET = set("{}[]")
    _PUNCT = set(":,")
    _DIGIT = set("0123456789.-+eE")

    def _json_style_for(self, line: str, col: int) -> str:
        ch = line[col]
        if ch in self._BRACKET:
            return "bold white"
        if ch in self._PUNCT:
            return "white"

        in_str = False
        for i in range(col + 1):
            if line[i] == '"' and (i == 0 or line[i - 1] != "\\"):
                in_str = not in_str

        if in_str or ch == '"':
            colon_pos = self._first_unquoted_colon(line)
            return "cyan" if (colon_pos == -1 or col < colon_pos) else "green"

        if ch in self._DIGIT:
            return "yellow"

        for kw in ("true", "false", "null"):
            p = line.lower().find(kw)
            if p != -1 and p <= col < p + len(kw):
                return "magenta"

        return "white"

    @staticmethod
    def _first_unquoted_colon(line: str) -> int:
        in_str = False
        for i, c in enumerate(line):
            if c == '"' and (i == 0 or line[i - 1] != "\\"):
                in_str = not in_str
            elif c == ":" and not in_str:
                return i
        return -1

    def _render_cursor_line(self, out: Text, line: str) -> None:
        for col, ch in enumerate(line):
            style = self._json_style_for(line, col)
            if col == self.cursor_col:
                out.append(ch, style=f"reverse {style}")
            else:
                out.append(ch, style=style)
        if self.cursor_col >= len(line):
            out.append(" ", style="reverse")
        out.append("\n")

    def _render_line(self, out: Text, line: str) -> None:
        for col, ch in enumerate(line):
            out.append(ch, style=self._json_style_for(line, col))
        out.append("\n")

    # =====================================================================
    # Key handling
    # =====================================================================

    def on_key(self, event: events.Key) -> None:
        event.prevent_default()
        event.stop()

        if self._mode == EditorMode.NORMAL:
            self._handle_normal(event)
        elif self._mode == EditorMode.INSERT:
            self._handle_insert(event)
        elif self._mode == EditorMode.COMMAND:
            self._handle_command(event)

        self._clamp_cursor()
        self.refresh()

    # -- NORMAL ------------------------------------------------------------

    def _enter_insert(self) -> None:
        self._mode = EditorMode.INSERT
        self.status_msg = "-- INSERT --"

    def _handle_normal(self, event: events.Key) -> None:
        key = event.key
        char = event.character or ""

        if self.pending:
            self._handle_pending(char, key)
            return

        # movement
        if char == "h" or key == "left":
            self.cursor_col -= 1
        elif char == "j" or key == "down":
            self.cursor_row += 1
        elif char == "k" or key == "up":
            self.cursor_row -= 1
        elif char == "l" or key == "right":
            self.cursor_col += 1
        elif char == "w":
            self._move_word_forward()
        elif char == "b":
            self._move_word_backward()
        elif char == "0":
            self.cursor_col = 0
        elif char == "$" or key == "end":
            self.cursor_col = max(0, len(self.lines[self.cursor_row]) - 1)
        elif char == "^" or key == "home":
            line = self.lines[self.cursor_row]
            self.cursor_col = len(line) - len(line.lstrip())
        elif char == "G":
            self.cursor_row = len(self.lines) - 1
        elif char == "%":
            self._jump_matching_bracket()
        elif key == "pagedown":
            self.cursor_row += self._visible_height()
        elif key == "pageup":
            self.cursor_row -= self._visible_height()

        # enter insert mode
        elif char == "i":
            self._enter_insert()
        elif char == "I":
            line = self.lines[self.cursor_row]
            self.cursor_col = len(line) - len(line.lstrip())
            self._enter_insert()
        elif char == "a":
            self.cursor_col += 1
            self._enter_insert()
        elif char == "A":
            self.cursor_col = len(self.lines[self.cursor_row])
            self._enter_insert()
        elif char == "o":
            self._save_undo()
            indent = self._current_indent()
            before = self.lines[self.cursor_row].rstrip()
            extra = "    " if before.endswith(("{", "[")) else ""
            self.cursor_row += 1
            self.lines.insert(self.cursor_row, " " * indent + extra)
            self.cursor_col = indent + len(extra)
            self._enter_insert()
        elif char == "O":
            self._save_undo()
            indent = self._current_indent()
            self.lines.insert(self.cursor_row, " " * indent)
            self.cursor_col = indent
            self._enter_insert()

        # single-key edits
        elif char == "x":
            self._save_undo()
            line = self.lines[self.cursor_row]
            if line and self.cursor_col < len(line):
                self.lines[self.cursor_row] = (
                    line[: self.cursor_col] + line[self.cursor_col + 1 :]
                )
        elif char == "p":
            self._paste_after()
        elif char == "P":
            self._paste_before()
        elif char == "u":
            self._undo()
        elif char == "J":
            self._join_lines()

        # multi-key starters
        elif char in ("d", "c", "y", "r", "g"):
            self.pending = char

        # command mode
        elif char == ":":
            self._mode = EditorMode.COMMAND
            self.command_buffer = ""
            self.status_msg = ""

    # -- Pending multi-char ------------------------------------------------

    def _handle_pending(self, char: str, key: str) -> None:
        if key == "escape" or not char:
            self.pending = ""
            self.status_msg = ""
            return

        combo = self.pending + char
        self.pending = ""

        if combo == "dd":
            self._save_undo()
            self.yank_buffer = [self.lines[self.cursor_row]]
            if len(self.lines) > 1:
                self.lines.pop(self.cursor_row)
                if self.cursor_row >= len(self.lines):
                    self.cursor_row = len(self.lines) - 1
            else:
                self.lines[0] = ""
            self.cursor_col = 0
            self.status_msg = "line deleted"

        elif combo == "dw":
            self._save_undo()
            self._delete_word()

        elif combo == "d$":
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = line[: self.cursor_col]

        elif combo == "d0":
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = line[self.cursor_col :]
            self.cursor_col = 0

        elif combo == "cw":
            self._save_undo()
            self._delete_word()
            self._enter_insert()

        elif combo == "cc":
            self._save_undo()
            indent = self._current_indent()
            self.yank_buffer = [self.lines[self.cursor_row]]
            self.lines[self.cursor_row] = " " * indent
            self.cursor_col = indent
            self._enter_insert()

        elif combo == "yy":
            self.yank_buffer = [self.lines[self.cursor_row]]
            self.status_msg = "line yanked"

        elif combo == "gg":
            self.cursor_row = 0
            self.cursor_col = 0

        elif len(combo) == 2 and combo[0] == "r":
            self._save_undo()
            line = self.lines[self.cursor_row]
            if self.cursor_col < len(line):
                self.lines[self.cursor_row] = (
                    line[: self.cursor_col] + combo[1] + line[self.cursor_col + 1 :]
                )
        else:
            self.status_msg = f"unknown: {combo}"

    # -- INSERT ------------------------------------------------------------

    def _handle_insert(self, event: events.Key) -> None:
        key = event.key
        char = event.character

        if key == "escape":
            self._mode = EditorMode.NORMAL
            self.cursor_col = max(0, self.cursor_col - 1)
            self.status_msg = ""
            return

        if key == "backspace":
            self._save_undo()
            if self.cursor_col > 0:
                line = self.lines[self.cursor_row]
                self.lines[self.cursor_row] = (
                    line[: self.cursor_col - 1] + line[self.cursor_col :]
                )
                self.cursor_col -= 1
            elif self.cursor_row > 0:
                prev = self.lines[self.cursor_row - 1]
                self.cursor_col = len(prev)
                self.lines[self.cursor_row - 1] = prev + self.lines[self.cursor_row]
                self.lines.pop(self.cursor_row)
                self.cursor_row -= 1
            return

        if key == "enter":
            self._save_undo()
            line = self.lines[self.cursor_row]
            indent = len(line) - len(line.lstrip()) if line.strip() else 0
            before = line[: self.cursor_col].rstrip()
            after = line[self.cursor_col :].lstrip()

            if before.endswith(("{", "[")) and after and after[0] in ("}", "]"):
                closing_indent = " " * indent
                new_indent = " " * indent + "    "
                self.lines[self.cursor_row] = line[: self.cursor_col]
                self.lines.insert(self.cursor_row + 1, new_indent)
                self.lines.insert(
                    self.cursor_row + 2,
                    closing_indent + line[self.cursor_col :].lstrip(),
                )
                self.cursor_row += 1
                self.cursor_col = len(new_indent)
                return

            extra = "    " if before.endswith(("{", "[")) else ""
            self.lines[self.cursor_row] = line[: self.cursor_col]
            new_line = " " * indent + extra + line[self.cursor_col :]
            self.cursor_row += 1
            self.lines.insert(self.cursor_row, new_line)
            self.cursor_col = indent + len(extra)
            return

        if key == "tab":
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = (
                line[: self.cursor_col] + "    " + line[self.cursor_col :]
            )
            self.cursor_col += 4
            return

        if key in ("left", "right", "up", "down"):
            delta = {"left": (0, -1), "right": (0, 1), "up": (-1, 0), "down": (1, 0)}
            dr, dc = delta[key]
            self.cursor_row += dr
            self.cursor_col += dc
            return

        # auto-dedent for closing brackets
        if char in ("}", "]"):
            self._save_undo()
            line = self.lines[self.cursor_row]
            before = line[: self.cursor_col]
            if before.strip() == "":
                new_indent = max(0, len(before) - 4)
                self.lines[self.cursor_row] = (
                    " " * new_indent + char + line[self.cursor_col :]
                )
                self.cursor_col = new_indent + 1
                return

        if char and char.isprintable():
            self._save_undo()
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = (
                line[: self.cursor_col] + char + line[self.cursor_col :]
            )
            self.cursor_col += 1

    # -- COMMAND -----------------------------------------------------------

    def _handle_command(self, event: events.Key) -> None:
        key = event.key
        char = event.character

        if key == "escape":
            self._mode = EditorMode.NORMAL
            self.command_buffer = ""
            self.status_msg = ""
            return

        if key == "enter":
            self._exec_command(self.command_buffer.strip())
            if self._mode == EditorMode.COMMAND:
                self._mode = EditorMode.NORMAL
            self.command_buffer = ""
            return

        if key == "backspace":
            if self.command_buffer:
                self.command_buffer = self.command_buffer[:-1]
            else:
                self._mode = EditorMode.NORMAL
            return

        if char and char.isprintable():
            self.command_buffer += char

    def _exec_command(self, cmd: str) -> None:
        if cmd == "w":
            self._validate_json()
        elif cmd == "q":
            self.post_message(self.Quit())
        elif cmd in ("wq", "x"):
            if self._validate_json():
                self.post_message(self.Quit())
        elif cmd in ("fmt", "format"):
            self._format_json()
        else:
            self.status_msg = f"unknown command: :{cmd}"

    # -- JSON operations ---------------------------------------------------

    def _validate_json(self) -> bool:
        content = self.get_content()
        try:
            json.loads(content)
            self.status_msg = "JSON valid"
            self.post_message(self.JsonValidated(content=content, valid=True))
            return True
        except json.JSONDecodeError as e:
            self.status_msg = f"JSON error: {e.msg} (line {e.lineno})"
            self.post_message(
                self.JsonValidated(content=content, valid=False, error=str(e))
            )
            return False

    def _format_json(self) -> None:
        content = self.get_content()
        try:
            parsed = json.loads(content)
            formatted = json.dumps(parsed, indent=4, ensure_ascii=False)
            self._save_undo()
            self.lines = formatted.split("\n")
            self.cursor_row = 0
            self.cursor_col = 0
            self.status_msg = "formatted"
        except json.JSONDecodeError as e:
            self.status_msg = f"cannot format: {e.msg} (line {e.lineno})"

    # -- Movement helpers --------------------------------------------------

    def _current_indent(self) -> int:
        line = self.lines[self.cursor_row]
        return len(line) - len(line.lstrip()) if line.strip() else 0

    def _move_word_forward(self) -> None:
        line = self.lines[self.cursor_row]
        col = self.cursor_col
        while col < len(line) and (line[col].isalnum() or line[col] == "_"):
            col += 1
        while col < len(line) and not (line[col].isalnum() or line[col] == "_"):
            col += 1
        if col >= len(line) and self.cursor_row < len(self.lines) - 1:
            self.cursor_row += 1
            nline = self.lines[self.cursor_row]
            self.cursor_col = len(nline) - len(nline.lstrip())
        else:
            self.cursor_col = min(col, max(0, len(line) - 1))

    def _move_word_backward(self) -> None:
        line = self.lines[self.cursor_row]
        col = self.cursor_col
        if col == 0:
            if self.cursor_row > 0:
                self.cursor_row -= 1
                self.cursor_col = max(0, len(self.lines[self.cursor_row]) - 1)
            return
        col -= 1
        while col > 0 and not (line[col].isalnum() or line[col] == "_"):
            col -= 1
        while col > 0 and (line[col - 1].isalnum() or line[col - 1] == "_"):
            col -= 1
        self.cursor_col = col

    def _jump_matching_bracket(self) -> None:
        line = self.lines[self.cursor_row]
        if self.cursor_col >= len(line):
            return
        ch = line[self.cursor_col]
        pairs = {"{": "}", "[": "]", "(": ")"}
        rpairs = {v: k for k, v in pairs.items()}
        if ch in pairs:
            self._search_bracket_forward(ch, pairs[ch])
        elif ch in rpairs:
            self._search_bracket_backward(ch, rpairs[ch])

    def _search_bracket_forward(self, open_ch: str, close_ch: str) -> None:
        depth = 1
        row, col = self.cursor_row, self.cursor_col + 1
        while row < len(self.lines):
            line = self.lines[row]
            while col < len(line):
                if line[col] == open_ch:
                    depth += 1
                elif line[col] == close_ch:
                    depth -= 1
                    if depth == 0:
                        self.cursor_row, self.cursor_col = row, col
                        return
                col += 1
            row += 1
            col = 0

    def _search_bracket_backward(self, close_ch: str, open_ch: str) -> None:
        depth = 1
        row, col = self.cursor_row, self.cursor_col - 1
        while row >= 0:
            line = self.lines[row]
            while col >= 0:
                if line[col] == close_ch:
                    depth += 1
                elif line[col] == open_ch:
                    depth -= 1
                    if depth == 0:
                        self.cursor_row, self.cursor_col = row, col
                        return
                col -= 1
            row -= 1
            if row >= 0:
                col = len(self.lines[row]) - 1

    # -- Edit helpers ------------------------------------------------------

    def _delete_word(self) -> None:
        line = self.lines[self.cursor_row]
        col = self.cursor_col
        start = col
        while col < len(line) and (line[col].isalnum() or line[col] == "_"):
            col += 1
        while col < len(line) and line[col] == " ":
            col += 1
        if col == start and col < len(line):
            col += 1
        self.lines[self.cursor_row] = line[:start] + line[col:]

    def _paste_after(self) -> None:
        if not self.yank_buffer:
            return
        self._save_undo()
        for i, line in enumerate(self.yank_buffer):
            self.lines.insert(self.cursor_row + 1 + i, line)
        self.cursor_row += 1
        self.cursor_col = 0

    def _paste_before(self) -> None:
        if not self.yank_buffer:
            return
        self._save_undo()
        for i, line in enumerate(self.yank_buffer):
            self.lines.insert(self.cursor_row + i, line)
        self.cursor_col = 0

    def _join_lines(self) -> None:
        if self.cursor_row >= len(self.lines) - 1:
            return
        self._save_undo()
        cur = self.lines[self.cursor_row].rstrip()
        nxt = self.lines[self.cursor_row + 1].lstrip()
        self.cursor_col = len(cur)
        self.lines[self.cursor_row] = cur + " " + nxt
        self.lines.pop(self.cursor_row + 1)

    def _undo(self) -> None:
        if not self.undo_stack:
            self.status_msg = "nothing to undo"
            return
        lines, row, col = self.undo_stack.pop()
        self.lines = lines
        self.cursor_row = row
        self.cursor_col = col
        self.status_msg = "undone"
