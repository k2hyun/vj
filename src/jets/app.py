"""Demo application for the JSON editor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Header, Static

from .editor import JsonEditor

# Data directory path
_DATA_DIR = Path(__file__).parent / "data"


def _load_data(filename: str) -> str:
    """Load content from data directory."""
    return (_DATA_DIR / filename).read_text(encoding="utf-8")


class JsonEditorApp(App):
    """TUI app that wraps the JsonEditor widget."""

    CSS_PATH = "app.tcss"
    TITLE = "JSON Editor"
    BINDINGS = []
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        file_path: str = "",
        initial_content: str = "",
        read_only: bool = False,
        jsonl: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.file_path = file_path
        self.initial_content = initial_content
        self.read_only = read_only
        self.jsonl = jsonl
        # Embedded edit state - stack of (row, col_start, col_end, parent_content, original_content)
        self._ej_stack: list[tuple[int, int, int, str, str]] = []
        self._main_was_read_only: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield JsonEditor(
            self.initial_content,
            read_only=self.read_only,
            jsonl=self.jsonl,
            id="editor",
        )
        with Vertical(id="help-panel"):
            with Horizontal(id="help-header"):
                yield Static("[b]Help[/b]", id="help-title")
                yield Button("\u2715", id="help-close", variant="error")
            yield JsonEditor(_load_data("help.json"), read_only=True, id="help-editor")
        with Vertical(id="ej-panel"):
            with Horizontal(id="ej-header"):
                yield Static("[b]Edit Embedded JSON[/b]", id="ej-title")
                yield Button("\u2715", id="ej-close", variant="error")
            yield JsonEditor("", id="ej-editor")

    def on_mount(self) -> None:
        self._update_title()
        self.query_one("#editor").focus()

    def _update_title(self) -> None:
        ro = " [RO]" if self.read_only else ""
        if self.file_path:
            self.sub_title = self.file_path + ro
        else:
            self.sub_title = "[new]" + ro

    # -- Event handlers ----------------------------------------------------

    def _is_help_editor_focused(self) -> bool:
        focused = self.focused
        return focused is not None and focused.id == "help-editor"

    def _is_ej_editor_focused(self) -> bool:
        focused = self.focused
        return focused is not None and focused.id == "ej-editor"

    def on_key(self) -> None:
        """Update ej title on key press to reflect modified state."""
        if self._is_ej_editor_focused() and self._ej_stack:
            self._update_ej_title()

    def on_json_editor_quit(self, event: JsonEditor.Quit) -> None:
        if self._is_help_editor_focused():
            self.query_one("#help-panel").remove_class("visible")
            self.query_one("#editor").focus()
        elif self._is_ej_editor_focused():
            if self._ej_has_unsaved_changes():
                self.notify("Unsaved changes! Use :w to save or :q! to discard", severity="warning")
            else:
                self._close_ej_panel()
        else:
            self.exit()

    def on_json_editor_force_quit(self, event: JsonEditor.ForceQuit) -> None:
        """Handle :q! to discard changes."""
        if self._is_help_editor_focused():
            self.query_one("#help-panel").remove_class("visible")
            self.query_one("#editor").focus()
        elif self._is_ej_editor_focused():
            self._close_ej_panel()
        else:
            self.exit()

    def on_json_editor_json_validated(
        self, event: JsonEditor.JsonValidated
    ) -> None:
        if event.valid:
            self.notify("JSON is valid", severity="information")
        else:
            self.notify(f"Invalid JSON: {event.error}", severity="error", timeout=6)

    def on_json_editor_file_save_requested(
        self, event: JsonEditor.FileSaveRequested
    ) -> None:
        # Help editor is read-only, so this shouldn't happen, but just in case
        if self._is_help_editor_focused():
            return

        # EJ editor: update parent and close/pop panel
        if self._is_ej_editor_focused() and self._ej_stack:
            row, col_start, col_end, prev_content, _ = self._ej_stack.pop()
            # Minify the JSON to a single line
            try:
                parsed = json.loads(event.content)
                minified = json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                self.notify("Invalid JSON", severity="error")
                # Restore the popped entry with current content as new original
                self._ej_stack.append((row, col_start, col_end, prev_content, event.content))
                return

            if self._ej_stack:
                # Update previous ej content and show it
                ej_editor = self.query_one("#ej-editor", JsonEditor)
                lines = prev_content.split("\n")
                line = lines[row]
                escaped = json.dumps(minified, ensure_ascii=False)
                lines[row] = line[:col_start] + escaped + line[col_end:]
                new_content = "\n".join(lines)
                ej_editor.set_content(new_content)
                # Keep original content unchanged so modified indicator stays
                self._update_ej_title()
                self.notify("Embedded JSON updated", severity="information")
            else:
                # Update main editor and restore its read-only state
                main_editor = self.query_one("#editor", JsonEditor)
                main_editor.read_only = self._main_was_read_only
                main_editor.update_embedded_string(row, col_start, col_end, minified)
                self.notify("Embedded JSON updated", severity="information")
                if event.quit_after:
                    self.query_one("#ej-panel").remove_class("visible")
                    main_editor.focus()
            return

        target = event.file_path or self.file_path
        if not target:
            self.notify("No file name — use :w <file>", severity="warning")
            return

        try:
            path = Path(target)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(event.content, encoding="utf-8")
            self.file_path = str(path)
            self._update_title()
            self.notify(f"Saved: {self.file_path}", severity="information")
            if event.quit_after:
                self.exit()
        except OSError as exc:
            self.notify(f"Save failed: {exc}", severity="error", timeout=6)

    def on_json_editor_file_open_requested(
        self, event: JsonEditor.FileOpenRequested
    ) -> None:
        target = event.file_path
        try:
            content = Path(target).read_text(encoding="utf-8")
        except FileNotFoundError:
            self.notify(f"File not found: {target}", severity="error", timeout=6)
            return
        except OSError as exc:
            self.notify(f"Cannot open: {exc}", severity="error", timeout=6)
            return

        editor = self.query_one("#editor", JsonEditor)
        editor.set_content(content)
        self.jsonl = target.lower().endswith(".jsonl")
        editor.jsonl = self.jsonl
        self.file_path = target
        self._update_title()
        self.notify(f"Opened: {target}", severity="information")

    def on_json_editor_help_toggle_requested(self) -> None:
        help_panel = self.query_one("#help-panel")
        help_panel.toggle_class("visible")
        if help_panel.has_class("visible"):
            self.query_one("#help-editor").focus()
        else:
            self.query_one("#editor").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.query_one("#help-panel").remove_class("visible")
            self.query_one("#editor").focus()
        elif event.button.id == "ej-close":
            self._close_ej_panel()

    def _ej_has_unsaved_changes(self) -> bool:
        """Check if current ej content differs from original."""
        if not self._ej_stack:
            return False
        ej_editor = self.query_one("#ej-editor", JsonEditor)
        current = ej_editor.get_content()
        _, _, _, _, original = self._ej_stack[-1]
        return current != original

    def _update_ej_title(self) -> None:
        """Update ej panel title with current nesting level and modified indicator."""
        level = len(self._ej_stack)
        title = self.query_one("#ej-title", Static)
        modified = " [+]" if self._ej_has_unsaved_changes() else ""
        title.update(f"[b]Edit Embedded JSON[/b] [dim](level {level}){modified}[/dim]")

    def _close_ej_panel(self) -> None:
        """Close or pop one level of ej editing."""
        if not self._ej_stack:
            self.query_one("#ej-panel").remove_class("visible")
            main_editor = self.query_one("#editor", JsonEditor)
            main_editor.read_only = self._main_was_read_only
            main_editor.focus()
            return

        # Pop current level and get content to restore
        _, _, _, restore_content, _ = self._ej_stack.pop()

        if self._ej_stack:
            # Restore previous level content
            ej_editor = self.query_one("#ej-editor", JsonEditor)
            ej_editor.set_content(restore_content)
            self._update_ej_title()
        else:
            # No more levels, close panel and restore main editor state
            self.query_one("#ej-panel").remove_class("visible")
            main_editor = self.query_one("#editor", JsonEditor)
            main_editor.read_only = self._main_was_read_only
            main_editor.focus()

    def on_json_editor_embedded_edit_requested(
        self, event: JsonEditor.EmbeddedEditRequested
    ) -> None:
        ej_editor = self.query_one("#ej-editor", JsonEditor)

        if self._is_ej_editor_focused():
            # Nested ej from ej panel - push to stack
            current_content = ej_editor.get_content()
            self._ej_stack.append((
                event.source_row,
                event.source_col_start,
                event.source_col_end,
                current_content,
                event.content,  # original content for change detection
            ))
        else:
            # From main editor - reset stack to level 1
            main_editor = self.query_one("#editor", JsonEditor)
            self._main_was_read_only = main_editor.read_only
            main_editor.read_only = True
            self._ej_stack = [(
                event.source_row,
                event.source_col_start,
                event.source_col_end,
                "",  # No previous ej content
                event.content,  # original content for change detection
            )]

        # Set content and show panel
        ej_editor.set_content(event.content)
        self._update_ej_title()
        self.query_one("#ej-panel").add_class("visible")
        ej_editor.focus()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vj",
        description="JSON Editor in Textual",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="",
        help="JSON file to open",
    )
    parser.add_argument(
        "-R", "--read-only",
        action="store_true",
        default=False,
        help="open in read-only mode",
    )
    args = parser.parse_args()

    file_path: str = args.file
    initial_content: str = _load_data("sample.json")
    jsonl: bool = file_path.lower().endswith(".jsonl") if file_path else False

    if file_path:
        path = Path(file_path)
        try:
            if path.exists():
                initial_content = path.read_text(encoding="utf-8")
            else:
                # New file — start with empty object / empty line
                initial_content = "" if jsonl else "{}"
        except PermissionError as exc:
            print(f"vj: {exc}", file=sys.stderr)
            sys.exit(1)

    app = JsonEditorApp(
        file_path=file_path,
        initial_content=initial_content,
        read_only=args.read_only,
        jsonl=jsonl,
    )
    app.run()


if __name__ == "__main__":
    main()
