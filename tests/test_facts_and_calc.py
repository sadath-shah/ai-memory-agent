import unittest

from memory_agent import facts
from memory_agent.calculator import CalcError, calculate, extract_expression, safe_calculate
from memory_agent.facts import Relation, parse, relate


def rel(a, b):
    return relate(parse(a), parse(b))


class FactTests(unittest.TestCase):
    def test_mem0_rewrites_are_equivalent(self):
        self.assertIs(rel("i love coding", "User loves coding"), Relation.SAME)
        self.assertIs(rel("i love coding", "User stated they love coding"), Relation.SAME)
        self.assertIs(rel("my favorite food is pasta", "User corrected their favorite food to pasta"), Relation.SAME)

    def test_different_value_is_conflict(self):
        self.assertIs(rel("my favorite food is pasta", "User's favorite food is biryani"), Relation.CONFLICT)

    def test_unrelated_facts_not_matched(self):
        self.assertIs(rel("i love coding", "User loves football"), Relation.UNRELATED)
        self.assertIs(rel("my favorite food is pasta", "User's favorite sport is football"), Relation.UNRELATED)

    def test_opposite_sentiment_is_only_related_never_same(self):
        self.assertIs(rel("i love coding", "User hates coding"), Relation.RELATED)

    def test_rendering(self):
        self.assertEqual(facts.to_memory_text("i love coding"), "User loves coding")
        self.assertEqual(facts.to_memory_text("Actually, my favorite food is pasta."), "User's favorite food is pasta")
        self.assertEqual(facts.to_memory_text("update my favorite food to pasta"), "User's favorite food is pasta")
        self.assertEqual(facts.to_memory_text("   "), "")
        self.assertEqual(facts.to_memory_text("I enjoy stress testing my own code"), "User enjoys stress testing their own code")
        self.assertEqual(facts.to_memory_text("I love my dog"), "User loves their dog")
        self.assertEqual(facts.to_memory_text("my name is Sadath"), "User's name is Sadath")

    def test_correction_detection(self):
        self.assertTrue(facts.strip_correction("Actually, my favorite food is pasta")[1])
        self.assertFalse(facts.strip_correction("my favorite food is pasta")[1])
        self.assertFalse(facts.strip_correction("nobody likes me")[1])


class CalculatorTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(safe_calculate("2+2"), "4")
        self.assertEqual(safe_calculate("10/4"), "2.5")
        self.assertEqual(safe_calculate("0.1+0.2"), "0.3")
        self.assertEqual(safe_calculate("-(3+4)*2"), "-14")
        self.assertEqual(safe_calculate("2^10"), "1024")
        self.assertEqual(safe_calculate("7//2"), "3")
        self.assertEqual(safe_calculate("7 % 4?"), "3")

    def test_division_by_zero(self):
        self.assertEqual(safe_calculate("1/0"), "Division by zero is undefined.")

    def test_rejects_unsafe_input(self):
        for bad in ["__import__('os').system('echo hi')", "open('x')", "a+1",
                    "[1,2]", "'a'*5", "True+1", "1j*2", "(lambda: 1)()", "", "   "]:
            self.assertEqual(safe_calculate(bad), "I couldn't calculate that.", bad)

    def test_resource_exhaustion_blocked(self):
        for bad in ["9**9**9", "10**100000", "2**-99999999", "(-8)**0.5", "1e308*10", "9" * 500]:
            with self.assertRaises((CalcError, ZeroDivisionError), msg=bad):
                calculate(bad)

    def test_symbol_and_word_operators_use_the_safe_calculator(self):
        cases = {"25 \u00d7 4": "100", "25 x 4": "100", "25X4": "100", "what is 25 \u00d7 4?": "100", "125 \u00f7 5": "25",
                 "125 divided by 5": "25", "25 times 4": "100", "12 plus 30": "42", "100 minus 58": "42",
                 "2 to the power of 10": "1024", "10 mod 3": "1", "5 \u2212 -3": "8", "calculate 3 multiplied by 7": "21"}
        for text, expected in cases.items():
            expr = extract_expression(text)
            self.assertIsNotNone(expr, text)
            self.assertEqual(safe_calculate(expr), expected, text)

    def test_normalisation_does_not_hijack_normal_sentences(self):
        for text in ["I have 2 plus points", "box 5 x 3 inches", "my x is 4", "tell me about times square", "what is 2 minus"]:
            expr = extract_expression(text)
            self.assertTrue(expr is None or safe_calculate(expr) == "I couldn't calculate that.", text)

    def test_extract_expression(self):
        self.assertEqual(extract_expression("what is 12 * (3+4)?"), "12 * (3+4)")
        self.assertEqual(extract_expression("calculate 5^2"), "5^2")
        self.assertIsNone(extract_expression("my favorite number is 7"))
        self.assertIsNone(extract_expression("hello"))
        self.assertIsNone(extract_expression("42"))


if __name__ == "__main__":
    unittest.main()
