"""Memory store: safe save / update / delete / search on top of a Mem0-like
backend (anything with add/get_all/search/update/delete as in mem0.Memory)."""
from dataclasses import dataclass, field
from enum import Enum

from . import config, facts
from .facts import Relation

# Vector similarity alone never decides anything. A hit is only surfaced as a
# "maybe the same" question when it is also lexically close.
_VECTOR_HINT_SCORE = 0.80
_VECTOR_HINT_OVERLAP = 0.34


# Verbs that normally have one current value, so "Actually, I prefer X" replaces the old one.
EXCLUSIVE_VERBS = {"prefer", "live", "work", "study"}


class Status(str, Enum):
    SAVED = "saved"
    DUPLICATE = "duplicate"
    UPDATED = "updated"
    DELETED = "deleted"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    ERROR = "error"


@dataclass
class Result:
    status: Status
    message: str
    memory_id: str | None = None
    text: str | None = None
    reason: str | None = None            # "conflict" | "similar" (NEEDS_CONFIRMATION)
    candidates: list = field(default_factory=list)
    correction: bool = False

    @property
    def ok(self):
        return self.status in (Status.SAVED, Status.UPDATED, Status.DELETED)


class MemoryStore:
    def __init__(self, backend, user_id=config.USER_ID):
        self.backend = backend
        self.user_id = user_id

    # ------------------------------------------------------------ reading
    @staticmethod
    def _rows(response):
        rows = response.get("results", []) if isinstance(response, dict) else response
        return rows or []

    def list(self):
        """All memories, in a stable order (oldest first, then id)."""
        response = self.backend.get_all(
            filters={"user_id": self.user_id}, top_k=config.MAX_MEMORIES)
        items = [
            {"id": r["id"], "memory": r["memory"],
             "created_at": r.get("created_at") or "",
             "updated_at": r.get("updated_at") or ""}
            for r in self._rows(response) if r.get("id") and r.get("memory")
        ]
        items.sort(key=lambda r: (r["created_at"], r["id"]))
        return items

    def find_duplicate_groups(self):
        """Read-only report: groups of equivalent memories and groups holding
        different values for the same attribute. Changes nothing."""
        items = self.list()
        parsed = [facts.parse(i["memory"]) for i in items]
        seen, same_groups, conflict_groups = set(), [], []
        for kind, out in ((Relation.SAME, same_groups), (Relation.CONFLICT, conflict_groups)):
            seen.clear()
            for i, a in enumerate(items):
                if i in seen:
                    continue
                group = [j for j in range(i, len(items))
                         if j not in seen and (j == i or facts.relate(parsed[i], parsed[j]) is kind)]
                if kind is Relation.CONFLICT:
                    group = [j for j in group if j == i or parsed[j].kind == "attribute"]
                    # drop members equivalent to the anchor; keep distinct values
                    group = [j for j in group
                             if j == i or facts.relate(parsed[i], parsed[j]) is Relation.CONFLICT]
                if len(group) > 1:
                    seen.update(group)
                    out.append([items[j] for j in group])
        return same_groups, conflict_groups

    def search(self, query, limit=5, min_score=0.0):
        if not query.strip():
            return []
        response = self.backend.search(
            query, filters={"user_id": self.user_id}, top_k=limit)
        hits = [
            {"id": r.get("id"), "memory": r.get("memory", ""),
             "score": r.get("score") or 0.0}
            for r in self._rows(response) if r.get("memory")
        ]
        hits = [h for h in hits if h["score"] >= min_score]
        return sorted(hits, key=lambda h: -h["score"])[:limit]

    # ------------------------------------------------------------ saving
    def save(self, user_text):
        """Save a statement unless it duplicates, corrects or resembles an
        existing memory. Never overwrites/deletes without a clear match."""
        user_text = (user_text or "").strip()
        proposed = facts.to_memory_text(user_text)
        if not proposed:
            return Result(Status.INVALID, "There is nothing to save.")
        correction = facts.strip_correction(user_text)[1]
        new_fact = facts.parse(proposed)

        try:
            existing = self.list()
        except Exception as exc:
            return Result(Status.ERROR, f"Could not read memories: {exc}")

        same, conflicts, related = [], [], []
        for item in existing:
            rel = facts.relate(new_fact, facts.parse(item["memory"]))
            if rel is Relation.SAME:
                same.append(item)
            elif rel is Relation.CONFLICT:
                conflicts.append(item)
            elif rel is Relation.RELATED:
                related.append(item)

        if correction and not same and not conflicts and new_fact.kind == "statement" \
                and new_fact.slot in EXCLUSIVE_VERBS:
            conflicts = [i for i in existing
                         if (f := facts.parse(i["memory"])).kind == "statement" and f.slot == new_fact.slot]

        if same:
            return Result(Status.DUPLICATE,
                          f"Already stored: \"{same[0]['memory']}\". Nothing was added.",
                          memory_id=same[0]["id"], text=same[0]["memory"])

        if conflicts:
            if correction and len(conflicts) == 1:
                return self.update(conflicts[0]["id"], proposed, _correction=True)
            return Result(Status.NEEDS_CONFIRMATION, "", text=proposed,
                          reason="conflict", candidates=conflicts,
                          correction=correction)

        if not related:
            related = self._vector_hints(proposed, existing)
        if related:
            return Result(Status.NEEDS_CONFIRMATION, "", text=proposed,
                          reason="similar", candidates=related,
                          correction=correction)

        return self.add_new(proposed)

    def _vector_hints(self, proposed, existing):
        try:
            hits = self.search(proposed, limit=5, min_score=_VECTOR_HINT_SCORE)
        except Exception:
            return []  # the hint is optional; structural checks already ran
        known = {m["id"]: m for m in existing}
        return [known[h["id"]] for h in hits
                if h["id"] in known
                and facts.lexical_overlap(proposed, h["memory"]) >= _VECTOR_HINT_OVERLAP]

    def add_new(self, text):
        """Add verbatim (no LLM rewriting, so what we compared is what we store)."""
        text = (text or "").strip()
        if not text:
            return Result(Status.INVALID, "There is nothing to save.")
        try:
            response = self.backend.add(text, user_id=self.user_id, infer=False)
            rows = self._rows(response)
            if not rows:
                return Result(Status.ERROR, "The memory store did not save it.")
            return Result(Status.SAVED, f"Saved: \"{text}\"",
                          memory_id=rows[0].get("id"), text=text)
        except Exception as exc:
            return Result(Status.ERROR, f"Could not save memory: {exc}")

    # ------------------------------------------------- update / delete
    def _find(self, memory_id):
        for item in self.list():
            if item["id"] == memory_id:
                return item
        return None

    def update(self, memory_id, new_text, _correction=False):
        new_text = (new_text or "").strip()
        if not new_text:
            return Result(Status.INVALID, "The replacement text is empty. Nothing changed.")
        try:
            current = self._find(memory_id)
            if current is None:
                return Result(Status.NOT_FOUND, "That memory no longer exists.")
            self.backend.update(memory_id, text=new_text)
        except Exception as exc:
            return Result(Status.ERROR, f"Could not update memory: {exc}")
        return Result(Status.UPDATED,
                      f"Updated: \"{current['memory']}\" -> \"{new_text}\"",
                      memory_id=memory_id, text=new_text, correction=_correction)

    def delete(self, memory_id, confirmed=False):
        """Deletes exactly one memory by id; `confirmed` must be True."""
        if not confirmed:
            return Result(Status.INVALID, "Deletion requires confirmation. Nothing was deleted.")
        try:
            current = self._find(memory_id)
            if current is None:
                return Result(Status.NOT_FOUND, "That memory no longer exists.")
            self.backend.delete(memory_id)
        except Exception as exc:
            return Result(Status.ERROR, f"Could not delete memory: {exc}")
        return Result(Status.DELETED, f"Deleted: \"{current['memory']}\"",
                      memory_id=memory_id, text=current["memory"])


def build_default_store():
    """Real Mem0 + local Qdrant store (imports mem0 lazily; it is slow)."""
    import os
    from mem0 import Memory
    # With a custom data dir (tests, demos) keep Mem0's own audit DB there too,
    # instead of writing to the real ~/.mem0.
    history_db = (config.DATA_DIR / "mem0_history.db"
                  if "MEMORY_AGENT_DATA_DIR" in os.environ else None)
    return MemoryStore(Memory.from_config(config.mem0_config(history_db_path=history_db)))
