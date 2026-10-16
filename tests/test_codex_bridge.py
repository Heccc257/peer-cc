"""Isolated bridge contract tests. No real models, live coop or servers touched."""

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from peer_cc import agents

SCRIPT = (
    Path(__file__).resolve().parents[1] / "skills/peer-cc-skill/scripts/codex_bridge.py"
)
spec = importlib.util.spec_from_file_location("codex_bridge", SCRIPT)
bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_module)


class FakeRpc:
    def __init__(self, cwd):
        self.cwd, self.status, self.calls, self.fail = str(cwd), "idle", [], False

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/read":
            return {
                "thread": {
                    "id": "thread-test",
                    "cwd": self.cwd,
                    "status": {"type": self.status},
                }
            }
        if self.fail:
            raise TimeoutError("unknown delivery")
        return {"turn": {"id": "turn-test"}}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.coop, self.worker = self.root / "coop", self.root / "worker"
        self.worker.mkdir()
        agents.register(self.coop, "codex", "worker", cwd=str(self.worker))
        self.inbox = self.coop / "comm/inbox/codex"
        self.inbox.mkdir(parents=True)
        self.message = self.inbox / "001-test.json"
        self.message.write_text(
            json.dumps({"id": "001-test", "to": "codex", "from": "peer"})
        )
        self.state = self.worker / "state.json"
        self.rpc = FakeRpc(self.worker)

    def make(self, **kw):
        return bridge_module.Bridge(
            self.rpc, self.coop, "codex", self.worker, "thread-test", self.state, **kw
        )

    def starts(self):
        return [params for method, params in self.rpc.calls if method == "turn/start"]

    def test_idle_delivery_is_deduplicated_without_consuming(self):
        b = self.make()
        self.assertEqual(b.tick(), "started")
        self.assertEqual(b.tick(), "idle")
        self.assertEqual(self.make().tick(), "idle")
        self.assertEqual(len(self.starts()), 1)
        self.assertTrue(self.message.exists())
        self.assertEqual(set(self.starts()[0]), {"threadId", "input"})
        record = json.loads((self.coop / "comm/agents/codex.json").read_text())
        self.assertEqual(record["thread_id"], "thread-test")

    def test_active_human_turn_queues(self):
        b = self.make()
        self.rpc.status = "active"
        self.assertEqual(b.tick(), "queued")
        self.assertEqual(self.starts(), [])
        self.rpc.status = "idle"
        self.assertEqual(b.tick(), "started")

    def test_unloaded_and_wrong_cwd_fail_closed(self):
        b = self.make()
        self.rpc.status = "notLoaded"
        with self.assertRaises(RuntimeError):
            b.tick()
        self.rpc.status, self.rpc.cwd = "idle", str(self.root)
        with self.assertRaises(RuntimeError):
            b.tick()
        self.assertEqual(self.starts(), [])

    def test_uncertain_submission_persists_pending_and_stops_restart(self):
        self.rpc.fail = True
        with self.assertRaises(TimeoutError):
            self.make().tick()
        self.assertTrue(json.loads(self.state.read_text())["pending"])
        with self.assertRaises(RuntimeError):
            self.make()
        self.assertEqual(len(self.starts()), 1)
        self.assertTrue(self.message.exists())

    def test_tasks_require_opt_in_and_symlinks_are_ignored(self):
        self.message.unlink()
        tasks = self.coop / "comm/tasks/pending"
        tasks.mkdir(parents=True)
        (tasks / "002-task.json").write_text("{}")
        (self.inbox / "bad.json").symlink_to(tasks / "002-task.json")
        self.assertEqual(self.make().tick(), "idle")
        self.assertEqual(self.make(watch_tasks=True).tick(), "started")
        self.assertTrue((tasks / "002-task.json").exists())

    def test_foreign_state_is_not_overwritten(self):
        self.state.write_text(json.dumps({"binding": {"thread_id": "other"}}))
        with self.assertRaises(RuntimeError):
            self.make()
        self.assertEqual(
            json.loads(self.state.read_text())["binding"]["thread_id"], "other"
        )

    def test_stdio_initialization_and_request(self):
        server = """
import json, sys
initialized = False
for line in sys.stdin:
    msg = json.loads(line)
    if msg['method'] == 'initialized':
        initialized = True
        continue
    result = {} if msg['method'] == 'initialize' else {'initialized': initialized}
    print(json.dumps({'id': msg['id'], 'result': result}), flush=True)
"""
        rpc = bridge_module.Rpc([sys.executable, "-u", "-c", server], timeout=2)
        try:
            self.assertTrue(
                rpc.request("thread/read", {"threadId": "test"})["initialized"]
            )
        finally:
            rpc.close()

    def test_unix_websocket_initialization_and_request(self):
        from websockets.sync.server import unix_serve

        def handler(connection):
            initialized = False
            for frame in connection:
                message = json.loads(frame)
                if message["method"] == "initialized":
                    initialized = True
                    continue
                result = (
                    {}
                    if message["method"] == "initialize"
                    else {"initialized": initialized}
                )
                connection.send(json.dumps({"id": message["id"], "result": result}))

        socket_path = self.root / "test.sock"
        with unix_serve(handler, str(socket_path)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            rpc = bridge_module.Rpc(socket_path=socket_path, timeout=2)
            try:
                self.assertTrue(
                    rpc.request("thread/read", {"threadId": "test"})["initialized"]
                )
            finally:
                rpc.close()
                server.shutdown()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
