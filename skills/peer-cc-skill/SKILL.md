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

**Priority: human always wins over peer signals.** While you're handling a
human turn and a peer-cc Monitor event fires (new inbox message, new task
notification), **finish the human's request first**. Do not abandon a human
mid-thought to inspect a peer message. The message file is durable on disk —
it will still be there on your next turn — and the peer expects asynchronous
delivery, not instant pickup. After the human turn closes, drain the inbox.
If a peer is genuinely blocked on you and the human turn is short, finish the
human cleanly, then process the inbox in the same response. If the human turn
is long, surface a one-line tail at the end ("N messages queued from B/C —
want me to handle them now?") and let the human decide. Peer notifications
**never** preempt human-facing work; that's how a single agent stays coherent
to the person it's actually talking to.

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

### When the human asks you a question

The human typically does **not** share your full context — especially after a
long multi-turn task, after they've been away, or after their conversation
context was compressed. They're asking you precisely because you hold state
they don't. Treat the answer as **needing evidence**, not just assertion.

- **Cite the source** — log line, file path + line number, message id, task
  id — that backs each non-trivial claim. "Training converged" →
  "Training converged: see `/abs/path/work/20260510-1430-smoke/stdout.log`
  around line 8421, final loss 0.31."
- **Pair quotes with paths.** A few lines lifted from the source can clarify,
  but always include the path so the human can scroll up and read more
  context. Never quote in isolation.
- **Show the input data behind decisions.** When you took an action on the
  human's behalf, point at the failing test, the error message, the config
  diff — not just the conclusion. The human shouldn't have to ask "why?".
- **Reference the work archive, not the chat.** Chat history compresses; the
  `<cwd>/work/<ts>-<slug>/` directory you wrote earlier doesn't. Lead the
  human to the durable record.
- **Flag memory-only claims explicitly.** If you're answering from
  recollection without a logged source — e.g. "I think B finished its crawl
  an hour ago" — say so. Lets the human decide whether to verify.

The asymmetry is sharpest after long autonomous runs. The human cannot reread
your inner reasoning; the durable record (logs, files, message archives) is
their only verification path. Make it easy to follow.

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

### Pass paths, not payloads (worker-to-worker content sharing)

The peer-cc premise is that **all participating agents share an accessible
mount** — every agent can resolve every absolute path on disk. So when you
hand a chunk of content to another worker (a script, a model output, a
dataset, a log, a written analysis), **don't inline it into `body.text`. Write
it to disk first, then message the absolute path plus a one-paragraph
summary.** This is the natural extension of the on-disk archive rule above:
content lives on disk by default, messages are pointers.

```
peer-cc send --to B --from <me> --type handoff --body \
  '{"path":"/abs/path/to/work/20260510-1430-smoke/result.md",
    "summary":"smoke test passed at iter 100, loss 0.31; full log at stdout.log in same dir, cmd.sh has the launch command"}'
```

Why:

- Messages are JSON files read in full whenever consumed; large bodies bloat
  the recipient's context window for no benefit.
- The recipient can re-read a file as many times as it needs and dip into
  parts of it; a consumed message moves to `processed/` and is awkward to
  reference again.
- Survives compression on the recipient side: if their chat history gets
  compressed, the file is still on disk; an inlined body that's already been
  acted on is effectively gone.
- Lets the recipient grep / `head` / `wc` / `jq` over the content with normal
  tools, instead of paging through a JSON body.

When NOT to use paths:

- Short instructions (`"retry the last task"`, `"you're the keeper, C is the
  guesser"`).
- Small structured params (ids, numbers, enums, choices) — JSON body is the
  right shape for these.
- One-shot signals (`status_query`, `ack`, `heartbeat_pong`).

Rule of thumb: if the content is longer than ~5 lines, contains code, or
includes anything the recipient would want to re-read in pieces, write to
disk first and reference the path in the message.

### Liveness checks for co-work (peers can die silently)

A CC session can interrupt at any moment — API errors, OOM, network blips,
terminal killed, context window exhausted. If your work **depends on a peer's
reply** (you're blocking on `B`'s `task_result`, `infra_ready`, or your
custom response type), the inbox message you wrote may sit there forever and
you may never know. Don't trust silence as progress.

Before you kick off co-work, set up liveness checks:

1. **Agree on a heartbeat cadence with the peer in the kickoff message.**
   Scale it with the task's complexity, not a fixed number:
   - Quick exchange (seconds): no polling, just trust the inbox.
   - Medium task (minutes): peer heartbeats every ~60 s, you check every ~2 min.
   - Long task (hours): peer heartbeats every ~5 min, you check every ~15 min.
   - Multi-day or human-in-the-loop: heartbeat cadence becomes pro forma; you
     mostly rely on the human noticing.

   Bake the cadence into the kickoff body — `"send a peer-cc heartbeat every
   60s while running this"` — so the peer doesn't forget. PROTOCOL.md §7
   covers the heartbeat mechanism itself.
2. **Run a periodic liveness check on your side.** A simple Monitor:

   ```bash
   while true; do
     uv run peer-cc info --id B --json \
       | jq -r '"B last_seen=\(.last_seen) tokens=\(.input_tokens // "?")"'
     sleep 120
   done
   ```

   Filter to emit only when `last_seen` goes stale (older than ~3× the agreed
   cadence) so you don't drown in noise. PROTOCOL.md §11 buffering rules apply
   — wrap with `stdbuf -oL` if needed.
3. **Define "stale" up front.** Generally `~3× agreed cadence` is the right
   threshold — covers a normal slow turn but flags a real death.
4. **When a peer goes stale, escalate, don't hang.** Tell the human in one
   line: `"B last seen 12 min ago, no reply on the crawl task — reroute,
   retry, or wait?"`. If the peer was holding a queued task, ask the
   coordinator to `peer-cc remove --id <peer>` — that returns the task to
   `pending/` so another worker can claim it.

For **fire-and-forget messages** (you sent an instruction and don't actually
need a reply to proceed), skip all of this — the peer's life expectancy
isn't your problem and polling them is just noise.

### Script your status emission (so humans / peers don't have to ask)

Every time a human or peer has to message you "what's the status?" and wait
for you to read logs, summarize, and reply, that costs Claude turns plus
human-attention seconds — for information that's mostly **mechanical to
extract from the run itself**. Don't be a synchronous summary engine if a
small script can do it.

When a task is non-trivial and will run long enough that updates are wanted,
write a **status-emitter script alongside the launch**, point it at a known
file, and tell the human / peer to read that file. They `tail -F` (or `cat`)
directly; no agent turn needed.

```bash
# work/<ts>-<slug>/progress.sh — runs alongside the main job
{
  while sleep 30; do
    iter=$(grep -oP 'Iter \K\d+' stdout.log 2>/dev/null | tail -1)
    loss=$(grep -oP 'loss=\K[\d.]+' stdout.log 2>/dev/null | tail -1)
    echo "$(date -Iseconds) iter=${iter:-?} loss=${loss:-?}"
  done
} >> progress.log &
```

Then in chat: `"progress at /abs/work/<ts>-<slug>/progress.log, updates
every 30 s — tail it, no need to ask me."`

For peer sync the equivalent is a small **state file the peer reads
directly** via the shared mount, instead of sending you a `status_query`
message and waiting for you to read+reply:

```bash
# work/<ts>-<slug>/state.json — atomically rewritten on phase change
{ "phase": "training", "last_update": "2026-05-12T08:30:00Z",
  "next_milestone": "iter 5000" }
```

Three patterns worth scripting:

- **Milestone extractor**: grep for known markers in the live log, append one
  line per interval to `progress.log`; `tail -F` becomes the dashboard.
- **State file**: small JSON, atomic-rewrite (`mv -f tmp state.json`) on
  phase change. Both human and peer poll it cheaply, no race.
- **Terminal-state sentinel**: a wrapper that drops `done.ok` / `done.fail`
  when the run finishes; peers detect completion without polling logs.

When NOT to bother:

- Task is short (< 1 min) — just block and report when done.
- Progress is genuinely non-mechanical (needs your reasoning to summarize —
  e.g., debugging a flaky test) — in-chat reporting is the right shape there.

**Principle**: agent turns are the scarce resource in any reporting loop.
Push the mechanical part down to a script; reserve the agent for actual
decisions.

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
