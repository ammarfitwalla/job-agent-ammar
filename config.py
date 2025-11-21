# Global configs (paths, API keys, target roles)
import os

# ==============
# LLM SETTINGS
# ==============
LLM_MODEL = "llama3.1:8b"  # Ollama model name
LLM_API_URL = "http://localhost:11434/v1/chat/completions"

# ==============
# JOB SEARCH SETTINGS
# ==============
TARGET_ROLES = [
    "AI Engineer",
    "Machine Learning Engineer",
    "Data Scientist",
    "Python Developer",
    "Founding AI Engineer",
    "ML Engineer",
]

KEYWORDS_INCLUDE = [
    "python", "tensorflow", "pytorch", "machine learning", "ml", "deep learning",
    "data science", "ai", "llm", "natural language processing", "nlp",
]

KEYWORDS_EXCLUDE = [
    "senior manager",
    "sales",
    "hr",
    "accounting",
    "non technical",
]

# Scrape limits per site
SCRAPE_LIMIT = 25

# ==============
# GOOGLE SHEETS
# ==============
GOOGLE_SHEET_NAME = "Ammar Job Tracker"

# ==============
# EMAIL SETTINGS
# ==============
SENDER_EMAIL = "ammarfitwalla@gmail.com"
DAILY_EMAIL_SUBJECT = "Daily Job Application Summary"

# ==============
# SYSTEM SETTINGS
# ==============
RESUME_PATH = "resume.txt"  # storing your resume text here
AUTO_APPLY = False  # semi-automatic (you click submit)
CHROME_PROFILE_PATH = ""     # optional browser profile path
