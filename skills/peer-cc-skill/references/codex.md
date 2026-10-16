# Codex integration

## Join without assuming Claude Code tools

1. Honor the user-supplied worker id and run the normal `peer-cc register` command.
   A collision is not permission to overwrite a live peer with `--force`.
2. Link this skill into `<worker-cwd>/.agents/skills/peer-cc-skill`. Check the
   destination first; preserve an existing directory or a different symlink.
3. Merge [the anchor template](../assets/codex-AGENTS.md.template) into the
   worker project's `AGENTS.md`, substituting its four placeholders. Do not
   overwrite existing instructions or add another worker's identity globally.
4. Check the actual notification capability. Without a client adapter,
   foreground polling requires an active turn, while `watch --daemon` merely
   records paths. Neither makes an idle Codex conversation automatically run.
5. Keep the kernel/task scope the human paused paused, including after a peer
   notification starts a new turn.

Codex discovers project skills under `.agents/skills`; it does not acquire
Claude Code's Monitor just by reading this protocol. `AGENTS.md` is the recovery
anchor; `.claude/peer-cc/exec.log` remains a shared log convention only.

## Connect an event source to the owning client

```text
peer message / eligible task → path notification → idle bound Codex thread
  → turn/start → worker reads + handles → reply + consume/complete
```

Use the **existing** server/client that owns the conversation. Do not spawn a
new App Server or use `codex exec resume` concurrently against the same history.
For a custom client, its follow-up-message API (for example an exposed
`send_message_to_thread`) can fill this role. An agent tool by that name does
not imply a daemon can call it: obtain the supported client endpoint and auth
from its operator. Do not inspect or print credential stores to guess access.

The supplied [bridge template](../scripts/codex_bridge.py) targets a verified,
already-running App Server control socket using WebSocket-over-Unix (the `codex`
optional dependency). It is a client, not a server, and never auto-resumes unloaded
threads. A Unix socket is **not** the stdio JSONL transport: `codex app-server
proxy` relays raw bytes and does not convert JSON lines to WebSocket frames.
Example:

```bash
uv run --directory /mnt/shared/peer-cc --extra codex python \
  /mnt/shared/peer-cc/skills/peer-cc-skill/scripts/codex_bridge.py \
  --coop /mnt/shared/peer-cc --id codex \
  --worker-cwd /path/to/project --thread-id YOUR_THREAD_ID \
  --socket /path/to/owning-app-server.sock --check
```

`--check` only checks the connection and binding; it starts no turn. Once the
operator authorizes automatic interaction, put the exact command in the worker's
work archive, replace `--check` with `--watch-tasks` if this subgroup's shared
tasks are in scope (otherwise omit both), and run it with unbuffered stdout to
an absolute log path. Stop that specific bridge process to disable wake-up.
Do not modify a shared server or service configuration without authorization.

The bridge stores delivery bookkeeping under the worker's
`.claude/peer-cc/codex-bridge-<id>.json`, with an exclusive lock. Use one bridge
per bound thread. It queues active/approval-waiting threads, deduplicates path
notifications, and never consumes messages or claims tasks on the model's behalf.
Before `turn/start`, it persists a pending delivery. If the request fails or its
result is uncertain, it stops without retrying: inspect the thread and pending
state before clearing it. Do not blindly resubmit potentially executed work.
Already-notified but unconsumed messages stay durable for manual recovery; the
bridge does not repeatedly wake the model for them after every turn.

Approval/tool requests are **not auto-approved** by the bridge. The owning
client/operator must handle them. An active human turn is never steered or
interrupted. Existing model, sandbox and approval settings are not overridden.
Heartbeat means the bound thread is loaded and reachable, not that its work
has succeeded. An unloaded thread fails closed rather than looking alive forever.

## Verify before claiming automatic interaction

- A safe message sent while idle must trigger exactly one intended thread turn.
- A message sent while the human is talking stays queued until that turn ends.
- The peer's reply and the receiver's consume are visible in `comm/`.
- Restart, duplicate notifications and failed delivery do not lose the original
  message. Approval requests do not gain automatic consent.

Only then report **auto-interaction verified**. Registration, a live daemon PID,
fresh heartbeat, unit tests or `--check` alone are insufficient. If the client's
endpoint is not available, report **watching only** and name the missing binding.

## Official references

- [Codex App Server](https://developers.openai.com/codex/app-server/): connection
  initialization, `thread/read`, runtime status, `turn/start`, `turn/completed`.
- [Agent instructions](https://developers.openai.com/codex/guides/agents-md/).
- [Codex skills](https://developers.openai.com/codex/skills/).

If the user supplies a documentation/Git proxy, apply it only to the relevant
command's environment; do not write it into global Git, shell or skill settings.
