import http.client
import json
import socket
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path

from memory_agent.agent import Agent
from memory_agent.history import ConversationHistory
from memory_agent.memory_store import MemoryStore
from memory_agent.web import make_handler
from tests.fakes import FakeBackend, FakeLLM


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WebFixture:
    """Real HTTP server over a fake memory backend and a temp dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = FakeBackend(["User loves coding", "User loves football"])
        self.agent = Agent(MemoryStore(self.backend, "u"),
                           ConversationHistory(Path(self.tmp.name) / "h.json"),
                           FakeLLM("hi there"))
        self.port = free_port()
        self.server = HTTPServer(("127.0.0.1", self.port), make_handler(self.agent, self.port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdrs = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body)
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, data, hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw)
        except ValueError:
            return resp.status, raw.decode()


class WebTests(WebFixture, unittest.TestCase):
    def test_index_served(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("AI Memory Agent", body)

    def test_list_memories(self):
        status, body = self.call("GET", "/api/memories")
        self.assertEqual(status, 200)
        self.assertEqual([m["memory"] for m in body["memories"]],
                         ["User loves coding", "User loves football"])

    def test_count_matches_list_and_chat(self):
        _, body = self.call("GET", "/api/memories")
        self.assertEqual(body["count"], len(body["memories"]))
        self.assertEqual(body["user_id"], "u")
        reply = self.call("POST", "/api/chat", {"message": "how many memories do I have?"})[1]["reply"]
        self.assertEqual(reply, f"I have {body['count']} memories stored.")

    def test_status_endpoint(self):
        status, body = self.call("GET", "/api/status")
        self.assertEqual((status, body["ok"], body["local"], body["count"]), (200, True, True, 2))
        self.backend.fail = RuntimeError("down")
        self.assertEqual(self.call("GET", "/api/status")[0], 500)

    def test_history_endpoint_returns_saved_conversation(self):
        self.call("POST", "/api/chat", {"message": "hello"})
        msgs = self.call("GET", "/api/history")[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])

    def test_chat_save_and_duplicate(self):
        _, first = self.call("POST", "/api/chat", {"message": "my favorite color is blue"})
        self.assertIn("Saved", first["reply"])
        _, second = self.call("POST", "/api/chat", {"message": "my favorite color is blue"})
        self.assertIn("Already stored", second["reply"])
        self.assertEqual(len(self.backend.texts()), 3)

    def test_chat_calculator_and_chat(self):
        self.assertEqual(self.call("POST", "/api/chat", {"message": "2+3"})[1]["reply"], "5")
        self.assertEqual(self.call("POST", "/api/chat", {"message": "hello"})[1]["reply"], "hi there")

    def test_chat_validation(self):
        for body in [{}, {"message": ""}, {"message": 5}, {"message": "   "}]:
            self.assertEqual(self.call("POST", "/api/chat", body)[0], 400)

    def test_update_memory(self):
        mid = self.call("GET", "/api/memories")[1]["memories"][0]["id"]
        status, body = self.call("PUT", f"/api/memories/{mid}", {"text": "User loves Python"})
        self.assertEqual((status, body["status"]), (200, "updated"))
        self.assertIn("User loves Python", self.backend.texts())
        self.assertEqual(self.call("PUT", f"/api/memories/{mid}", {"text": " "})[0], 400)
        self.assertEqual(self.call("PUT", "/api/memories/nope", {"text": "x"})[0], 404)

    def test_delete_requires_confirm_and_only_removes_one(self):
        mid = self.call("GET", "/api/memories")[1]["memories"][0]["id"]
        self.assertEqual(self.call("DELETE", f"/api/memories/{mid}")[0], 400)
        self.assertEqual(len(self.backend.texts()), 2)
        status, _ = self.call("DELETE", f"/api/memories/{mid}?confirm=yes")
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.texts(), ["User loves football"])
        self.assertEqual(self.call("DELETE", f"/api/memories/{mid}?confirm=yes")[0], 404)

    def test_backend_error_is_json_500(self):
        self.backend.fail = RuntimeError("down")
        status, body = self.call("GET", "/api/memories")
        self.assertEqual(status, 500)
        self.assertIn("down", body["error"])

    def test_foreign_host_and_origin_rejected(self):
        self.assertEqual(self.call("GET", "/api/memories", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("POST", "/api/chat", {"message": "hi"},
                                   headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.backend.texts()[0], "User loves coding")

    def test_chat_modes(self):
        self.assertEqual(self.call("POST", "/api/chat", {"message": "2+3", "mode": "tools"})[1]["reply"], "5")
        r = self.call("POST", "/api/chat", {"message": "hello", "mode": "tools"})[1]
        self.assertEqual(r["action"], "MODE_HINT")
        self.assertEqual(self.call("POST", "/api/chat", {"message": "hi", "mode": "root"})[0], 400)
        self.assertEqual(self.call("POST", "/api/chat", {"message": "hi", "mode": 5})[0], 400)

    def test_static_assets_served_and_locked_down(self):
        from memory_agent.web import STATIC
        for name in ("app.js", "app.css"):
            if (STATIC / name).exists():
                self.assertEqual(self.call("GET", f"/static/{name}")[0], 200)
        self.assertEqual(self.call("GET", "/static/index.html")[0], 404)       # not js/css
        self.assertEqual(self.call("GET", "/static/../main.py")[0], 404)
        self.assertEqual(self.call("GET", "/static/%2e%2e/main.py")[0], 404)
        self.assertEqual(self.call("GET", "/static/nope.js")[0], 404)

    def test_unknown_route(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
