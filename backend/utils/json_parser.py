import re
import json
from typing import Optional, Union


def extract_json(text: str) -> Optional[Union[dict, list]]:
    """Extract JSON from an LLM response, stripping markdown fences and <think> blocks."""
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = text.strip()

    decoder = json.JSONDecoder()

    # Try parsing from each { or [ position
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            try:
                obj, _ = decoder.raw_decode(text, i)
                return obj
            except (json.JSONDecodeError, ValueError):
                continue

    return None
