"""End-to-end agent behaviour for natural-language memory commands (fake store)."""
import unittest

from memory_agent.agent import Agent
from tests.test_agent import AgentTestCase
from tests.fakes import FakeLLM

SEED = ["User loves football", "User's favorite food is pasta", "User loves coding"]


class MemoryCommandTests(AgentTestCase):
    def test_show_memories_returns_the_real_records_without_calling_the_llm(self):
        a = self.build(*SEED)
        r = a.handle("can u show my memories?")
        self.assertEqual(r.action, "LIST_MEMORIES")
        for text in SEED:
            self.assertIn(text, r.text)
        self.assertIn("You have 3 stored memories", r.text)
        self.assertEqual(self.llm.calls, [])

    def test_what_do_you_remember_about_me_lists_retrieved_memories(self):
        a = self.build(*SEED)
        r = a.handle("What do you remember about me?")
        self.assertIn("Here's what I remember about you (3):", r.text)
        self.assertIn("User's favorite food is pasta", r.text)
        self.assertEqual(self.llm.calls, [])

    def test_empty_store_is_stated_honestly(self):
        r = self.build().handle("show my memories")
        self.assertIn("don't have any memories stored yet", r.text)
        self.assertNotIn("1.", r.text)

    def test_store_error_is_reported_not_hidden_or_faked(self):
        a = self.build(*SEED)
        self.backend.fail = RuntimeError("qdrant is locked")
        for msg in ["show my memories", "search my memories about coding", "how many memories do I have"]:
            r = a.handle(msg)
            self.assertIn("qdrant is locked", r.text, msg)
            self.assertNotIn("User loves", r.text)

    def test_search_topic_returns_only_matching_records(self):
        a = self.build(*SEED)
        r = a.handle("Search my memories about coding")
        self.assertEqual(r.action, "SEARCH_RECORDS")
        self.assertIn("User loves coding", r.text)
        self.assertNotIn("football", r.text)
        self.assertIn('about "coding"', r.text)

    def test_search_topic_without_matches_says_so(self):
        a = self.build(*SEED)
        r = a.handle("search my memories about zebras")
        self.assertIn("found nothing matching", r.text)
        self.assertIn("3 stored in total", r.text)

    def test_remember_that_saves_then_show_lists_it(self):
        a = self.build(*SEED)
        r = a.handle("Remember that I like testing memory features")
        self.assertEqual(r.action, "SAVE_MEMORY")
        self.assertIn("Saved", r.text)
        self.assertIn("User likes testing memory features", self.backend.texts())
        self.assertIn("User likes testing memory features", a.handle("show my memories").text)
        self.assertEqual(len(self.backend.texts()), 4)

    def test_remember_twice_does_not_duplicate(self):
        a = self.build()
        a.handle("remember that I like tea")
        self.assertIn("Already stored", a.handle("Remember that I like tea").text)
        self.assertEqual(len(self.backend.texts()), 1)

    def test_remember_conflicting_fact_asks_before_changing_anything(self):
        a = self.build("User's favorite food is biryani")
        r = a.handle("remember that my favorite food is pasta")
        self.assertIn("different value", r.text)
        self.assertEqual(self.backend.texts(), ["User's favorite food is biryani"])

    def test_forget_never_deletes_a_best_match_without_pick_and_confirm(self):
        a = self.build(*SEED)
        r = a.handle("Forget that I love coding")
        self.assertIn("Nothing is deleted until you pick one and confirm", r.text)
        self.assertIn("User loves coding", r.text)
        self.assertEqual(len(self.backend.texts()), 3)
        a.handle("1")
        self.assertEqual(len(self.backend.texts()), 3)          # still needs "yes"
        self.assertIn("Deletion cancelled", a.handle("no").text)
        self.assertEqual(len(self.backend.texts()), 3)

    def test_forget_ambiguous_lists_all_candidates_for_clarification(self):
        a = self.build("User loves football", "User plays football on Sundays", "User loves coding")
        r = a.handle("forget football")
        self.assertIn("1. ", r.text)
        self.assertIn("2. ", r.text)
        self.assertNotIn("coding", r.text)
        a.handle("2"); a.handle("yes")
        self.assertCountEqual(self.backend.texts(), ["User loves football", "User loves coding"])

    def test_multiword_topic_needs_more_than_one_shared_word(self):
        a = self.build("User likes testing memory features", "User is working on an AI memory agent project")
        r = a.handle("Forget that I like testing memory features")
        self.assertIn("1. User likes testing memory features", r.text)
        self.assertNotIn("agent project", r.text)            # shares only "memory"
        r = a.handle("cancel")
        r = a.handle("search my memories about testing")
        self.assertIn("User likes testing memory features", r.text)
        self.assertNotIn("agent project", r.text)

    def test_forget_with_no_match_deletes_nothing(self):
        a = self.build(*SEED)
        r = a.handle("forget zebras")
        self.assertIn("Nothing was deleted", r.text)
        self.assertEqual(len(self.backend.texts()), 3)

    def test_forget_everything_is_never_a_bulk_delete(self):
        a = self.build(*SEED)
        r = a.handle("delete all my memories")
        self.assertIn("one memory", r.text.lower())
        self.assertEqual(len(self.backend.texts()), 3)
        a.handle("cancel")
        self.assertEqual(len(self.backend.texts()), 3)

    def test_update_with_topic_offers_matching_memories_then_updates_selected(self):
        a = self.build(*SEED)
        r = a.handle("edit my memory about coding")
        self.assertIn("User loves coding", r.text)
        self.assertNotIn("football", r.text)
        a.handle("1")
        self.assertIn("Updated", a.handle("User loves Python").text)
        self.assertCountEqual(self.backend.texts(), ["User loves football", "User's favorite food is pasta", "User loves Python"])

    def test_commands_work_in_memory_mode_and_are_blocked_in_tools_mode(self):
        a = self.build(*SEED)
        self.assertIn("User loves coding", a.handle("can u show my memories?", "memory").text)
        self.assertEqual(a.handle("show my memories", "tools").action, "MODE_HINT")
        self.assertEqual(len(self.backend.texts()), 3)


class GroundedChatTests(AgentTestCase):
    def test_prompt_has_only_relevant_memories_not_all_of_them(self):
        seed = [f"User likes hobby{i} zzz{i}" for i in range(30)] + ["User's favorite food is pasta"]
        a = self.build(*seed)
        a.handle("what is my favorite food?")
        system = self.llm.calls[-1][0]["content"]
        self.assertIn("User's favorite food is pasta", system)
        self.assertLessEqual(system.count("- User"), 5)

    def test_model_denying_memory_access_is_replaced_by_the_retrieved_facts(self):
        a = self.build("User's favorite food is pasta", llm=FakeLLM("I don't have access to your personal memories, sorry."))
        r = a.handle("what is my favorite food?")
        self.assertNotIn("don't have access", r.text)
        self.assertIn("User's favorite food is pasta", r.text)

    def test_model_denial_with_nothing_retrieved_gets_an_honest_search_result(self):
        a = self.build("zzzz", llm=FakeLLM("I can't remember previous conversations or retain personal information."))
        r = a.handle("can you recall previous conversations?")
        self.assertIn("searched your stored memories and found nothing relevant", r.text)
        self.assertNotIn("can't remember", r.text)

    def test_conflicting_records_are_surfaced_not_resolved_by_the_model(self):
        a = self.build("User's favorite food is biryani", "User's favorite food is pasta", "User loves football",
                       llm=FakeLLM("Your favorite food is pasta."))
        r = a.handle("what is my favorite food?")
        self.assertIn("conflicting records", r.text)
        self.assertIn("biryani", r.text)
        self.assertIn("pasta", r.text)
        self.assertEqual(self.llm.calls, [])               # the model never got to pick a winner

    def test_same_value_repeated_is_not_a_conflict(self):
        a = self.build("User's favorite food is pasta", "User stated their favorite food is pasta",
                       llm=FakeLLM("Your favorite food is pasta."))
        self.assertEqual(a.handle("what is my favorite food?").text, "Your favorite food is pasta.")

    def test_prompt_says_stored_memories_override_stale_chat(self):
        a = self.build("User's locker number is 2000")
        a.handle("what is my locker number?")
        self.assertIn("current truth", self.llm.calls[-1][0]["content"])

    def test_fresh_memories_are_restated_in_the_last_turn_but_history_stays_clean(self):
        a = self.build("User's locker number is 2000")
        a.handle("what is my locker number?")
        last = self.llm.calls[-1][-1]
        self.assertEqual(last["role"], "user")
        self.assertIn("Current stored memories", last["content"])
        self.assertIn("2000", last["content"])
        self.assertEqual(self.history.messages[0], {"role": "user", "content": "what is my locker number?"})

    def test_no_restatement_when_nothing_was_retrieved(self):
        a = self.build("zzzz")
        a.handle("what is the capital of France?")
        self.assertNotIn("Current stored memories", self.llm.calls[-1][-1]["content"])

    def test_personal_question_without_relevant_memory_never_reaches_the_model(self):
        """Regression: the model once invented 'you prefer beer while watching football'."""
        a = self.build("User loves football", "User's favorite sport is football", llm=FakeLLM("You prefer beer while watching football."))
        for q in ["What do I prefer to drink?", "What is my mother's name?", "Where was I born?"]:
            r = a.handle(q)
            self.assertIn("don't have anything stored", r.text, q)
        self.assertEqual(self.llm.calls, [])

    def test_questions_about_the_conversation_itself_still_use_the_model(self):
        a = self.build("User loves football", llm=FakeLLM("You asked about the capital of France."))
        r = a.handle("What did I just ask you?")
        self.assertEqual(r.text, "You asked about the capital of France.")

    def test_relevance_uses_words_or_a_calibrated_semantic_score(self):
        rel = Agent._relevant
        self.assertTrue(rel({"memory": "User's favorite food is pasta", "score": 0.50}, "what is my favorite food?"))   # word overlap
        self.assertTrue(rel({"memory": "User's favorite food is pasta", "score": 0.64}, "what do I like to eat?"))      # semantic only
        self.assertFalse(rel({"memory": "User's favorite sport is football", "score": 0.555}, "What do I prefer to drink?"))

    def test_model_saying_nothing_is_stored_despite_a_relevant_hit_is_overruled(self):
        a = self.build("User's locker number is 2000", llm=FakeLLM("I found nothing stored about your locker number."))
        r = a.handle("what is my locker number?")
        self.assertIn("User's locker number is 2000", r.text)
        self.assertNotIn("found nothing", r.text)

    def test_nothing_stored_answer_is_kept_when_hits_are_irrelevant(self):
        a = self.build("User loves football", llm=FakeLLM("I found nothing stored about the weather."))
        self.assertEqual(a.handle("what is the weather like?").text, "I found nothing stored about the weather.")

    def test_normal_answers_pass_through_unchanged(self):
        a = self.build("User's favorite food is pasta", llm=FakeLLM("Your favorite food is pasta."))
        self.assertEqual(a.handle("what is my favorite food?").text, "Your favorite food is pasta.")
        a2 = self.build(llm=FakeLLM("Paris is the capital of France."))
        self.assertEqual(a2.handle("what is the capital of France?").text, "Paris is the capital of France.")

    def test_conversations_and_memories_stay_separate(self):
        a = self.build(*SEED)
        a.handle("remember that I like tea")
        self.assertEqual(len(self.backend.texts()), 4)
        self.assertNotIn("remember that", " ".join(self.backend.texts()).lower())   # chat text isn't a memory
        self.assertEqual([m["role"] for m in self.history.messages], ["user", "assistant"])


if __name__ == "__main__":
    unittest.main()
