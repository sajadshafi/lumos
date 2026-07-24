"""Structured execution logging.

One JSONL file per run, append-only. JSONL rather than a formatted log because
the timeline is queried far more often than it is read top-to-bottom, and
`jq` over one event per line beats regex over prose.

Named `logging_` to avoid shadowing the stdlib `logging` module for anything else
importing from this package.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Event:
    """One entry in the execution timeline."""

    timestamp: float
    run_id: str
    event: str
    stage: str | None = None
    skill: str | None = None
    status: str | None = None
    attempt: int | None = None
    duration_seconds: float | None = None
    error: str | None = None
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ts": round(self.timestamp, 3),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.timestamp)),
            "run_id": self.run_id,
            "event": self.event,
        }
        optional = {
            "stage": self.stage,
            "skill": self.skill,
            "status": self.status,
            "attempt": self.attempt,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "detail": self.detail,
        }
        payload.update({k: v for k, v in optional.items() if v is not None})
        return payload


class RunLogger:
    """Append-only structured logger scoped to a single run."""

    def __init__(self, log_file: Path, run_id: str) -> None:
        self._file = log_file
        self._run_id = run_id
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields: Any) -> Event:
        entry = Event(timestamp=time.time(), run_id=self._run_id, event=event, **fields)
        line = json.dumps(entry.to_dict(), ensure_ascii=False, separators=(",", ":"))
        # Append with O_APPEND so concurrent writers cannot interleave partial lines.
        fd = os.open(self._file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return entry

    def read(self) -> list[dict[str, Any]]:
        return list(iter_events(self._file))


def iter_events(log_file: Path) -> Iterator[dict[str, Any]]:
    """Stream events, skipping any line corrupted by an interrupted write.

    A truncated final line must not make the whole timeline unreadable — the log
    is a diagnostic aid, and failing to read it during an incident is the worst
    possible time to be strict.
    """
    if not log_file.is_file():
        return
    with log_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def render_timeline(events: list[dict[str, Any]]) -> str:
    """Human-readable execution timeline for the final summary."""
    if not events:
        return "No events recorded."

    start = events[0].get("ts", 0)
    lines = [
        f"{'ELAPSED':>9}  {'EVENT':<22} {'SKILL':<28} {'STATUS':<18} DETAIL",
        f"{'-' * 9}  {'-' * 22} {'-' * 28} {'-' * 18} {'-' * 30}",
    ]
    for entry in events:
        elapsed = entry.get("ts", start) - start
        detail_parts: list[str] = []
        if entry.get("attempt"):
            detail_parts.append(f"attempt {entry['attempt']}")
        if entry.get("duration_seconds") is not None:
            detail_parts.append(f"{entry['duration_seconds']:.1f}s")
        if entry.get("error"):
            detail_parts.append(str(entry["error"])[:60])
        lines.append(
            f"{_clock(elapsed):>9}  "
            f"{str(entry.get('event', ''))[:22]:<22} "
            f"{str(entry.get('skill') or entry.get('stage') or ''):<28.28} "
            f"{str(entry.get('status') or ''):<18.18} "
            f"{', '.join(detail_parts)}"
        )
    return "\n".join(lines)


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
