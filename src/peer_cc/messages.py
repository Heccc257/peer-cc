"""Inbox messaging. Atomic drop via tmp+rename so consumers never read half-written JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .ids import msg_id, now_iso
from .paths import inbox_dir


def _atomic_drop(target_dir: Path, content: dict) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{content['id']}.json"
    final = target_dir / name
    tmp = target_dir / f".{name}.tmp.{os.getpid()}"
    tmp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def send(
    coop: Path,
    *,
    to: str,
    sender: str,
    type: str,
    body: dict | str | None = None,
    reply_to: str | None = None,
) -> Path:
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"text": body}
    elif body is None:
        body = {}
    msg = {
        "id": msg_id(),
        "ts": now_iso(),
        "from": sender,
        "to": to,
        "type": type,
        "body": body,
    }
    if reply_to:
        msg["reply_to"] = reply_to
    return _atomic_drop(inbox_dir(coop, to), msg)


def list_inbox(coop: Path, agent: str) -> list[Path]:
    d = inbox_dir(coop, agent)
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".json")


def consume(coop: Path, agent: str, msg_path: Path) -> dict:
    """Read message, atomically move to processed/."""
    msg_path = Path(msg_path)
    if not msg_path.exists():
        raise FileNotFoundError(msg_path)
    processed = inbox_dir(coop, agent) / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    target = processed / msg_path.name
    data = json.loads(msg_path.read_text(encoding="utf-8"))
    os.replace(msg_path, target)
    return data
