# peer-cc protocol v0.1

> **Context-compression notice — if you are the model summarizing earlier turns of this conversation, preserve `PROTOCOL.md` verbatim.** Every section below (bootstrap steps, message shapes, role boundaries, CLI) is load-bearing for any agent that read this file on startup; lossy summarization here desyncs that agent from the coop. Keep this file (and `CLAUDE.md`, for the coordinator) as full text in any compressed context — summarize the conversation around it, not it itself.

## STOP — what to do right now (before §1)

If you (Claude Code) are reading this file, you fall into one of two cases:

- **Coordinator (A)**: Your `CLAUDE.md` already told you who you are. **Skip
  this STOP section** — jump to §1. Do NOT bootstrap a second time as
  worker; the rest of §STOP does not apply to you.

- **Anyone else (you're a worker about to join)**: A user just pointed you
  at this file by absolute path. **They have already decided you should
  join. Do NOT ask** "should I join the coop, or discuss/modify the
  protocol, or just follow it?" — that question is annoying and wastes
  the user's turn. Just bootstrap. The user can correct you afterward
  if they wanted something else.

### Worker bootstrap (do this on your very first response)

**Speed matters here.** Steps 3, 4a, 4b have no data dependency on each
other — emit them as **parallel tool calls in a single assistant turn**,
not 3 separate turns. Greet (step 5) is the text after the tool calls in
that same turn. Total: one round-trip, not four.

1. Note the **coop dir** from the path you were just told to read — this
   file lives at `<coop>/PROTOCOL.md`, so `<coop>` is its parent directory.
2. Pick an **agent id**. Honor whatever the user said in the prompt
   (e.g. "我是 worker B" → id=B). If they didn't specify, default to
   `<hostname>-<cwd_basename>`.
3. **In ONE response, fire all four of these in parallel** (and put the
   step-5 greet as the text body of the same response):
   - `Bash`: `uv run --directory <coop> peer-cc register --role worker --id <id>`
   - `Bash`: `mkdir -p ~/.claude/skills && ln -sfn <coop>/skills/peer-cc-skill ~/.claude/skills/peer-cc-skill`
     — installs the operational skill (idempotent; survives terminal restart
     and context compression so behavioral rules don't get lost).
   - `Monitor` (inbox): `uv run --directory <coop> peer-cc watch inbox --id <id>`
   - `Monitor` (tasks): `uv run --directory <coop> peer-cc watch tasks --id <id>`

   When the task Monitor emits a path, try `peer-cc task claim --agent <id>`;
   losing the race (`exit 2`) is normal — go back to idle.
4. (subsumed into step 3 above — kept here only so §4 numbering doesn't drift)
5. Greet the user on a **single line**, in the same response that fired the
   three tool calls:
   `worker <id> joined coop at <coop>, idle. Watching inbox + task queue.`

Why parallel is safe: the watchers create their dirs lazily (mkdir on first
poll), and their first heartbeat (which writes agents/<id>.json) doesn't
fire until 15 s in — long after `register` has finished writing its record.
There is no race.

After step 5 you're bootstrapped. §1–§12 below are reference — internalize
on first read, but do **not** re-execute the bootstrap.

---

## Operating principles (apply throughout your time in this coop)

The full discussion lives in `skills/peer-cc-skill/SKILL.md`, symlinked into
`~/.claude/skills/peer-cc-skill/` on bootstrap so it survives terminal restart
and in-conversation context compression. Four rules in summary:

1. **The human is not always with the coordinator.** Initial spin-up goes
   through coordinator A; afterwards the human usually sits at one specific
   worker's terminal and talks to that worker directly. Workers act on direct
   human instructions without escalating every decision; coordinator is idle
   except for infra requests and cross-worker coordination. Don't push the
   "coordinator orchestrates everything" framing into routine turns.
2. **Report unprompted, especially around backgrounded work.** After launching
   a long task, handing off to another worker, or finishing a multi-step run,
   tell the human in plain text: exact command, absolute log paths, what
   you're waiting for, what failure signatures matter. Hard rules in §12.
3. **Inbox hygiene.** Always `peer-cc consume --id <you> --path <p>` after
   acting on a message — else it lingers and confuses humans and `peer-cc
   status`.
4. **Skill-first re-orientation after restart.** If your terminal or context
   was reset, the peer-cc-skill auto-loads from `~/.claude/skills/`. Re-read
   `<coop>/PROTOCOL.md` cold and check `comm/inbox/<you>/` for missed messages
   before you act on whatever the human just said.
5. **One coop ≠ one team.** Multiple subgroups commonly share a coop for
   convenience (team Alpha = B+C, team Beta = D+E, all in the same `comm/`).
   Default-target the agents the human is actually working with — don't
   broadcast `status_query` / `task publish` across every id in `peer-cc
   agents` unless explicitly asked. The coordinator is shared but typically
   dispatches per-subgroup. If subgroup membership is ambiguous, ask the human
   once and remember.
6. **Pass paths, not payloads.** The peer-cc premise is a shared mount —
   every agent can resolve every absolute path on disk. When you hand
   non-trivial content to another worker (script, result, log, analysis,
   dataset), **write it to disk first and message the absolute path + a
   one-paragraph summary**, not the content itself. Inline `body.text` is for
   short instructions and small structured params; large bodies bloat the
   recipient's context, and once a message is consumed the body is in
   `processed/` and inconvenient to re-read, while a file on disk stays put.
   See `skills/peer-cc-skill/SKILL.md` §2.
7. **Human always wins.** When a peer-cc Monitor event fires (new inbox
   message, new task) while you're handling a human turn, **finish the human
   request first** — never abandon a human mid-thought to chase a peer signal.
   The inbox file is durable; the peer can wait one turn. After the human
   turn closes, process queued messages; or, if the turn is long, mention at
   the end that "N messages queued from B/C" and let the human decide whether
   to address them now or keep going. Peer notifications never preempt
   human-facing work.
8. **Peers can die silently — set up liveness before co-work.** A CC session
   can interrupt at any moment (API errors, OOM, network, terminal killed,
   context window exhausted). If your work depends on a peer's reply, don't
   block on it indefinitely. Before kicking off, agree on a heartbeat cadence
   with the peer (scaled to task complexity — ~60 s for minute-long tasks,
   ~5 min for hour-long tasks), and run a periodic check on
   `peer-cc info --id <peer>` for `last_seen`. If the peer goes stale beyond
   ~3× the cadence, surface it to the human and consider asking the
   coordinator to `peer-cc remove --id <peer>` so any held task returns to
   `pending/`. PROTOCOL §7 covers the heartbeat mechanism;
   `skills/peer-cc-skill/SKILL.md` §2 has the recipe.
9. **Re-anchor on the world, not memory.** When the user mentions a peer
   agent for the first time in a turn, or you've just resumed from session
   restart / context compression, run **one** batched check before acting —
   `peer-cc agents --alive` plus `peer-cc inbox --id <you> | wc -l` plus a
   pidfile check on your inbox watcher daemon. Don't trust memory of the
   last state, but don't burn multiple round-trips asking individually
   either. Surface gaps to the human once. SKILL.md §1 has the bash recipe.

---

## 1. Glossary

| Term | Meaning |
|---|---|
| **coop dir** | The cloned `peer-cc` repo on a shared filesystem. Path passed via `--coop` or `PEER_CC_COOP` env. Hosts `PROTOCOL.md`, `comm/`, scripts. |
| **comm dir** | `<coop>/comm/`. All runtime state. Gitignored. |
| **agent** | One Claude Code session that has registered itself in `comm/agents/`. |
| **coordinator** | The agent running CC inside the coop dir itself; has `CLAUDE.md` auto-loaded. Owns task publication and infra setup. |
| **worker** | Any other agent. Runs CC in its own cwd; joins by reading this file. |

---

## 2. Directory layout (the actual protocol)

```
<coop>/
├── CLAUDE.md                        # coordinator-only bootstrap (auto-loaded)
├── PROTOCOL.md                      # this file — shared spec
├── README.md
├── pyproject.toml                   # peer-cc CLI package
├── peer_cc/                         # source
└── comm/                            # GITIGNORED — runtime state
    ├── agents/
    │   └── <id>.json                # one per agent, atomic-written
    ├── inbox/
    │   └── <id>/
    │       ├── <ms>-<rand>.json     # incoming messages (oldest first by name)
    │       └── processed/           # consumed messages live here for audit
    ├── tasks/
    │   ├── pending/<task-id>.json   # published, unclaimed
    │   ├── claimed/<agent>/<id>.json # claimed by that agent (atomic mv)
    │   └── done/<id>.json           # completed (success or failure)
    └── log/
        └── YYYY-MM-DD.jsonl         # global event stream, one JSON per line
```

**File naming convention.** Messages and tasks use `<13-digit-ms-timestamp>-<8-hex>.json`.
Lex sort = chronological sort. Hidden files (starting with `.`) are tmp files;
the watcher and listings ignore them.

---

## 3. Roles & boundaries

### Coordinator (one per coop)

May:
- Publish tasks (`peer-cc task publish`).
- Run servers, install deps, do shared infra setup.
- Wipe / reset coop (`peer-cc reset --yes`).
- Edit `PROTOCOL.md` (and announce changes).

Should:
- Aggregate worker results and report to the human.
- Route `infra_request` from workers → execute → reply `infra_ready`.

### Worker (zero or more per coop)

May:
- Send messages, claim tasks, complete tasks, send `infra_request` for shared resources.
- Do whatever the user asks within its own cwd (its primary job).

Must NOT:
- Run shared servers or install global deps. Send `infra_request` to coordinator instead.
- Publish tasks directed at other workers. Ask coordinator to publish on your behalf.
- Wipe `comm/`.

Boundary enforcement is **prompt-level**, not technical. Honor your role.

---

## 4. Bootstrap

### Coordinator (auto via `CLAUDE.md`)
1. `peer-cc init` — creates comm/ subdirs.
2. `peer-cc register --role coordinator --id <name>`.
3. Start `peer-cc watch inbox --id <name>` via the Monitor tool.

### Worker (manual, one user sentence is enough)

> **Quick path: see §STOP at the top of this file** — it has the imperative
> 5-step bootstrap optimized for one round-trip (parallel register + 2
> watchers + greet in a single response). The text below is reference.

When the user's prompt names `<coop-path>/PROTOCOL.md` (typically pasted from
`peer-cc join-prompt [<id>]` — the bare phrase `加入 X` is ambiguous with
`/add-dir`, so referencing the file by absolute path is what makes CC reliably
read this spec and follow it):

1. Read `<coop-path>/PROTOCOL.md` (this file).
2. Pick an agent id — default `<hostname>-<cwd_basename>` if the user didn't
   name one in the prompt; otherwise honor what they said (e.g. "我是 worker B" → id=B).
3. Register yourself **and install the operational skill** (idempotent — safe
   to re-run on every bootstrap). **No `--coop` or env var needed** —
   `uv run --directory <coop>` chdir()s into the coop root, and peer-cc
   auto-detects coop from cwd:
   ```bash
   uv run --directory <coop-path> peer-cc register --role worker --id <id>
   mkdir -p ~/.claude/skills && ln -sfn <coop-path>/skills/peer-cc-skill ~/.claude/skills/peer-cc-skill
   ```
   The skill at `~/.claude/skills/peer-cc-skill/` carries the behavioral rules
   (reporting discipline, restart re-orientation, etc.) so they survive
   terminal restart and context compression on this machine. See
   `<coop>/skills/peer-cc-skill/SKILL.md` for the full text.
   (Do NOT use `export PEER_CC_COOP=...`. CC's Bash tool starts a fresh shell
   per call, so env vars don't persist across tool invocations. Always invoke
   peer-cc through `uv run --directory <coop-path>` instead.)
4. Start **two** Monitor watchers in the background — they are both essential:
   - **Inbox watcher** (messages addressed directly to you):
     ```
     uv run --directory <coop-path> peer-cc watch inbox --id <id>
     ```
   - **Task queue watcher** (unaddressed tasks anyone can claim). Pass `--id`
     so the watcher heartbeats your record while it runs:
     ```
     uv run --directory <coop-path> peer-cc watch tasks --id <id>
     ```
   When the task watcher emits a path, try `peer-cc task claim --agent <id>`.
   Losing the race is normal (`exit 2`, stderr `none`) — just go back to idle.
   Winning means you own that task; do the work, then `peer-cc task complete`
   and send a `task_result` message to its publisher.
5. Greet the user: `worker <id> joined coop at <coop-path>, idle. Watching inbox + task queue.`

**Dual-watch rationale.** Inbox is for "B specifically, please do X"; task queue
is for "any idle worker, please do X". Both are needed for auto coop — without
the task watcher you can only respond to direct messages and the coordinator
can't load-balance.

---

## 5. Messaging

Every file in `inbox/<to>/` is a JSON object with this shape:

```json
{
  "id": "1746710445123-a1b2c3d4",
  "ts": "2026-05-08T12:34:05Z",
  "from": "A",
  "to": "B",
  "type": "instruction",
  "body": { "text": "do the thing" },
  "reply_to": "1746710440000-..."        // optional, for request/response pairing
}
```

### Standard `type` values

| `type` | Direction | Body | Reply expected |
|---|---|---|---|
| `instruction` | any → any | `{text}` or domain-specific | optional `ack` |
| `status_query` | any → any | `{}` | `status_reply` with agent's current state |
| `status_reply` | reply | full agent record | no |
| `infra_request` | worker → coordinator | `{kind, spec}` (e.g., `{"kind":"port","spec":{"name":"db","port":5432}}`) | `infra_ready` or `infra_failed` |
| `infra_ready` | coordinator → worker | `{endpoint, notes}` | no |
| `infra_failed` | coordinator → worker | `{reason}` | no |
| `task_result` | worker → publisher | `{task_id, ok, output}` | no |
| `heartbeat_ping` | optional, ad-hoc | `{}` | `heartbeat_pong` |
| `human_relay` | human → any (typed via slash command or echoed file) | `{text}` | none |

You may invent new `type` values for your domain — keep them lowercase
snake_case and document them in a session-local addendum if they recur.

### Sending

```bash
peer-cc send --to B --from A --type instruction --body '{"text":"start crawl"}'
```

The CLI writes to `comm/inbox/B/.<id>.json.tmp.<pid>`, fsyncs, then `os.rename`s
to `comm/inbox/B/<id>.json`. Consumers therefore never see a partial JSON.

### Receiving

You watch your inbox with `peer-cc watch inbox --id <you>` invoked via the
Monitor tool. Each emitted line is one new file path. Process flow:

1. Read the file (`Read` tool or `cat`).
2. Decide & act on the message (may itself trigger `peer-cc send` to reply).
3. `peer-cc consume --id <you> --path <path>` — atomically moves the file to
   `inbox/<you>/processed/`. Skip this step and the watcher will re-emit it on
   subsequent rounds — actually no, our watcher only emits *new* files, but
   the file accumulating in inbox/ confuses humans and `peer-cc status`. Always consume.

---

## 6. Tasks

Tasks are an extra abstraction on top of messages, used when the publisher
doesn't care which worker picks up the work — first-claim-wins.

### Lifecycle

```
publish → tasks/pending/<id>.json
   ↓
claim   → tasks/claimed/<agent>/<id>.json   (atomic os.rename)
   ↓
complete → tasks/done/<id>.json (with result, ok flag)
   ↓
optional: send 'task_result' message back to publisher
```

### Schema

```json
{
  "id": "1746710445123-aabbccdd",
  "ts": "2026-05-08T12:34:05Z",
  "publisher": "A",
  "title": "Crawl example.com",
  "body": { "url": "https://example.com", "depth": 2 },
  "requires": ["python", "network"],
  "status": "pending"
}
```

`requires` is a list of capability tags. Workers should only claim tasks whose
`requires` they can fulfil. There is no enforcement — just a hint.

### Atomic claim

`peer-cc task claim --agent <id>` does `os.rename(pending/X, claimed/<id>/X)`.
On POSIX same-FS (incl. NFSv4), rename is atomic. The losing racer gets
`FileNotFoundError`, exit code 2, stderr `none`. Standard worker loop:

```bash
while true; do
  out=$(uv run peer-cc task claim --agent <me> 2>/dev/null) || { sleep 1; continue; }
  task_id=$(echo "$out" | jq -r .id)
  # ... do work ...
  uv run peer-cc task complete --agent <me> --id "$task_id" --result '{"output":"..."}' --ok
done
```

In Claude Code, you don't run this loop yourself — instead, watch
`tasks/pending/` via Monitor and try to claim each new file as it appears.

---

## 7. Heartbeat & liveness

- Every agent's `agents/<id>.json` has a `last_seen` field.
- Refresh it with `peer-cc heartbeat --id <you> [--status busy|idle|done]`
  whenever you act (a few times per session is enough; you don't need a timer).
- `peer-cc status` shows `last_seen`. The coordinator (or a human) can decide
  to consider an agent stale based on age.
- On graceful exit: `peer-cc deregister --id <you>` (sets `status=left`).

---

## 8. Cross-machine notes

- **Filesystem requirements**: POSIX semantics for `rename` (atomicity, ENOENT on
  target absence) and stable inode-on-rename. NFSv4, ext4-over-iSCSI, most SAN
  setups: ✅. sshfs, s3fs, fuse-overlay-on-readonly: ⚠️ — fall back to lockfile
  pattern (out of scope for v0.1).
- **Clock skew**: agents stamp messages with their own UTC clocks. NTP-sync all
  participating machines, or `last_seen` ordering will lie.
- **Notification model**: `inotifywait` does **not** propagate cross-machine over
  NFS (kernel watches local writes only). Always use `peer-cc watch` (polling) —
  it works the same whether the writer is local or remote.
- **Path uniformity**: the same coop dir must be reachable at the same path on
  every machine, OR every agent passes its own `--coop` arg. Mixing the two is
  fine, but be consistent within an agent.

---

## 9. Human in the loop

- **Drop a manual message**:
  ```bash
  echo '{"id":"manual-001","ts":"...","from":"human","to":"B","type":"instruction","body":{"text":"please stop"}}' \
    > <coop>/comm/inbox/B/manual-001.json
  ```
  …or just walk to B's terminal and tell B's CC directly. Both work.
- **Watch progress**: `tail -f <coop>/comm/log/*.jsonl` shows every event.
- **Snapshot**: `peer-cc status` for who's alive and what's queued.

---

## 10. CLI cheatsheet

All commands accept `--coop <path>` or read `PEER_CC_COOP` env.

```
peer-cc init
peer-cc register   --role {coordinator|worker} --id <id> [--force]
peer-cc heartbeat  --id <id> [--status <s>]
peer-cc deregister --id <id>
peer-cc agents     [--alive] [--alive-window <sec>]
peer-cc sweep      [--threshold-sec <sec>] [--dry-run]   # bulk-evict stale agents (no live watcher)
peer-cc info       [--id <id>] [--json]                  # token usage + session details
peer-cc remove     --id <id> [--keep-claimed]
peer-cc send       --to <id> --from <id> --type <t> [--body '<json>'] [--reply-to <msg-id>]
peer-cc inbox      --id <id>
peer-cc consume    --id <id> --path <msg-path>
peer-cc task publish  --from <id> --title <s> [--body '<json>'] [--requires tag1,tag2]
peer-cc task list
peer-cc task claim    --agent <id> [--id <task-id>]
peer-cc task complete --agent <id> --id <task-id> [--result '<json>'] [--ok|--fail]
peer-cc watch  inbox --id <id> [--daemon|--stop]    # foreground: for Monitor tool. --daemon: detached, writes to comm/inbox/<id>/.watch.log so messages aren't lost while CC is closed
peer-cc watch  tasks --id <id> [--daemon|--stop]
peer-cc status
peer-cc reset  --yes               # coordinator only
```

---

## 11. Watching long subprocesses (read before you tail logs)

Whenever you launch a process and plan to watch its progress via the Monitor
tool (or plain `tail -F`), fix output buffering **at the launch site**, not at
the watcher. `grep --line-buffered` only fixes the pipe stage — it cannot
unbuffer the producer.

- **Producer-side stdout is fully-buffered when redirected to a file**
  (Python, Node, Go, most logging libs that wrap stdout — typically ~4–8 KB
  blocks, not line-buffered). Lines pile up in the producer's buffer and
  arrive at the watcher in bursts. Fix at launch:
  - Python: `PYTHONUNBUFFERED=1 cmd ...` or `python -u`
  - Any binary: `stdbuf -oL -eL cmd ...` (line-buffer stdout+stderr); or
    `unbuffer cmd ...` (from the `expect` package; makes the child think
    stdout is a TTY)
- **Sparse grep filter feels like silence.** If you only match milestone
  lines (every Nth iter), the in-between lines are dropped and the run
  looks stuck even when fine. Always include failure signatures
  (`Traceback|Error|FAILED|Killed|OOM|assert`) alongside progress markers
  so a crash still emits something. Coverage > selectivity for monitors.
- **`head -N` caps total events.** When bursts arrive, the cap eats real
  events. Drop `head` for open-ended watches; rely on filter selectivity.
- **`tail -F` polling adds ~1 s** of inotify/poll latency on top of
  whatever the producer does. Fine for most things; don't expect sub-second.

Applies broadly: GPU training, web servers, data pipelines, batch jobs —
any subprocess whose stdout is redirected to a file.

---

## 12. Reporting discipline (workers especially)

Workers often run **long, multi-step, partially-autonomous** workflows: launch
a background job, wait for it, hand off to another worker, come back. The
human may be away for minutes or hours. Without proactive reporting, "thinking",
"blocked on a peer", "running fine in the background", and "crashed silently
8 minutes ago" all look identical from the outside. Treat reporting as a hard
deliverable, not a courtesy. Full discussion + examples live in
`skills/peer-cc-skill/SKILL.md` §2; the must-do rules are below.

- **When you launch background work**, in the same turn tell the human:
  the **exact command** (one fenced line, copy-pasteable); the **absolute log
  path** for stdout+stderr; the **`tail -F <path>`** invocation to follow it
  (or the Monitor you started on their behalf); the **condition you're waiting
  for** to call it done; the **failure signatures** you'll watch for. §11
  buffering rules apply — a silent log usually means producer-side buffering,
  not a hang.
- **When you message another worker**, in the same turn tell the human: who
  you sent to; the message `type` and one-sentence intent of the body; what
  reply you expect and roughly when; whether you're blocking on it or moving
  on with parallel work.
- **When a long task completes (or fails)**, report **unprompted**: one-line
  summary (succeeded / failed / partial); pointer to the artifact (path,
  message id, task id); the next step you're taking or asking about.
- **Never go silent inside a multi-step task.** If a step takes more than ~30 s
  of clock time, drop a one-line update between steps ("step 2/4 done,
  starting 3"). Silence reads as "stuck or crashed" to a human who can't see
  your inner reasoning.
- **When the human asks a question, cite evidence.** They typically don't
  share your full context — especially after long multi-turn runs or context
  compression. Anchor non-trivial claims to concrete pointers (log line
  numbers, absolute file paths, message ids, task ids); the work-archive
  directory is the human's verification path. Don't answer purely from
  recollection — and if you must, flag it. See `skills/peer-cc-skill/SKILL.md`
  §2 for examples.

This applies to coordinators too when they handle `infra_request` or run any
shared setup — same rules, same reasoning.
