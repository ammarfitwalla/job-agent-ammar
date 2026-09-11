# Unified LLM client — routes to provider, falls back gracefully
import time
from typing import Optional, Callable
from config import LLM_PROVIDER, \
    GROQ_API_KEY, GROQ_MODEL, GROQ_KEYWORDS_MODEL, OLLAMA_MODEL, OLLAMA_API_URL, \
    NVIDIA_API_KEY, NVIDIA_MODEL
from llm.providers import GroqProvider, OllamaProvider, NvidiaProvider
from utils.logger import log


_providers = {
    "groq": GroqProvider(api_key=GROQ_API_KEY, model=GROQ_MODEL),
    "groq_keywords": GroqProvider(api_key=GROQ_API_KEY, model=GROQ_KEYWORDS_MODEL),
    "nvidia": NvidiaProvider(api_key=NVIDIA_API_KEY, model=NVIDIA_MODEL),
    "ollama": OllamaProvider(model=OLLAMA_MODEL, api_url=OLLAMA_API_URL),
}

# Fallback order when primary provider fails
_FALLBACK_CHAIN = ["groq"]


class LLMClient:

    @staticmethod
    def chat(prompt: str, max_tokens: int = 600, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        return LLMClient._route(prompt, max_tokens, cancel_check)

    @staticmethod
    def batch_chat(prompt: str, max_tokens: int = 3000, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        """Batch variant — same routing, higher token ceiling."""
        return LLMClient._route(prompt, max_tokens, cancel_check)

    @staticmethod
    def keyword_chat(prompt: str, max_tokens: int = 4000, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        """Use the smaller/faster Groq keyword-extraction model."""
        provider = _providers.get("groq_keywords")
        if provider is None:
            return LLMClient._route(prompt, max_tokens, cancel_check)
        return provider.chat(prompt, max_tokens, cancel_check=cancel_check)

    @staticmethod
    def _usage_tokens(provider) -> str:
        usage = getattr(provider, "_last_usage", None)
        if not usage:
            return ""
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        return f"{pt}in/{ct}out"

    @staticmethod
    def _route(prompt: str, max_tokens: int, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        primary = _providers.get(LLM_PROVIDER)
        if primary is None:
            log(f"[LLM] Unknown provider '{LLM_PROVIDER}'")
            return ""

        started = time.monotonic()
        result = primary.chat(prompt, max_tokens, cancel_check=cancel_check)
        elapsed = time.monotonic() - started
        log(f"[LLM] scoring provider='{primary.name}' route='primary' ok={1 if result else 0} "
            f"elapsed={elapsed:.1f}s prompt_len={len(prompt)} resp_len={len(result)} "
            f"usage={LLMClient._usage_tokens(primary)} max_tokens={max_tokens}")
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
            started = time.monotonic()
            result = fallback.chat(prompt, max_tokens, cancel_check=cancel_check)
            elapsed = time.monotonic() - started
            log(f"[LLM] scoring provider='{fallback.name}' route='fallback' ok={1 if result else 0} "
                f"elapsed={elapsed:.1f}s prompt_len={len(prompt)} resp_len={len(result)} "
                f"usage={LLMClient._usage_tokens(fallback)} max_tokens={max_tokens}")
            if result:
                return result

        log("[LLM] all providers exhausted, returning EMPTY")
        return ""
