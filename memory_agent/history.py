"""Conversation history persisted as JSON (atomic writes, corruption-safe)."""
import json
import os
import tempfile
import time
from pathlib import Path


class ConversationHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.messages = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [m for m in data
                        if isinstance(m, dict) and "role" in m and "content" in m]
            raise ValueError("history file is not a list")
        except (OSError, ValueError):
            # Never overwrite an unreadable file: keep it aside first.
            aside = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            try:
                os.replace(self.path, aside)
            except OSError:
                pass
            return []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.messages, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def append(self, role, content):
        self.messages.append({"role": role, "content": content})
        self._save()

    def pop_last(self, role):
        """Drop the final message if it has `role` (used to undo a turn that
        never got an answer, so a retry doesn't leave a duplicate)."""
        if self.messages and self.messages[-1].get("role") == role:
            self.messages.pop()
            self._save()
            return True
        return False

    def window(self, n):
        return list(self.messages[-n:]) if n > 0 else []
