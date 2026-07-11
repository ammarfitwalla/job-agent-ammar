# Global configs — copy this to config.py and fill in your values
import os

# ==============
# LLM SETTINGS
# ==============
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "cerebras")  # "cerebras", "groq", or "ollama"

# Cerebras (primary)
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
CEREBRAS_API_URL = os.environ.get("CEREBRAS_API_URL", "https://api.cerebras.ai/v1")

# Internship Cerebras (separate key for internship mode)
INTERNSHIP_CEREBRAS_API_KEY = os.environ.get("INTERNSHIP_CEREBRAS_API_KEY", "")
INTERNSHIP_CEREBRAS_MODEL = os.environ.get("INTERNSHIP_CEREBRAS_MODEL", CEREBRAS_MODEL)
INTERNSHIP_CEREBRAS_RATE = int(os.environ.get("INTERNSHIP_CEREBRAS_RATE", "4"))

# Groq (fallback)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# Ollama (local fallback)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/v1/chat/completions")

# ==============
# ADZUNA API
# ==============
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_KEY = os.environ.get("ADZUNA_KEY", "")

# ==============
# JOB SEARCH SETTINGS
# ==============
ROLES_BY_CATEGORY = {
    "tech": [
        "AI Engineer", "Machine Learning Engineer", "Data Scientist", "Data Analyst", "Business Intelligence Analyst",
        "Python Developer", "Backend Engineer", "Frontend Engineer",
        "Full Stack Developer", "Software Engineer", "DevOps Engineer",
        "Site Reliability Engineer", "Cloud Engineer", "Security Engineer",
        "Data Engineer", "Mobile Developer", "QA Engineer",
        "Game Developer", "Embedded Systems Engineer", "Systems Administrator",
        "Network Engineer", "Blockchain Developer",
        "Database Administrator", "Technical Writer",
    ],
    "sales": [
        "Sales Representative", "Account Executive", "Sales Manager",
        "Business Development Manager", "Customer Success Manager",
        "Account Manager", "Sales Operations Analyst",
        "Sales Engineer",
    ],
    "media": [
        "Content Writer", "Copywriter", "Editor", "Social Media Manager",
        "Digital Marketing Specialist", "SEO Specialist", "Graphic Designer",
        "Video Editor", "Photographer", "Art Director",
        "Brand Manager", "PR Specialist",
    ],
    "healthcare": [
        "Doctor", "Nurse", "Pharmacist", "Medical Assistant",
        "Healthcare Administrator", "Physical Therapist", "Dentist",
        "Lab Technician", "Veterinarian", "Dental Hygienist",
        "Radiologist", "Speech Therapist",
    ],
    "finance": [
        "Accountant", "Financial Analyst", "Auditor", "Tax Specialist",
        "Financial Advisor", "Risk Analyst",
        "Investment Analyst", "Underwriter", "Credit Analyst",
    ],
    "admin": [
        "Administrative Assistant", "Office Manager", "Executive Assistant",
        "Human Resources Manager", "Recruiter", "Operations Manager",
        "Project Manager",
        "Receptionist", "Payroll Specialist", "Data Entry Clerk", "HR Generalist",
    ],
    "legal": [
        "Lawyer", "Paralegal", "Legal Assistant", "Compliance Officer",
        "Corporate Counsel", "Contract Manager", "Patent Attorney",
    ],
    "education": [
        "Teacher", "Professor", "Tutor", "Instructional Designer",
        "Curriculum Designer", "Education Administrator",
        "Special Education Teacher", "Academic Advisor", "ESL Teacher", "School Counselor",
    ],
    "civil": [
        "Civil Engineer", "Structural Engineer", "Construction Manager",
        "Site Engineer", "Quantity Surveyor", "Infrastructure Engineer",
        "Urban Planner", "Surveyor", "Civil Engineering Technician",
        "Construction Project Manager",
    ],
    "engineering": [
        "Electrical Engineer", "Mechanical Engineer", "Chemical Engineer",
        "Biomedical Engineer", "Industrial Engineer",
    ],
    "design": [
        "UI/UX Designer", "Product Designer",
    ],
    "product": [
        "Product Manager", "Business Analyst", "Scrum Master",
    ],
    "supply_chain": [
        "Supply Chain Manager", "Logistics Coordinator",
        "Procurement Specialist", "Warehouse Manager",
    ],
    "hospitality": [
        "Chef", "Restaurant Manager", "Hotel Manager",
    ],
}

# Flat list of all roles (for scraper fallback if user picks none)
TARGET_ROLES = []
for roles in ROLES_BY_CATEGORY.values():
    TARGET_ROLES.extend(roles)

KEYWORDS_INCLUDE = []

KEYWORDS_EXCLUDE = [
    "senior manager",
    "sales",
    "hr",
    "accounting",
    "non technical",
    "non-technical",
    "media",
    "marketing",
    
]

INTERNSHIP_KEYWORDS = [
    "internship", "intern", "entry level", "fresher", "graduate",
    "trainee", "junior", "apprentice", "graduate trainee",
]

# Scrape limits per site
SCRAPE_LIMIT = 1000

# ==============
# GOOGLE SHEETS 
# ==============
GOOGLE_SHEET_NAME = "Ammar Job Tracker"

# ==============
# EMAIL SETTINGS
# ==============
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "yourmail@gmail.com")
DAILY_EMAIL_SUBJECT = "Daily Job Application Summary"

# ==============
# SYSTEM SETTINGS
# ==============
RESUME_PATH = "resume.txt"
AUTO_APPLY = False
CHROME_PROFILE_PATH = ""

EMAIL_HOST=os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT=int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USER=os.environ.get("EMAIL_USER", "")
EMAIL_PASSWORD=os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO=os.environ.get("EMAIL_TO", "")

X_ENABLED = "True"
X_CLIENT_ID = os.environ.get("X_CLIENT_ID", "")
X_CLIENT_SECRET = os.environ.get("X_CLIENT_SECRET", "")
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_REFRESH_TOKEN = os.environ.get("X_REFRESH_TOKEN", "")

X_SCHEDULE = [
    {"day": "mon", "window": "09:00-11:00", "template": "promo_1"},
    {"day": "tue", "window": "10:00-12:00", "template": "feature_1"},
]

X_TEMPLATES = {
    "promo_1": "🚀 AI Job Agent scans LinkedIn, Indeed, RemoteOK & 5 more job boards — finds roles matching YOUR resume. Try it free \u2192 https://job-agent.space",
    "feature_1": "🆕 Internship mode is live! Finds intern & entry-level roles across 8 job boards with AI scoring. #internship #jobs",
}
