import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESUME_PATH = os.path.join(_BASE, "resume.txt")

with open(_RESUME_PATH, "r", encoding="utf-8") as f:
    RESUME_TEXT = f.read()
