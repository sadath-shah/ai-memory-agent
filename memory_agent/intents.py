"""Deterministic recognition of memory commands.

These requests must never depend on a language model deciding whether it "has
access" to memory, so they are matched with plain patterns and routed to the
real store functions. Anything not matched here falls through to the normal
routing / chat path.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    kind: str            # LIST | SEARCH | SAVE | FORGET | FORGET_ALL | UPDATE | COUNT | DUPLICATES
    arg: str = ""        # topic / fact text
    about_me: bool = False


_MEM = r"(?:memories|memory|memorys|memorie|facts)"
_LEAD = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|so|well|pls|please|kindly|can you|can u|could you|could u|would you|"
    r"would u|will you|can i|could i|may i|let me|i want to|i wanna|i would like to|i'd like to|"
    r"i want you to|i need you to|go ahead and|just)\b[\s,:-]*)+", re.I)
_SLANG = [(r"\bu\b", "you"), (r"\bur\b", "your"), (r"\bpls\b", "please"), (r"\bplz\b", "please")]

_SHOW_VERBS = r"(?:show|list|display|view|see|print|give|tell|bring up|pull up|open|read|get|fetch|check|dump)"
_FIND_VERBS = r"(?:search|find|look up|look through|look for|look in|lookup|query|scan)"
_TOPIC = re.compile(r"\b(?:about|on|regarding|related to|concerning|for|mentioning|containing|with)\s+(?P<t>.+)$")
_ME_WORDS = {"me", "myself", "my", "i", "us", "you", "everything", "anything", "all"}


def normalize(text):
    t = " ".join((text or "").lower().replace("’", "'").split())
    for pat, rep in _SLANG:
        t = re.sub(pat, rep, t)
    t = _LEAD.sub("", t)
    return t.strip(" \t.!?,;:")


def _clean_topic(topic):
    topic = re.sub(r"^(?:the |my |any |all |that |this )+", "", topic.strip(" .!?,;:\"'"))
    topic = re.sub(r"\b(?:please|thanks|thank you)$", "", topic).strip(" .!?,;:\"'")
    return topic


def _topic_or_list(rest, about_me=False):
    m = _TOPIC.search(rest)
    topic = _clean_topic(m.group("t")) if m else ""
    if not topic or topic in _ME_WORDS:
        return Intent("LIST", about_me=about_me)
    return Intent("SEARCH", topic)


def parse_intent(text):
    """Return an Intent for memory commands, else None."""
    t = normalize(text)
    if not t:
        return None

    # --- count / housekeeping reports
    if re.search(rf"\bhow many (?:{_MEM}|things do you (?:remember|know))\b", t):
        return Intent("COUNT")
    if re.fullmatch(rf"(?:find|show|list|check)(?: for)?(?: me)?(?: the)? (?:duplicate|duplicates|duplicate {_MEM})", t):
        return Intent("DUPLICATES")

    # --- "what do you remember / know about me"
    m = re.fullmatch(r"what (?:do|did|have|can|would) you (?:remember|know|recall|learn|learned|store|stored|save|saved|"
                     r"remembered|memorized|memorised)(?: so far)?(?: about (?P<t>.+))?", t)
    if m:
        topic = _clean_topic(re.sub(r"\s+so far$", "", m.group("t") or ""))
        return Intent("LIST", about_me=True) if not topic or topic in _ME_WORDS else Intent("SEARCH", topic)
    if re.fullmatch(r"(?:(?:tell|show|give|list)(?: me)? )?(?:everything|all) (?:that )?you (?:remember|know)(?: about me)?", t) or \
       re.fullmatch(r"tell me what you (?:remember|know)(?: about me)?", t) or \
       re.fullmatch(r"do you (?:remember|know) anything(?: about me)?", t):
        return Intent("LIST", about_me=True)
    if re.fullmatch(rf"what (?:are |is )?(?:all )?(?:my |the |your )?(?:stored |saved )?{_MEM}(?: do you (?:have|know))?"
                    rf"(?: stored| saved)?(?: about me)?", t) or \
       re.fullmatch(rf"what {_MEM} (?:do you have|have you (?:stored|saved|kept))(?: about me)?(?: stored| saved)?", t):
        return Intent("LIST", about_me=True)

    # --- delete / forget (never bulk, never a blind best match)
    if re.fullmatch(r"(?:forget|delete|remove|erase|wipe|clear)(?: out)? (?:everything(?: you (?:know|remember))?|"
                    r"all(?: of)?(?: my| the| your)?(?: memories| facts)?|"
                    r"(?:my |the |your )(?:entire |whole |all )?(?:memories|facts))(?: about me)?", t):
        return Intent("FORGET_ALL")
    if re.fullmatch(rf"(?:delete|remove|forget|erase)(?: a| one| the| my)? ?(?:memory|memories|memorys)", t):
        return Intent("FORGET")
    m = re.match(rf"^(?:forget|delete|remove|erase)\s+(?:the |my |your )?(?:{_MEM}\s+(?:about|of|on|regarding|that)\s+|"
                 rf"(?:about|that)\s+)?(?P<t>.+)$", t)
    if m:
        topic = _clean_topic(re.sub(rf"\s+from (?:my |your |the )?{_MEM}$", "", m.group("t")))
        return Intent("FORGET", topic or "")

    # --- update / edit
    m = re.fullmatch(rf"(?:update|edit|change|modify|correct|fix)(?: a| one| the| my| some)? ?{_MEM}"
                     rf"(?:\s+(?:about|on|regarding|of|that)\s+(?P<t>.+))?", t)
    if m:
        return Intent("UPDATE", _clean_topic(m.group("t") or ""))

    # --- save (extracted from the original text so the fact keeps its casing)
    raw = _LEAD.sub("", " ".join((text or "").replace("\u2019", "'").split()))
    m = re.match(r"(?i)^(?:add (?:this )?to (?:my )?memory|save this(?: as a memory| to memory| memory)?|make a note|"
                 r"remember|memorize|memorise|note|save|store|keep in mind|don't forget|do not forget)"
                 r"(?:\s+(?:that|this|down that|down|about me that))?\s*[:,\-]?\s+(?P<f>.{3,})$", raw)
    if m and not re.match(r"(?i)^(?:how|when|why|what|where|if|whether)\b", m.group("f")):
        return Intent("SAVE", m.group("f").strip(" :,-").rstrip(" ."))

    # --- show / search verbs aimed at memory
    m = re.match(rf"^(?:{_SHOW_VERBS}|{_FIND_VERBS})\b(?P<rest>.*)$", t)
    if m and re.search(rf"\b{_MEM}\b", m.group("rest")) and not re.search(r"\b(?:delete|remove|forget)\b", t):
        verb_is_find = re.match(rf"^{_FIND_VERBS}\b", t) is not None
        rest = m.group("rest")
        intent = _topic_or_list(rest, about_me=False)
        if intent.kind == "LIST" and verb_is_find and not re.fullmatch(rf"\s*(?:me )?(?:all )?(?:in )?(?:my |the |your )?(?:stored |saved )?{_MEM}\s*", rest):
            # "search my memories coding" -> topic is whatever follows the memory word
            tail = re.split(rf"\b{_MEM}\b", rest, maxsplit=1)[1].strip()
            if tail:
                return Intent("SEARCH", _clean_topic(tail))
        return intent
    return None
