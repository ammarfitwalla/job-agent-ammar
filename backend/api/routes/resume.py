import os, shutil, zipfile, io, time
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from utils.json_parser import extract_json

router = APIRouter(prefix="/resume", tags=["resume"])

RESUME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")
os.makedirs(RESUME_DIR, exist_ok=True)


class ResumeKeywordsRequest(BaseModel):
    resume_text: str


class ResumeKeywordsResponse(BaseModel):
    keywords: list[dict]


EXTRACT_PROMPT = """Extract the top 20 most relevant keywords from this resume. Only include skills, tools, software, concepts, certifications, and domain expertise that explicitly appear in the resume text.

Rules:
- ONLY extract keywords that are literally written in the resume
- Do NOT guess, infer, or add related terms
- Return ONLY a JSON array of lowercase strings
- No markdown, no explanation
- Max 20 items

Resume:
{resume}"""


def _extract_text(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        import fitz
        doc = fitz.open(filepath)
        return "\n".join(doc[i].get_text() or "" for i in range(len(doc)))
    elif ext == ".docx":
        import docx
        doc = docx.Document(filepath)
        return "\n".join(p.text for p in doc.paragraphs)
    elif ext == ".txt":
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    os.makedirs(RESUME_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".docx", ".txt"):
        raise HTTPException(400, "Only PDF, DOCX, and TXT files are supported")

    ts = int(time.time())
    filename = f"resume_{ts}{ext}"
    filepath = os.path.join(RESUME_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())

    text = _extract_text(filepath)
    if not text.strip():
        raise HTTPException(400, "Could not extract any text from the file")

    return {"filename": filename, "text": text}


@router.get("/download")
async def download_resumes():
    if not os.path.isdir(RESUME_DIR) or not os.listdir(RESUME_DIR):
        raise HTTPException(404, "No resumes found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(RESUME_DIR):
            for fname in files:
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, os.path.dirname(RESUME_DIR))
                zf.write(fpath, arcname)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=resumes.zip"})


@router.delete("/storage")
async def delete_resumes():
    if os.path.isdir(RESUME_DIR):
        shutil.rmtree(RESUME_DIR)
    os.makedirs(RESUME_DIR, exist_ok=True)
    return {"message": "Resume storage cleared"}


@router.post("/keywords", response_model=ResumeKeywordsResponse)
async def extract_keywords(req: ResumeKeywordsRequest):
    try:
        from config import GROQ_API_KEY, GROQ_MODEL
        from llm.providers import GroqProvider
        prompt = EXTRACT_PROMPT.format(resume=req.resume_text)
        response = GroqProvider(api_key=GROQ_API_KEY, model=GROQ_MODEL).chat(prompt, max_tokens=500)
        print(f"[KEYWORDS] LLM response received ({len(response)} chars)")

        parsed = extract_json(response)
        if isinstance(parsed, list):
            words = parsed[:30]
        else:
            print(f"[KEYWORDS] LLM parse failed, returning empty")
            words = []
    except Exception as e:
        print(f"[KEYWORDS] Exception: {e}, returning empty")
        words = []

    keywords = [{"word": w, "suggested": True, "selected": True} for w in words]
    return ResumeKeywordsResponse(keywords=keywords)
