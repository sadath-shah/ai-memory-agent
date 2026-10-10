import json
import tempfile
import time
import unittest
from pathlib import Path

from memory_agent.agent import Agent
from memory_agent.conversations import DEFAULT_ID, ConversationManager
from memory_agent.history import ConversationHistory
from memory_agent.llm import LLMError
from memory_agent.memory_store import MemoryStore
from tests.fakes import FakeBackend, FakeLLM
from tests.test_web import WebFixture


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.legacy_path = Path(self.tmp.name) / "conversation_history.json"
        self.legacy = ConversationHistory(self.legacy_path)
        self.mgr = ConversationManager(Path(self.tmp.name) / "conversations", self.legacy)

    def test_empty_everything_lists_nothing(self):
        self.assertEqual(self.mgr.list(), [])

    def test_legacy_history_is_the_default_conversation_and_stays_in_place(self):
        self.legacy.append("user", "hello legacy")
        before = self.legacy_path.read_bytes()
        cid = self.mgr.new_id()
        self.mgr.get(cid, create=True).append("user", "a brand new chat")
        self.assertEqual(self.legacy_path.read_bytes(), before)          # untouched by new chats
        listed = {c["id"]: c for c in self.mgr.list()}
        self.assertEqual(set(listed), {DEFAULT_ID, cid})
        self.assertEqual(listed[DEFAULT_ID]["title"], "hello legacy")
        self.assertEqual(listed["" + cid]["title"], "a brand new chat")

    def test_new_chats_persist_across_manager_instances(self):
        cid = self.mgr.new_id()
        self.mgr.get(cid, create=True).append("user", "remember me")
        again = ConversationManager(self.mgr.dir, ConversationHistory(self.legacy_path))
        self.assertEqual(again.get(cid).messages, [{"role": "user", "content": "remember me"}])

    def test_sorted_most_recent_first_and_long_titles_truncated(self):
        a, b = self.mgr.new_id(), self.mgr.new_id()
        self.mgr.get(a, create=True).append("user", "first " + "x" * 200)
        time.sleep(0.02)
        self.mgr.get(b, create=True).append("user", "second")
        listed = self.mgr.list()
        self.assertEqual([c["id"] for c in listed], [b, a])
        self.assertLessEqual(len(listed[1]["title"]), 56)

    def test_invalid_and_traversal_ids_rejected(self):
        for bad in ["../x", "..", "a" * 31, "A" * 32, "default/..", "", None, 5]:
            self.assertFalse(ConversationManager.valid(bad), bad)
        with self.assertRaises(ValueError):
            self.mgr.get("../../etc/passwd")

    def test_unknown_id_is_none_and_corrupt_file_does_not_break_listing(self):
        self.assertIsNone(self.mgr.get("0" * 32))
        self.mgr.dir.mkdir(parents=True)
        (self.mgr.dir / ("1" * 32 + ".json")).write_text("{broken")
        self.assertEqual(self.mgr.list(), [])

    def test_discard_if_empty_only_removes_unused_new_chats(self):
        cid = self.mgr.new_id()
        h = self.mgr.get(cid, create=True)
        h.append("user", "x"); h.pop_last("user")
        self.assertTrue(h.path.exists())
        self.mgr.discard_if_empty(cid)
        self.assertFalse(h.path.exists())
        self.legacy.append("user", "keep")
        self.mgr.discard_if_empty(DEFAULT_ID)
        self.assertEqual(len(self.legacy.messages), 1)


class AgentTurnTests(unittest.TestCase):
    def test_failed_turn_is_not_left_in_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            hist = ConversationHistory(Path(tmp) / "h.json")
            agent = Agent(MemoryStore(FakeBackend(), "u"), hist, FakeLLM(error=LLMError("down")))
            self.assertEqual(agent.handle("hello there").action, "ERROR")
            self.assertEqual(hist.messages, [])

    def test_switching_conversation_clears_open_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            h1, h2 = ConversationHistory(Path(tmp) / "1.json"), ConversationHistory(Path(tmp) / "2.json")
            agent = Agent(MemoryStore(FakeBackend(["User's favorite food is biryani"]), "u"), h1, FakeLLM())
            agent.handle("my favorite food is pasta")
            self.assertIsNotNone(agent.pending)
            agent.use_history(h2)
            self.assertIsNone(agent.pending)
            agent.use_history(h2)   # same history: no-op
            self.assertEqual(agent.history, h2)


class WebConversationTests(WebFixture, unittest.TestCase):
    def chat(self, text, cid=None):
        body = {"message": text}
        if cid is not None:
            body["conversation_id"] = cid
        return self.call("POST", "/api/chat", body)

    def test_omitted_id_keeps_using_the_original_history(self):
        status, body = self.chat("hello")
        self.assertEqual((status, body["conversation_id"]), (200, DEFAULT_ID))
        self.assertEqual([m["role"] for m in self.agent.history.messages], ["user", "assistant"])

    def test_new_conversation_flow_and_listing(self):
        self.chat("legacy message")
        _, first = self.chat("start a new chat about tea", "new")
        cid = first["conversation_id"]
        self.assertRegex(cid, r"^[0-9a-f]{32}$")
        self.assertEqual(len(self.agent.history.messages), 2)        # legacy history not touched
        _, second = self.chat("and again", cid)
        self.assertEqual(second["conversation_id"], cid)
        titles = {c["id"]: c["title"] for c in self.call("GET", "/api/conversations")[1]["conversations"]}
        self.assertEqual(titles[cid], "start a new chat about tea")
        self.assertEqual(titles[DEFAULT_ID], "legacy message")
        msgs = self.call("GET", f"/api/history?conversation_id={cid}")[1]["messages"]
        self.assertEqual([m["content"] for m in msgs if m["role"] == "user"],
                         ["start a new chat about tea", "and again"])
        self.assertEqual(len(self.call("GET", "/api/history")[1]["messages"]), 2)   # default

    def test_rejects_bad_and_unknown_ids(self):
        self.assertEqual(self.chat("hi", "../../etc")[0], 400)
        self.assertEqual(self.chat("hi", 7)[0], 400)
        self.assertEqual(self.chat("hi", "f" * 32)[0], 404)
        self.assertEqual(self.call("GET", "/api/history?conversation_id=f" + "f" * 31)[0], 404)
        self.assertEqual(self.call("GET", "/api/history?conversation_id=..")[0], 404)

    def test_failed_first_message_leaves_no_ghost_conversation(self):
        self.agent.llm = FakeLLM(error=LLMError("model down"))
        _, body = self.chat("hello there", "new")
        self.assertEqual(body["action"], "ERROR")
        self.assertIsNone(body["conversation_id"])
        self.assertEqual(self.call("GET", "/api/conversations")[1]["conversations"], [])

    def test_memories_unaffected_by_new_chats(self):
        before = self.backend.texts()
        self.chat("my favorite color is green", "new")
        self.assertEqual(len(self.backend.texts()), len(before) + 1)
        self.assertEqual(self.call("GET", "/api/memories")[1]["count"], len(before) + 1)

    def test_settings_endpoint_is_read_only_info(self):
        status, body = self.call("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertTrue(body["local"] and body["telemetry"] is False and body["user_id"] == "u")
        self.assertEqual(self.call("POST", "/api/settings", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
