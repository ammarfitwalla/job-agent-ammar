# Unified LLM client — routes to provider, falls back gracefully
from config import LLM_PROVIDER
from llm.providers import CerebrasProvider, GroqProvider, OllamaProvider
from utils.logger import log


_providers = {
    "cerebras": CerebrasProvider(),
    "groq": GroqProvider(),
    "ollama": OllamaProvider(),
}

# Fallback order when primary provider fails (cerbras → groq)
_FALLBACK_CHAIN = ["cerebras", "groq"]


class LLMClient:

    @staticmethod
    def chat(prompt: str, max_tokens: int = 600) -> str:
        return LLMClient._route(prompt, max_tokens)

    @staticmethod
    def batch_chat(prompt: str, max_tokens: int = 3000) -> str:
        """Batch variant — same routing, higher token ceiling."""
        return LLMClient._route(prompt, max_tokens)

    @staticmethod
    def _route(prompt: str, max_tokens: int) -> str:
        primary = _providers.get(LLM_PROVIDER)
        if primary is None:
            log(f"[LLM] Unknown provider '{LLM_PROVIDER}'")
            return ""

        result = primary.chat(prompt, max_tokens)
        if result:
            return result

        # Fallback: try providers in chain, skip the primary
        for name in _FALLBACK_CHAIN:
            if name == LLM_PROVIDER:
                continue
            fallback = _providers.get(name)
            if fallback is None:
                continue
            log(f"[LLM] Falling back to '{name}'")
            result = fallback.chat(prompt, max_tokens)
            if result:
                return result

        return ""
