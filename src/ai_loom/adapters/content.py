"""Small, dependency-free rich-text normalizers used by tracker adapters."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "pre"}:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "h1", "h2", "h3", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: Any) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    parser.feed(str(value))
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def adf_to_text(value: Any) -> str:
    """Render the useful structure of Atlassian Document Format as Markdown."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(adf_to_text(item) for item in value)
    if not isinstance(value, dict):
        return str(value)
    kind = value.get("type", "")
    text = str(value.get("text", ""))
    attrs = value.get("attrs", {}) or {}
    if kind == "inlineCard" and attrs.get("url"):
        text = str(attrs["url"])
    children = "".join(adf_to_text(item) for item in value.get("content", []) or [])
    combined = text + children
    if kind == "hardBreak":
        return "\n"
    if kind in {"paragraph", "heading", "blockquote"}:
        return combined.rstrip() + "\n\n"
    if kind == "listItem":
        return "- " + combined.strip() + "\n"
    if kind == "codeBlock":
        return f"```\n{combined.strip()}\n```\n\n"
    if kind in {"bulletList", "orderedList", "doc"}:
        return combined
    return combined


def task_list(text: str) -> str:
    """Extract Markdown task-list items as acceptance criteria."""
    markers = ("- [ ]", "- [x]", "- [X]")
    return "\n".join(line.strip() for line in text.splitlines() if line.lstrip().startswith(markers))
