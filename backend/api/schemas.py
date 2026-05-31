from pydantic import BaseModel
from typing import Optional


class Job(BaseModel):
    title: str
    company: str
    location: str
    url: str
    description: str
    tags: list[str] = []
    ai_score: Optional[int] = None
    keyword_score: Optional[int] = None
    total_score: Optional[int] = None
    reason: Optional[str] = None


class ScrapeResponse(BaseModel):
    total_scraped: int
    relevant_jobs: int
    jobs: list[Job]


class HealthResponse(BaseModel):
    status: str
    scrapers_configured: list[str]


class ScrapeRequest(BaseModel):
    sites: list[str] = ["remoteok", "weworkremotely"]
    keywords: list[str] = []
    resume_text: str = ""
    roles: list[str] = []
