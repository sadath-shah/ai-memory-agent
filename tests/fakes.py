import difflib
import itertools


class FakeBackend:
    """In-memory stand-in for mem0.Memory. Mimics its quirks: get_all/search
    default to top_k=20, and add(infer=False) stores text verbatim."""

    def __init__(self, texts=()):
        self.rows = {}
        self.fail = None            # set to an exception to simulate outages
        self._ids = itertools.count(1)
        for t in texts:
            self.add(t, user_id="u")

    def _check(self):
        if self.fail:
            raise self.fail

    def add(self, messages, *, user_id=None, infer=True, **kw):
        self._check()
        n = next(self._ids)
        rid = f"id-{n:04d}"
        self.rows[rid] = {"id": rid, "memory": messages, "user_id": user_id,
                          "created_at": f"2026-01-01T00:00:{n:02d}", "updated_at": None}
        return {"results": [{"id": rid, "memory": messages, "event": "ADD"}]}

    def get_all(self, *, filters=None, top_k=20, **kw):
        self._check()
        return {"results": list(self.rows.values())[:top_k]}

    def search(self, query, *, top_k=20, filters=None, threshold=0.1, **kw):
        self._check()
        scored = [dict(r, score=difflib.SequenceMatcher(
            None, query.lower(), r["memory"].lower()).ratio())
            for r in self.rows.values()]
        scored = [r for r in scored if r["score"] >= threshold]
        return {"results": sorted(scored, key=lambda r: -r["score"])[:top_k]}

    def update(self, memory_id, text=None, **kw):
        self._check()
        self.rows[memory_id]["memory"] = text
        return {"message": "ok"}

    def delete(self, memory_id):
        self._check()
        del self.rows[memory_id]
        return {"message": "ok"}

    def texts(self):
        return [r["memory"] for r in self.rows.values()]


class FakeLLM:
    def __init__(self, reply="LLM reply", error=None):
        self.reply, self.error, self.calls = reply, error, []

    def chat(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply
