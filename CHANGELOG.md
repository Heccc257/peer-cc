# Changelog

All notable changes to peer-cc are recorded here. Versioning follows
[Semantic Versioning](https://semver.org/): MAJOR.MINOR.PATCH where
- MAJOR = breaking protocol or CLI changes
- MINOR = new features (commands, message types) — backward compatible
- PATCH = bug fixes and doc/infrastructure improvements

The current version is the value of `__version__` in `src/peer_cc/__init__.py`,
which hatchling reads at build time (see `[tool.hatch.version]` in pyproject.toml).

## [0.1.1] — 2026-05-08

### Added
- `peer-cc --version` / `-V` global flag — print version and exit.
- Single-source-of-truth versioning: `pyproject.toml` reads version from
  `src/peer_cc/__init__.py.__version__`, no more drift between the two.
- `CHANGELOG.md` (this file).

## [0.1.0] — 2026-05-08

Initial release. File-based multi-agent coop bus for Claude Code:

### Core
- `comm/` directory layout (agents/, inbox/, tasks/{pending,claimed,done}/, log/)
  as the single source of runtime truth — gitignored.
- One peer-cc dir = one persistent session. Workers join/leave freely; the
  session lives as long as `comm/` does.
- Atomic JSON writes via tmp + `os.rename`; race-safe task claim across
  machines via `os.rename(pending/X, claimed/<me>/X)`.

### Agents
- `peer-cc init / register / heartbeat / deregister / agents / info / remove`
- Coordinator collision detection: `register --role coordinator` refuses to
  overwrite a live record (heartbeat fresher than 60 s) unless `--force`,
  exit code 3.
- `peer-cc info` surfaces each worker's Claude session id, transcript path,
  and context-token usage by walking `~/.claude/projects/`.
- `peer-cc remove` evicts an agent and recycles claimed-but-incomplete tasks
  back to `tasks/pending/`.

### Messaging & tasks
- `peer-cc send / inbox / consume` for direct addressed messages.
- `peer-cc task publish / list / claim / complete` for first-claim-wins tasks.
- `peer-cc watch inbox|tasks --id <id>` — NFS-safe polling watcher; auto-
  heartbeats agent's `last_seen` every 15 s while running.

### Bootstrap & UX
- `CLAUDE.md` + `.claude/settings.json` SessionStart hook for coordinator
  zero-touch bootstrap (just `cd peer-cc && claude`).
- `PROTOCOL.md` shared spec; top-level §STOP section is imperative for
  workers ("if you're reading this, just bootstrap — don't ask").
- `peer-cc join-prompt [<id>]` — prints unambiguous worker join prompt that
  names PROTOCOL.md by absolute path (avoids `加入 X` being misread as
  `/add-dir`).
- Coop dir auto-detection from cwd when invoked via
  `uv run --directory <coop> peer-cc ...` (no `--coop` or env var needed).

### Testing
- `tests/e2e.sh` — 11-step CLI-only end-to-end self-test covering register,
  send/consume, task publish/claim/complete, concurrent claim race,
  heartbeat, watcher, log integrity, deregister, reset.
