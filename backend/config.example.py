# Global configs — copy this to config.py and fill in your values
import os

# ==============
# LLM SETTINGS
# ==============
LLM_PROVIDER = "groq"  # "groq" or "ollama"

# Groq
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "gsk_xxx")  # Replace with your Groq API key
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

# Ollama (fallback)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/v1/chat/completions")

# ==============
# ADZUNA API
# ==============
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "your_adzuna_app_id")
ADZUNA_KEY = os.environ.get("ADZUNA_KEY", "your_adzuna_key")

# ==============
# JOB SEARCH SETTINGS
# ==============
ROLES_BY_CATEGORY = {
    "tech": [
        "AI Engineer", "Machine Learning Engineer", "Data Scientist",
        "Python Developer", "Backend Engineer", "Frontend Engineer",
        "Full Stack Developer", "Software Engineer", "DevOps Engineer",
        "Site Reliability Engineer", "Cloud Engineer", "Security Engineer",
        "Data Engineer", "Mobile Developer", "QA Engineer",
        "Game Developer", "Embedded Systems Engineer", "Systems Administrator",
        "Network Engineer", "Blockchain Developer",
    ],
    "sales": [
        "Sales Representative", "Account Executive", "Sales Manager",
        "Business Development Manager", "Customer Success Manager",
        "Account Manager", "Sales Operations Analyst",
    ],
    "media": [
        "Content Writer", "Copywriter", "Editor", "Social Media Manager",
        "Digital Marketing Specialist", "SEO Specialist", "Graphic Designer",
        "Video Editor", "Photographer", "Art Director",
    ],
    "healthcare": [
        "Doctor", "Nurse", "Pharmacist", "Medical Assistant",
        "Healthcare Administrator", "Physical Therapist", "Dentist",
    ],
    "finance": [
        "Accountant", "Financial Analyst", "Auditor", "Tax Specialist",
        "Financial Advisor", "Risk Analyst",
    ],
    "admin": [
        "Administrative Assistant", "Office Manager", "Executive Assistant",
        "Human Resources Manager", "Recruiter", "Operations Manager",
        "Project Manager",
    ],
    "legal": [
        "Lawyer", "Paralegal", "Legal Assistant", "Compliance Officer",
    ],
    "education": [
        "Teacher", "Professor", "Tutor", "Instructional Designer",
        "Curriculum Designer", "Education Administrator",
    ],
    "civil": [
        "Civil Engineer", "Structural Engineer", "Construction Manager",
        "Site Engineer", "Quantity Surveyor", "Infrastructure Engineer",
        "Urban Planner", "Surveyor", "Civil Engineering Technician",
        "Construction Project Manager",
    ],
}

# Flat list of all roles (for scraper fallback if user picks none)
TARGET_ROLES = []
for roles in ROLES_BY_CATEGORY.values():
    TARGET_ROLES.extend(roles)

KEYWORDS_INCLUDE = [
    "python", "tensorflow", "pytorch", "machine learning", "ml", "deep learning",
    "data science", "ai", "llm", "natural language processing", "nlp",
]

KEYWORDS_EXCLUDE = [
    "senior manager", "sales", "hr", "accounting",
    "non technical", "non-technical", "media", "marketing",
]

# Scrape limits per site
SCRAPE_LIMIT = 100

# ==============
# GOOGLE SHEETS
# ==============
GOOGLE_SHEET_NAME = "My Job Tracker"

# ==============
# EMAIL SETTINGS
# ==============
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "your@email.com")
DAILY_EMAIL_SUBJECT = "Daily Job Application Summary"

# ==============
# SYSTEM SETTINGS
# ==============
RESUME_PATH = "resume.txt"
AUTO_APPLY = False
CHROME_PROFILE_PATH = ""

EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USER = os.environ.get("EMAIL_USER", "your@email.com")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "your-app-password")
EMAIL_TO = os.environ.get("EMAIL_TO", "your@email.com")
