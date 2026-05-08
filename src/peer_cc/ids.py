"""ID & timestamp helpers. Sortable, no external deps."""
from __future__ import annotations

import os
import secrets
import socket
import time
from pathlib import Path


def real_cwd() -> str:
    """The agent's logical cwd. Prefer $PWD over getcwd() so that when peer-cc
    is invoked via `uv run --directory <repo>` (which chdir()s into <repo>),
    we still report where the calling shell — i.e. the agent — is working.
    chdir(2) does not update $PWD; the shell does."""
    return os.environ.get("PWD") or str(Path.cwd())


def default_agent_id() -> str:
    host = socket.gethostname().split(".")[0]
    cwd_name = Path(real_cwd()).name or "root"
    return f"{host}-{cwd_name}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def now_ts_ms() -> int:
    return int(time.time() * 1000)


def msg_id() -> str:
    """Sortable: ms timestamp + 4-byte hex. Lex-sort == time-sort."""
    return f"{now_ts_ms():013d}-{secrets.token_hex(4)}"


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())
