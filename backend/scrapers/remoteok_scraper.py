# remoteok scraper (fixed using RemoteOK API)
import re
import requests
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES


def scrape_remoteok(roles=None):
    log("[SCRAPER] RemoteOK started")
    jobs = []

    try:
        # RemoteOK Public API
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20
        )

        data = r.json()

        # API includes metadata in first element
        postings = [job for job in data if isinstance(job, dict)]

        # Use user-selected roles, fall back to config defaults
        active_roles = roles if roles else TARGET_ROLES
        print(f"[REMOTEOK] Matching against {len(active_roles)} roles: {active_roles[:5]}...")

        # Build keyword sets from target roles
        all_keywords = set()  # all individual words from all roles
        tech_keywords = set()  # for tag matching (excludes generic words)
        for role in active_roles:
            for word in role.lower().split():
                all_keywords.add(word)
                if word not in ('engineer', 'developer', 'founding'):
                    tech_keywords.add(word)

        for job in postings:
            position_lower = (job.get('position', '') or '').lower()
            tags_lower = [t.lower() for t in (job.get('tags', []) or [])]

            matched = False

            # C1: Full target role phrase in position title (original exact match)
            for role in active_roles:
                if role.lower() in position_lower:
                    matched = True
                    break

            # C2: Individual keywords in position title
            if not matched:
                for kw in all_keywords:
                    if len(kw) < 3:
                        if re.search(r'\b' + re.escape(kw) + r'\b', position_lower):
                            matched = True
                            break
                    else:
                        if kw in position_lower:
                            matched = True
                            break

            # C3: Tech-specific keywords matched in tags (exact match)
            if not matched and set(tags_lower) & tech_keywords:
                matched = True

            if not matched:
                continue

            title = job.get("position", "").strip()
            company = job.get("company", "").strip()
            url = job.get("url", "").strip()
            location = "Remote"
            tags = list(set(t.lower() for t in (job.get("tags", []) or []) if t))

            # Description is HTML → strip tags
            desc_html = job.get("description", "")
            soup = BeautifulSoup(desc_html, "html.parser")
            description = soup.get_text().strip()

            print(f"[REMOTEOK] Matched: {title} @ {company} tags={tags[:5]}")
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "description": description,
                "tags": tags
            })

            if len(jobs) >= SCRAPE_LIMIT:
                break

        log(f"[SCRAPER] RemoteOK found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[RemoteOK ERROR] {e}")
        return []
