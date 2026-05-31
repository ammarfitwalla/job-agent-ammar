# Unified LLM client — Groq primary, Ollama fallback
import time
from groq import Groq, RateLimitError
import requests
from config import (
    LLM_PROVIDER,
    GROQ_API_KEY, GROQ_MODEL,
    OLLAMA_MODEL, OLLAMA_API_URL,
)
from utils.logger import log


class LLMClient:

    @staticmethod
    def chat(prompt: str, max_tokens: int = 600) -> str:
        if LLM_PROVIDER == "groq" and GROQ_API_KEY:
            return LLMClient._groq_chat(prompt, max_tokens)
        return LLMClient._ollama_chat(prompt, max_tokens)

    # ---------- Groq ----------

    @staticmethod
    def _groq_chat(prompt: str, max_tokens: int, retries: int = 3) -> str:
        for attempt in range(retries):
            try:
                client = Groq(api_key=GROQ_API_KEY, timeout=30)
                completion = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_completion_tokens=max_tokens,
                    top_p=0.95,
                    stream=False,
                    timeout=30,
                )
                return completion.choices[0].message.content or ""
            except RateLimitError as e:
                wait = (attempt + 1) * 10
                log(f"[GROQ RATE LIMITED] attempt {attempt+1}/{retries}, waiting {wait}s — {e}")
                time.sleep(wait)
            except Exception as e:
                log(f"[GROQ ERROR] {e}")
                return ""
        log("[GROQ] All retries exhausted")
        return ""

    # ---------- Ollama (fallback) ----------

    @staticmethod
    def _ollama_chat(prompt: str, max_tokens: int) -> str:
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.25,
                "stream": False,
            }
            resp = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
            if resp.status_code != 200:
                log(f"[OLLAMA ERROR] {resp.text}")
                return ""
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log(f"[OLLAMA EXCEPTION] {e}")
            return ""
