"""Typer CLI: `peer-cc <command> ...`. Thin wrapper over peer_cc.* modules."""
from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from . import agents as _agents
from . import log as _log
from . import messages as _messages
from . import sessions as _sessions
from . import tasks as _tasks
from . import watch as _watch
from . import __version__
from .ids import default_agent_id
from .paths import (
    agents_dir,
    comm_dir,
    coop_root,
    ensure_layout,
    inbox_dir,
    tasks_claimed,
    tasks_done,
    tasks_pending,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"peer-cc {__version__}")
        raise typer.Exit()


app = typer.Typer(no_args_is_help=True, help="peer-cc: file-based multi-agent coop bus")
task_app = typer.Typer(no_args_is_help=True, help="Task pub / claim / complete")
app.add_typer(task_app, name="task")


@app.callback()
def _root(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show peer-cc version and exit.",
    ),
) -> None:
    """peer-cc CLI."""
    return None


def _coop_opt(default: str | None = None) -> typer.Option:
    return typer.Option(
        default, "--coop", "-c", help="Coop dir (or env PEER_CC_COOP)"
    )


@app.command()
def init(coop: str = typer.Option(None, "--coop", "-c")):
    """Create comm/ subdir layout under coop dir."""
    root = coop_root(coop)
    ensure_layout(root)
    typer.echo(f"layout ready: {comm_dir(root)}")


@app.command(name="join-prompt")
def join_prompt(
    agent: str = typer.Argument(
        None,
        help="optional agent id, e.g. B. Omit to let the worker default to <host>-<cwd_basename>.",
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Print the exact one-line prompt to paste into a worker's CC session.

    The bare phrase '加入 <path>' is ambiguous — CC may interpret it as
    /add-dir (the 'add directory to working dirs' slash command) instead of
    'join the coop as a worker'. Including the absolute path of PROTOCOL.md
    is the key — that alone is enough for CC to read the file and follow §4.
    """
    root = coop_root(coop)
    if agent:
        typer.echo(f"读 {root}/PROTOCOL.md, 我是 worker {agent}")
    else:
        typer.echo(f"读 {root}/PROTOCOL.md")


@app.command()
def register(
    role: str = typer.Option(..., "--role", help="coordinator|worker"),
    agent: str = typer.Option(None, "--id", help="agent id (default: host-cwd)"),
    force: bool = typer.Option(
        False,
        "--force",
        help="override existing registration even if it appears alive (use only if you know the previous instance is dead)",
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Register an agent. Refuses to overwrite a live registration unless
    --force; exit code 3 indicates a collision with a still-alive agent."""
    root = coop_root(coop)
    ensure_layout(root)
    aid = agent or default_agent_id()
    try:
        data = _agents.register(root, aid, role, force=force)
    except _agents.AgentCollision as e:
        typer.echo(f"refusing to register: {e}", err=True)
        raise typer.Exit(code=3)
    inbox_dir(root, aid).mkdir(parents=True, exist_ok=True)
    _log.append_event(root, aid, "register", role=role, force=force)
    typer.echo(json.dumps(data, ensure_ascii=False))


@app.command()
def heartbeat(
    agent: str = typer.Option(..., "--id"),
    status: str = typer.Option(None, "--status"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Bump last_seen and optionally update status."""
    root = coop_root(coop)
    data = _agents.heartbeat(root, agent, status=status)
    typer.echo(json.dumps(data, ensure_ascii=False))


@app.command()
def deregister(
    agent: str = typer.Option(..., "--id"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Mark agent as left. Call on graceful exit."""
    root = coop_root(coop)
    _agents.deregister(root, agent)
    _log.append_event(root, agent, "deregister")
    typer.echo("ok")


@app.command()
def agents(
    alive: bool = typer.Option(
        False,
        "--alive",
        help="only show agents whose last_seen is fresh (within --alive-window seconds)",
    ),
    alive_window: int = typer.Option(
        60,
        "--alive-window",
        help="seconds threshold for --alive; matches register's collision window by default",
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """List registered agents (one JSON per line). Pass --alive to filter
    out zombies whose watcher has been gone for more than --alive-window
    seconds (default 60s = ~4× watcher heartbeat interval)."""
    root = coop_root(coop)
    for a in _agents.list_agents(root):
        if alive and not _agents.is_alive(a, fresh_window_sec=alive_window):
            continue
        typer.echo(json.dumps(a, ensure_ascii=False))


@app.command()
def info(
    agent: str = typer.Option(None, "--id", help="filter to one agent"),
    json_out: bool = typer.Option(False, "--json", help="output JSON, one line per agent"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Detailed agent listing including Claude session id, transcript path,
    and context size. Walks ~/.claude/projects/ on the local machine — agents
    on other hosts will show 'no local CC project dir'."""
    root = coop_root(coop)
    rows = []
    for a in _agents.list_agents(root):
        if agent and a.get("id") != agent:
            continue
        sess = _sessions.latest_session(a.get("cwd", "")) or {}
        rows.append({**a, "session": sess})

    if json_out:
        for r in rows:
            typer.echo(json.dumps(r, ensure_ascii=False))
        return

    for a in rows:
        typer.echo(
            f"{a.get('id', '?'):<10s} role={a.get('role', '?'):<12s} "
            f"status={a.get('status', '?'):<8s} last_seen={a.get('last_seen', '?')}"
        )
        typer.echo(f"           machine: {a.get('machine', '?')}  pid: {a.get('pid', '?')}")
        typer.echo(f"           cwd:     {a.get('cwd', '?')}")
        sess = a.get("session") or {}
        sid = sess.get("session_id")
        if sid:
            size_kb = (sess.get("size_bytes") or 0) / 1024
            tokens = sess.get("context_tokens")
            tok_str = f"{tokens:,} tokens" if tokens is not None else "tokens unknown"
            typer.echo(f"           session: {sid}")
            typer.echo(
                f"                    {size_kb:.1f} KiB · {sess.get('messages')} messages · "
                f"{tok_str} · updated {sess.get('mtime')}"
            )
            typer.echo(f"                    transcript: {sess.get('transcript_path')}")
        else:
            typer.echo(f"           session: (no local Claude project dir for this cwd)")
        typer.echo("")


@app.command()
def remove(
    agent: str = typer.Option(..., "--id"),
    return_claimed: bool = typer.Option(
        True,
        "--return-claimed/--keep-claimed",
        help="return any claimed-but-incomplete tasks to pending (default: yes)",
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Evict an agent: delete agents/<id>.json, return claimed tasks to pending,
    wipe inbox/<id>/. Does NOT kill the agent's CC process — close the terminal
    or Ctrl+C the inbox watcher yourself if you want it fully gone."""
    root = coop_root(coop)
    summary = _agents.evict(root, agent, return_claimed=return_claimed)
    if not summary["existed"]:
        typer.echo(f"no such agent: {agent}", err=True)
        raise typer.Exit(code=2)
    _log.append_event(root, agent, "remove", tasks_returned=summary["tasks_returned"])
    typer.echo(
        f"removed agent {agent} (returned {summary['tasks_returned']} claimed task(s) to pending)"
    )


@app.command()
def sweep(
    threshold_sec: int = typer.Option(
        86400,
        "--threshold-sec",
        help="evict agents whose last_seen is older than this (default 24h)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="report what would be evicted without doing it"
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Evict every agent whose last_seen is older than --threshold-sec.

    Useful at coordinator startup to drop zombies from past sessions whose
    terminals were closed without `peer-cc deregister`. The default 24h
    threshold is far longer than the watcher's 15s heartbeat interval, so any
    agent with a live watcher is safe.
    """
    root = coop_root(coop)
    swept = _agents.sweep_stale(root, threshold_sec=threshold_sec, dry_run=dry_run)
    if not dry_run:
        for s in swept:
            _log.append_event(
                root,
                s.get("agent", "?"),
                "sweep_evict",
                tasks_returned=s.get("tasks_returned", 0),
            )
    typer.echo(
        json.dumps(
            {"swept": [s.get("agent") for s in swept], "dry_run": dry_run, "threshold_sec": threshold_sec},
            ensure_ascii=False,
        )
    )


@app.command()
def send(
    to: str = typer.Option(..., "--to"),
    sender: str = typer.Option(..., "--from", "-f"),
    type: str = typer.Option(..., "--type"),
    body: str = typer.Option(None, "--body", help="JSON object or plain text"),
    reply_to: str = typer.Option(None, "--reply-to"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Drop a message into <to>'s inbox atomically."""
    root = coop_root(coop)
    p = _messages.send(
        root, to=to, sender=sender, type=type, body=body, reply_to=reply_to
    )
    _log.append_event(
        root, sender, "send", to=to, type=type, msg_path=str(p.relative_to(root))
    )
    typer.echo(str(p))


@app.command()
def inbox(
    agent: str = typer.Option(..., "--id"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """List unprocessed message paths in <agent>'s inbox."""
    root = coop_root(coop)
    for p in _messages.list_inbox(root, agent):
        typer.echo(str(p))


@app.command()
def consume(
    agent: str = typer.Option(..., "--id"),
    path: str = typer.Option(..., "--path"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Read message at <path>, then atomically move it to inbox/<agent>/processed/."""
    root = coop_root(coop)
    data = _messages.consume(root, agent, Path(path))
    _log.append_event(
        root,
        agent,
        "consume",
        msg_id=data.get("id"),
        msg_type=data.get("type"),
        sender=data.get("from"),
    )
    typer.echo(json.dumps(data, ensure_ascii=False))


@task_app.command("publish")
def task_publish(
    publisher: str = typer.Option(..., "--from", "-f"),
    title: str = typer.Option(..., "--title"),
    body: str = typer.Option(None, "--body", help="JSON object"),
    requires: str = typer.Option(
        None, "--requires", help="comma-separated capability tags"
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Publish a task into tasks/pending/."""
    root = coop_root(coop)
    body_dict = json.loads(body) if body else {}
    req = [r.strip() for r in requires.split(",")] if requires else []
    data = _tasks.publish(
        root, publisher=publisher, title=title, body=body_dict, requires=req
    )
    _log.append_event(root, publisher, "task_publish", task_id=data["id"], title=title)
    typer.echo(json.dumps(data, ensure_ascii=False))


@task_app.command("list")
def task_list(coop: str = typer.Option(None, "--coop", "-c")):
    """List pending task paths."""
    root = coop_root(coop)
    for p in _tasks.list_pending(root):
        typer.echo(str(p))


@task_app.command("claim")
def task_claim(
    agent: str = typer.Option(..., "--agent"),
    task_id: str = typer.Option(None, "--id", help="specific task id; omit to claim oldest"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Atomically claim a pending task. Exit code 2 means none claimed (race lost or empty)."""
    root = coop_root(coop)
    data = _tasks.claim(root, agent=agent, task_id=task_id)
    if data is None:
        typer.echo("none", err=True)
        raise typer.Exit(code=2)
    _log.append_event(root, agent, "task_claim", task_id=data["id"])
    typer.echo(json.dumps(data, ensure_ascii=False))


@task_app.command("complete")
def task_complete(
    agent: str = typer.Option(..., "--agent"),
    task_id: str = typer.Option(..., "--id"),
    result: str = typer.Option(None, "--result", help="JSON object"),
    ok: bool = typer.Option(True, "--ok/--fail"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Move claimed task to tasks/done/ with result attached."""
    root = coop_root(coop)
    result_dict = json.loads(result) if result else {}
    data = _tasks.complete(
        root, agent=agent, task_id=task_id, result=result_dict, ok=ok
    )
    _log.append_event(root, agent, "task_complete", task_id=task_id, ok=ok)
    typer.echo(json.dumps(data, ensure_ascii=False))


@app.command(name="watch")
def watch_cmd(
    kind: str = typer.Argument(..., help="inbox|tasks"),
    agent: str = typer.Option(None, "--id", help="required for kind=inbox; for tasks, used to heartbeat"),
    interval: float = typer.Option(1.0, "--interval", help="poll interval seconds"),
    daemon: bool = typer.Option(
        False,
        "--daemon",
        help="spawn detached, append output to comm/.../<watch>.log; idempotent — does nothing if already running",
    ),
    stop: bool = typer.Option(
        False, "--stop", help="kill the daemon for this kind+agent (no foreground watch)"
    ),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Poll-watch a dir; print new file paths to stdout. NFS-safe.

    Foreground (default): prints to stdout, dies with parent — designed for CC's
    Monitor tool. Heartbeats the agent's last_seen every 15s while running.

    --daemon: forks a fully-detached process whose lifetime is independent of
    the parent shell or CC session. Output goes to comm/.../<watch>.log
    (appended). Use `tail -F` (or CC's Monitor on the log file) to consume
    events. Survives terminal close and CC harness restart, so messages that
    arrive while no CC is open are still recorded.

    --stop: kills any daemon previously started with --daemon for the same
    kind+agent.
    """
    root = coop_root(coop)
    if stop and daemon:
        raise typer.BadParameter("--stop and --daemon are mutually exclusive")

    if kind == "inbox":
        if not agent:
            raise typer.BadParameter("inbox watch requires --id")
        d = inbox_dir(root, agent)
        d.mkdir(parents=True, exist_ok=True)
        pidfile = d / ".watch.pid"
        logfile = d / ".watch.log"
    elif kind == "tasks":
        d = tasks_pending(root)
        d.mkdir(parents=True, exist_ok=True)
        if not agent:
            raise typer.BadParameter("--id required for tasks watch (used for heartbeat + pidfile)")
        pidfile = d.parent / f".tasks-watch-{agent}.pid"
        logfile = d.parent / f".tasks-watch-{agent}.log"
    else:
        raise typer.BadParameter(f"unknown kind: {kind!r} (expected inbox|tasks)")

    if stop:
        ok = _watch.daemon_stop(pidfile)
        typer.echo(json.dumps({"stopped": ok, "pidfile": str(pidfile)}, ensure_ascii=False))
        return

    hb = (root, agent) if agent else None

    if daemon:
        # Daemon does NOT heartbeat — it's an "answering machine" that records
        # message arrivals to the logfile while no CC is open. Liveness
        # (agents/<id>.json last_seen) belongs to the foreground Monitor inside
        # CC; if the daemon also heartbeated, A would still look "alive" after
        # the user closes their terminal, and the next SessionStart's register
        # call would falsely fail with AgentCollision.
        pid, already = _watch.daemon_start_fork(
            _watch.watch_dir,
            args=(d,),
            kwargs={"interval": interval, "heartbeat": None},
            pidfile=pidfile,
            logfile=logfile,
        )
        typer.echo(
            json.dumps(
                {
                    "pid": pid,
                    "already_running": already,
                    "logfile": str(logfile),
                    "pidfile": str(pidfile),
                },
                ensure_ascii=False,
            )
        )
        return

    _watch.watch_dir(d, interval=interval, heartbeat=hb)


@app.command()
def status(coop: str = typer.Option(None, "--coop", "-c")):
    """Human-readable snapshot of the coop state."""
    root = coop_root(coop)
    typer.echo(f"coop:  {root}")
    typer.echo(f"comm:  {comm_dir(root)}")
    typer.echo("")
    typer.echo("agents:")
    for a in _agents.list_agents(root):
        typer.echo(
            f"  {a.get('id', '?'):24s} role={a.get('role', '?'):12s} "
            f"status={a.get('status', '?'):8s} last_seen={a.get('last_seen', '?')}"
        )
    if not _agents.list_agents(root):
        typer.echo("  (none)")
    typer.echo("")
    pending = _tasks.list_pending(root)
    typer.echo(f"tasks pending: {len(pending)}")
    for p in pending:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            typer.echo(f"  {d.get('id')} {d.get('title')!r} by {d.get('publisher')}")
        except Exception:
            typer.echo(f"  {p.name} (unreadable)")
    cr = tasks_claimed(root)
    if cr.exists():
        per_agent = {}
        for sub in sorted(cr.iterdir()):
            if not sub.is_dir():
                continue
            files = sorted(sub.glob("*.json"))
            if files:
                per_agent[sub.name] = files
        if per_agent:
            typer.echo("tasks claimed:")
            for ag, files in per_agent.items():
                for p in files:
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                        typer.echo(
                            f"  {d.get('id')} by {ag}: {d.get('title')!r}"
                        )
                    except Exception:
                        typer.echo(f"  {p.name} by {ag} (unreadable)")
    done = list(tasks_done(root).glob("*.json")) if tasks_done(root).exists() else []
    typer.echo(f"tasks done: {len(done)}")


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", help="confirm wipe of comm/"),
    coop: str = typer.Option(None, "--coop", "-c"),
):
    """Wipe comm/ entirely. Coordinator-only operation."""
    import shutil

    root = coop_root(coop)
    cd = comm_dir(root)
    if not yes:
        typer.echo(f"would wipe {cd} — pass --yes to confirm", err=True)
        raise typer.Exit(code=2)
    if cd.exists():
        shutil.rmtree(cd)
    ensure_layout(root)
    typer.echo(f"wiped and re-initialized: {cd}")


if __name__ == "__main__":
    app()
