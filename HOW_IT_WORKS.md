# How It Works

## End-to-End Workflow

```
Upload Resume → AI Keyword Extraction → Review/Edit → Add Custom → Select Roles
                 (LLM reads resume,    Keywords       Keywords
                  extracts top 20)

                                                                                       
                                  Pick Sites → Choose State/Region
                                                                                       
                                          ↓                                             
                                                                                       
                              ┌───────────────────┐                                   
                              │   Search Jobs      │                                   
                              └────────┬──────────┘                                   
                                       ↓                                              
                              ┌───────────────────┐                                   
                              │  Scrape Job Boards │ ← Adzuna, Indeed (each role       
                              │  (rate-limited)    │   scraped individually)           
                              └────────┬──────────┘                                   
                                       ↓                                              
                              ┌───────────────────┐                                   
                              │  Raw Jobs Pool     │ ← all jobs collected              
                              └────────┬──────────┘                                   
                                       ↓                                              
                              ┌───────────────────┐                                   
                              │  Keyword Pre-Filter│ ← top 10 by keyword match         
                              └────────┬──────────┘                                   
                                       ↓                                              
                              ┌───────────────────┐                                   
                              │  AI Scoring        │ ← Groq LLM compares each          
                              │  (3 workers,       │   job vs your resume              
                              │   shows results    │                                   
                              │   incrementally)   │                                   
                              └────────┬──────────┘                                   
                                       ↓                                              
                              ┌───────────────────┐                                   
                              │  Final Score       │ ← 70% AI + 30% Keywords           
                              │  (sorted by score) │                                   
                              └────────┬──────────┘                                   
                                       ↓                                              
                              ┌───────────────────┐                                   
                              │  Show Results      │ ← top 5 visible, rest locked      
                              │  (vote to unlock)  │   until 100 votes                 
                              └───────────────────┘                                   
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
