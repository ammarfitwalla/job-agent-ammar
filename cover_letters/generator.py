# Cover letter generation
from llm.ollama_client import OllamaLLM
from llm.prompts import cover_letter_prompt
from utils.logger import log

def generate_cover_letter(job: dict) -> str:
    """
    Generates a personalized cover letter for a single job.

    job dict must contain:
    {
        "title": job title,
        "company": company name,
        "description": job description
    }
    """
    try:
        prompt = cover_letter_prompt(
            company=job["company"],
            role=job["title"],
            jd=job["description"]
        )
        cover_letter = OllamaLLM.chat(prompt, max_tokens=400)
        return cover_letter.strip()
    except Exception as e:
        log(f"[COVER LETTER ERROR] {e}")
        return ""
