"""Multiple conversations on top of the existing JSON history format.

The original `conversation_history.json` (also used by the CLI) stays exactly
where it is and is exposed as the conversation id "default". New chats are
stored one file each in `<data dir>/conversations/<id>.json`, in the same
format, so `ConversationHistory` works for all of them. Nothing is migrated,
rewritten or deleted.
"""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .history import ConversationHistory

DEFAULT_ID = "default"
_ID = re.compile(r"^[0-9a-f]{32}$")
TITLE_LEN = 56


class ConversationManager:
    def __init__(self, directory, default_history):
        self.dir = Path(directory)
        self._open = {DEFAULT_ID: default_history}

    @staticmethod
    def valid(cid):
        """Only 'default' or a 32-hex id: blocks any path tricks."""
        return isinstance(cid, str) and (cid == DEFAULT_ID or bool(_ID.fullmatch(cid)))

    def new_id(self):
        return uuid.uuid4().hex

    def get(self, cid, create=False):
        if not self.valid(cid):
            raise ValueError("invalid conversation id")
        if cid in self._open:
            return self._open[cid]
        path = self.dir / f"{cid}.json"
        if not path.exists() and not create:
            return None
        history = ConversationHistory(path)
        self._open[cid] = history
        return history

    def _ids(self):
        ids = [DEFAULT_ID]
        if self.dir.is_dir():
            ids += sorted(p.stem for p in self.dir.glob("*.json") if _ID.fullmatch(p.stem))
        return ids

    @staticmethod
    def _title(history):
        for m in history.messages:
            if m.get("role") == "user" and str(m.get("content", "")).strip():
                text = " ".join(str(m["content"]).split())
                return text if len(text) <= TITLE_LEN else text[:TITLE_LEN - 1].rstrip() + "…"
        return "New chat"

    def list(self):
        items = []
        for cid in self._ids():
            history = self.get(cid)
            if history is None or not history.messages:
                continue
            try:
                stamp = history.path.stat().st_mtime
            except OSError:
                stamp = 0.0
            items.append({
                "id": cid,
                "title": self._title(history),
                "updated_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                "message_count": len(history.messages),
                "_sort": stamp,
            })
        items.sort(key=lambda i: -i["_sort"])
        for i in items:
            del i["_sort"]
        return items

    def discard_if_empty(self, cid):
        """Remove a never-used new conversation (e.g. its first send failed)."""
        history = self._open.get(cid)
        if cid == DEFAULT_ID or history is None or history.messages:
            return
        self._open.pop(cid, None)
        try:
            history.path.unlink(missing_ok=True)
        except OSError:
            pass
