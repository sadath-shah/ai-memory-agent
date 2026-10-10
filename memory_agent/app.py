"""Wiring: build the real agent from config."""
from . import config
from .agent import Agent
from .history import ConversationHistory
from .llm import OllamaLLM
from .memory_store import build_default_store


def build_agent():
    return Agent(build_default_store(),
                 ConversationHistory(config.HISTORY_FILE),
                 OllamaLLM())
