# peer-cc

A file-based multi-agent coop bus for Claude Code. No daemon, no SQLite, no
MCP server — just a shared directory, JSON messages, and ~10 atomic CLI ops.
Designed so a human can `tail -f` the whole conversation and intervene by
hand at any time.

## How it works

Three Claude Code sessions cooperate by reading and writing files under a
shared `comm/` directory:

```
A (coordinator)  ──┐
B (worker)       ──┼──→  /mnt/shared/peer-cc/comm/{agents,inbox,tasks,log}/
C (worker)       ──┘
```

- **A** clones this repo, runs `claude` inside it. CLAUDE.md auto-loads and
  tells A "you are the coordinator" — it inits comm/, registers itself, and
  starts watching its inbox.
- **B** and **C** run CC in their own work directories. The user types one
  sentence: `加入 /mnt/shared/peer-cc, 我是 worker`. CC reads PROTOCOL.md
  from the coop, registers as a worker, watches its own inbox, and gets back
  to the user's actual work.
- All inter-agent traffic is JSON files atomically written into `comm/inbox/`
  and `comm/tasks/`. Atomicity is `os.rename` over a tmp file → no half-written
  reads. Cross-machine claiming is `os.rename(pending/X, claimed/me/X)` — the
  losing racer gets ENOENT.

## Session model

**One peer-cc directory = one persistent session.** The `comm/` dir IS the
session — agents come and go, the session lives as long as comm/ does.

- Workers can join, leave, crash, and rejoin freely. Their `agents/<id>.json`
  records persist; new joins refresh the same record.
- Only **one coordinator at a time** per session. If you accidentally launch
  a second `claude` in the peer-cc dir, the SessionStart hook detects the
  collision (existing coordinator's heartbeat is fresh — the running watcher
  bumps `last_seen` every 15 s) and refuses to register the new CC. Either
  close the duplicate or wipe the session.
- **Wipe the session** with `uv run peer-cc reset --yes` — deletes everything
  under `comm/` (agents, inbox, tasks, log) and recreates the empty layout.
  Existing worker CC sessions become "orphaned" (their watchers see empty
  dirs); close them too or have them re-join with the same one-sentence prompt.

## Install

The coop dir must live on a shared filesystem reachable by every participating
machine (NFSv4, SAN, etc. — not sshfs/s3fs).

```bash
# on a shared FS
git clone <this-repo> /mnt/shared/peer-cc
cd /mnt/shared/peer-cc
uv sync                          # creates .venv, installs typer
```

Each agent's machine just needs `uv` available. No global install required —
agents run `uv run --directory /mnt/shared/peer-cc peer-cc ...`.

## Usage

### Coordinator (machine A)

```bash
cd /mnt/shared/peer-cc
claude                           # CLAUDE.md auto-loads, A boots up
```

That's it — CC handles `peer-cc init`, registration, and the inbox watcher
itself by following CLAUDE.md.

### Worker (machine B, in its own work dir)

```bash
cd ~/my-actual-project
claude
```

Then in CC, paste a prompt that names the **absolute path** of PROTOCOL.md.
(The bare phrase `加入 <path>` is risky — CC may interpret it as the
`/add-dir` slash command. Naming the protocol file by full path makes the
intent unambiguous.)

```bash
uv run --directory /mnt/shared/peer-cc peer-cc join-prompt        # no id → worker self-names <host>-<cwd_basename>
# Outputs:  读 /mnt/shared/peer-cc/PROTOCOL.md

uv run --directory /mnt/shared/peer-cc peer-cc join-prompt B      # pin id=B
# Outputs:  读 /mnt/shared/peer-cc/PROTOCOL.md, 我是 worker B
```

Paste either line into B's CC. It will read `/mnt/shared/peer-cc/PROTOCOL.md`,
follow §4 worker bootstrap (register, start inbox + tasks watchers), and from
this point on do two things in parallel: its own work for you, and processing
inbox messages as they arrive.

### Human supervision

```bash
# tail the global event log
tail -f /mnt/shared/peer-cc/comm/log/*.jsonl

# snapshot
uv run peer-cc status --coop /mnt/shared/peer-cc

# inject a manual message
uv run peer-cc send \
  --coop /mnt/shared/peer-cc \
  --from human --to B --type instruction \
  --body '{"text":"please switch to plan B"}'
```

…or just walk to B's terminal and chat with B's CC directly. Both channels
co-exist.

## Worked example: B↔C cooperate on a number-guessing game

Once A, B, and C are all up (each greeted you with "ready / joined"), open
a 4th terminal as your audience seat:

```bash
tail -f /mnt/shared/peer-cc/comm/log/*.jsonl
```

Then in **A's CC**, paste this — pure natural language, no CLI literals; A
itself decides which `peer-cc send` calls to issue:

```
三人玩个猜数字游戏,你只下指令然后旁观,中段不要插手。

让 C 在 1–100 里挑一个秘密整数,只记心里别说出来,等 B 来猜;每次 B 发一个数,
C 回 hint:B 猜的比秘密大就 lower,小就 higher,正好就 correct。

让 B 从 50 开始用二分搜索猜 C 的数,每收到 hint 就调整下次猜的区间,直到收到
correct。

两人都搞定后,各自把 attempts 汇报给你。最后告诉我:B 报的 attempts 和 C 报的
对不对得上,数字是不是落在 1–7 之间。
```

A translates that into a `game_setup` message to C and a `game_start` to B,
then idles. B and C exchange `guess` ↔ `hint` messages directly (not through
A) for ~5–7 rounds, each side managing range/secret state in its own CC
conversation context. Both report `game_over` to A when done.

In your tail terminal you'll see roughly:

```
... event:register agent:A ...
... event:register agent:B ...
... event:register agent:C ...
... event:send from:A to:C type:game_setup ...
... event:send from:A to:B type:game_start ...
... event:send from:B to:C type:guess  body:{"n":50}
... event:send from:C to:B type:hint   body:{"result":"higher"}
... event:send from:B to:C type:guess  body:{"n":75}
... event:send from:C to:B type:hint   body:{"result":"lower"}
... (more guess/hint rounds) ...
... event:send from:C to:B type:hint   body:{"result":"correct"}
... event:send from:C to:A type:game_over body:{"secret":73,"attempts":5}
... event:send from:B to:A type:game_over body:{"attempts":5}
```

This exercises every key piece: dual-watch (B and C each running inbox
watcher), worker-to-worker direct messaging (no coordinator middleman),
multi-turn state in CC conversation, and the human reading log in real time.

## Reset between sessions

`comm/` is gitignored, so:

```bash
uv run peer-cc reset --yes
```

…or just `rm -rf comm/`. The coop tool itself stays clean and version-controlled.

## Project layout

```
peer-cc/
├── CLAUDE.md            # auto-loaded by CC for the coordinator agent
├── PROTOCOL.md          # shared spec — read by every agent on join
├── README.md            # this file
├── pyproject.toml       # uv-managed; only runtime dep is typer
├── .claude/settings.json  # SessionStart hook for coordinator auto-bootstrap
├── src/peer_cc/         # CLI source (src layout)
├── tests/e2e.sh         # end-to-end self-test of the CLI (no LLM)
└── comm/                # gitignored runtime state
```

See `PROTOCOL.md` for the full spec: file layout, message schema, role
boundaries, atomic claim semantics, cross-machine caveats.

## CLI reference

All commands auto-detect the coop dir from cwd when invoked via
`uv run --directory <coop> peer-cc ...` (uv chdir's into the coop, peer-cc
reads cwd). You can also pass `--coop <path>` explicitly. **Never use
`export PEER_CC_COOP=…`** — Claude Code's Bash tool starts a fresh shell
per call, so env vars don't persist across tool invocations.

### Lifecycle

```
peer-cc init                                    # create comm/ subdirs (idempotent)
peer-cc register --role {coordinator|worker} --id <id> [--force]
                                                # exit 3 = collision (live agent already there)
peer-cc heartbeat   --id <id> [--status <s>]    # bump last_seen
peer-cc deregister  --id <id>                   # mark status=left (record kept)
peer-cc remove      --id <id> [--keep-claimed]  # delete record + inbox; recycle claimed tasks
peer-cc reset --yes                             # nuke comm/ entirely (coordinator-only)
```

### Messaging

```
peer-cc send  --to <id> --from <id> --type <t> [--body '<json>'] [--reply-to <msg-id>]
peer-cc inbox    --id <id>                       # list unprocessed message paths
peer-cc consume  --id <id> --path <msg-path>     # read & atomically move to processed/
```

### Tasks

```
peer-cc task publish  --from <id> --title <s> [--body '<json>'] [--requires tag1,tag2]
peer-cc task list                                # paths in tasks/pending/
peer-cc task claim    --agent <id> [--id <task-id>]   # atomic; exit 2 = lost race / empty
peer-cc task complete --agent <id> --id <task-id> [--result '<json>'] [--ok|--fail]
```

### Watching (NFS-safe polling, designed for CC's Monitor tool)

```
peer-cc watch inbox --id <id>     # prints new file paths; auto-heartbeats every 15 s
peer-cc watch tasks [--id <id>]   # workers poll for unaddressed tasks
```

### Observability

```
peer-cc agents                  # one JSON per line (machine-readable)
peer-cc info [--id <id>] [--json]
                                # detailed: + Claude session id, transcript path, context tokens
peer-cc status                  # human-readable summary of agents + tasks
peer-cc join-prompt [<id>]      # print prompt to paste; id optional (worker self-names if omitted)
```

## Limitations (v0.1)

- Cross-machine notification is polling-only (1 s by default). For
  near-real-time, lower the interval; for true push, build a notify-fanout
  service and add a `--push` flag (out of scope for now).
- No backpressure / inbox bound. A misbehaving sender can fill someone's inbox.
- No auth — anyone with FS access to comm/ can impersonate any agent.
  Run on a trusted shared volume.
- Workers go offline whenever their CC session exits. Heartbeat staleness is
  the liveness signal; consume it accordingly.
