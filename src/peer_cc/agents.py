"""Agent registry: register / heartbeat / deregister / list / evict / sweep."""
from __future__ import annotations

import json
import os
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path

from .ids import now_iso, real_cwd
from .paths import agents_dir, inbox_dir, tasks_claimed, tasks_pending


class AgentCollision(Exception):
    """Raised when attempting to register an id that is already alive elsewhere.
    See `is_alive` for the liveness heuristic."""


def is_alive(record: dict, fresh_window_sec: int = 60) -> bool:
    """Heuristic: an agent is alive if its last_seen is within fresh_window_sec.

    The pid stored in a record is the pid of the `peer-cc register` subprocess,
    which exits seconds after writing the file — useless for liveness. The
    inbox/task watchers (long-lived) heartbeat the record every ~15s, so a
    last_seen older than ~60s means no watcher is keeping it warm and the
    agent is effectively dead.
    """
    ts = record.get("last_seen", "")
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - t).total_seconds()
    return age < fresh_window_sec


# Backward-compat alias — keep the old private name working for any external caller.
_existing_is_alive = is_alive


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def register(coop: Path, agent: str, role: str, force: bool = False, **extra) -> dict:
    """Register or refresh an agent record.

    Refuses to overwrite an existing record that appears alive (see
    `is_alive`) unless `force=True`. This catches the common foot-gun
    of accidentally running a second coordinator in the same coop dir.
    """
    fp = agents_dir(coop) / f"{agent}.json"
    if fp.exists() and not force:
        try:
            existing = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if is_alive(existing):
            raise AgentCollision(
                f"agent '{agent}' is already alive "
                f"(machine={existing.get('machine')}, pid={existing.get('pid')}, "
                f"last_seen={existing.get('last_seen')}). "
                f"Close that one, or pass --force to override."
            )
    data = {
        "id": agent,
        "role": role,
        "machine": socket.gethostname(),
        "cwd": real_cwd(),
        "pid": os.getpid(),
        "started_at": now_iso(),
        "last_seen": now_iso(),
        "status": "idle",
        **extra,
    }
    _atomic_write_json(fp, data)
    return data


def heartbeat(coop: Path, agent: str, status: str | None = None, **extra) -> dict:
    fp = agents_dir(coop) / f"{agent}.json"
    if fp.exists():
        data = json.loads(fp.read_text(encoding="utf-8"))
    else:
        data = {"id": agent, "role": "unknown"}
    data["last_seen"] = now_iso()
    if status:
        data["status"] = status
    data.update(extra)
    _atomic_write_json(fp, data)
    return data


def deregister(coop: Path, agent: str) -> None:
    fp = agents_dir(coop) / f"{agent}.json"
    if fp.exists():
        data = json.loads(fp.read_text(encoding="utf-8"))
        data["status"] = "left"
        data["left_at"] = now_iso()
        _atomic_write_json(fp, data)


def list_agents(coop: Path) -> list[dict]:
    out: list[dict] = []
    d = agents_dir(coop)
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def evict(coop: Path, agent: str, return_claimed: bool = True) -> dict:
    """Hard-delete an agent's registration + inbox dir, optionally returning
    its claimed tasks to pending/. Used by both `peer-cc remove` (manual,
    targeted) and `peer-cc sweep` (bulk, age-based).

    Returns a summary {agent, existed, tasks_returned}.
    """
    fp = agents_dir(coop) / f"{agent}.json"
    summary = {"agent": agent, "existed": fp.exists(), "tasks_returned": 0}
    if not fp.exists():
        return summary

    if return_claimed:
        cdir = tasks_claimed(coop, agent)
        if cdir.exists():
            for tf in list(cdir.glob("*.json")):
                try:
                    data = json.loads(tf.read_text(encoding="utf-8"))
                except Exception:
                    tf.unlink()
                    continue
                data.pop("claimed_by", None)
                data.pop("claimed_at", None)
                data["status"] = "pending"
                target = tasks_pending(coop) / tf.name
                tmp = target.with_name(f".{target.name}.tmp.{os.getpid()}")
                tmp.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                os.replace(tmp, target)
                tf.unlink()
                summary["tasks_returned"] += 1
            try:
                cdir.rmdir()
            except OSError:
                pass

    ibx = inbox_dir(coop, agent)
    if ibx.exists():
        shutil.rmtree(ibx)

    fp.unlink()
    return summary


def sweep_stale(
    coop: Path, threshold_sec: int = 86400, dry_run: bool = False
) -> list[dict]:
    """Evict every agent whose last_seen is older than threshold_sec.

    Default threshold is 24h — generous enough that a worker idle for several
    hours under an active watcher (15s heartbeat) is never swept, but cleans
    up genuinely-dead zombies from past sessions.

    Returns a list of summaries (one per agent considered for eviction).
    """
    swept: list[dict] = []
    for a in list_agents(coop):
        if is_alive(a, fresh_window_sec=threshold_sec):
            continue
        if dry_run:
            swept.append({"agent": a.get("id"), "existed": True, "tasks_returned": 0, "dry_run": True})
        else:
            swept.append(evict(coop, a.get("id"), return_claimed=True))
    return swept
