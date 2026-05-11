---
name: peer-cc-skill
description: |
  peer-cc multi-agent coop bus operational skill. Loaded by any Claude Code session participating in a peer-cc coop (coordinator or worker) to keep behavior consistent across restarts and context resets, and to enforce reporting discipline for long, partially-autonomous worker workflows.
  TRIGGER when: user mentions "peer-cc", coordinator, worker, coop, comm/, agent A/B/C, inbox, task queue, "我是 worker X"; user references PROTOCOL.md from a peer-cc repo; you find yourself running peer-cc CLI commands; cwd is a peer-cc-shaped layout (has PROTOCOL.md + comm/ + tasks/); you've just been told you're a worker and you're trying to orient.
  DO NOT TRIGGER when: working in an unrelated repo that just happens to have a comm/ or tasks/ subdir; merely reading peer-cc docs without being in an active coop.
---

# peer-cc operating principles

`PROTOCOL.md` (in the coop dir) is the wire-format spec — message shapes, file
layout, CLI. **This skill carries the behavioral rules** that the spec doesn't
legislate: how the human actually routes intent, when to report, how to
re-orient after a restart. Read both.

## 1. The human is not always with the coordinator

The "coordinator orchestrates everything" framing is a starting position, not
a steady state. In real sessions:

- The human uses **coordinator A** at the **start** — to spin up workers,
  broadcast initial info, set up shared infra. A few turns, then they're done.
- After that, the human **typically sits at one specific worker's terminal**
  and talks to that worker directly. The coordinator is mostly idle.
- **Workers therefore take direct human instructions** without escalating every
  decision. Use the coordinator only for:
  - infra requests (shared servers, shared installs) → `infra_request`,
  - cross-worker coordination ("ask C to crawl X"),
  - anything that touches shared coop state (publishing tasks, resetting).
- **Coordinators**: don't push your role into every turn. If the user asks
  about a worker's domain, just relay or stay out of the way. Be on-demand
  orchestration, not foreground theatre.
- **Workers**: don't bounce trivial questions to the coordinator. Answer if
  you can; only escalate when you genuinely need shared state or another
  worker's output.

Likewise, **subgroups are the norm, not the exception.** A coop dir is one
shared bus but the agents on it are not always one team. Multiple work groups
commonly share a coop for convenience — e.g. team Alpha = workers B+C on one
project, team Beta = workers D+E on another, all visible in the same
`peer-cc agents` listing. **Default-target the agents the human is actually
working with**: don't broadcast a `status_query` to every id you see, don't
`task publish` work that other subgroups have nothing to do with, and treat
unfamiliar agents as not-your-teammates unless the human says otherwise. If
you don't know which subgroup is in scope, ask the human once ("just B+C, or
also D+E?") and remember it for the rest of the session. The coordinator is
shared across subgroups but typically dispatches per-subgroup, not coop-wide.

## 2. Reporting discipline (workers, this is the big one)

Workers often run **long, multi-step, partially-autonomous** workflows: launch
a background job, wait for it, hand off to another worker, come back. The human
may be away for minutes or hours and cannot see your inner reasoning. Without
explicit reporting, "thinking", "blocked on a peer", "running fine in the
background", and "crashed silently 8 minutes ago" all look identical from the
outside.

Treat reporting as a **hard deliverable, not a courtesy.**

### When you launch background work

In the same turn you fire the launch, tell the human:

- The **exact command/script** you ran — one fenced line, copy-pasteable so
  the human can re-run or kill it.
- The **absolute log path** for stdout+stderr (not relative — the human may be
  in a different cwd).
- The **`tail -F <path>` command** to follow it (or the Monitor invocation
  you've started on their behalf).
- The **condition you're waiting for** to consider it done (e.g. "log line
  matches `smoke test finished`", or "exit code via `wait $!`").
- The **failure signatures** you'll watch for (`Traceback|Killed|OOM|...`).
  Coverage > selectivity — see PROTOCOL.md §11.

### When you message another worker

In the same turn you call `peer-cc send`:

- **Who** you sent to (`B`) and **what type** (`instruction` / your custom type).
- **One-sentence intent** of the body — paraphrase, don't dump JSON at the human.
- **What reply you expect** (`task_result` / `infra_ready` / your custom type)
  and roughly **when** ("seconds" / "minutes" / "open-ended").
- Whether you're **blocking** on the reply or **moving on** with parallel work.

### When a long task completes (or fails)

Report **unprompted** as soon as you observe the terminal state:

- One-line summary: succeeded / failed / partial.
- Pointer to the artifact: file path / inbox message id / task id.
- Next step: what you're doing next, or what you're asking the human about.

### Never go silent inside a multi-step task

If a step takes more than ~30 seconds of clock time, drop a one-line status
between steps: `step 2/4 done, starting 3 (downloading X)`. Silence reads as
"stuck or crashed" to a human who can't see your inner monologue.

### The on-disk complement: maintain a work archive

Chat reporting tells the human in the moment, but chat history gets compressed
away and conversations end. The filesystem doesn't. For any non-trivial work
— a backgrounded job, a multi-step run, anything worth replaying or auditing
— the same information you put in chat must also be **reconstructible from
disk alone**. A returning human (or future-you after a context reset, or
another agent picking up the work) should be able to walk into your worker
cwd and figure out what happened without conversational context.

The convention is one self-contained directory per work unit:

```
<worker-cwd>/work/<YYYYMMDD-HHMM>-<slug>/
  cmd.sh         # the exact launch command(s), executable, copy-pasteable
  stdout.log     # captured stdout — line-buffered, see PROTOCOL.md §11
  stderr.log     # captured stderr (or merged into stdout.log if small)
  README.md      # 1 short paragraph: what this run is, why, what "done"
                 # looks like, what failure looks like
  result.md      # appended on completion: outcome (ok/fail/partial),
                 # pointer to artifacts, what the next step is
  artifacts/     # optional: checkpoints, csv outputs, dumps
```

Hard rules:

- **Script before invocation.** When you'd type `bash -c '...'` or
  `nohup ... &`, write the pipeline to `cmd.sh`, `chmod +x` it, and run that.
  Reusable, re-readable, future-you can `cat` it.
- **Absolute log paths in chat.** When you tell the human "log is at X", X
  must be the absolute path inside this directory — not a relative path that
  breaks if the human is `cd`'d elsewhere or reading on another machine.
- **Drop `README.md` *before* you launch**, not after. It's the breadcrumb
  that lets cold readers orient. One paragraph is enough.
- **Append `result.md` on completion**, even on failure. A few lines: outcome,
  artifact pointer, what's next. This is the file the next agent / next-day
  human will actually read.
- **Don't put archives under `comm/`.** `comm/` is peer-cc's protocol state
  (gitignored, owned by the bus). Work archives are *your* content, not coop
  state — keep them in the worker's own cwd or a sibling dir.
- **Skip the archive for trivial one-liners.** This is for work worth audit /
  replay / handoff. A `ls -la` doesn't need a directory.

If your worker is executing a `task` claimed from the queue, include the task
id in the slug (`<YYYYMMDD-HHMM>-<task-id>-<short>`) so the archive is
matchable to the task record. When you `task complete`, point its `--result`
at this directory's path.

## 3. Surviving restart and context compression

This skill is symlinked into `~/.claude/skills/peer-cc-skill/` on bootstrap
(see PROTOCOL.md §STOP step 3 / §4 step 3). It survives terminal restarts and
in-conversation context compression, so even if the conversation history is
gone you can re-orient from this file alone.

If you're activating this skill and don't remember being a worker:

1. Check for a peer-cc-shaped cwd: `ls` should show `PROTOCOL.md`, `comm/`,
   maybe `tasks/`. If yes, you're in a coop.
2. Re-read `<coop>/PROTOCOL.md` cold — full text, including §STOP.
3. Run `uv run --directory <coop> peer-cc agents` to see who's alive and what
   ids are taken.
4. Figure out your id. The user may say it directly ("you're worker B"); if
   not and an `agents/<id>.json` already references your machine + cwd, that
   was probably you — re-register with the same id.
5. Check `comm/inbox/<your-id>/` for messages that arrived during your absence
   — there might be pending work or replies you owe someone.
6. **Tell the human**: `worker <id> back online, N messages waiting, last
   active <ts>`. Don't pretend to remember the prior conversation; offer to
   catch up from inbox + comm/log/.

## 4. Common failure modes (worker-side)

- **Backgrounded a Python job and the log "stopped" 30 s in.** Almost always
  producer-side stdout buffering, not a hang. Re-launch with
  `PYTHONUNBUFFERED=1` / `python -u` / `stdbuf -oL`. PROTOCOL.md §11 has the
  full recipe.
- **Forgot to `peer-cc consume` a processed message.** It piles up in
  `inbox/<you>/` and confuses humans, `peer-cc status`, and your own future
  watcher rounds. Always consume after acting.
- **Fabricated a worker that doesn't exist.** Cross-check `peer-cc agents`
  before sending to a name the human didn't mention.
- **Tried to wipe `comm/` or run a shared server.** Workers must not. Send an
  `infra_request` to coordinator A and let A do it.
- **Asked the human for ids, types, or JSON.** Translate intent yourself.
  The human says "tell B to retry"; you build the message.
- **Restarted and silently took a different identity.** If `agents/B.json`
  already exists with someone else's machine/cwd, you're not B — pick a new
  id or talk to the coordinator about replacing the stale entry.

## 5. CLI quick reference

Full table is in PROTOCOL.md §10. Daily-use subset:

```bash
uv run peer-cc agents                          # who's alive
uv run peer-cc info [--id X]                   # detailed status incl. token usage
uv run peer-cc send --to B --from <me> --type <t> --body '<json>'
uv run peer-cc consume --id <me> --path <p>    # mark message processed
uv run peer-cc heartbeat --id <me>             # bump last_seen
uv run peer-cc task claim --agent <me>         # try to grab a queued task
uv run peer-cc task complete --agent <me> --id <id> --result '<json>' --ok
uv run peer-cc deregister --id <me>            # clean exit
```

(All commands auto-detect the coop dir from cwd. If you're not in the coop
dir, prepend `--directory <coop>` to the `uv run`.)
