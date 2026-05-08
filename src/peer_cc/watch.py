"""Polling-based directory watcher. NFS-safe (unlike inotifywait).

Prints each new file path to stdout, line-buffered. Runs forever — kill it
externally. Hidden files (starting with '.') and the 'processed' subdir are
ignored, so atomic tmp files don't trigger spurious events.

When a (coop, agent_id) heartbeat target is provided, also bumps that agent's
last_seen on a slow timer (default every 15s). This is what makes liveness
detection work across processes — register's own pid dies seconds after it
writes the record, so we use heartbeat freshness instead of pid checks for
the AgentCollision logic.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import agents as _agents


def _scan(d: Path, suffix: str) -> set[str]:
    try:
        return {
            p.name
            for p in d.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.name.endswith(suffix)
        }
    except FileNotFoundError:
        return set()


def watch_dir(
    d: Path,
    *,
    interval: float = 1.0,
    suffix: str = ".json",
    heartbeat: tuple[Path, str] | None = None,
    heartbeat_interval: float = 15.0,
) -> None:
    """Poll d for new files; print new paths. Optionally heartbeat
    (coop_root, agent_id) every heartbeat_interval seconds so the agent
    stays counted as alive while this watcher is running."""
    d.mkdir(parents=True, exist_ok=True)
    seen = _scan(d, suffix)
    last_hb = 0.0
    while True:
        now = _scan(d, suffix)
        new = sorted(now - seen)
        for name in new:
            print(str(d / name), flush=True)
        seen = now
        if heartbeat:
            t = time.time()
            if t - last_hb >= heartbeat_interval:
                try:
                    _agents.heartbeat(heartbeat[0], heartbeat[1])
                except Exception:
                    pass  # never let a heartbeat error crash the watcher
                last_hb = t
        time.sleep(interval)
