import re
import requests
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES
from match_engine.relevance_engine import role_match_count


def scrape_remoteok(roles=None):
    log("[SCRAPER] RemoteOK started")
    jobs = []
    seen_urls = set()
    active_roles = roles if roles else TARGET_ROLES

    try:
        for page in range(1, 6):
            if len(jobs) >= SCRAPE_LIMIT:
                break

            r = requests.get(
                f"https://remoteok.com/api?page={page}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20
            )
            r.raise_for_status()
            data = r.json()

            postings = [job for job in data if isinstance(job, dict) and job.get("position")]
            if not postings:
                log(f"[REMOTEOK] Page {page}: empty, stopping pagination")
                break

            log(f"[REMOTEOK] Page {page}: {len(postings)} postings")

            for job in postings:
                if len(jobs) >= SCRAPE_LIMIT:
                    break

                position_lower = (job.get("position", "") or "").lower()
                url = (job.get("url", "") or "").strip()

                if url in seen_urls:
                    continue

                matched_role = next(
                    (role for role in active_roles if role_match_count(position_lower, [role]) > 0),
                    None
                )
                if not matched_role:
                    continue

                seen_urls.add(url)

                desc_html = job.get("description", "") or ""
                description = BeautifulSoup(desc_html, "html.parser").get_text().strip()

                jobs.append({
                    "title": job.get("position", "").strip(),
                    "company": job.get("company", "").strip(),
                    "location": "Remote",
                    "url": url,
                    "description": description,
                    "tags": list({t.lower() for t in (job.get("tags", []) or []) if t}),
                    "matched_role": matched_role,
                })

                log(f"[REMOTEOK] Match '{matched_role}': {jobs[-1]['title']} @ {jobs[-1]['company']}")

            from utils.delay import delay as _rd
            _rd(1, 2)

        log(f"[SCRAPER] RemoteOK done: {len(jobs)} jobs across {page} pages")
        return jobs

    except requests.RequestException as e:
        log(f"[RemoteOK ERROR] Network: {e}")
        return []
    except Exception as e:
        log(f"[RemoteOK ERROR] {e}")
        return []