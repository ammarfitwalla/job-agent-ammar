# How It Works

## End-to-End Workflow

```
               ┌────────────┐
               │ Upload     │ ──→ PDF/DOCX/TXT parsed → text editable in textarea
               │ Resume     │
               └─────┬──────┘
                     │  click "Extract Keywords"
                     ↓
               ┌────────────┐
               │ AI Keyword │ ──→ LLM reads resume, returns top 20 skills/tools
               │ Extraction │     (only literally-written terms, no hallucination)
               └─────┬──────┘
                     │
                     ↓
             ┌────────────────┐
             │  Search Jobs   │
             └───────┬────────┘
                     ↓
             ┌────────────────┐
             │ Scrape Boards  │ ← each role scraped individually
             │ (rate-limited) │    Adzuna + Indeed
             └───────┬────────┘
                     ↓
             ┌──────────────────────┐
             │ AI Scoring (Groq)    │ ← compares each job vs resume
             │ 3 parallel workers   │    shows results incrementally
             └───────┬──────────────┘
                     ↓
             ┌──────────────────────┐
             │ Final Score          │ ← 70% AI + 30% Keywords
             │ (sorted descending)  │    sorted by score
             └───────┬──────────────┘
                     ↓
             ┌──────────────────────┐
             │ Show Jobs            │ ← top Jobs visible
             │                      │
             └──────────────────────┘
```

## AI Keyword Extraction

When you upload a resume (PDF/DOCX/TXT) or paste text, clicking **Extract Keywords** sends it to the LLM with this instruction:

> *"Extract the top 20 most relevant keywords from this resume. Only include skills, tools, software, concepts, certifications, and domain expertise that explicitly appear in the resume text. Do NOT guess, infer, or add related terms."*

The LLM returns only keywords literally written in the resume — no hallucinated or inferred terms. You can then:
- ✅ Toggle suggested keywords on/off
- ➕ Add custom keywords manually (purple chips)
- ❌ Remove any keyword

These keywords are used for both the **keyword pre-filter** (step 1 of scoring) and the **keyword score component**.

## How Scoring Works

### 1. Keyword Score (30% weight)
```
[ job title + description + tags ] ← match against → [ selected keywords ]

Each matched keyword → +10 points  (capped at 100)
```

### 2. AI Score (70% weight)

The LLM (Groq) analyzes the job description against your resume like a hiring manager:

| Criteria | Points |
|---|---|
| Core role/domain matches your background | +40 |
| Required tools, tech & methodologies match | +20 |
| Relevant experience level | +15 |
| Secondary skills or nice-to-haves match | +10 |
| Different domain or seniority mismatch | -20 |
| Completely unrelated role | -40 |

```
Final Score = (AI Score × 0.7) + (Keyword Score × 0.3)
             ─────────────────────────────────────────
             Range: 0–100
```

### 3. What the Score Means

**It measures relevance — not probability.**

A high score means "this job is closely aligned with your resume — you should apply." It does **not** predict:
- Whether you'll be shortlisted (depends on competition, ATS filters, hiring manager preferences)
- Your chances of getting hired
- Salary fit or location feasibility

The score is there to **prioritize which jobs to spend time on**, not to guarantee outcomes.
