"""Paths and model settings. Everything runs locally; see README for the
few external-network touch points (none by default)."""
import os
from pathlib import Path

# Mem0 sends anonymous usage events to PostHog unless told otherwise. This
# must be set before `mem0` is imported anywhere.
os.environ.setdefault("MEM0_TELEMETRY", "False")

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("MEMORY_AGENT_DATA_DIR", PROJECT_DIR))

USER_ID = os.environ.get("MEMORY_AGENT_USER_ID", "sadath")
QDRANT_PATH = str(DATA_DIR / "qdrant")
HISTORY_FILE = DATA_DIR / "conversation_history.json"

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
CHAT_MODEL = "llama3.2:3b"
EMBED_MODEL = "nomic-embed-text:latest"

# How many memories we are willing to load in one call. Mem0's own default
# is 20, which silently truncates larger stores.
MAX_MEMORIES = 1000
# Minimum cosine score for a memory to be used as context in an answer.
MIN_CONTEXT_SCORE = 0.55
# A retrieved memory with no word overlap with the question only counts as relevant above this
# score. Measured on real data: true semantic matches >= 0.587, "no stored answer" noise <= 0.555.
SEMANTIC_RELEVANCE = 0.58
HISTORY_WINDOW = 10


def mem0_config(qdrant_path=QDRANT_PATH, history_db_path=None):
    cfg = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "sadath_memory",
                "embedding_model_dims": 768,
                "path": qdrant_path,
            },
        },
        "llm": {
            "provider": "ollama",
            "config": {"model": CHAT_MODEL, "ollama_base_url": OLLAMA_URL},
        },
        "embedder": {
            "provider": "ollama",
            "config": {"model": EMBED_MODEL, "ollama_base_url": OLLAMA_URL},
        },
    }
    if history_db_path:
        cfg["history_db_path"] = str(history_db_path)
    return cfg
