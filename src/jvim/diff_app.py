"""Side-by-side JSON diff viewer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Static

from .diff import DiffHunk, DiffResult, DiffTag, compute_json_diff
from .editor import JsonEditor


class DiffEditor(JsonEditor):
    """JsonEditor 서브클래스: diff 배경 하이라이팅과 hunk 네비게이션."""

    # diff 태그별 배경색
    _DIFF_BG = {
        DiffTag.DELETE: "on #3c1616",
        DiffTag.INSERT: "on #1a3320",
        DiffTag.REPLACE: "on #3c3016",
    }
    _FILLER_BG = "on #262626"

    def __init__(
        self,
        initial_content: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(initial_content, read_only=True, name=name, id=id, classes=classes)
        self._line_tags: list[DiffTag] = []
        self._filler_rows: set[int] = set()
        self._diff_hunks: list[DiffHunk] = []
        self._current_hunk: int = -1

    def set_diff_data(
        self,
        lines: list[str],
        tags: list[DiffTag],
        filler_rows: set[int],
        hunks: list[DiffHunk],
    ) -> None:
        """Diff 결과를 설정."""
        self.lines = lines if lines else [""]
        self._line_tags = tags
        self._filler_rows = filler_rows
        self._diff_hunks = hunks
        self._current_hunk = -1
        self._invalidate_caches()
        self.refresh()

    def _line_background(self, line_idx: int) -> str:
        if line_idx < len(self._line_tags):
            tag = self._line_tags[line_idx]
            if line_idx in self._filler_rows:
                return self._FILLER_BG
            return self._DIFF_BG.get(tag, "")
        return ""

    def _update_hunk_status(self) -> None:
        total = len(self._diff_hunks)
        if total == 0:
            self.status_msg = "Files are identical"
        elif self._current_hunk >= 0:
            self.status_msg = f"Hunk {self._current_hunk + 1}/{total}"
        else:
            self.status_msg = f"{total} hunks"

    def _goto_next_hunk(self) -> None:
        if not self._diff_hunks:
            self.status_msg = "No diffs"
            return
        self._current_hunk += 1
        if self._current_hunk >= len(self._diff_hunks):
            self._current_hunk = 0
        hunk = self._diff_hunks[self._current_hunk]
        self.cursor_row = hunk.left_start
        self.cursor_col = 0
        self._scroll_cursor_to_center()
        self._update_hunk_status()

    def _goto_prev_hunk(self) -> None:
        if not self._diff_hunks:
            self.status_msg = "No diffs"
            return
        self._current_hunk -= 1
        if self._current_hunk < 0:
            self._current_hunk = len(self._diff_hunks) - 1
        hunk = self._diff_hunks[self._current_hunk]
        self.cursor_row = hunk.left_start
        self.cursor_col = 0
        self._scroll_cursor_to_center()
        self._update_hunk_status()

    def _handle_normal(self, event) -> None:
        char = event.character or ""
        if self.pending in ("]", "["):
            self._handle_pending(char, event.key)
            return
        if char in ("]", "["):
            self.pending = char
            return
        super()._handle_normal(event)

    def _handle_pending(self, char: str, key: str) -> None:
        combo = self.pending + char
        if combo == "]c":
            self.pending = ""
            self._goto_next_hunk()
            return
        if combo == "[c":
            self.pending = ""
            self._goto_prev_hunk()
            return
        super()._handle_pending(char, key)


class JsonDiffApp(App):
    """Side-by-side JSON diff viewer."""

    CSS_PATH = "diff_app.tcss"
    TITLE = "JSON Diff"
    BINDINGS = []
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        left_path: str,
        right_path: str,
        normalize: bool = True,
        jsonl: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.left_path = left_path
        self.right_path = right_path
        self.normalize = normalize
        self.jsonl = jsonl

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="diff-container"):
            with Vertical(id="left-panel"):
                yield Static(f"[b]{self.left_path}[/b]", id="left-title")
                yield DiffEditor("", id="left-editor")
            with Vertical(id="right-panel"):
                yield Static(f"[b]{self.right_path}[/b]", id="right-title")
                yield DiffEditor("", id="right-editor")

    def on_mount(self) -> None:
        left_content = Path(self.left_path).read_text(encoding="utf-8")
        right_content = Path(self.right_path).read_text(encoding="utf-8")

        diff_result = compute_json_diff(
            left_content, right_content,
            normalize=self.normalize, jsonl=self.jsonl,
        )

        left_editor = self.query_one("#left-editor", DiffEditor)
        right_editor = self.query_one("#right-editor", DiffEditor)

        # filler 행 계산: 빈 문자열이고 EQUAL이 아닌 행
        left_fillers = {
            i for i, (line, tag) in enumerate(
                zip(diff_result.left_lines, diff_result.left_line_tags)
            )
            if not line and tag != DiffTag.EQUAL
        }
        right_fillers = {
            i for i, (line, tag) in enumerate(
                zip(diff_result.right_lines, diff_result.right_line_tags)
            )
            if not line and tag != DiffTag.EQUAL
        }

        left_editor.set_diff_data(
            diff_result.left_lines, diff_result.left_line_tags,
            left_fillers, diff_result.hunks,
        )
        right_editor.set_diff_data(
            diff_result.right_lines, diff_result.right_line_tags,
            right_fillers, diff_result.hunks,
        )

        left_editor._update_hunk_status()
        right_editor._update_hunk_status()
        left_editor.focus()

    def on_key(self) -> None:
        """동기 스크롤: 포커스된 패널의 scroll_top을 다른 쪽에 복사."""
        left = self.query_one("#left-editor", DiffEditor)
        right = self.query_one("#right-editor", DiffEditor)
        focused = self.focused

        if focused is left:
            right._scroll_top = left._scroll_top
            right.refresh()
        elif focused is right:
            left._scroll_top = right._scroll_top
            left.refresh()

    def on_json_editor_quit(self, event: JsonEditor.Quit) -> None:
        self.exit()

    def on_json_editor_force_quit(self, event: JsonEditor.ForceQuit) -> None:
        self.exit()

    def key_tab(self) -> None:
        """Tab으로 좌/우 패널 전환."""
        left = self.query_one("#left-editor", DiffEditor)
        right = self.query_one("#right-editor", DiffEditor)
        if self.focused is left:
            right.focus()
        else:
            left.focus()


def diff_main() -> None:
    parser = argparse.ArgumentParser(
        prog="jvimdiff",
        description="JSON diff viewer with vim-style keybindings",
    )
    parser.add_argument("file1", help="First JSON file")
    parser.add_argument("file2", help="Second JSON file")
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Don't normalize JSON formatting before diffing",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        default=None,
        help="Treat files as JSONL (auto-detected by .jsonl extension)",
    )
    args = parser.parse_args()

    for f in (args.file1, args.file2):
        if not Path(f).exists():
            print(f"jvimdiff: {f}: No such file", file=sys.stderr)
            sys.exit(1)

    # JSONL 자동 감지: 둘 중 하나라도 .jsonl 확장자면 JSONL 모드
    jsonl = args.jsonl
    if jsonl is None:
        jsonl = any(
            f.lower().endswith(".jsonl") for f in (args.file1, args.file2)
        )

    app = JsonDiffApp(
        left_path=args.file1,
        right_path=args.file2,
        normalize=not args.no_normalize,
        jsonl=jsonl,
    )
    app.run()


if __name__ == "__main__":
    diff_main()
