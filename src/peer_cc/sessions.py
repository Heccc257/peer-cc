"""Introspect Claude Code session metadata from ~/.claude/projects/.

Each CC session writes a JSONL transcript to
  ~/.claude/projects/<sanitized-cwd>/<session-uuid>.jsonl

We use cwd-based path mapping (the same convention CC itself uses) to find
the most recently active session for a given agent's cwd. Agent self-reports
nothing here — peer-cc walks the local filesystem on demand.

If peer-cc is run on a different machine than the agent's CC session, the
project dir won't exist locally and we return None — caller handles that.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def project_dir_for(cwd: str) -> Path:
    """Map an agent cwd → ~/.claude/projects/<sanitized> dir.
    CC's sanitization: replace `/` with `-`, e.g. /mnt/foo → -mnt-foo."""
    sanitized = cwd.replace("/", "-")
    return Path.home() / ".claude" / "projects" / sanitized


def latest_session(cwd: str) -> dict | None:
    """Metadata for the most recently modified .jsonl in the agent's project
    dir, or None if no project dir / no transcripts found / not on this host."""
    proj = project_dir_for(cwd)
    if not proj.is_dir():
        return None
    sessions = list(proj.glob("*.jsonl"))
    if not sessions:
        return None
    latest = max(sessions, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    try:
        with open(latest, "rb") as f:
            line_count = sum(1 for _ in f)
    except OSError:
        line_count = -1
    return {
        "session_id": latest.stem,
        "transcript_path": str(latest),
        "size_bytes": stat.st_size,
        "messages": line_count,
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
        "context_tokens": _last_usage_tokens(latest),
    }


def _last_usage_tokens(transcript: Path) -> int | None:
    """Walk transcript lines from the end; return the most recent input_tokens
    count (including cache reads/creates). None if the schema doesn't match
    what we expect — caller treats None as 'unknown'."""
    try:
        with open(transcript, "rb") as f:
            content = f.read()
    except OSError:
        return None
    for line in reversed(content.splitlines()):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        usage = obj.get("usage") or obj.get("message", {}).get("usage") or {}
        if "input_tokens" in usage:
            cr = usage.get("cache_read_input_tokens") or 0
            cc = usage.get("cache_creation_input_tokens") or 0
            return int(usage["input_tokens"]) + int(cr) + int(cc)
    return None
