---
title: Job Agent
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Job Agent

Automated job scraper + AI scoring + web dashboard.

## How it works

1. **Scrape** — searches LinkedIn, Indeed, RemoteOK, WeWorkRemotely, Naukri, GulfTalent, EuroJobs for relevant roles
2. **Score** — uses Groq LLM to score each job against your resume on relevance, skills match, experience, and growth potential
3. **Filter** — auto-dispatches top matches via email with a dashboard for review

## Stack

- **Backend:** Python + FastAPI + Playwright + BeautifulSoup
- **Frontend:** HTML/CSS/JS dashboard served by FastAPI
- **AI:** Groq API (configurable to Ollama for local inference)
- **Scraping:** Multi-pass with rate limiting & rotating user-agents

## Configuration

Copy `config.example.py` to `config.py` and set API keys, email credentials, and search preferences. Supports both remote and location-based job searches.

## Deploy

- **Render** — auto-deploys from GitHub via `render.yaml`
- **Hugging Face Spaces** — uses root `Dockerfile`, port 7860
