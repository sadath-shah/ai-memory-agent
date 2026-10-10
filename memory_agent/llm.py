"""Thin Ollama chat wrapper so the rest of the code (and tests) can inject a fake."""
from . import config


class LLMError(RuntimeError):
    pass


class OllamaLLM:
    def __init__(self, model=config.CHAT_MODEL, host=config.OLLAMA_URL):
        self.model = model
        self.host = host

    def chat(self, messages):
        try:
            import ollama
            response = ollama.Client(host=self.host).chat(
                model=self.model, messages=messages)
            return response["message"]["content"].strip()
        except Exception as exc:
            raise LLMError(
                f"Could not reach the local model ({exc}). Is `ollama serve` running?"
            ) from exc
