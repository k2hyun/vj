"""Side-by-side JSON diff viewer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Header, Static

from rich.text import Text

from .diff import DiffHunk, DiffTag, compute_json_diff
from .widget import JsonEditor


class SyncJsonEditor(JsonEditor):
    """스크롤 동기화를 지원하는 JsonEditor."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sync_target: SyncJsonEditor | None = None

    def _ensure_cursor_visible(self, avail: int) -> None:
        if not self.has_focus and self._sync_target is not None:
            return
        super()._ensure_cursor_visible(avail)

    def _sync_folds_to_target(self) -> None:
        """fold 상태를 sync target에 복사."""
        if self._sync_target is not None:
            self._sync_target._folds = dict(self._folds)
            self._sync_target._collapsed_strings = set(self._collapsed_strings)
            self._sync_target.refresh()

    def _toggle_fold(self, line_idx: int) -> None:
        super()._toggle_fold(line_idx)
        self._sync_folds_to_target()

    def _open_fold(self, line_idx: int) -> None:
        super()._open_fold(line_idx)
        self._sync_folds_to_target()

    def _close_fold(self, line_idx: int) -> None:
        super()._close_fold(line_idx)
        self._sync_folds_to_target()

    def _fold_all(self) -> None:
        super()._fold_all()
        self._sync_folds_to_target()

    def _unfold_all(self) -> None:
        super()._unfold_all()
        self._sync_folds_to_target()

    def render(self) -> Text:
        if not self.has_focus and self._sync_target is not None:
            self._scroll_top = self._sync_target._scroll_top
        result = super().render()
        if self.has_focus and self._sync_target is not None:
            if self._sync_target._scroll_top != self._scroll_top:
                self._sync_target._scroll_top = self._scroll_top
                self._sync_target.refresh()
        return result


class DiffEditor(SyncJsonEditor):
    """SyncJsonEditor 서브클래스: diff 배경 하이라이팅과 hunk 네비게이션."""

    # diff 태그별 배경색
    _DIFF_BG = {
        DiffTag.DELETE: "on #72261a",
        DiffTag.INSERT: "on #1e5c34",
        DiffTag.REPLACE: "#1e1e1e on #6a6a6a",
    }
    _FILLER_BG = "on #2a2a2a"

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
        self.cursor_row = 0
        self.cursor_col = 0
        self._scroll_top = 0
        self._folds.clear()
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

    CSS_PATH = "differ.tcss"
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
        self._left_ej_stack: list[str] = []
        self._right_ej_stack: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="diff-container"):
            with Vertical(id="left-panel"):
                yield Static(f"[b]{self.left_path}[/b]", id="left-title")
                yield DiffEditor("", id="left-editor")
                with Vertical(id="left-ej-panel"):
                    with Horizontal(id="left-ej-header"):
                        yield Static("[b]Embedded JSON[/b]", id="left-ej-title")
                        yield Button("\u2715", id="left-ej-close", variant="error")
                    yield DiffEditor("", id="left-ej-editor")
            with Vertical(id="right-panel"):
                yield Static(f"[b]{self.right_path}[/b]", id="right-title")
                yield DiffEditor("", id="right-editor")
                with Vertical(id="right-ej-panel"):
                    with Horizontal(id="right-ej-header"):
                        yield Static("[b]Embedded JSON[/b]", id="right-ej-title")
                        yield Button("\u2715", id="right-ej-close", variant="error")
                    yield DiffEditor("", id="right-ej-editor")

    @staticmethod
    def _unfold_diff_regions(editor: DiffEditor) -> None:
        """diff가 있는 라인을 포함하는 fold/collapsed string을 unfold."""
        to_remove = []
        for start, end in editor._folds.items():
            for i in range(start, end + 1):
                if i < len(editor._line_tags) and editor._line_tags[i] != DiffTag.EQUAL:
                    to_remove.append(start)
                    break
        for s in to_remove:
            del editor._folds[s]
        # diff가 있는 collapsed string도 펼기
        to_expand = [
            i for i in editor._collapsed_strings
            if i < len(editor._line_tags) and editor._line_tags[i] != DiffTag.EQUAL
        ]
        for i in to_expand:
            editor._collapsed_strings.discard(i)

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

        # 렌더 타임 스크롤 동기화 설정
        left_editor._sync_target = right_editor
        right_editor._sync_target = left_editor

        # EJ 패널 스크롤 동기화
        left_ej = self.query_one("#left-ej-editor", DiffEditor)
        right_ej = self.query_one("#right-ej-editor", DiffEditor)
        left_ej._sync_target = right_ej
        right_ej._sync_target = left_ej

        # 모든 depth fold 후 diff 있는 부분만 unfold
        left_editor._fold_all_nested()
        self._unfold_diff_regions(left_editor)
        right_editor._folds = dict(left_editor._folds)
        right_editor._collapsed_strings = set(left_editor._collapsed_strings)

        left_editor._update_hunk_status()
        right_editor._update_hunk_status()
        left_editor.focus()

    def on_json_editor_quit(self, event: JsonEditor.Quit) -> None:
        focused = self.focused
        fid = focused.id if focused else ""
        if fid in ("left-ej-editor", "right-ej-editor"):
            side = "left" if fid == "left-ej-editor" else "right"
            self._close_ej_panel(side)
        else:
            self.exit()

    def on_json_editor_force_quit(self, event: JsonEditor.ForceQuit) -> None:
        focused = self.focused
        fid = focused.id if focused else ""
        if fid in ("left-ej-editor", "right-ej-editor"):
            side = "left" if fid == "left-ej-editor" else "right"
            self._close_ej_panel(side)
        else:
            self.exit()

    def on_json_editor_embedded_edit_requested(
        self, event: JsonEditor.EmbeddedEditRequested
    ) -> None:
        focused = self.focused
        if focused is None:
            return
        fid = focused.id
        if fid in ("left-editor", "left-ej-editor"):
            side = "left"
            other_side = "right"
        elif fid in ("right-editor", "right-ej-editor"):
            side = "right"
            other_side = "left"
        else:
            return

        # EJ 에디터에서 중첩 호출
        if fid == f"{side}-ej-editor":
            ej_stack = self._left_ej_stack if side == "left" else self._right_ej_stack
            other_ej_stack = self._right_ej_stack if side == "left" else self._left_ej_stack
            ej_editor = self.query_one(f"#{side}-ej-editor", DiffEditor)
            other_ej_editor = self.query_one(f"#{other_side}-ej-editor", DiffEditor)

            this_content = event.content
            other_content = self._find_ej_content_in(
                other_ej_editor, event.source_row,
            )

            ej_stack.append(ej_editor.get_content())
            if other_content is not None:
                other_ej_stack.append(other_ej_editor.get_content())
                left_content = this_content if side == "left" else other_content
                right_content = other_content if side == "left" else this_content
                self._open_ej_with_diff(left_content, right_content)
                self._update_ej_title(other_side)
            else:
                lines = this_content.split("\n") if this_content else [""]
                tags = [DiffTag.EQUAL] * len(lines)
                ej_editor.set_diff_data(lines, tags, set(), [])

            self._update_ej_title(side)
            ej_editor.focus()
            return

        # diff 에디터에서 ej 호출 → 양쪽 diff 표시
        this_content = event.content
        other_editor = self.query_one(f"#{other_side}-editor", DiffEditor)
        other_content = self._find_ej_content_in(other_editor, event.source_row)

        if other_content is not None:
            left_content = this_content if side == "left" else other_content
            right_content = other_content if side == "left" else this_content
            self._open_ej_with_diff(left_content, right_content)
        else:
            ej_editor = self.query_one(f"#{side}-ej-editor", DiffEditor)
            ej_panel = self.query_one(f"#{side}-ej-panel")
            lines = this_content.split("\n") if this_content else [""]
            tags = [DiffTag.EQUAL] * len(lines)
            ej_editor.set_diff_data(lines, tags, set(), [])
            self._update_ej_title(side)
            ej_panel.add_class("visible")

        self.query_one(f"#{side}-ej-editor", DiffEditor).focus()

    def _find_ej_content_in(
        self, editor: DiffEditor, source_row: int,
    ) -> str | None:
        """에디터의 지정 행에서 임베디드 JSON을 찾아 포맷팅된 문자열 반환."""
        if source_row >= len(editor.lines):
            return None

        saved_row = editor.cursor_row
        editor.cursor_row = source_row
        result = editor._find_string_at_cursor()
        editor.cursor_row = saved_row

        if result is None:
            return None

        _, _, content = result
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, (list, dict)):
                return None
            return json.dumps(parsed, indent=4, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            return None

    def _open_ej_with_diff(
        self, left_content: str, right_content: str
    ) -> None:
        """양쪽 EJ 패널에 diff 결과를 표시."""
        diff_result = compute_json_diff(
            left_content, right_content, normalize=False,
        )

        left_ej = self.query_one("#left-ej-editor", DiffEditor)
        right_ej = self.query_one("#right-ej-editor", DiffEditor)

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

        left_ej.set_diff_data(
            diff_result.left_lines, diff_result.left_line_tags,
            left_fillers, diff_result.hunks,
        )
        right_ej.set_diff_data(
            diff_result.right_lines, diff_result.right_line_tags,
            right_fillers, diff_result.hunks,
        )

        left_ej._update_hunk_status()
        right_ej._update_hunk_status()

        self._update_ej_title("left")
        self._update_ej_title("right")
        self.query_one("#left-ej-panel").add_class("visible")
        self.query_one("#right-ej-panel").add_class("visible")

    def _close_ej_panel(self, side: str) -> None:
        """EJ 패널 닫기 또는 중첩 레벨 팝."""
        other_side = "right" if side == "left" else "left"
        ej_stack = self._left_ej_stack if side == "left" else self._right_ej_stack
        other_stack = self._right_ej_stack if side == "left" else self._left_ej_stack

        if ej_stack:
            this_prev = ej_stack.pop()
            # 반대편 스택도 함께 pop하여 diff 재계산
            if other_stack:
                other_prev = other_stack.pop()
                left_content = this_prev if side == "left" else other_prev
                right_content = other_prev if side == "left" else this_prev
                self._open_ej_with_diff(left_content, right_content)
                self._update_ej_title(other_side)
            else:
                ej_editor = self.query_one(f"#{side}-ej-editor", DiffEditor)
                lines = this_prev.split("\n") if this_prev else [""]
                tags = [DiffTag.EQUAL] * len(lines)
                ej_editor.set_diff_data(lines, tags, set(), [])
            self._update_ej_title(side)
        else:
            # 패널 닫기 — 반대편도 함께
            self.query_one(f"#{side}-ej-panel").remove_class("visible")
            self.query_one(f"#{other_side}-ej-panel").remove_class("visible")
            other_stack.clear()
            self.query_one(f"#{side}-editor", DiffEditor).focus()

    def _update_ej_title(self, side: str) -> None:
        ej_stack = self._left_ej_stack if side == "left" else self._right_ej_stack
        level = len(ej_stack) + 1
        title = self.query_one(f"#{side}-ej-title", Static)
        title.update(f"[b]Embedded JSON[/b] [dim](level {level})[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "left-ej-close":
            self._close_ej_panel("left")
        elif event.button.id == "right-ej-close":
            self._close_ej_panel("right")

    def key_tab(self) -> None:
        """Tab으로 좌/우 패널 전환."""
        focused = self.focused
        fid = focused.id if focused else ""
        if fid and fid.startswith("right"):
            self.query_one("#left-editor", DiffEditor).focus()
        else:
            self.query_one("#right-editor", DiffEditor).focus()


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
