import json
import tempfile
import unittest
from pathlib import Path

from memory_agent.history import ConversationHistory


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "h.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_persists_across_instances(self):
        h = ConversationHistory(self.path)
        h.append("user", "hi")
        h.append("assistant", "hello")
        again = ConversationHistory(self.path)
        self.assertEqual(again.messages, [{"role": "user", "content": "hi"},
                                          {"role": "assistant", "content": "hello"}])

    def test_window_limits_prompt_size(self):
        h = ConversationHistory(self.path)
        for i in range(30):
            h.append("user", str(i))
        self.assertEqual(len(h.window(10)), 10)
        self.assertEqual(h.window(10)[-1]["content"], "29")
        self.assertEqual(h.window(0), [])

    def test_corrupt_file_is_kept_aside_not_overwritten(self):
        self.path.write_text("{not json")
        h = ConversationHistory(self.path)
        self.assertEqual(h.messages, [])
        aside = list(Path(self.dir.name).glob("h.json.corrupt-*"))
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_text(), "{not json")

    def test_wrong_shape_is_kept_aside(self):
        self.path.write_text(json.dumps({"a": 1}))
        self.assertEqual(ConversationHistory(self.path).messages, [])
        self.assertEqual(len(list(Path(self.dir.name).glob("*.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main()
