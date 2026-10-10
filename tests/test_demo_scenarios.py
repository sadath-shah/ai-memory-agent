"""The three portfolio demos as automated tests (real HTTP server, fake memory store and model).

Demo 1  verifiable long-term memory: save, retrieve in a new chat, update, delete
Demo 2  honesty and safety: unknown facts, no bulk deletion, duplicate handling
Demo 3  reliability: safe calculator, independent persistent chats, graceful model outage
"""
import os
import unittest
from pathlib import Path

from memory_agent.conversations import ConversationManager
from memory_agent.history import ConversationHistory
from memory_agent.llm import LLMError
from tests.fakes import FakeBackend, FakeLLM
from tests.test_web import WebFixture


class WordAwareBackend(FakeBackend):
    """Like the fake store, but a shared word also counts as similarity (embeddings do this)."""

    def search(self, query, *, top_k=20, filters=None, threshold=0.1, **kw):
        hits = super().search(query, top_k=top_k, filters=filters, threshold=0.0)["results"]
        q = query.lower().replace("?", "").split()
        for h in hits:
            words = h["memory"].lower().split()
            if any(len(os.path.commonprefix([a, b])) >= 5 for a in q for b in words):   # prefer ~ prefers
                h["score"] = max(h["score"], 0.7)
        hits = [h for h in hits if h["score"] >= threshold]
        return {"results": sorted(hits, key=lambda h: -h["score"])[:top_k]}


class DemoBase(WebFixture):
    def setUp(self):
        super().setUp()
        self.server.shutdown(); self.server.server_close()           # rebuild with the word-aware store
        self.backend = WordAwareBackend(["User loves football"])
        self.agent.store.backend = self.backend
        from http.server import HTTPServer
        import threading
        from memory_agent.web import make_handler
        self.server = HTTPServer(("127.0.0.1", self.port), make_handler(self.agent, self.port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.llm = self.agent.llm

    def chat(self, text, cid="new", mode="agent"):
        status, body = self.call("POST", "/api/chat", {"message": text, "conversation_id": cid, "mode": mode})
        self.assertEqual(status, 200, body)
        return body

    def texts(self):
        return [m["memory"] for m in self.call("GET", "/api/memories")[1]["memories"]]


class Demo1VerifiableMemoryTests(DemoBase, unittest.TestCase):
    def test_save_retrieve_in_new_chat_update_and_delete(self):
        # save
        first = self.chat("Remember that I prefer black coffee")
        self.assertIn("Saved", first["reply"])
        self.assertIn("User prefers black coffee", self.texts())
        memory_id = next(m["id"] for m in self.call("GET", "/api/memories")[1]["memories"] if "coffee" in m["memory"])

        # retrieve in a brand-new conversation: the model is given the stored memory
        second = self.chat("What do I prefer to drink?")
        self.assertNotEqual(second["conversation_id"], first["conversation_id"])
        prompt = self.llm.calls[-1]
        self.assertIn("User prefers black coffee", prompt[0]["content"])
        self.assertIn("User prefers black coffee", prompt[-1]["content"])

        # update the selected record only
        status, _ = self.call("PUT", f"/api/memories/{memory_id}", {"text": "User prefers green tea"})
        self.assertEqual(status, 200)
        self.assertCountEqual(self.texts(), ["User loves football", "User prefers green tea"])
        self.chat("What do I prefer to drink?")
        self.assertIn("green tea", self.llm.calls[-1][0]["content"])
        self.assertNotIn("black coffee", self.llm.calls[-1][0]["content"])

        # delete requires confirmation, then it is really gone and no longer retrievable
        self.assertEqual(self.call("DELETE", f"/api/memories/{memory_id}")[0], 400)
        self.assertIn("User prefers green tea", self.texts())
        self.assertEqual(self.call("DELETE", f"/api/memories/{memory_id}?confirm=yes")[0], 200)
        self.assertEqual(self.texts(), ["User loves football"])
        calls_before = len(self.llm.calls)
        gone = self.chat("What do I prefer to drink?")
        self.assertIn("don't have anything stored", gone["reply"])
        self.assertEqual(len(self.llm.calls), calls_before)            # answered without asking the model


class Demo2HonestyAndSafetyTests(DemoBase, unittest.TestCase):
    def test_unknown_personal_facts_are_never_invented(self):
        self.agent.llm.reply = "You prefer beer while watching football."     # what a hallucinating model would say
        for question in ["What is my mother's name?", "Where was I born?", "What is my phone number?"]:
            reply = self.chat(question)["reply"]
            self.assertIn("don't have anything stored", reply, question)
            self.assertNotIn("beer", reply)
        self.assertEqual(self.llm.calls, [])

    def test_bulk_deletion_is_refused_and_single_deletion_needs_pick_and_yes(self):
        self.chat("Remember that I like tea")
        before = self.texts()
        cid = None
        for command in ["forget everything", "delete all my memories", "wipe my memories"]:
            body = self.chat(command, cid or "new")
            cid = body["conversation_id"]
            self.assertIn("don't delete everything in one step", body["reply"])
            self.assertEqual(self.chat("cancel", cid)["action"], "CANCEL")
            self.assertEqual(self.texts(), before, command)
        self.chat("forget that I like tea", cid)
        self.assertEqual(self.texts(), before)                          # listing candidates deletes nothing
        self.chat("1", cid)
        self.assertEqual(self.texts(), before)                          # picking is not enough
        self.chat("yes", cid)
        self.assertNotIn("User likes tea", self.texts())
        self.assertIn("User loves football", self.texts())              # unrelated memory preserved

    def test_duplicates_are_detected_even_when_worded_differently(self):
        self.chat("i love coding")
        for variant in ["i love coding", "I love coding!", "Remember that I love coding"]:
            self.assertIn("Already stored", self.chat(variant)["reply"], variant)
        self.assertEqual(sum("coding" in t for t in self.texts()), 1)

    def test_conflicting_records_are_flagged_not_resolved_by_the_model(self):
        self.backend.add("User's favorite food is biryani", user_id="u")
        self.backend.add("User's favorite food is pasta", user_id="u")
        reply = self.chat("What is my favorite food?")["reply"]
        self.assertIn("conflicting records", reply)
        self.assertEqual(self.llm.calls, [])


class Demo3ReliabilityTests(DemoBase, unittest.TestCase):
    def test_safe_calculator(self):
        for text, expected in [("25 × 4", "100"), ("125 ÷ 5", "25"), ("0.1 + 0.2", "0.3"), ("-5 * 3", "-15"),
                               ("1/0", "Division by zero is undefined."), ("9**9**9", "I couldn't calculate that."),
                               ("2 +", "I couldn't calculate that.")]:
            self.assertEqual(self.chat(text)["reply"], expected, text)
        from memory_agent.calculator import safe_calculate
        for hostile in ["__import__('os').system('echo pwned')", "open('/etc/passwd').read()", "eval('1+1')", "(lambda: 1)()"]:
            self.assertEqual(safe_calculate(hostile), "I couldn't calculate that.", hostile)

    def test_independent_conversations_persist_across_a_restart(self):
        a = self.chat("What is the capital of Italy?")["conversation_id"]
        b = self.chat("What is 12 × 12?")["conversation_id"]
        self.chat("And of Spain?", a)
        users = lambda cid: [m["content"] for m in self.call("GET", f"/api/history?conversation_id={cid}")[1]["messages"] if m["role"] == "user"]
        self.assertEqual(users(a), ["What is the capital of Italy?", "And of Spain?"])
        self.assertEqual(users(b), ["What is 12 × 12?"])
        # "restart": brand-new objects reading the same files
        legacy = ConversationHistory(Path(self.tmp.name) / "h.json")
        reopened = ConversationManager(Path(self.tmp.name) / "conversations", legacy)
        self.assertEqual([m["content"] for m in reopened.get(a).messages if m["role"] == "user"], users(a))
        self.assertEqual({c["id"] for c in reopened.list()}, {a, b})

    def test_model_outage_is_reported_honestly_and_leaves_nothing_half_saved(self):
        existing = self.chat("What is the capital of Italy?")["conversation_id"]
        count = len(self.call("GET", f"/api/history?conversation_id={existing}")[1]["messages"])
        self.agent.llm = FakeLLM(error=LLMError("Could not reach the local model. Is `ollama serve` running?"))
        outage = self.chat("hello again", existing)
        self.assertEqual(outage["action"], "ERROR")
        self.assertIn("ollama serve", outage["reply"])
        # the failed turn is not stored, so retrying cannot create duplicates
        self.assertEqual(len(self.call("GET", f"/api/history?conversation_id={existing}")[1]["messages"]), count)
        # a failed first message does not create an empty ghost conversation
        before = len(self.call("GET", "/api/conversations")[1]["conversations"])
        self.assertIsNone(self.chat("brand new question")["conversation_id"])
        self.assertEqual(len(self.call("GET", "/api/conversations")[1]["conversations"]), before)
        # memory features that need no model keep working during the outage
        self.assertIn("User loves football", self.chat("show my memories", existing)["reply"])
        # recovery
        self.agent.llm = FakeLLM("Back online.")
        self.assertEqual(self.chat("hello again", existing)["reply"], "Back online.")


if __name__ == "__main__":
    unittest.main()
