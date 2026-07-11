import os, shutil, zipfile, io, time, json
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from utils.json_parser import extract_json
from llm.llm_client import LLMClient
from config import TARGET_ROLES

router = APIRouter(prefix="/resume", tags=["resume"])

RESUME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")
os.makedirs(RESUME_DIR, exist_ok=True)


class ResumeKeywordsRequest(BaseModel):
    resume_text: str


class ResumeKeywordsResponse(BaseModel):
    keywords: list[dict]
    suggested_roles: list[str] = []


EXTRACT_PROMPT = """You are a career coach. Given a resume, do TWO things:

PART 1: Extract the top 20 most relevant keywords (skills, tools, certifications, domain expertise) that explicitly appear in the resume text. ONLY extract what is literally written.

PART 2: Suggest 0-3 job roles from the available list that best match the candidate's OVERALL career track and domain (e.g., data analytics, healthcare, finance, engineering). Consider education, work history titles, and primary domain FIRST. Do NOT suggest roles based on a single skill keyword. ONLY suggest if highly confident (80%+). Fewer is better than wrong.

Available roles: {available_roles}

Resume:
{resume}

Return ONLY this JSON (no markdown, no explanation):
{{"keywords": ["keyword1", "keyword2", ...], "suggested_roles": ["Role 1", "Role 2"]}}
"""


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
    words = []
    suggested = []
    for attempt in range(2):
        try:
            prompt = EXTRACT_PROMPT.format(available_roles=json.dumps(TARGET_ROLES), resume=req.resume_text)
            print(f"[KEYWORDS] Calling LLM attempt {attempt+1}/2 (prompt_len={len(prompt)})")
            response = LLMClient.chat(prompt, max_tokens=2000)
            print(f"[KEYWORDS] LLM response received ({len(response)} chars)")
            if response:
                print(f"[KEYWORDS] First 200 chars: {response[:200]}")
                parsed = extract_json(response)
                if isinstance(parsed, dict):
                    words = parsed.get("keywords", [])[:30]
                    suggested = parsed.get("suggested_roles", [])[:3]
                    if words:
                        break
                    print(f"[KEYWORDS] Dict parsed but empty keywords, attempt {attempt+1}/2")
                elif isinstance(parsed, list):
                    words = parsed[:30]
                    print(f"[KEYWORDS] Legacy list format, attempt {attempt+1}/2")
                    if words:
                        break
                else:
                    print(f"[KEYWORDS] Parse failed type={type(parsed).__name__}, attempt {attempt+1}/2")
            else:
                print(f"[KEYWORDS] Empty response, attempt {attempt+1}/2")
        except Exception as e:
            print(f"[KEYWORDS] Exception on attempt {attempt+1}/2: {e}")

    keywords = [{"word": w, "suggested": True, "selected": True} for w in words]
    return ResumeKeywordsResponse(keywords=keywords, suggested_roles=suggested)
