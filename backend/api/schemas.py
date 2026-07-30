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
    sites: list[str] = ["remoteok", "weworkremotely"]
    keywords: list[str] = []
    roles: list[str] = []
    adzuna_country: str = "us"
    location: str = ""
    indeed_country: str = "USA"
    internship_mode: bool = False
    user_email: str = ""
    scrape_limit: int = 30
