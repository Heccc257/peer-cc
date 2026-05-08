"""Append-only event log. One JSON line per event. Atomic on POSIX for short writes."""
from __future__ import annotations

import json
from pathlib import Path

from .ids import now_iso, today
from .paths import log_dir


def append_event(coop: Path, agent: str, event: str, **fields) -> None:
    rec = {"ts": now_iso(), "agent": agent, "event": event, **fields}
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    fp = log_dir(coop) / f"{today()}.jsonl"
    fp.parent.mkdir(parents=True, exist_ok=True)
    with open(fp, "a", encoding="utf-8") as f:
        f.write(line)
