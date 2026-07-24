"""YAML support without a hard dependency on PyYAML.

This repository's toolchain is .NET and pnpm; there is no Python virtualenv to
install into, so the orchestrator must run on a bare interpreter. When PyYAML is
importable we use it. Otherwise we fall back to a deliberately small parser that
covers the subset workflow definitions actually use:

    key: value            scalars (str, int, float, bool, null)
    key:                  nested mappings by indentation
      nested: value
    - item                block sequences, of scalars or of mappings
    # comment             full-line and trailing comments
    "quoted: value"       single- or double-quoted scalars

Not supported, by design: anchors, aliases, multi-line scalars, flow collections,
multiple documents, tags. A workflow file that needs any of those is too clever;
`validate` will reject it with a clear message rather than half-parsing it.

The emitter is one-way (dict -> YAML text) and exists only to render human-facing
views. Durable state is persisted as JSON, which round-trips exactly.
"""

from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - exercised implicitly by whichever branch is installed
    import yaml as _pyyaml
except ImportError:  # pragma: no cover
    _pyyaml = None

USING_PYYAML = _pyyaml is not None

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}
_NULL = {"", "null", "~", "none"}


class YamlError(ValueError):
    """Raised when the fallback parser cannot make sense of a line."""


def load(text: str) -> Any:
    """Parse a YAML document into Python data."""
    if _pyyaml is not None:
        return _pyyaml.safe_load(text)
    return _parse(text)


def dump(data: Any) -> str:
    """Render Python data as YAML text. Presentation only."""
    if _pyyaml is not None:
        return _pyyaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)
    lines: list[str] = []
    _emit(data, 0, lines)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Fallback parser
# --------------------------------------------------------------------------- #


def _scalar(raw: str) -> Any:
    token = raw.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    # Flow collections are out of the supported subset. Returning the raw string
    # would hand `{"max_attempts": 2}` to config parsing as a str and fail later
    # with an opaque AttributeError, so reject it here where the cause is obvious.
    if token in ("{}", "[]"):
        return {} if token == "{}" else []
    if token[:1] in ("{", "["):
        raise YamlError(
            f"inline flow collections are not supported by the bundled YAML parser: {token!r}. "
            "Use block style, or install PyYAML."
        )
    lowered = token.lower()
    if lowered in _NULL:
        return None
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _strip_comment(line: str) -> str:
    """Remove a trailing comment, respecting quotes."""
    out: list[str] = []
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        out.append(char)
    return "".join(out).rstrip()


def _rows(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"line {lineno}: tab indentation is not allowed in YAML")
        content = _strip_comment(raw)
        if not content.strip():
            continue
        rows.append((len(content) - len(content.lstrip()), content.strip()))
    return rows


def _parse(text: str) -> Any:
    rows = _rows(text)
    if not rows:
        return None
    value, index = _parse_block(rows, 0, rows[0][0])
    if index != len(rows):
        raise YamlError("unexpected trailing content; check indentation consistency")
    return value


def _parse_block(rows: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if rows[index][1].startswith("- "):
        return _parse_sequence(rows, index, indent)
    return _parse_mapping(rows, index, indent)


def _parse_mapping(rows: list[tuple[int, str]], index: int, indent: int) -> tuple[dict, int]:
    result: dict[str, Any] = {}
    while index < len(rows):
        row_indent, content = rows[index]
        if row_indent < indent:
            break
        if row_indent > indent:
            raise YamlError(f"unexpected indentation at {content!r}")
        if ":" not in content:
            raise YamlError(f"expected 'key: value' but found {content!r}")
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()
        index += 1
        if rest:
            result[key] = _scalar(rest)
            continue
        # Value is a nested block, or an explicit empty value.
        if index < len(rows) and rows[index][0] > indent:
            child, index = _parse_block(rows, index, rows[index][0])
            result[key] = child
        elif index < len(rows) and rows[index][0] == indent and rows[index][1].startswith("- "):
            child, index = _parse_sequence(rows, index, indent)
            result[key] = child
        else:
            result[key] = None
    return result, index


def _parse_sequence(rows: list[tuple[int, str]], index: int, indent: int) -> tuple[list, int]:
    result: list[Any] = []
    while index < len(rows):
        row_indent, content = rows[index]
        if row_indent < indent or not content.startswith("- "):
            break
        if row_indent > indent:
            raise YamlError(f"unexpected indentation at {content!r}")
        item = content[2:].strip()
        index += 1
        if ":" in item and not _is_quoted(item):
            # Inline first key of a mapping item; subsequent keys are indented under it.
            key, _, rest = item.partition(":")
            entry: dict[str, Any] = {}
            inner_indent = indent + 2
            if rest.strip():
                entry[key.strip()] = _scalar(rest)
            elif index < len(rows) and rows[index][0] > inner_indent:
                child, index = _parse_block(rows, index, rows[index][0])
                entry[key.strip()] = child
            else:
                entry[key.strip()] = None
            while index < len(rows) and rows[index][0] == inner_indent and not rows[index][1].startswith("- "):
                more, index = _parse_mapping(rows, index, inner_indent)
                entry.update(more)
            result.append(entry)
        else:
            result.append(_scalar(item))
    return result, index


# --------------------------------------------------------------------------- #
# Fallback emitter
# --------------------------------------------------------------------------- #


def _emit(data: Any, indent: int, lines: list[str]) -> None:
    pad = " " * indent
    if isinstance(data, dict):
        if not data:
            lines.append(f"{pad}{{}}")
            return
        for key, value in data.items():
            if isinstance(value, (dict, list)) and value:
                lines.append(f"{pad}{key}:")
                _emit(value, indent + 2, lines)
            else:
                lines.append(f"{pad}{key}: {_format(value)}")
    elif isinstance(data, list):
        if not data:
            lines.append(f"{pad}[]")
            return
        for item in data:
            if isinstance(item, dict) and item:
                first = True
                for key, value in item.items():
                    prefix = f"{pad}- " if first else f"{pad}  "
                    first = False
                    if isinstance(value, (dict, list)) and value:
                        lines.append(f"{prefix}{key}:")
                        _emit(value, indent + 4, lines)
                    else:
                        lines.append(f"{prefix}{key}: {_format(value)}")
            else:
                lines.append(f"{pad}- {_format(item)}")
    else:
        lines.append(f"{pad}{_format(data)}")


def _format(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#\n") or text.strip() != text:
        return json.dumps(text)
    return text


def _is_quoted(token: str) -> bool:
    return len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
