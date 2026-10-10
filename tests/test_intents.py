import unittest

from memory_agent.agent import decide_action
from memory_agent.intents import parse_intent


def kind(text):
    i = parse_intent(text)
    return (i.kind, i.arg) if i else None


class IntentTests(unittest.TestCase):
    def test_list_phrasings(self):
        for t in ["show my memories", "Show my memories", "can u show my memories?", "could you list my memories please",
                  "list memories", "display all my memories", "view my stored memories", "give me my memories",
                  "what memories do you have?", "what are my memories", "what facts do you have about me",
                  "please show me everything you remember about me"]:
            self.assertEqual(kind(t), ("LIST", ""), t)

    def test_what_do_you_remember_about_me_is_a_list_with_header_flag(self):
        for t in ["What do you remember about me?", "what do you know about me", "what have you learned about me so far",
                  "tell me what you remember", "do you remember anything about me"]:
            i = parse_intent(t)
            self.assertEqual((i.kind, i.about_me), ("LIST", True), t)

    def test_topic_search(self):
        self.assertEqual(kind("Search my memories about coding"), ("SEARCH", "coding"))
        self.assertEqual(kind("search memories for pasta"), ("SEARCH", "pasta"))
        self.assertEqual(kind("find my memory about football"), ("SEARCH", "football"))
        self.assertEqual(kind("show me memories about my favorite food"), ("SEARCH", "favorite food"))
        self.assertEqual(kind("what do you remember about football?"), ("SEARCH", "football"))
        self.assertEqual(kind("look through my memories for food"), ("SEARCH", "food"))

    def test_save_keeps_the_fact_and_its_casing(self):
        self.assertEqual(kind("Remember that I like testing memory features"), ("SAVE", "I like testing memory features"))
        self.assertEqual(kind("please remember: I live in Berlin"), ("SAVE", "I live in Berlin"))
        self.assertEqual(kind("note that I'm vegan"), ("SAVE", "I'm vegan"))
        self.assertEqual(kind("don't forget that I work at Acme"), ("SAVE", "I work at Acme"))
        self.assertEqual(kind("remember my favorite color is blue"), ("SAVE", "my favorite color is blue"))
        self.assertEqual(kind("save this memory: I speak Hindi"), ("SAVE", "I speak Hindi"))
        self.assertEqual(kind("remember: My birthday is May 5."), ("SAVE", "My birthday is May 5"))

    def test_forget_variants_carry_a_topic_never_a_bulk_wipe(self):
        self.assertEqual(kind("Forget that I like testing memory features")[0], "FORGET")
        self.assertEqual(kind("forget my favorite color"), ("FORGET", "favorite color"))
        self.assertEqual(kind("delete the memory about football"), ("FORGET", "football"))
        self.assertEqual(kind("remove football from my memories"), ("FORGET", "football"))
        self.assertEqual(kind("delete memory"), ("FORGET", ""))
        for t in ["forget everything", "delete all my memories", "forget all", "wipe my memories", "erase everything you know about me"]:
            self.assertEqual(kind(t), ("FORGET_ALL", ""), t)

    def test_update_count_duplicates(self):
        self.assertEqual(kind("update memory"), ("UPDATE", ""))
        self.assertEqual(kind("I want to edit a memory"), ("UPDATE", ""))
        self.assertEqual(kind("edit my memory about food"), ("UPDATE", "food"))
        self.assertEqual(kind("how many memories do I have"), ("COUNT", ""))
        self.assertEqual(kind("find duplicates"), ("DUPLICATES", ""))

    def test_ordinary_messages_are_not_hijacked(self):
        for t in ["what is the capital of France", "show me a python example", "tell me a joke", "list the planets",
                  "I remember my childhood", "remember", "remember how to ride a bike", "what do you think about memory",
                  "hello there", "my favorite food is pasta", "2+2", "update my favorite food to pasta", "", "   "]:
            self.assertIsNone(parse_intent(t), t)

    def test_routing_uses_intents_before_any_llm(self):
        class Boom:                      # would fail the test if the LLM were consulted
            def chat(self, *_):
                raise AssertionError("LLM must not be used for memory commands")
        for t, action in [("can u show my memories?", "LIST_MEMORIES"), ("what do you remember about me?", "LIST_MEMORIES"),
                          ("Search my memories about coding", "SEARCH_RECORDS"), ("Remember that I like tea", "SAVE_MEMORY"),
                          ("forget my favorite color", "FORGET"), ("delete memory", "DELETE_MEMORY"),
                          ("forget everything", "FORGET_ALL"), ("edit my memory about food", "UPDATE_MEMORY")]:
            self.assertEqual(decide_action(t, Boom()), action, t)


if __name__ == "__main__":
    unittest.main()
