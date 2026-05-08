"""Coop dir layout. comm/ is the runtime state root; everything below is under it."""
from __future__ import annotations

import os
from pathlib import Path

COMM = "comm"


def _looks_like_coop(p: Path) -> bool:
    """Heuristic: a peer-cc coop dir has both a peer_cc package (src/ layout
    or flat) and PROTOCOL.md at its root. Used as the autodetect signal."""
    has_protocol = (p / "PROTOCOL.md").is_file()
    has_pkg = (p / "src" / "peer_cc" / "__init__.py").is_file() or (
        p / "peer_cc" / "__init__.py"
    ).is_file()
    return has_protocol and has_pkg


def coop_root(coop: str | None = None) -> Path:
    if coop:
        p = Path(coop).expanduser().resolve()
    else:
        env = os.environ.get("PEER_CC_COOP")
        if env:
            p = Path(env).expanduser().resolve()
        else:
            # Autodetect: when invoked via `uv run --directory <coop>`, uv has
            # chdir'd into <coop>, so getcwd() == coop. Walk up too in case the
            # caller is a few levels deep.
            cur = Path.cwd().resolve()
            for cand in [cur, *cur.parents]:
                if _looks_like_coop(cand):
                    p = cand
                    break
            else:
                raise SystemExit(
                    "no coop dir: pass --coop <path>, set PEER_CC_COOP, "
                    "or invoke via `uv run --directory <coop> peer-cc ...`"
                )
    if not p.is_dir():
        raise SystemExit(f"coop dir not found: {p}")
    return p


def comm_dir(coop: Path) -> Path:
    return coop / COMM


def agents_dir(coop: Path) -> Path:
    return comm_dir(coop) / "agents"


def inbox_dir(coop: Path, agent: str | None = None) -> Path:
    base = comm_dir(coop) / "inbox"
    return base / agent if agent else base


def tasks_pending(coop: Path) -> Path:
    return comm_dir(coop) / "tasks" / "pending"


def tasks_claimed(coop: Path, agent: str | None = None) -> Path:
    base = comm_dir(coop) / "tasks" / "claimed"
    return base / agent if agent else base


def tasks_done(coop: Path) -> Path:
    return comm_dir(coop) / "tasks" / "done"


def log_dir(coop: Path) -> Path:
    return comm_dir(coop) / "log"


def ensure_layout(coop: Path) -> None:
    for d in [
        comm_dir(coop),
        agents_dir(coop),
        inbox_dir(coop),
        tasks_pending(coop),
        tasks_claimed(coop),
        tasks_done(coop),
        log_dir(coop),
    ]:
        d.mkdir(parents=True, exist_ok=True)
