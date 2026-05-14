"""Polling-based directory watcher. NFS-safe (unlike inotifywait).

Prints each new file path to stdout, line-buffered. Runs forever — kill it
externally (or use the daemon helpers below for detached operation). Hidden
files (starting with '.') and the 'processed' subdir are ignored, so atomic
tmp files don't trigger spurious events.

**Startup emits already-pending files.** On startup `seen` is empty, so the
first poll treats every existing un-consumed file as new and emits it. This
fixes the "watcher restart silently drops pending messages" bug: if the old
watcher died with N un-consumed messages still in the inbox, the new watcher
re-announces them. Trade-off: an unconsumed file is re-emitted on every new
watcher process — so always `peer-cc consume` after handling, otherwise you
get duplicate notifications next restart.

When a (coop, agent_id) heartbeat target is provided, also bumps that agent's
last_seen on a slow timer (default every 15s). This is what makes liveness
detection work across processes — register's own pid dies seconds after it
writes the record, so we use heartbeat freshness instead of pid checks for
the AgentCollision logic.

Daemon helpers (`daemon_start_fork`, `daemon_status`, `daemon_stop`) let the
watcher run as a detached system process whose lifetime is decoupled from the
parent shell / Claude Code session. The CC Monitor tool then `tail -F`s the
daemon's logfile instead of holding the watcher itself, so closing the
terminal doesn't kill the watcher.
"""
from __future__ import annotations

import errno
import os
import signal
import sys
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
    """Poll d for new files; print new paths. On startup, emits every existing
    file too (`seen` starts empty), so a freshly-launched watcher re-announces
    any pending un-consumed messages from a prior watcher's lifetime.
    Optionally heartbeat (coop_root, agent_id) every heartbeat_interval seconds
    so the agent stays counted as alive while this watcher is running."""
    d.mkdir(parents=True, exist_ok=True)
    # Start with an empty `seen` so the first poll emits every already-pending
    # file. This is the watcher-restart-doesn't-miss-messages fix.
    seen: set[str] = set()
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


# ----------------------------------------------------------------------
# Daemon helpers — run watch_dir as a detached process whose lifetime is
# independent of the parent CC session.

def _is_pid_alive(pid: int) -> bool:
    """`kill -0 <pid>`: True if the pid exists and we can signal it."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as e:
        # ESRCH: no such process. EPERM: exists but owned by another uid (still alive).
        return e.errno == errno.EPERM
    return True


def daemon_status(pidfile: Path) -> tuple[int | None, bool]:
    """Returns (pid_from_file_or_None, is_alive)."""
    try:
        pid = int(pidfile.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None, False
    return pid, _is_pid_alive(pid)


def daemon_start_fork(
    target: callable,
    args: tuple = (),
    kwargs: dict | None = None,
    *,
    pidfile: Path,
    logfile: Path,
) -> tuple[int, bool]:
    """Spawn target(*args, **kwargs) in a fully-detached daemon process.
    Idempotent: if pidfile points to a live process already, returns
    (existing_pid, True). Otherwise double-forks, writes pidfile, redirects
    stdout+stderr to logfile (append mode so history survives daemon
    restarts), and returns the grandchild's pid + False.
    """
    kwargs = kwargs or {}
    pid, alive = daemon_status(pidfile)
    if alive:
        return pid, True

    pidfile.parent.mkdir(parents=True, exist_ok=True)
    logfile.parent.mkdir(parents=True, exist_ok=True)

    # Stale pidfile from a dead process — clean up before spawning new
    if pidfile.exists():
        try:
            pidfile.unlink()
        except OSError:
            pass

    # First fork: parent waits for intermediate child to exit (which writes pidfile)
    intermediate = os.fork()
    if intermediate > 0:
        os.waitpid(intermediate, 0)
        try:
            new_pid = int(pidfile.read_text().strip())
        except (FileNotFoundError, ValueError):
            new_pid = -1
        return new_pid, False

    # Intermediate child: detach into a new session, fork again, write pidfile, exit
    try:
        os.setsid()
    except OSError:
        pass
    grandchild = os.fork()
    if grandchild > 0:
        try:
            pidfile.write_text(str(grandchild))
        except OSError:
            pass
        os._exit(0)

    # Grandchild (the actual daemon): redirect fds, run target, never return
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        devnull_fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(devnull_fd, 0)
        os.close(devnull_fd)
        log_fd = os.open(
            str(logfile), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
        )
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        os.close(log_fd)
        target(*args, **kwargs)
    except BaseException as e:
        try:
            print(f"daemon error: {e!r}", flush=True)
        except Exception:
            pass
    finally:
        try:
            pidfile.unlink()
        except OSError:
            pass
        os._exit(0)


def daemon_stop(pidfile: Path, sig: int = signal.SIGTERM, wait_sec: float = 2.0) -> bool:
    """Kill the daemon recorded in pidfile. Returns True if a live process was
    killed; False if no daemon was running (pidfile missing or stale)."""
    pid, alive = daemon_status(pidfile)
    if not alive:
        if pidfile.exists():
            try:
                pidfile.unlink()
            except OSError:
                pass
        return False
    try:
        os.kill(pid, sig)
    except OSError:
        pass
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    if pidfile.exists():
        try:
            pidfile.unlink()
        except OSError:
            pass
    return True
