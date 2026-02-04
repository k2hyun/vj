"""Demo application for the JSON editor."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from .editor import JsonEditor

SAMPLE_JSON = """\
{
    "name": "json-editor",
    "version": "1.0.0",
    "description": "A modal JSON editor built with Textual",
    "features": [
        "normal mode",
        "insert mode",
        "command mode",
        "syntax highlighting",
        "json validation",
        "bracket matching"
    ],
    "config": {
        "theme": "dark",
        "indent_size": 4,
        "auto_format": true,
        "max_undo": 200,
        "nested": {
            "deep": {
                "value": null
            }
        }
    },
    "scores": [100, 200, 300]
}"""


class JsonEditorApp(App):
    """TUI app that wraps the JsonEditor widget."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #editor {
        height: 1fr;
        border: solid $accent;
    }
    #help-bar {
        height: auto;
        max-height: 5;
        padding: 0 1;
        color: $text-muted;
        background: $surface;
        border-top: solid $accent 50%;
    }
    """

    TITLE = "JSON Editor"
    BINDINGS = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield JsonEditor(SAMPLE_JSON, id="editor")
        yield Static(
            "[b]Move:[/b] h j k l  w b  0 $ ^  gg G  %  PgUp/PgDn\n"
            "[b]Edit:[/b] i I a A o O  x  dd dw d$ cw cc  r[dim]{c}[/]"
            "  J  yy p P  u\n"
            "[b]Cmd :[/b] :w [dim]validate[/]  :fmt [dim]format[/]"
            "  :q [dim]quit[/]  :wq [dim]validate+quit[/]",
            id="help-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#editor").focus()

    def on_json_editor_quit(self) -> None:
        self.exit()

    def on_json_editor_json_validated(
        self, event: JsonEditor.JsonValidated
    ) -> None:
        if event.valid:
            self.notify("JSON is valid", severity="information")
        else:
            self.notify(f"Invalid JSON: {event.error}", severity="error", timeout=6)


def main() -> None:
    app = JsonEditorApp()
    app.run()


if __name__ == "__main__":
    main()
