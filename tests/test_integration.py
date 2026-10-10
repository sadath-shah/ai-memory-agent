"""Real Mem0 + Ollama + Qdrant, in a throwaway temp dir (never your real data).
Skipped unless RUN_INTEGRATION=1 and Ollama is reachable."""
import os
import tempfile
import unittest
import urllib.request

from memory_agent import config

RUN = os.environ.get("RUN_INTEGRATION") == "1"


def ollama_up():
    try:
        urllib.request.urlopen(config.OLLAMA_URL + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(RUN and ollama_up(), "set RUN_INTEGRATION=1 with Ollama running")
class RealStackTests(unittest.TestCase):
    def test_duplicates_corrections_and_isolation(self):
        from mem0 import Memory
        from memory_agent.memory_store import MemoryStore, Status

        with tempfile.TemporaryDirectory() as tmp:
            cfg = config.mem0_config(f"{tmp}/qdrant", f"{tmp}/history.db")
            self.assertNotEqual(os.path.realpath(cfg["vector_store"]["config"]["path"]),
                                os.path.realpath(config.QDRANT_PATH))
            store = MemoryStore(Memory.from_config(cfg), user_id="itest")

            self.assertEqual(store.save("i love coding").status, Status.SAVED)
            for _ in range(3):
                self.assertEqual(store.save("i love coding").status, Status.DUPLICATE)
            self.assertEqual(store.save("I love coding!").status, Status.DUPLICATE)
            self.assertEqual(len(store.list()), 1)

            self.assertEqual(store.save("my favorite food is biryani").status, Status.SAVED)
            self.assertEqual(store.save("Actually, my favorite food is pasta").status, Status.UPDATED)
            texts = sorted(m["memory"] for m in store.list())
            self.assertEqual(texts, ["User loves coding", "User's favorite food is pasta"])

            hits = store.search("what food do I like", limit=3)
            self.assertEqual(hits[0]["memory"], "User's favorite food is pasta")

            victim = next(m for m in store.list() if "coding" in m["memory"])
            self.assertEqual(store.delete(victim["id"], confirmed=True).status, Status.DELETED)
            self.assertEqual([m["memory"] for m in store.list()], ["User's favorite food is pasta"])


if __name__ == "__main__":
    unittest.main()
