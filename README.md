# jvim

JSON editor with vim-style keybindings, built with [Textual](https://github.com/Textualize/textual).

[한국어](README.kr.md)

## Features

- **Vim-style modal editing** - Normal, Insert, Command, and Search modes
- **Syntax highlighting** - JSON-aware colorization
- **JSON validation** - Real-time validation with error reporting
- **JSONPath search** - Search using JSONPath expressions (`$.foo.bar`)
- **JSONL support** - Edit JSON Lines files with smart formatting
- **Embedded JSON editing** - Edit JSON strings within JSON with nested level support
- **Bracket matching** - Jump to matching brackets with `%`
- **Undo/Redo** - Full undo history

## Installation

```bash
pip install jvim
```

## Usage

```bash
# Open a file
jvim data.json

# Open in read-only mode
jvim -R data.json

# Create new file
jvim newfile.json
```

Also available as `jvi` and `jv` shortcuts.

## JSONL Support

jvim provides special handling for JSON Lines (`.jsonl`) files:

- **Pretty-printed editing**: Each JSONL record is automatically formatted with indentation for easy reading and editing
- **Compact saving**: When you save, each record is minified back to a single line, preserving the JSONL format
- **Record numbers**: A second column shows the record number (1, 2, 3...) for easy navigation
- **Floating header**: When scrolling through a multi-line record, the physical line number stays visible at the top

Example: A JSONL file with two records:
```
{"name": "Alice", "age": 30}
{"name": "Bob", "age": 25}
```

Opens in jvim as:
```
{
    "name": "Alice",
    "age": 30
}
{
    "name": "Bob",
    "age": 25
}
```

And saves back to the original compact format.

## JSONPath Search

jvim supports powerful JSONPath searching with value filtering.

### Basic JSONPath

Search patterns starting with `$.` or `$[` are automatically recognized as JSONPath:

```
/$.name              # Find the "name" field
/$..email            # Find all "email" fields (recursive)
/$.users[0]          # First user
/$.users[*].name     # All user names
```

### Value Filtering

You can filter search results by value using comparison operators:

| Operator | Description | Example |
|----------|-------------|---------|
| `=` | Equals | `$.status="active"` |
| `!=` | Not equals | `$.status!=null` |
| `>` | Greater than | `$.age>18` |
| `<` | Less than | `$.price<100` |
| `>=` | Greater or equal | `$.count>=5` |
| `<=` | Less or equal | `$.count<=10` |
| `~` | Regex match | `$.email~@gmail\.com$` |

### Examples

```
/$.users[*].age>30           # Users older than 30
/$.items[*].status="active"  # Items with active status
/$..name~^J                  # All names starting with J
/$.price<=1000               # Price 1000 or less
/$.config.enabled=true       # Enabled configs
```

### Search Modifiers

| Suffix | Description |
|--------|-------------|
| `\j` | Force JSONPath mode for ambiguous patterns |
| `\c` | Case insensitive (for regex text search) |
| `\C` | Case sensitive (for regex text search) |

## Embedded JSON Editing

JSON files often contain escaped JSON strings as values. jvim lets you edit these nested JSON structures naturally.

### How it works

1. Position your cursor on a line containing a JSON string value
2. Type `ej` in normal mode
3. A new editor panel opens with the parsed and formatted JSON
4. Edit the embedded JSON with full syntax highlighting and validation
5. Save with `:w` to update the parent document (minified) or `:q` to cancel

### Nested levels

You can edit embedded JSON within embedded JSON:
- The panel title shows the current nesting level: `Edit Embedded JSON (level 1)`
- A `[+]` indicator appears when you have unsaved changes
- `:w` saves and returns to the previous level
- `:q!` discards changes and returns to the previous level

### Example

Given this JSON:
```json
{
    "config": "{\"host\": \"localhost\", \"port\": 8080}"
}
```

Using `ej` on the config line opens:
```json
{
    "host": "localhost",
    "port": 8080
}
```

After editing and saving, the parent is updated with the minified result.

## Keybindings

### Movement
| Key | Action |
|-----|--------|
| `h j k l` | Left/Down/Up/Right |
| `w b` | Word forward/backward |
| `0 $ ^` | Line start/end/first char |
| `gg G` | File start/end |
| `%` | Jump to matching bracket |
| `PgUp PgDn` | Page up/down |
| `Ctrl+d/u` | Half page down/up |

### Search
| Key | Action |
|-----|--------|
| `/` | Search forward |
| `?` | Search backward |
| `n N` | Next/previous match |
| `$.path` | JSONPath search (auto-detect) |
| `$.path=val` | JSONPath with value filter |
| `$.path~regex` | JSONPath with regex filter |
| `\j` | JSONPath suffix for patterns |
| `\c \C` | Case insensitive/sensitive |

### Insert Mode
| Key | Action |
|-----|--------|
| `i I` | Insert at cursor/line start |
| `a A` | Append after cursor/line end |
| `o O` | Open line below/above |

### Editing
| Key | Action |
|-----|--------|
| `x` | Delete char |
| `dd` | Delete line |
| `dw d$` | Delete word/to end |
| `cw cc` | Change word/line |
| `r{c}` | Replace char |
| `J` | Join lines |
| `yy p P` | Yank/paste after/before |
| `u` | Undo |
| `Ctrl+r` | Redo |
| `.` | Repeat last edit |
| `ej` | Edit embedded JSON string |

### Commands
| Command | Action |
|---------|--------|
| `:w` | Save |
| `:w {file}` | Save as |
| `:e {file}` | Open file |
| `:fmt` | Format JSON |
| `:q` | Quit |
| `:q!` | Quit (discard changes) |
| `:wq` | Save and quit |
| `:help` | Toggle help panel |

## License

MIT
