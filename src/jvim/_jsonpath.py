"""JSONPath utilities shared by search and substitute modules."""

from __future__ import annotations

import json
import re


def jsonpath_find(data: object, path: str) -> list[list[str | int]]:
    """Simple JSONPath implementation supporting:
    - $ (root)
    - .key (child)
    - [n] (array index)
    - [*] (wildcard)
    - .. (recursive descent)

    Returns list of paths (each path is list of keys/indices).
    """
    if not path.startswith("$"):
        raise ValueError("JSONPath must start with $")

    path = path[1:]  # Remove $
    results: list[list[str | int]] = []
    _traverse(data, path, [], results)
    return results


def _traverse(
    data: object,
    remaining_path: str,
    current_path: list[str | int],
    results: list[list[str | int]],
) -> None:
    """Traverse JSON data following the path pattern."""
    if not remaining_path:
        results.append(current_path.copy())
        return

    if remaining_path.startswith(".."):
        rest = remaining_path[2:]
        next_key, after = _next_segment(rest)
        if next_key is not None:
            _recursive_descent(data, next_key, after, current_path, results)
        return

    if remaining_path.startswith("."):
        rest = remaining_path[1:]
        key, after = _next_segment(rest)
        if key is None:
            return

        if key == "*":
            if isinstance(data, dict):
                for k, v in data.items():
                    _traverse(v, after, current_path + [k], results)
            elif isinstance(data, list):
                for i, v in enumerate(data):
                    _traverse(v, after, current_path + [i], results)
        elif isinstance(data, dict) and key in data:
            _traverse(data[key], after, current_path + [key], results)
        return

    if remaining_path.startswith("["):
        end = remaining_path.find("]")
        if end == -1:
            raise ValueError("Unclosed bracket")

        index_str = remaining_path[1:end]
        after = remaining_path[end + 1 :]

        if index_str == "*":
            if isinstance(data, list):
                for i, v in enumerate(data):
                    _traverse(v, after, current_path + [i], results)
            elif isinstance(data, dict):
                for k, v in data.items():
                    _traverse(v, after, current_path + [k], results)
        elif index_str.lstrip("-").isdigit():
            idx = int(index_str)
            if isinstance(data, list) and -len(data) <= idx < len(data):
                _traverse(data[idx], after, current_path + [idx], results)
        else:
            key = index_str.strip("'\"")
            if isinstance(data, dict) and key in data:
                _traverse(data[key], after, current_path + [key], results)
        return


def _next_segment(path: str) -> tuple[str | None, str]:
    """Extract the next segment from path. Returns (segment, remaining)."""
    if not path:
        return None, ""

    if path.startswith("["):
        end = path.find("]")
        if end == -1:
            return None, path
        return path[1:end], path[end + 1 :]

    if path.startswith("."):
        return None, path

    end = len(path)
    for i, ch in enumerate(path):
        if ch in ".[]":
            end = i
            break

    return path[:end], path[end:]


def _recursive_descent(
    data: object,
    target_key: str,
    remaining_path: str,
    current_path: list[str | int],
    results: list[list[str | int]],
) -> None:
    """Recursively search for target_key in data."""
    if isinstance(data, dict):
        for k, v in data.items():
            if target_key == "*" or k == target_key:
                _traverse(v, remaining_path, current_path + [k], results)
            _recursive_descent(
                v, target_key, remaining_path, current_path + [k], results
            )
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _recursive_descent(
                v, target_key, remaining_path, current_path + [i], results
            )


def parse_jsonpath_filter(pattern: str) -> tuple[str, str, object]:
    """Parse JSONPath with optional value filter.

    Supports:
      $.path=value    (equals)
      $.path!=value   (not equals)
      $.path>value    (greater than)
      $.path<value    (less than)
      $.path>=value   (greater or equal)
      $.path<=value   (less or equal)
      $.path~regex    (regex match)

    Returns (path, operator, value) or (path, "", None) if no filter.
    """
    operators = ["!=", ">=", "<=", "~", "=", ">", "<"]
    for op in operators:
        idx = 0
        bracket_depth = 0
        while idx < len(pattern):
            ch = pattern[idx]
            if ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth -= 1
            elif bracket_depth == 0 and pattern[idx:].startswith(op):
                path = pattern[:idx]
                value_str = pattern[idx + len(op) :]
                value = parse_json_value(value_str)
                return (path, op, value)
            idx += 1

    return (pattern, "", None)


def parse_json_value(value_str: str) -> object:
    """Parse a value string into Python object."""
    value_str = value_str.strip()
    if not value_str:
        return None

    try:
        return json.loads(value_str)
    except json.JSONDecodeError:
        pass

    if len(value_str) >= 2 and value_str[0] == "'" and value_str[-1] == "'":
        return value_str[1:-1]

    return value_str


def jsonpath_value_matches(actual: object, op: str, expected: object) -> bool:
    """Check if actual value matches the expected value with given operator."""
    if op == "=" or op == "==":
        return actual == expected
    elif op == "!=":
        return actual != expected
    elif op == ">":
        try:
            return actual > expected
        except TypeError:
            return False
    elif op == "<":
        try:
            return actual < expected
        except TypeError:
            return False
    elif op == ">=":
        try:
            return actual >= expected
        except TypeError:
            return False
    elif op == "<=":
        try:
            return actual <= expected
        except TypeError:
            return False
    elif op == "~":
        if not isinstance(actual, str):
            actual = str(actual)
        pattern = expected if isinstance(expected, str) else str(expected)
        try:
            return bool(re.search(pattern, actual))
        except re.error:
            return False
    return False


def get_value_at_path(data: object, path: list[str | int]) -> object:
    """Get the value at a given path in data."""
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int):
            if 0 <= key < len(current):
                current = current[key]
            else:
                return None
        else:
            return None
    return current
