import re
import requests
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES  # removed ROLES_BY_CATEGORY

GENERIC_WORDS = {"senior", "lead", "staff", "founding", "junior", "mid", "remote"}


def _sig_words(role: str) -> set:
    return {w for w in role.lower().split() if len(w) >= 3 and w not in GENERIC_WORDS}


def _role_matches(position_lower: str, role: str) -> bool:
    role_lower = role.lower()
    sig = _sig_words(role)

    # C1: Full phrase in title
    if role_lower in position_lower:
        return True

    # C2: Word overlap in title (handles compound words e.g. "fullstack" → "full" + "stack")
    if sig:
        title_words = set(re.findall(r'[a-z]{3,}', position_lower))
        matched_count = len(sig & title_words)
        threshold = len(sig) if len(sig) <= 2 else max(2, len(sig) // 2)
        if matched_count >= threshold:
            return True
        # compound-word fallback: check if any sig word is a substring of title tokens
        for tw in title_words:
            matched_count += sum(1 for w in sig if w not in title_words and w in tw)
        if matched_count >= threshold:
            return True

    return False


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
                    (role for role in active_roles if _role_matches(position_lower, role)),
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