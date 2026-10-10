"""The agent: action routing + conversation flows shared by CLI and web UI."""
import re
from dataclasses import dataclass

from . import config
from .calculator import extract_expression, safe_calculate
from . import facts
from .facts import strip_correction
from .intents import Intent, parse_intent
from .llm import LLMError
from .memory_store import Status

MODES = ("agent", "memory", "tools")
_MEMORY_ACTIONS = {"LIST_MEMORIES", "UPDATE_MEMORY", "DELETE_MEMORY", "FORGET", "FORGET_ALL", "SAVE_MEMORY",
                   "SEARCH_MEMORY", "SEARCH_RECORDS", "COUNT_MEMORIES", "FIND_DUPLICATES"}
_INTENT_ACTION = {"LIST": "LIST_MEMORIES", "SEARCH": "SEARCH_RECORDS", "SAVE": "SAVE_MEMORY",
                  "FORGET": "FORGET", "FORGET_ALL": "FORGET_ALL", "UPDATE": "UPDATE_MEMORY",
                  "COUNT": "COUNT_MEMORIES", "DUPLICATES": "FIND_DUPLICATES"}
TOOLS_HINT = ("Tools mode currently provides the calculator. Try \"12*(3+4)\" or "
              "\"what is 2^10\". Switch to Agent for chat or Memory for your memories.")
MEMORY_HINT = ("Memory mode is for your stored memories: ask about them, tell me facts, or try "
               "\"show my memories\", \"find duplicates\", \"update memory\", \"delete memory\".")

ACTIONS = ("SAVE_MEMORY", "SEARCH_MEMORY", "CALCULATE", "FORGET", "CHAT")

_PERSONAL = (
    "my ", "i am ", "i'm ", "i like ", "i love ", "i hate ", "i dislike ",
    "i want ", "i need ", "i study ", "i work ", "i live ", "i have ",
    "i enjoy ", "i prefer ", "i play ", "i speak ", "i use ", "i own ",
    "i don't like ", "i do not like ", "i was born ",
)
_QUESTION_START = (
    "what", "who", "where", "when", "why", "how", "which", "do i", "did i",
    "am i", "is my", "are my", "can you tell", "tell me", "remind me",
    "do you remember", "what's", "whats",
)
_NO_ACCESS = re.compile(r"(don't|do not|can't|cannot|can not|unable|not able|no way)\b.{0,45}\b(access|have|retain|recall|remember|store|retrieve|see|keep)\b", re.I | re.S)
_NOTHING_FOUND = re.compile(r"\b(found nothing|nothing (?:stored|saved|relevant)|no (?:stored |saved |relevant )?(?:information|records?|memor(?:y|ies))|"
                           r"(?:don't|do not) have (?:any|that|this)|couldn't find|could not find|not stored)\b", re.I)
_QUESTION_STOP = {"what", "which", "who", "whom", "where", "when", "how", "your", "you", "user", "have", "does", "did", "tell",
                  "about", "know", "remember", "can", "are", "was", "were", "the", "and", "for", "with", "this", "that", "mine"}
_ABOUT_CONVERSATION = re.compile(r"\b(just|earlier|before|previous(?:ly)?|last|above|said|asked|mentioned|talked|discussed|"
                                r"conversation|chat|message|we were|you said|i told you)\b", re.I)
_MEMORY_TALK = re.compile(r"memor|previous (?:conversation|chat)|past (?:conversation|chat)|personal (?:info|data)|about you\b", re.I)
_FIRST_PERSON = re.compile(r"\b(i|i'm|i've|my|mine|we|our)\b", re.I)
_ABOUT_USER = re.compile(r"\b(my|i|me|mine|we|our|remember|know about me)\b", re.I)


@dataclass
class Reply:
    text: str
    action: str = "CHAT"


def decide_action(text, llm=None):
    """Rule-based routing first; the LLM only decides ambiguous messages."""
    t = " ".join(text.lower().split())
    if not t:
        return "CHAT"
    intent = parse_intent(text)                 # deterministic memory commands, no LLM involved
    if intent is not None:
        if intent.kind == "FORGET" and not intent.arg:
            return "DELETE_MEMORY"              # bare "delete memory": browse + pick one
        return _INTENT_ACTION[intent.kind]
    if extract_expression(text) is not None:
        return "CALCULATE"
    if t.startswith(("update my ", "change my ")):
        return "SAVE_MEMORY"

    body = strip_correction(t)[0]
    is_question = t.endswith("?") or t.startswith(_QUESTION_START)
    if is_question:
        return "SEARCH_MEMORY" if _ABOUT_USER.search(t) else "CHAT"
    if body.startswith(_PERSONAL):
        return "SAVE_MEMORY"

    if llm is None:
        return "CHAT"
    prompt = (
        "Classify the user's message into exactly ONE action.\n"
        "SAVE_MEMORY: user states a personal fact, preference or goal.\n"
        "SEARCH_MEMORY: user asks about something from their stored memories.\n"
        "CALCULATE: user wants arithmetic.\n"
        "FORGET: user wants something forgotten/deleted.\n"
        "CHAT: anything else.\n"
        f"Message: {text}\nReply with only the action name."
    )
    try:
        answer = llm.chat([{"role": "user", "content": prompt}]).upper()
    except LLMError:
        return "CHAT"
    for action in ACTIONS:
        if action in answer:
            # A small model over-eagerly "saves" ordinary sentences. Only
            # statements about the user may become memories.
            if action == "SAVE_MEMORY" and not _FIRST_PERSON.search(text):
                return "CHAT"
            return action
    return "CHAT"


def _numbered(items):
    return "\n".join(f"{i}. {m['memory']}" for i, m in enumerate(items, 1))


def _pick(choice, items):
    choice = choice.strip()
    if choice.isdigit() and 1 <= int(choice) <= len(items):
        return items[int(choice) - 1]
    return None


class Agent:
    def __init__(self, store, history, llm):
        self.store, self.history, self.llm = store, history, llm
        self.pending = None   # multi-step flow awaiting the user's next message

    def use_history(self, history):
        """Switch conversation. Open multi-step questions belong to the old one."""
        if history is not self.history:
            self.history = history
            self.pending = None

    # ------------------------------------------------------------ entry
    def handle(self, message, mode="agent"):
        """`mode`: agent (default routing) | memory (memory actions only) |
        tools (calculator only)."""
        message = (message or "").strip()
        if not message:
            return Reply("Please type something.", "NONE")
        if mode not in MODES:
            return Reply(f"Unknown mode '{mode}'.", "ERROR")
        self.history.append("user", message)
        try:
            reply = self._dispatch(message, mode)
        except LLMError as exc:
            self.history.pop_last("user")        # unanswered turn: keep the log clean
            return Reply(str(exc), "ERROR")
        except Exception as exc:                 # never crash the loop/server
            self.history.pop_last("user")
            return Reply(f"Something went wrong: {exc}", "ERROR")
        self.history.append("assistant", reply.text)
        return reply

    def _dispatch(self, message, mode="agent"):
        if self.pending:
            state, self.pending = self.pending, None
            # A fresh sentence (not a number / new / cancel) while a choice is
            # open just dismisses the question; nothing was changed. Route it.
            is_answer = state["type"] in ("replacement", "confirm_delete") or \
                message.strip().isdigit() or message.strip().lower() in ("new", "cancel")
            if is_answer:
                return self._continue(state, message)

        # Only the default mode may spend an LLM call on routing.
        action = decide_action(message, self.llm if mode == "agent" else None)
        if mode == "memory":
            if action == "CHAT":
                action = "SEARCH_MEMORY"
            elif action not in _MEMORY_ACTIONS:
                return Reply(MEMORY_HINT, "MODE_HINT")
        elif mode == "tools" and action != "CALCULATE":
            return Reply(TOOLS_HINT, "MODE_HINT")
        intent = parse_intent(message) or Intent("")
        if action == "LIST_MEMORIES":
            return self._list(about_me=intent.about_me)
        if action == "SEARCH_RECORDS":
            return self._search_records(intent.arg)
        if action == "COUNT_MEMORIES":
            return self._count()
        if action == "FIND_DUPLICATES":
            return self._duplicates()
        if action == "UPDATE_MEMORY":
            return self._update_flow(intent.arg)
        if action == "DELETE_MEMORY":
            return self._start_choice("delete")
        if action == "FORGET_ALL":
            return self._start_choice("delete", header="I don't delete everything in one step. "
                                      "Pick the one memory to delete (you'll be asked to confirm):")
        if action == "FORGET":
            return self._forget(intent.arg)
        if action == "SAVE_MEMORY":
            return self._save(intent.arg or message)
        if action == "CALCULATE":
            expr = extract_expression(message) or message
            return Reply(safe_calculate(expr), action)
        return self._answer(message, action)

    # ------------------------------------------------------------ memory flows
    def _list(self, about_me=False):
        try:
            memories = self.store.list()
        except Exception as exc:
            return Reply(f"I couldn't read your memories right now: {exc}", "LIST_MEMORIES")
        if not memories:
            return Reply("I don't have any memories stored yet. Tell me something like "
                         "\"remember that I like tea\" and I'll keep it.", "LIST_MEMORIES")
        n = len(memories)
        head = (f"Here's what I remember about you ({n}):" if about_me
                else f"You have {n} stored {'memory' if n == 1 else 'memories'}:")
        return Reply(head + "\n\n" + _numbered(memories), "LIST_MEMORIES")

    def _count(self):
        try:
            n = len(self.store.list())    # same source as the memory panel
        except Exception as exc:
            return Reply(f"I couldn't read your memories right now: {exc}", "COUNT_MEMORIES")
        return Reply(f"I have {n} {'memory' if n == 1 else 'memories'} stored.", "COUNT_MEMORIES")

    def _find_matches(self, topic, limit=8):
        """Memories matching `topic`. Word overlap is the primary signal (embedding
        scores for unrelated text are high, 0.45-0.6, so they can't decide alone):
        multi-word topics must share at least half their words. Strong vector hits
        (>=0.70) are added; if nothing matched by words, vector hits >=0.62 are used
        so purely semantic queries still work. Raises only if the store can't be read."""
        everything = self.store.list()
        known = {m["id"]: m for m in everything}
        try:
            scored = {h["id"]: h["score"] for h in self.store.search(topic, limit=limit * 2)}
        except Exception:
            scored = {}                  # lexical matching below still works
        wanted = facts.parse(topic).tokens or frozenset(w for w in topic.lower().split() if len(w) > 2)
        need = max(1, -(-len(wanted) // 2))          # ceil(len/2)
        lexical = [m for m in everything if len(wanted & facts.parse(m["memory"]).tokens) >= need]
        strong = [known[i] for i, sc in sorted(scored.items(), key=lambda kv: -kv[1]) if i in known and sc >= 0.70]
        picked = lexical + [m for m in strong if m not in lexical]
        if not picked:
            picked = [known[i] for i, sc in sorted(scored.items(), key=lambda kv: -kv[1]) if i in known and sc >= 0.62]
        else:                            # best vector score first within the lexical set
            picked.sort(key=lambda m: -scored.get(m["id"], 0.0))
        return picked[:limit], len(everything)

    def _search_records(self, topic):
        try:
            matches, total = self._find_matches(topic, limit=10)
        except Exception as exc:
            return Reply(f"I couldn't search your memories right now: {exc}", "SEARCH_RECORDS")
        if not matches:
            return Reply(f"I searched your memories for \"{topic}\" and found nothing matching. "
                         f"I have {total} stored in total; say \"show my memories\" to see them all.",
                         "SEARCH_RECORDS")
        n = len(matches)
        return Reply(f"Found {n} {'memory' if n == 1 else 'memories'} about \"{topic}\":\n\n"
                     + _numbered(matches), "SEARCH_RECORDS")

    def _update_flow(self, topic):
        if not topic:
            return self._start_choice("update")
        try:
            matches, _ = self._find_matches(topic, limit=8)
        except Exception as exc:
            return Reply(f"I couldn't read your memories right now: {exc}", "UPDATE_MEMORY")
        if not matches:
            return Reply(f"No memory matched \"{topic}\". Nothing was changed. "
                         "Say \"update memory\" to pick from all of them.", "UPDATE_MEMORY")
        return self._start_choice("update", matches, f"These memories match \"{topic}\". Which one do you want to update?")

    def _duplicates(self):
        same, conflicts = self.store.find_duplicate_groups()
        if not same and not conflicts:
            return Reply("No duplicate or conflicting memories found.", "FIND_DUPLICATES")
        lines = ["Review only; nothing was changed."]
        for title, groups in (("Equivalent memories", same),
                              ("Conflicting values for the same fact", conflicts)):
            if groups:
                lines.append(f"\n{title}:")
                for g in groups:
                    lines.append("- " + "  |  ".join(m["memory"] for m in g))
        lines.append("\nUse 'delete memory' or 'update memory' to fix any of these.")
        return Reply("\n".join(lines), "FIND_DUPLICATES")

    def _start_choice(self, kind, items=None, header=None):
        items = items if items is not None else self.store.list()
        if not items:
            return Reply(f"No stored memories to {kind}.", f"{kind.upper()}_MEMORY")
        self.pending = {"type": f"choose_{kind}", "items": items}
        return Reply(
            (header or f"Which memory do you want to {kind}?") + "\n"
            + _numbered(items) + "\nEnter the number, or type 'cancel'.",
            f"{kind.upper()}_MEMORY")

    def _forget(self, topic):
        """Never deletes on its own: lists candidates, then asks you to pick one and confirm."""
        if not topic:
            return self._start_choice("delete")
        try:
            matches, _ = self._find_matches(topic, limit=8)
        except Exception as exc:
            return Reply(f"I couldn't read your memories right now: {exc}. Nothing was deleted.", "FORGET")
        if not matches:
            return Reply(f"I couldn't find a memory matching \"{topic}\". Nothing was deleted. "
                         "Try \"delete memory\" to browse them all.", "FORGET")
        return self._start_choice(
            "delete", matches,
            f"These memories might match \"{topic}\". Nothing is deleted until you pick one and confirm:")

    def _save(self, message):
        res = self.store.save(message)
        if res.status is Status.NEEDS_CONFIRMATION:
            self.pending = {"type": "resolve_save", "result": res}
            why = ("This looks like a different value for a fact I already have"
                   if res.reason == "conflict" else
                   "I already have something similar")
            return Reply(
                f"{why}:\n{_numbered(res.candidates)}\n"
                f"You said: \"{res.text}\"\n"
                "Enter a number to replace that memory, 'new' to keep both, "
                "or 'cancel' to keep things as they are.", "SAVE_MEMORY")
        prefix = {
            Status.SAVED: "🧠 ", Status.UPDATED: "✏️ ", Status.DUPLICATE: "ℹ️ ",
            Status.ERROR: "⚠️ ", Status.INVALID: "⚠️ ",
        }.get(res.status, "")
        return Reply(prefix + res.message, "SAVE_MEMORY")

    def _continue(self, state, message):
        answer = message.strip()
        low = answer.lower()
        kind = state["type"]

        if low == "cancel":
            return Reply("Cancelled. No memories were changed.", "CANCEL")

        if kind == "resolve_save":
            res = state["result"]
            if low == "new":
                return Reply(self.store.add_new(res.text).message, "SAVE_MEMORY")
            chosen = _pick(answer, res.candidates)
            if chosen is None:
                return Reply("Invalid selection. No memories were changed.", "SAVE_MEMORY")
            return Reply(self.store.update(chosen["id"], res.text).message, "SAVE_MEMORY")

        if kind in ("choose_update", "choose_delete"):
            chosen = _pick(answer, state["items"])
            if chosen is None:
                return Reply("Invalid selection. No memories were changed.", "NONE")
            if kind == "choose_update":
                self.pending = {"type": "replacement", "chosen": chosen}
                return Reply(f"Current: \"{chosen['memory']}\"\n"
                             "Enter the replacement memory, or 'cancel'.", "UPDATE_MEMORY")
            self.pending = {"type": "confirm_delete", "chosen": chosen}
            return Reply(f"Delete this memory permanently?\n\"{chosen['memory']}\"\n"
                         "Type 'yes' to confirm, anything else cancels.", "DELETE_MEMORY")

        if kind == "replacement":
            return Reply(self.store.update(state["chosen"]["id"], answer).message,
                         "UPDATE_MEMORY")

        if kind == "confirm_delete":
            if low != "yes":
                return Reply("Deletion cancelled. Nothing was deleted.", "DELETE_MEMORY")
            res = self.store.delete(state["chosen"]["id"], confirmed=True)
            return Reply(res.message, "DELETE_MEMORY")

        return Reply("Cancelled.", "CANCEL")

    # ------------------------------------------------------------ RAG / chat
    @staticmethod
    def _relevant(hit, question):
        """A retrieved memory counts as relevant if it shares a content word with the
        question or scores very high; raw scores alone are too generous (0.45-0.6 for noise)."""
        words = {facts._stem(w) for w in re.findall(r"[a-z0-9]{3,}", question.lower()) if w not in _QUESTION_STOP}
        return bool(words & facts.parse(hit["memory"]).tokens) or hit.get("score", 0) >= config.SEMANTIC_RELEVANCE

    def _conflict_reply(self, hits):
        """If the retrieved memories hold different values for the same attribute
        (e.g. favorite food = biryani and = pasta), say so instead of guessing."""
        slots = {}
        for h in hits:
            fact = facts.parse(h["memory"])
            if fact.kind == "attribute" and fact.slot:
                slots[fact.slot] = fact
        if not slots:
            return None
        try:
            everything = self.store.list()
        except Exception:
            return None
        for slot in slots:
            by_value = {}
            for m in everything:
                fact = facts.parse(m["memory"])
                if fact.kind == "attribute" and fact.slot == slot and fact.value:
                    by_value.setdefault(fact.value, m["memory"])
            if len(by_value) > 1:
                lines = "\n".join(f"- {text}" for text in by_value.values())
                return ("I have conflicting records about this, so I can't be sure which is current:\n"
                        f"{lines}\n\nTell me the right one (for example \"Actually, my {slot} is ...\") "
                        "and I'll update it, or say \"delete memory\" to remove the wrong one.")
        return None

    def _answer(self, question, action):
        try:
            found = self.store.search(question, limit=5, min_score=config.MIN_CONTEXT_SCORE)
        except Exception:
            found = []  # chat still works if the memory store is unavailable
        # Loosely similar records are what a small model embroiders into "memories": keep relevant ones only.
        hits = [h for h in found if self._relevant(h, question)]
        if action == "SEARCH_MEMORY" and not hits and not _ABOUT_CONVERSATION.search(question):
            # A personal question with nothing relevant stored: say so, don't let the model guess.
            return Reply("I don't have anything stored about that. You can tell me with \"remember that ...\", "
                         "or say \"show my memories\" to see everything I know.", action)
        if hits:
            grounding = ("Memories retrieved just now for this message (stored facts):\n"
                         + "\n".join(f"- {h['memory']}" for h in hits))
        else:
            grounding = "Memories retrieved for this message: none matched."
        system = (
            "You are a personal assistant with a real long-term memory system.\n"
            f"{grounding}\n"
            "Rules:\n"
            "- You DO have access to the user's stored memories; they were searched for you above. "
            "Never say you cannot access or don't have memories. If none matched, say you found "
            "nothing stored about it.\n"
            "- Stored memories are the current truth: if one differs from something said earlier in "
            "this conversation (for example after the user corrected it), use the stored memory.\n"
            "- Keep stored facts and guesses apart: facts from the memories above are certain; "
            "anything else is general knowledge or a guess and must be labelled as such "
            "(e.g. \"I'm guessing...\"). Never invent personal details about the user.\n"
            "- If the user wants to see or change their memories, tell them to say "
            "\"show my memories\", \"remember that ...\", or \"forget ...\".\n"
            "- Do not mention IDs or scores. Be concise."
        )
        conflict = self._conflict_reply(hits)
        if conflict:                     # don't let a 3B model pick a winner between contradicting records
            return Reply(conflict, action)
        messages = [{"role": "system", "content": system}]
        messages += self.history.window(config.HISTORY_WINDOW)
        if hits and messages[-1]["role"] == "user":
            # A small model leans on the most recent text and would otherwise repeat its own
            # earlier (possibly outdated) answer, so restate the fresh memories in the last turn.
            # Prompt-only: the saved conversation keeps the user's original words.
            fresh = "\n".join(f"- {h['memory']}" for h in hits)
            messages[-1] = {"role": "user", "content": (
                f"{messages[-1]['content']}\n\n[Current stored memories, newer than anything said earlier "
                f"in this chat; answer from these:\n{fresh}]")}
        text = self.llm.chat(messages)
        relevant = [h for h in hits if self._relevant(h, question)]
        if relevant and _NOTHING_FOUND.search(text):
            # Retrieval found a relevant record but the model says there is none: trust retrieval.
            text = "Here is what I have stored that's relevant:\n\n" + _numbered(relevant)
        elif _NO_ACCESS.search(text) and _MEMORY_TALK.search(text):
            # The model denied having memory access although retrieval works.
            # Don't pass that on: answer from what was actually retrieved.
            if hits:
                text = ("Here is what I have stored that's relevant:\n\n" + _numbered(hits))
            else:
                text = ("I searched your stored memories and found nothing relevant to that. "
                        "Say \"show my memories\" to see everything I've stored.")
        return Reply(text, action)
