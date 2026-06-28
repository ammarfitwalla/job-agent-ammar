# Unified LLM client — routes to provider, falls back gracefully
from typing import Optional, Callable
from config import LLM_PROVIDER, CEREBRAS_API_KEY, CEREBRAS_MODEL, CEREBRAS_API_URL, \
    GROQ_API_KEY, GROQ_MODEL, OLLAMA_MODEL, OLLAMA_API_URL
from llm.providers import CerebrasProvider, GroqProvider, OllamaProvider
from utils.logger import log


_providers = {
    "cerebras": CerebrasProvider(api_key=CEREBRAS_API_KEY, model=CEREBRAS_MODEL, base_url=CEREBRAS_API_URL),
    "groq": GroqProvider(api_key=GROQ_API_KEY, model=GROQ_MODEL),
    "ollama": OllamaProvider(model=OLLAMA_MODEL, api_url=OLLAMA_API_URL),
}

# Fallback order when primary provider fails (cerbras → groq)
_FALLBACK_CHAIN = ["cerebras", "groq"]


class LLMClient:

    @staticmethod
    def chat(prompt: str, max_tokens: int = 600, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        return LLMClient._route(prompt, max_tokens, cancel_check)

    @staticmethod
    def batch_chat(prompt: str, max_tokens: int = 3000, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        """Batch variant — same routing, higher token ceiling."""
        return LLMClient._route(prompt, max_tokens, cancel_check)

    @staticmethod
    def _route(prompt: str, max_tokens: int, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        primary = _providers.get(LLM_PROVIDER)
        # print(f"[DBG LLM] _route: LLM_PROVIDER='{LLM_PROVIDER}', primary={primary.name if primary else 'None'}")
        if primary is None:
            log(f"[LLM] Unknown provider '{LLM_PROVIDER}'")
            return ""

        result = primary.chat(prompt, max_tokens, cancel_check=cancel_check)
        # print(f"[DBG LLM] _route: primary '{primary.name}' returned {'SUCCESS' if result else 'EMPTY'} (len={len(result)})")
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
            # print(f"[DBG LLM] _route: trying fallback '{name}'")
            result = fallback.chat(prompt, max_tokens, cancel_check=cancel_check)
            # print(f"[DBG LLM] _route: fallback '{name}' returned {'SUCCESS' if result else 'EMPTY'} (len={len(result)})")
            if result:
                return result

        # print(f"[DBG LLM] _route: all providers exhausted, returning EMPTY")
        return ""
