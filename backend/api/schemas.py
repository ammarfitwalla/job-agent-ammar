from pydantic import BaseModel
from typing import Optional


class Job(BaseModel):
    title: str
    company: str
    location: str
    url: str
    description: str
    tags: list[str] = []
    keyword_score: Optional[int] = None
    salary: Optional[str] = None
    experience_level: Optional[str] = None
    date_posted: Optional[str] = None
    company_url: Optional[str] = None
    job_level: Optional[str] = None


class ScrapeResponse(BaseModel):
    total_scraped: int
    jobs: list[Job]


class HealthResponse(BaseModel):
    status: str
    scrapers_configured: list[str]


class ScrapeRequest(BaseModel):
    search_id: str = ""
    sites: list[str] = ["indeed", "linkedin", "naukri"]
    keywords: list[str] = []
    roles: list[str] = []
    location: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    indeed_country: str = "USA"
    internship_mode: bool = False
    user_email: str = ""
    resume_filename: str = ""
    resume_text: str = ""
    scrape_limit: int = 30
    hours_old: int = 168
