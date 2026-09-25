"""LLM helpers. OpenRouter is the preferred chat provider when a key is set."""

from .env import get_openrouter_key, load_dotenv, openrouter_model
from .openrouter import chat_text, chat_completion, ping

__all__ = [
    "chat_completion",
    "chat_text",
    "get_openrouter_key",
    "load_dotenv",
    "openrouter_model",
    "ping",
]
