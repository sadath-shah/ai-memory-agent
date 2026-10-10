import tempfile
import unittest
from pathlib import Path

from memory_agent.agent import Agent, decide_action
from memory_agent.history import ConversationHistory
from memory_agent.llm import LLMError
from memory_agent.memory_store import MemoryStore
from tests.fakes import FakeBackend, FakeLLM


class RoutingTests(unittest.TestCase):
    def test_rules(self):
        cases = {
            "show my memories": "LIST_MEMORIES",
            "delete memory": "DELETE_MEMORY",
            "update memory": "UPDATE_MEMORY",
            "what is 2+2": "CALCULATE",
            "12 * (3+4)": "CALCULATE",
            "forget my favorite food": "FORGET",
            "i love coding": "SAVE_MEMORY",
            "Actually, my favorite food is pasta": "SAVE_MEMORY",
            "update my favorite food to pasta": "SAVE_MEMORY",
            "what is my favorite food?": "SEARCH_MEMORY",
            "do you remember my name": "SEARCH_MEMORY",
            "what is the capital of France?": "CHAT",
            "hello there": "CHAT",
        }
        for text, expected in cases.items():
            self.assertEqual(decide_action(text), expected, text)

    def test_llm_fallback_and_failure(self):
        self.assertEqual(decide_action("blah", FakeLLM("I think SEARCH_MEMORY.")), "SEARCH_MEMORY")
        self.assertEqual(decide_action("blah", FakeLLM("nonsense")), "CHAT")
        # LLM may only choose SAVE_MEMORY for first-person statements
        self.assertEqual(decide_action("this should survive a network failure", FakeLLM("SAVE_MEMORY")), "CHAT")
        self.assertEqual(decide_action("the weather is nice today", FakeLLM("SAVE_MEMORY")), "CHAT")
        self.assertEqual(decide_action("we moved to Berlin last year", FakeLLM("SAVE_MEMORY")), "SAVE_MEMORY")
        self.assertEqual(decide_action("blah", FakeLLM(error=LLMError("down"))), "CHAT")


class AgentTestCase(unittest.TestCase):
    def build(self, *texts, llm=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = FakeBackend(texts)
        self.llm = llm or FakeLLM("LLM reply")
        self.history = ConversationHistory(Path(self.tmp.name) / "h.json")
        self.agent = Agent(MemoryStore(self.backend, "u"), self.history, self.llm)
        return self.agent


class SaveFlowTests(AgentTestCase):
    def test_messages_match_what_happened(self):
        a = self.build()
        self.assertIn("Saved", a.handle("i love coding").text)
        r = a.handle("i love coding")
        self.assertIn("Already stored", r.text)
        self.assertNotIn("Saved", r.text)
        self.assertEqual(len(self.backend.texts()), 1)

    def test_failed_save_never_claims_success(self):
        a = self.build()
        self.backend.fail = RuntimeError("down")
        r = a.handle("i love coding")
        self.assertIn("⚠️", r.text)
        self.assertNotIn("Saved", r.text)
        self.assertEqual(self.llm.calls, [])     # no chatty LLM reply that could contradict

    def test_correction_updates(self):
        a = self.build("User's favorite food is biryani")
        r = a.handle("Actually, my favorite food is pasta")
        self.assertIn("Updated", r.text)
        self.assertEqual(self.backend.texts(), ["User's favorite food is pasta"])

    def test_conflict_asks_then_replace_choice(self):
        a = self.build("User's favorite food is biryani", "User loves football")
        r = a.handle("my favorite food is pasta")
        self.assertIn("biryani", r.text)
        self.assertIn("1.", r.text)
        self.assertEqual(len(self.backend.texts()), 2)         # nothing changed yet
        r = a.handle("1")
        self.assertIn("Updated", r.text)
        self.assertCountEqual(self.backend.texts(),
                              ["User's favorite food is pasta", "User loves football"])

    def test_conflict_keep_both_and_cancel(self):
        a = self.build("User's favorite food is biryani")
        a.handle("my favorite food is pasta")
        self.assertIn("Saved", a.handle("new").text)
        self.assertEqual(len(self.backend.texts()), 2)
        a.handle("my favorite food is rice")
        self.assertIn("Cancelled", a.handle("cancel").text)
        self.assertEqual(len(self.backend.texts()), 2)

    def test_new_statement_dismisses_open_question_and_is_handled(self):
        a = self.build("User's favorite food is biryani")
        a.handle("my favorite food is pasta")
        r = a.handle("i love gardening")
        self.assertIn("Saved", r.text)
        self.assertIsNone(a.pending)
        self.assertCountEqual(self.backend.texts(), ["User's favorite food is biryani", "User loves gardening"])

    def test_invalid_choice_changes_nothing(self):
        a = self.build("User's favorite food is biryani")
        a.handle("my favorite food is pasta")
        self.assertIn("Invalid", a.handle("99").text)
        self.assertEqual(self.backend.texts(), ["User's favorite food is biryani"])


class ManageFlowTests(AgentTestCase):
    def test_list(self):
        a = self.build("User a1", "User b2")
        r = a.handle("show my memories")
        self.assertIn("1. User a1", r.text)
        self.assertIn("2. User b2", r.text)
        self.assertIn("You have 2 stored memories", r.text)
        self.assertIn("don't have any memories stored yet", self.build().handle("show my memories").text)

    def test_count_comes_from_the_store_not_the_llm(self):
        a = self.build(*[f"User likes hobby{i}" for i in range(30)])
        r = a.handle("how many memories do I have?")
        self.assertEqual(r.text, "I have 30 memories stored.")
        self.assertEqual(self.llm.calls, [])
        self.assertEqual(self.build("User a").handle("how many memories are stored?").text,
                         "I have 1 memory stored.")

    def test_find_duplicates_is_read_only(self):
        a = self.build("User loves coding", "User stated they love coding", "User loves football")
        r = a.handle("find duplicates")
        self.assertIn("User loves coding", r.text)
        self.assertIn("nothing was changed", r.text)
        self.assertEqual(len(self.backend.texts()), 3)
        self.assertIn("No duplicate", self.build("User loves coding").handle("find duplicates").text)

    def test_update_selected(self):
        a = self.build("User a1", "User b2")
        a.handle("update memory")
        a.handle("2")
        r = a.handle("User b3")
        self.assertIn("Updated", r.text)
        self.assertCountEqual(self.backend.texts(), ["User a1", "User b3"])

    def test_update_invalid_empty_and_cancel(self):
        a = self.build("User a1")
        a.handle("update memory")
        self.assertIn("Invalid", a.handle("7").text)            # number out of range
        a.handle("update memory")
        r = a.handle("2+2")                                      # new request dismisses the question
        self.assertEqual(r.text, "4")
        self.assertIsNone(a.pending)
        a.handle("update memory")
        a.handle("1")
        a.handle("cancel")
        self.assertEqual(self.backend.texts(), ["User a1"])
        self.assertIn("No stored memories", self.build().handle("update memory").text)

    def test_delete_requires_selection_and_yes(self):
        a = self.build("User a1", "User b2")
        a.handle("delete memory")
        a.handle("1")
        r = a.handle("yes")
        self.assertIn("Deleted", r.text)
        self.assertEqual(self.backend.texts(), ["User b2"])

    def test_delete_cancelled_at_confirmation(self):
        a = self.build("User a1")
        a.handle("delete memory")
        a.handle("1")
        self.assertIn("cancelled", a.handle("no").text.lower())
        self.assertEqual(self.backend.texts(), ["User a1"])

    def test_delete_invalid_selection(self):
        a = self.build("User a1")
        a.handle("delete memory")
        self.assertIn("Invalid", a.handle("7").text)
        self.assertEqual(len(self.backend.texts()), 1)

    def test_forget_never_deletes_without_selection_and_confirmation(self):
        a = self.build("User's favorite color is blue", "User loves football")
        r = a.handle("forget my favorite color")
        self.assertIn("blue", r.text)
        self.assertEqual(len(self.backend.texts()), 2)         # nothing deleted yet
        a.handle("1")
        self.assertEqual(len(self.backend.texts()), 2)         # still needs "yes"
        a.handle("yes")
        self.assertEqual(self.backend.texts(), ["User loves football"])

    def test_forget_without_match(self):
        a = self.build("User loves football")
        r = a.handle("forget qwertyuiop")
        self.assertIn("Nothing was deleted", r.text)

    def test_store_errors_do_not_crash(self):
        a = self.build("User a1")
        self.backend.fail = RuntimeError("down")
        for msg in ["show my memories", "update memory", "delete memory", "i love coding"]:
            self.assertTrue(a.handle(msg).text, msg)


class ModeTests(AgentTestCase):
    def test_default_mode_unchanged(self):
        a = self.build()
        self.assertEqual(a.handle("2+2").text, "4")
        self.assertEqual(a.handle("hello there").text, "LLM reply")

    def test_tools_mode_only_runs_tools_and_never_calls_llm_or_store(self):
        a = self.build("User loves coding")
        self.assertEqual(a.handle("what is 6*7?", "tools").text, "42")
        r = a.handle("i love hiking", "tools")
        self.assertEqual(r.action, "MODE_HINT")
        self.assertIn("calculator", r.text)
        self.assertEqual(a.handle("hello", "tools").action, "MODE_HINT")
        self.assertEqual(self.backend.texts(), ["User loves coding"])
        self.assertEqual(self.llm.calls, [])

    def test_memory_mode_manages_memories(self):
        a = self.build("User loves coding")
        self.assertIn("1. User loves coding", a.handle("show my memories", "memory").text)
        self.assertIn("Saved", a.handle("i love hiking", "memory").text)
        self.assertEqual(a.handle("how many memories do I have", "memory").text, "I have 2 memories stored.")
        self.assertEqual(len(self.backend.texts()), 2)

    def test_memory_mode_free_text_is_a_memory_lookup_never_open_chat(self):
        a = self.build("User loves coding")
        r = a.handle("tell me a joke", "memory")
        self.assertEqual(r.action, "SEARCH_MEMORY")
        self.assertIn("don't have anything stored", r.text)
        self.assertEqual(self.llm.calls, [])

    def test_memory_mode_rejects_calculator(self):
        a = self.build()
        self.assertEqual(a.handle("2+2", "memory").action, "MODE_HINT")

    def test_unknown_mode_rejected_without_side_effects(self):
        a = self.build()
        r = a.handle("i love coding", "root")
        self.assertEqual(r.action, "ERROR")
        self.assertEqual(self.backend.texts(), [])
        self.assertEqual(self.history.messages, [])


class RagAndHistoryTests(AgentTestCase):
    def test_answer_is_grounded_in_retrieved_memories(self):
        a = self.build("User's favorite food is pasta", "xxxxxxxxxxxx unrelated yyyyyyy")
        r = a.handle("what is my favorite food?")
        system = self.llm.calls[-1][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("User's favorite food is pasta", system["content"])
        self.assertNotIn("unrelated", system["content"])
        self.assertIn("DO have access", system["content"])
        self.assertIn("guess", system["content"])
        self.assertEqual(r.text, "LLM reply")

    def test_personal_question_with_nothing_relevant_is_answered_honestly_without_the_model(self):
        a = self.build("zzzz")
        r = a.handle("what is my favorite food?")
        self.assertIn("don't have anything stored", r.text)
        self.assertEqual(self.llm.calls, [])

    def test_general_question_with_no_matching_memory_still_goes_to_the_model(self):
        a = self.build("zzzz")
        a.handle("what is the capital of France?")
        self.assertIn("none matched", self.llm.calls[-1][0]["content"])

    def test_prompt_uses_bounded_history_with_roles(self):
        a = self.build()
        for i in range(15):
            a.handle(f"hello {i}")
        sent = self.llm.calls[-1]
        self.assertEqual(len(sent), 1 + 10)
        self.assertEqual(sent[-1], {"role": "user", "content": "hello 14"})

    def test_history_persisted_for_every_action(self):
        a = self.build()
        a.handle("i love coding")
        a.handle("2+2")
        a.handle("show my memories")
        again = ConversationHistory(self.history.path).messages
        self.assertEqual([m["role"] for m in again], ["user", "assistant"] * 3)
        self.assertEqual(again[3]["content"], "4")

    def test_llm_down_is_reported_not_raised(self):
        a = self.build(llm=FakeLLM(error=LLMError("Ollama is down")))
        r = a.handle("hello there")
        self.assertEqual(r.action, "ERROR")
        self.assertIn("Ollama is down", r.text)

    def test_memory_search_failure_falls_back_to_chat(self):
        a = self.build("User a1")
        self.backend.fail = RuntimeError("down")
        self.assertEqual(a.handle("hello there").text, "LLM reply")

    def test_calculator_symbols_work_through_the_agent_without_the_llm(self):
        a = self.build()
        for text, out in [("25 \u00d7 4", "100"), ("what is 25 \u00d7 4?", "100"), ("125 \u00f7 5", "25"), ("12 plus 30", "42")]:
            r = a.handle(text)
            self.assertEqual((r.action, r.text), ("CALCULATE", out), text)
        self.assertEqual(self.llm.calls, [])

    def test_calculator_routing_and_empty_input(self):
        a = self.build()
        self.assertEqual(a.handle("what is 6*7?").text, "42")
        self.assertEqual(a.handle("1/0").text, "Division by zero is undefined.")
        self.assertEqual(a.handle("   ").action, "NONE")
        self.assertEqual(len(self.history.messages), 4)        # blank input not recorded


if __name__ == "__main__":
    unittest.main()
