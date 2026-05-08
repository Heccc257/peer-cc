# peer-cc protocol v0.1

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
3. **In ONE response, fire all three of these in parallel** (and put the
   step-5 greet as the text body of the same response):
   - `Bash`: `uv run --directory <coop> peer-cc register --role worker --id <id>`
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

After step 5 you're bootstrapped. §1–§10 below are reference — internalize
on first read, but do **not** re-execute the bootstrap.

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
3. Register yourself. **No `--coop` or env var needed** — `uv run --directory <coop>`
   chdir()s into the coop root, and peer-cc auto-detects coop from cwd:
   ```bash
   uv run --directory <coop-path> peer-cc register --role worker --id <id>
   ```
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
peer-cc register   --role {coordinator|worker} --id <id>
peer-cc heartbeat  --id <id> [--status <s>]
peer-cc deregister --id <id>
peer-cc agents
peer-cc send       --to <id> --from <id> --type <t> [--body '<json>'] [--reply-to <msg-id>]
peer-cc inbox      --id <id>
peer-cc consume    --id <id> --path <msg-path>
peer-cc task publish  --from <id> --title <s> [--body '<json>'] [--requires tag1,tag2]
peer-cc task list
peer-cc task claim    --agent <id> [--id <task-id>]
peer-cc task complete --agent <id> --id <task-id> [--result '<json>'] [--ok|--fail]
peer-cc watch  inbox --id <id>     # for Monitor tool — prints new file paths
peer-cc watch  tasks               # for workers polling tasks/pending/
peer-cc status
peer-cc reset  --yes               # coordinator only
```
