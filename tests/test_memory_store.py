import unittest

from memory_agent.memory_store import MemoryStore, Status
from tests.fakes import FakeBackend


def make(*texts):
    backend = FakeBackend(texts)
    return MemoryStore(backend, user_id="u"), backend


class SaveTests(unittest.TestCase):
    def test_new_memory_saved(self):
        store, b = make()
        res = store.save("i love coding")
        self.assertEqual(res.status, Status.SAVED)
        self.assertEqual(b.texts(), ["User loves coding"])

    def test_identical_twice_saves_once(self):
        store, b = make()
        self.assertEqual(store.save("i love coding").status, Status.SAVED)
        self.assertEqual(store.save("i love coding").status, Status.DUPLICATE)
        self.assertEqual(len(b.texts()), 1)

    def test_many_repeats_never_add_records(self):
        store, b = make()
        for _ in range(5):
            store.save("I love coding!")
        self.assertEqual(len(b.texts()), 1)

    def test_semantically_equivalent_to_mem0_style_text(self):
        for stored in ["User loves coding", "User stated they love coding"]:
            store, b = make(stored)
            res = store.save("i love coding")
            self.assertEqual(res.status, Status.DUPLICATE, stored)
            self.assertEqual(b.texts(), [stored])

    def test_duplicate_found_beyond_mem0_default_top_k(self):
        # Regression: get_all() defaults to 20 rows; the match is the 30th.
        filler = [f"User likes hobby{i}" for i in range(29)]
        store, b = make(*filler, "User loves coding")
        self.assertEqual(store.save("i love coding").status, Status.DUPLICATE)
        self.assertEqual(len(b.texts()), 30)
        self.assertEqual(len(store.list()), 30)

    def test_unrelated_memories_preserved(self):
        store, b = make("User loves football", "User's favorite color is blue")
        store.save("i love coding")
        self.assertEqual(len(b.texts()), 3)
        self.assertIn("User loves football", b.texts())
        self.assertIn("User's favorite color is blue", b.texts())

    def test_explicit_correction_updates_the_single_matching_fact(self):
        store, b = make("User's favorite food is biryani", "User loves football")
        res = store.save("Actually, my favorite food is pasta")
        self.assertEqual(res.status, Status.UPDATED)
        self.assertCountEqual(b.texts(), ["User's favorite food is pasta", "User loves football"])

    def test_actually_correction_of_a_single_valued_verb_replaces_not_stacks(self):
        store, b = make("User prefers black coffee", "User loves football")
        res = store.save("Actually, I prefer green tea")
        self.assertEqual(res.status, Status.UPDATED)
        self.assertCountEqual(b.texts(), ["User prefers green tea", "User loves football"])

    def test_actually_with_several_same_verb_memories_asks(self):
        store, b = make("User prefers black coffee", "User prefers dark mode")
        res = store.save("Actually, I prefer green tea")
        self.assertEqual(res.status, Status.NEEDS_CONFIRMATION)
        self.assertEqual(len(b.texts()), 2)

    def test_plain_statement_with_same_verb_is_still_just_added(self):
        store, b = make("User prefers black coffee")
        self.assertEqual(store.save("I prefer dark mode").status, Status.SAVED)
        self.assertEqual(len(b.texts()), 2)

    def test_actually_does_not_touch_non_exclusive_verbs(self):
        store, b = make("User loves football")
        self.assertEqual(store.save("Actually, I love chess").status, Status.SAVED)
        self.assertEqual(len(b.texts()), 2)

    def test_conflict_without_correction_marker_asks(self):
        store, b = make("User's favorite food is biryani")
        res = store.save("my favorite food is pasta")
        self.assertEqual(res.status, Status.NEEDS_CONFIRMATION)
        self.assertEqual(res.reason, "conflict")
        self.assertEqual(b.texts(), ["User's favorite food is biryani"])  # untouched

    def test_correction_with_several_candidates_asks(self):
        store, b = make("User's favorite food is biryani", "User corrected their favorite food to rice")
        res = store.save("Actually, my favorite food is pasta")
        self.assertEqual(res.status, Status.NEEDS_CONFIRMATION)
        self.assertEqual(len(res.candidates), 2)
        self.assertEqual(len(b.texts()), 2)

    def test_conflicting_sentiment_asks_instead_of_adding(self):
        store, b = make("User hates coding")
        res = store.save("i love coding")
        self.assertEqual(res.status, Status.NEEDS_CONFIRMATION)
        self.assertEqual(res.reason, "similar")
        self.assertEqual(b.texts(), ["User hates coding"])

    def test_empty_input_invalid(self):
        store, b = make()
        for blank in ["", "   ", None]:
            self.assertEqual(store.save(blank).status, Status.INVALID)
        self.assertEqual(b.texts(), [])

    def test_store_error_reported_not_saved(self):
        store, b = make()
        b.fail = RuntimeError("qdrant down")
        res = store.save("i love coding")
        self.assertEqual(res.status, Status.ERROR)
        self.assertFalse(res.ok)
        self.assertIn("qdrant down", res.message)

    def test_add_failure_reported_as_error(self):
        store, b = make()
        b.add = lambda *a, **k: {"results": []}      # backend silently stored nothing
        self.assertEqual(store.save("i love coding").status, Status.ERROR)


class ManageTests(unittest.TestCase):
    def test_list_has_stable_ids_and_order(self):
        store, _ = make("User a1", "User b2", "User c3")
        first, second = store.list(), store.list()
        self.assertEqual(first, second)
        self.assertEqual([m["memory"] for m in first], ["User a1", "User b2", "User c3"])
        self.assertTrue(all(m["id"] for m in first))

    def test_update_only_selected(self):
        store, b = make("User loves coding", "User loves football")
        target = store.list()[0]["id"]
        res = store.update(target, "User loves Python")
        self.assertEqual(res.status, Status.UPDATED)
        self.assertCountEqual(b.texts(), ["User loves Python", "User loves football"])

    def test_update_invalid_inputs(self):
        store, b = make("User loves coding")
        self.assertEqual(store.update(store.list()[0]["id"], "  ").status, Status.INVALID)
        self.assertEqual(store.update("nope", "x").status, Status.NOT_FOUND)
        self.assertEqual(b.texts(), ["User loves coding"])

    def test_delete_requires_confirmation(self):
        store, b = make("User loves coding")
        res = store.delete(store.list()[0]["id"])
        self.assertEqual(res.status, Status.INVALID)
        self.assertEqual(len(b.texts()), 1)

    def test_delete_only_selected(self):
        store, b = make("User loves coding", "User loves football")
        res = store.delete(store.list()[0]["id"], confirmed=True)
        self.assertEqual(res.status, Status.DELETED)
        self.assertEqual(b.texts(), ["User loves football"])

    def test_delete_unknown_id(self):
        store, b = make("User loves coding")
        self.assertEqual(store.delete("nope", confirmed=True).status, Status.NOT_FOUND)
        self.assertEqual(len(b.texts()), 1)

    def test_update_and_delete_errors(self):
        store, b = make("User loves coding")
        mid = store.list()[0]["id"]
        b.fail = RuntimeError("boom")
        self.assertEqual(store.update(mid, "x").status, Status.ERROR)
        self.assertEqual(store.delete(mid, confirmed=True).status, Status.ERROR)

    def test_search_filters_by_score_and_handles_blank(self):
        store, _ = make("User loves coding", "zzzz qqqq")
        hits = store.search("User loves coding", min_score=0.9)
        self.assertEqual([h["memory"] for h in hits], ["User loves coding"])
        self.assertEqual(store.search("   "), [])


class DuplicateReportTests(unittest.TestCase):
    def test_groups_equivalents_and_conflicts_without_changing_anything(self):
        store, b = make("User loves coding", "User stated they love coding",
                        "User's favorite food is biryani", "User's favorite food is pasta",
                        "User loves football")
        same, conflicts = store.find_duplicate_groups()
        self.assertEqual([[m["memory"] for m in g] for g in same],
                         [["User loves coding", "User stated they love coding"]])
        self.assertEqual([[m["memory"] for m in g] for g in conflicts],
                         [["User's favorite food is biryani", "User's favorite food is pasta"]])
        self.assertEqual(len(b.texts()), 5)

    def test_clean_store_reports_nothing(self):
        store, _ = make("User loves coding", "User loves football")
        self.assertEqual(store.find_duplicate_groups(), ([], []))


if __name__ == "__main__":
    unittest.main()
