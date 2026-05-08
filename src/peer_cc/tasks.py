"""Tasks: publish (atomic), claim (atomic rename across machines), complete."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .ids import msg_id, now_iso
from .paths import tasks_claimed, tasks_done, tasks_pending


def _atomic_drop(target_dir: Path, content: dict) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{content['id']}.json"
    final = target_dir / name
    tmp = target_dir / f".{name}.tmp.{os.getpid()}"
    tmp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def publish(
    coop: Path,
    *,
    publisher: str,
    title: str,
    body: dict | None = None,
    requires: list[str] | None = None,
) -> dict:
    task = {
        "id": msg_id(),
        "ts": now_iso(),
        "publisher": publisher,
        "title": title,
        "body": body or {},
        "requires": requires or [],
        "status": "pending",
    }
    _atomic_drop(tasks_pending(coop), task)
    return task


def list_pending(coop: Path) -> list[Path]:
    d = tasks_pending(coop)
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".json")


def claim(coop: Path, *, agent: str, task_id: str | None = None) -> dict | None:
    """Atomically claim one pending task. Returns the task dict, or None on lost race / empty."""
    pend = tasks_pending(coop)
    claimed_dir = tasks_claimed(coop, agent)
    claimed_dir.mkdir(parents=True, exist_ok=True)

    if task_id:
        candidates = [pend / f"{task_id}.json"]
    else:
        candidates = list_pending(coop)

    for src in candidates:
        if not src.exists():
            continue
        dst = claimed_dir / src.name
        try:
            os.rename(src, dst)
        except FileNotFoundError:
            continue  # lost race, try next
        # success — update fields
        data = json.loads(dst.read_text(encoding="utf-8"))
        data["status"] = "claimed"
        data["claimed_by"] = agent
        data["claimed_at"] = now_iso()
        tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, dst)
        return data
    return None


def complete(
    coop: Path,
    *,
    agent: str,
    task_id: str,
    result: dict | None = None,
    ok: bool = True,
) -> dict:
    src = tasks_claimed(coop, agent) / f"{task_id}.json"
    if not src.exists():
        raise FileNotFoundError(f"task not in claimed/{agent}/: {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    data["status"] = "done" if ok else "failed"
    data["completed_at"] = now_iso()
    data["result"] = result or {}
    data["ok"] = ok
    target = tasks_done(coop) / src.name
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    src.unlink()
    return data
