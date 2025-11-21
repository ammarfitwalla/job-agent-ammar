# LLM wrapper for local Ollama 7B
import requests
import json
from config import LLM_API_URL, LLM_MODEL
from utils.logger import log


class OllamaLLM:
    """
    Wrapper to interact with local Ollama model (Llama 3.1 7B).
    This replicates OpenAI ChatCompletion style for consistency.
    """

    @staticmethod
    def chat(prompt: str, max_tokens: int = 600):
        try:
            payload = {
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.25,
                "stream": False
            }

            response = requests.post(LLM_API_URL, json=payload)

            if response.status_code != 200:
                log(f"[LLM ERROR] {response.text}")
                return ""

            data = response.json()
            return data["choices"][0]["message"]["content"]

        except Exception as e:
            log(f"[LLM EXCEPTION] {str(e)}")
            return ""
