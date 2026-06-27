# Provider classes — each wraps one LLM API behind a common interface
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Callable

from openai import OpenAI
from groq import Groq, RateLimitError
import requests

from utils.logger import log


class TokenBucket:
    """Adaptive rate limiter — token bucket refilling at `rate` tokens/second."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def acquire(self, tokens: int = 1):
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                sleep_for = (tokens - self.tokens) / self.refill_rate
            time.sleep(min(sleep_for, 0.25))


class BaseProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(self, prompt: str, max_tokens: int, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        ...

    @staticmethod
    def _backoff(attempt: int, base: float = 5.0, max_wait: float = 60.0) -> float:
        sleep = min(base * (2 ** attempt), max_wait)
        jitter = random.uniform(0, sleep * 0.25)
        return sleep + jitter


# ── Cerebras ────────────────────────────────────────────────────────────────

class CerebrasProvider(BaseProvider):
    name = "cerebras"

    def __init__(self, api_key, model, base_url, rate_limit=4):
        self._model = model
        self._bucket = TokenBucket(capacity=rate_limit, refill_rate=rate_limit / 60)
        if api_key:
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=60,
            )
        else:
            self._client = None

    def chat(self, prompt: str, max_tokens: int = 3000, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        if self._client is None:
            return ""
        for attempt in range(3):
            if cancel_check and cancel_check():
                log(f"[CEREBRAS] Cancelled during retry — aborting")
                return ""
            self._bucket.acquire()
            try:
                completion = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=max_tokens,
                    top_p=0.95,
                    stream=False,
                )
                return completion.choices[0].message.content or ""
            except Exception as e:
                err = str(e)
                log(f"[CEREBRAS ERROR] attempt {attempt+1}/3 — {err[:200]}")
                is_retryable = (
                    "timeout" in err.lower()
                    or "503" in err
                    or "queue_exceeded" in err
                    or "429" in err
                )
                if is_retryable:
                    wait = self._backoff(attempt, base=10.0, max_wait=60.0)
                    log(f"[CEREBRAS] Retrying in {wait:.1f}s (attempt {attempt+1}/3)")
                    for _ in range(int(wait / 0.5)):
                        if cancel_check and cancel_check():
                            log(f"[CEREBRAS] Cancelled during backoff — aborting")
                            return ""
                        time.sleep(0.5)
                else:
                    return ""
        return ""


# ── Groq ────────────────────────────────────────────────────────────────────

class GroqProvider(BaseProvider):
    name = "groq"

    def __init__(self, api_key, model):
        self._api_key = api_key
        self._model = model
        self._bucket = TokenBucket(capacity=28, refill_rate=28 / 60)

    def chat(self, prompt: str, max_tokens: int = 600, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        for attempt in range(3):
            if cancel_check and cancel_check():
                log(f"[GROQ] Cancelled during retry — aborting")
                return ""
            self._bucket.acquire()
            try:
                client = Groq(api_key=self._api_key, timeout=30)
                completion = client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_completion_tokens=max_tokens,
                    top_p=0.95,
                    stream=False,
                    timeout=30,
                )
                return completion.choices[0].message.content or ""
            except RateLimitError as e:
                wait = self._backoff(attempt, base=10.0, max_wait=60.0)
                log(f"[GROQ RATE LIMITED] attempt {attempt+1}/3, waiting {wait:.1f}s — {e}")
                for _ in range(int(wait / 0.5)):
                    if cancel_check and cancel_check():
                        log(f"[GROQ] Cancelled during backoff — aborting")
                        return ""
                    time.sleep(0.5)
            except Exception as e:
                log(f"[GROQ ERROR] {e}")
                return ""
        log("[GROQ] All retries exhausted")
        return ""


# ── Ollama (local fallback) ─────────────────────────────────────────────────

class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model, api_url):
        self._model = model
        self._api_url = api_url
        self._bucket = TokenBucket(capacity=28, refill_rate=28 / 60)

    def chat(self, prompt: str, max_tokens: int = 600, cancel_check: Optional[Callable[[], bool]] = None) -> str:
        if cancel_check and cancel_check():
            return ""
        self._bucket.acquire()
        try:
            payload = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.25,
                "stream": False,
            }
            resp = requests.post(self._api_url, json=payload, timeout=60)
            if resp.status_code != 200:
                log(f"[OLLAMA ERROR] {resp.text}")
                return ""
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log(f"[OLLAMA EXCEPTION] {e}")
            return ""
