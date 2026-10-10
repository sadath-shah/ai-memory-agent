"""Deterministic fact normalisation and comparison.

Mem0 rewrites input with an LLM ("i love coding" -> "User loves coding" or
"User stated they love coding"), so raw strings can't be compared. We reduce
both the new statement and every stored memory to a small structured Fact and
compare those. Vector similarity is NOT used here; callers may use it only as
an extra hint to ask the user, never to decide to overwrite or delete.
"""
import re
from dataclasses import dataclass
from enum import Enum


class Relation(str, Enum):
    SAME = "same"            # equivalent fact
    CONFLICT = "conflict"    # same attribute, different value
    RELATED = "related"      # overlapping but not provably the same
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class Fact:
    kind: str                # "attribute" | "statement" | "other"
    slot: str                # attribute name or (negated) verb stem
    value: frozenset         # stemmed content tokens of the value
    tokens: frozenset        # all stemmed content tokens


_CORRECTION_RE = re.compile(
    r"^\s*(?:actually|correction|no|nope|wait|sorry|oops|i meant|i mean|"
    r"rather|update|change|let me correct that|to correct myself)\b[\s,:;.!-]*",
    re.I)
_NOISE = {"stated", "states", "state", "said", "says", "mentioned", "corrected",
          "correction", "initially", "originally", "previously", "also",
          "that", "just", "really", "actually", "now", "currently", "again"}
_SUBJECTS = {"i", "user", "they", "he", "she", "my", "their", "his", "her", "our", "we"}
_ARTICLES = {"a", "an", "the"}
_STOP = _ARTICLES | {"is", "are", "am", "be", "was", "to", "of", "and", "as", "in", "on"}
_IRREGULAR = {"is": "be", "am": "be", "are": "be", "has": "have", "does": "do"}
_VERBS = {"love", "like", "enjoy", "hate", "dislike", "want", "need", "study",
          "work", "live", "have", "be", "prefer", "play", "use", "speak", "own",
          "plan", "go", "drive", "eat", "drink", "read", "watch", "hope",
          "learn", "know", "build"}
_ATTR_RE = re.compile(r"^(?P<slot>[a-z0-9 ]+?) (?:is|are|was|to be|to|as) (?P<val>.+)$")
_CONTRACTIONS = [
    (r"\bi'm\b", "i am"), (r"\bi've\b", "i have"), (r"\bdon't\b", "do not"),
    (r"\bdoesn't\b", "does not"), (r"\bcan't\b", "can not"),
]


def strip_correction(text):
    """Return (text without leading correction markers, was_correction)."""
    corrected = False
    while True:
        new = _CORRECTION_RE.sub("", text, count=1)
        if new == text:
            return text.strip(), corrected
        text, corrected = new, True


def _clean(text):
    text = text.lower().replace("’", "'")
    for pattern, repl in _CONTRACTIONS:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"(\w)'s\b", r"\1", text)
    text = text.replace("favourite", "favorite").replace("colour", "color")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def _stem(word):
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _content(words):
    return frozenset(_stem(w) for w in words if w not in _STOP)


def parse(text):
    stripped, _ = strip_correction(text)
    words = [w for w in _clean(stripped).split() if w not in _NOISE]
    while words and words[0] in _SUBJECTS:
        words = words[1:]
    tokens = _content(words)
    if not words:
        return Fact("other", "", frozenset(), frozenset())

    negated = False
    rest = words
    if len(rest) > 2 and rest[0] in ("do", "does") and rest[1] == "not":
        negated, rest = True, rest[2:]
    verb = _stem(rest[0])
    if verb in _VERBS:
        value = _content([w for w in rest[1:] if w not in _ARTICLES])
        return Fact("statement", ("not " if negated else "") + verb, value, tokens)

    m = _ATTR_RE.match(" ".join(words))
    if m:
        slot = " ".join(_stem(w) for w in m["slot"].split() if w not in _ARTICLES)
        return Fact("attribute", slot, _content(m["val"].split()), tokens)
    return Fact("other", "", tokens, tokens)


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def relate(new, old):
    if not new.tokens or not old.tokens:
        return Relation.UNRELATED
    if new.kind == old.kind == "attribute":
        if new.slot != old.slot:
            return Relation.UNRELATED
        return Relation.SAME if new.value == old.value else Relation.CONFLICT
    if new.kind == old.kind == "statement":
        if new.value and new.value == old.value:
            return Relation.SAME if new.slot == old.slot else Relation.RELATED
        if new.slot == old.slot and _jaccard(new.value, old.value) >= 0.5:
            return Relation.RELATED
        return Relation.UNRELATED
    score = _jaccard(new.tokens, old.tokens)
    if score == 1.0:
        return Relation.SAME
    return Relation.RELATED if score >= 0.6 else Relation.UNRELATED


def lexical_overlap(a, b):
    return _jaccard(parse(a).tokens, parse(b).tokens)


# ---------------------------------------------------------------- rendering

def _conjugate(verb):
    if verb == "have":
        return "has"
    if re.search(r"(s|sh|ch|x|o)$", verb):
        return verb + "es"
    if re.search(r"[^aeiou]y$", verb):
        return verb[:-1] + "ies"
    return verb + "s"


def to_memory_text(text):
    """Rewrite a first-person statement as a third-person memory sentence."""
    s, _ = strip_correction(text)
    s = s.strip().rstrip(".!? ").strip()
    s = s.replace("’", "'")
    s = re.sub(r"\bi'm\b", "I am", s, flags=re.I)
    s = re.sub(r"\bi've\b", "I have", s, flags=re.I)
    s = re.sub(r"^i am\b", "User is", s, flags=re.I)
    s = re.sub(r"^i (?:do not|don't) (\w+)", r"User does not \1", s, flags=re.I)
    s = re.sub(r"^i (\w+)", lambda m: "User " + _conjugate(m.group(1).lower()), s, flags=re.I)
    s = re.sub(r"^my\b", "User's", s, flags=re.I)          # "my favorite food ..." -> "User's favorite food ..."
    s = re.sub(r"\bmy\b", "their", s, flags=re.I)          # mid-sentence: "stress testing my own code"
    s = re.sub(r"\b(?:me|myself)\b", "User", s, flags=re.I)
    s = re.sub(r"\bI\b", "User", s)
    s = re.sub(r"(favou?rite [\w ]+?) (?:to be|to|as) ", r"\1 is ", s, flags=re.I)
    if not s:
        return ""
    s = s[0].upper() + s[1:]
    return s if s.startswith("User") else f"User said: {s}"
