#!/usr/bin/env bash
# End-to-end self-test: simulate coordinator A and workers B, C, exercising
# every piece of peer-cc — atomic send, race-safe claim, consume, watcher,
# heartbeat, log, status, reset.
#
# Run with: bash tests/e2e.sh
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
COOP=$REPO
export PEER_CC_COOP=$COOP

PEER="uv run --quiet --directory $REPO peer-cc"

log() { printf '\n=== %s ===\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_eq() {
  if [[ "$1" != "$2" ]]; then fail "expected $2, got $1 ($3)"; fi
}

# JSON helpers (stdlib, no jq required)
# get_field <file> <dotted.key>     -> read a key from a JSON file
# pipe_field <dotted.key>           -> read from stdin
get_field() {
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): d = d[k]
print(d)' "$1" "$2"
}
pipe_field() {
  python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in sys.argv[1].split("."): d = d[k]
print(d)' "$1"
}
# pipe_check <python-expr>          -> exit 0 iff expression on stdin is truthy
pipe_check() {
  python3 -c '
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if eval(sys.argv[1], {"d": d}) else 1)' "$1"
}

# ---------- setup ----------

log "1. clean slate"
rm -rf "$REPO/comm" "$REPO/tests/.scratch"
mkdir -p "$REPO/tests/.scratch/B" "$REPO/tests/.scratch/C"
$PEER init
[[ -d "$COOP/comm/agents" ]] || fail "agents/ not created"
[[ -d "$COOP/comm/inbox" ]] || fail "inbox/ not created"
[[ -d "$COOP/comm/tasks/pending" ]] || fail "tasks/pending/ not created"
[[ -d "$COOP/comm/log" ]] || fail "log/ not created"

log "2. register A (coordinator) from repo cwd, B and C (workers) from their own cwds"
$PEER register --role coordinator --id A >/dev/null
( cd "$REPO/tests/.scratch/B" && $PEER register --role worker --id B ) >/dev/null
( cd "$REPO/tests/.scratch/C" && $PEER register --role worker --id C ) >/dev/null

count=$($PEER agents | wc -l)
assert_eq "$count" "3" "agent count"

# Verify B's recorded cwd is tests/.scratch/B, not the repo root — cross-cwd registration works
b_cwd=$(get_field "$COOP/comm/agents/B.json" cwd)
assert_eq "$b_cwd" "$REPO/tests/.scratch/B" "B cwd"

# ---------- direct messaging ----------

log "3. A sends instruction to B; B lists, consumes, verifies content"
msg_path=$($PEER send --to B --from A --type instruction --body '{"text":"hello B"}')
[[ -f "$msg_path" ]] || fail "message file missing"
ls -1 "$COOP/comm/inbox/B/" | grep -v '^\.\|^processed$' | wc -l | grep -q '^1$' \
  || fail "B inbox should have exactly 1 file"

inbox_listing=$($PEER inbox --id B)
[[ "$inbox_listing" == "$msg_path" ]] || fail "inbox listing mismatch"

consumed=$($PEER consume --id B --path "$msg_path")
echo "$consumed" | pipe_check 'd["from"] == "A" and d["to"] == "B" and d["body"]["text"] == "hello B"' \
  || fail "consumed message wrong content"

# Original path should be gone, processed/ should have it
[[ ! -f "$msg_path" ]] || fail "message not removed from inbox/"
processed_count=$(ls "$COOP/comm/inbox/B/processed/" 2>/dev/null | wc -l)
assert_eq "$processed_count" "1" "processed count"

# ---------- task lifecycle ----------

log "4. A publishes task, B claims, B completes; verify state"
task_json=$($PEER task publish --from A --title "ping example.com" \
  --body '{"url":"https://example.com"}' --requires "network")
task_id=$(echo "$task_json" | pipe_field id)

pending_count=$($PEER task list | wc -l)
assert_eq "$pending_count" "1" "pending count after publish"

claimed=$($PEER task claim --agent B)
echo "$claimed" | pipe_check "d['id'] == '$task_id' and d['claimed_by'] == 'B'" \
  || fail "claim returned wrong shape"

[[ -f "$COOP/comm/tasks/claimed/B/$task_id.json" ]] || fail "task not in B's claimed/"
[[ ! -f "$COOP/comm/tasks/pending/$task_id.json" ]] || fail "task still in pending/"

$PEER task complete --agent B --id "$task_id" --result '{"latency_ms":42}' --ok >/dev/null
[[ -f "$COOP/comm/tasks/done/$task_id.json" ]] || fail "task not in done/"
[[ ! -f "$COOP/comm/tasks/claimed/B/$task_id.json" ]] || fail "task still claimed/"

done_ok=$(get_field "$COOP/comm/tasks/done/$task_id.json" ok)
assert_eq "$done_ok" "True" "done.ok"

# ---------- concurrent claim race ----------

log "5. Concurrent claim race: publish 1 task, B and C both try to claim"
race_json=$($PEER task publish --from A --title "racy" --body '{}')
race_id=$(echo "$race_json" | pipe_field id)

# Fire both claims in parallel via background subshells
out_b_file=$(mktemp); out_c_file=$(mktemp)
rc_b_file=$(mktemp); rc_c_file=$(mktemp)
( $PEER task claim --agent B >"$out_b_file" 2>/dev/null; echo $? >"$rc_b_file" ) &
( $PEER task claim --agent C >"$out_c_file" 2>/dev/null; echo $? >"$rc_c_file" ) &
wait

rc_b=$(cat "$rc_b_file"); rc_c=$(cat "$rc_c_file")
# Exactly one should succeed (rc=0), the other should fail with rc=2 (none).
# But because both agents see the file, one wins os.rename, the other gets ENOENT
# inside claim(), which loops to next candidate (none) → returns None → exit 2.
winners=0
for rc in "$rc_b" "$rc_c"; do
  [[ "$rc" == "0" ]] && winners=$((winners + 1))
done
assert_eq "$winners" "1" "race winners"

# The winner's claimed/ dir should have the task
b_has=$([[ -f "$COOP/comm/tasks/claimed/B/$race_id.json" ]] && echo 1 || echo 0)
c_has=$([[ -f "$COOP/comm/tasks/claimed/C/$race_id.json" ]] && echo 1 || echo 0)
assert_eq "$((b_has + c_has))" "1" "exactly one claimed/ has the file"

[[ ! -f "$COOP/comm/tasks/pending/$race_id.json" ]] || fail "racy task still pending"

# Cleanup the racy task by completing it
winner=$([[ "$b_has" == "1" ]] && echo B || echo C)
$PEER task complete --agent "$winner" --id "$race_id" --result '{}' >/dev/null

# ---------- heartbeat ----------

log "6. Heartbeat updates last_seen and status"
before=$(get_field "$COOP/comm/agents/B.json" last_seen)
sleep 1
$PEER heartbeat --id B --status busy >/dev/null
after=$(get_field "$COOP/comm/agents/B.json" last_seen)
[[ "$before" != "$after" ]] || fail "last_seen did not change"
status_b=$(get_field "$COOP/comm/agents/B.json" status)
assert_eq "$status_b" "busy" "B status"

# ---------- watcher ----------

log "7. Watcher emits new file paths (polling, NFS-safe)"
watch_log=$(mktemp)
( $PEER watch inbox --id C --interval 0.2 >"$watch_log" 2>&1 ) &
watch_pid=$!
sleep 0.5  # let watcher snapshot baseline
$PEER send --to C --from A --type instruction --body '{"text":"watch me"}' >/dev/null
sleep 1.0  # give the watcher time to detect
kill "$watch_pid" 2>/dev/null || true
wait "$watch_pid" 2>/dev/null || true

emitted=$(grep -c '^/' "$watch_log" || true)
[[ "$emitted" -ge "1" ]] || { cat "$watch_log"; fail "watcher emitted nothing"; }

# ---------- log integrity ----------

log "8. Event log has every action"
log_file=$(ls "$COOP/comm/log/"*.jsonl)
events=$(wc -l <"$log_file")
[[ "$events" -ge "10" ]] || fail "log too short: $events events"
# Spot check: must contain register, send, consume, task_publish, task_claim, task_complete
for ev in register send consume task_publish task_claim task_complete; do
  grep -q "\"event\":\"$ev\"" "$log_file" || fail "log missing event: $ev"
done
# Each line should be valid JSON
while IFS= read -r line; do
  echo "$line" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' \
    || fail "bad JSON in log: $line"
done <"$log_file"

# ---------- status output ----------

log "9. Status snapshot"
$PEER status

# ---------- deregister ----------

log "10. Deregister B"
$PEER deregister --id B >/dev/null
b_status=$(get_field "$COOP/comm/agents/B.json" status)
assert_eq "$b_status" "left" "B status after deregister"

# ---------- reset ----------

log "11. Reset wipes comm/ and recreates layout"
$PEER reset --yes >/dev/null
agents_after=$($PEER agents | wc -l)
assert_eq "$agents_after" "0" "agents after reset"
[[ -d "$COOP/comm/agents" ]] || fail "layout not recreated after reset"

log "ALL E2E TESTS PASSED"
