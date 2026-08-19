"""LinkedIn scraper using HTTP requests + BeautifulSoup.
Falls back to Playwright-based scraper if HTTP fails.
"""
import re
import os
import json
import time
import random
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.delay import delay

DEBUG_DIR = os.path.join(os.path.dirname(__file__), "linkedin_debug")


class LinkedInRateLimited(Exception):
    """Raised once the rate-limit circuit trips, so callers can bail fast
    instead of paying the full retry/backoff cost on every subsequent request."""
    pass


class _RateLimitCircuit:
    """Tracks consecutive full-retry-exhaustions for a single scrape run.
    Once tripped, _request_with_retry raises immediately instead of retrying
    with escalating backoff, so we stop burning time against a wall that's
    already up."""
    def __init__(self, trip_after: int = 2):
        self.trip_after = trip_after
        self.consecutive_exhausted = 0
        self.tripped = False

    def record_success(self):
        self.consecutive_exhausted = 0

    def record_exhausted(self):
        self.consecutive_exhausted += 1
        if self.consecutive_exhausted >= self.trip_after:
            self.tripped = True


def _save_debug_response(resp: requests.Response, label: str):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_label = re.sub(r"[^\w-]", "_", label)[:40]
    path = os.path.join(DEBUG_DIR, f"{ts}_{safe_label}.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!-- URL: {resp.url} -->\n")
            f.write(f"<!-- Status: {resp.status_code} -->\n")
            f.write(f"<!-- Label: {label} -->\n")
            f.write(resp.text)
        print(f"[LINKEDIN-DEBUG] Saved {label} response to {path}")
    except Exception as e:
        print(f"[LINKEDIN-DEBUG] Failed to save debug response: {e}")


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting"
LINKEDIN_PAGE_SIZE = 25
LINKEDIN_BATCH_SIZE = 50


def _parse_location_terms(requested: str) -> list[str]:
    if not requested or not requested.strip():
        return []
    parts = [p.strip().lower() for p in requested.split(",") if p.strip()]
    terms = []
    for p in parts:
        terms.append(p)
        p_clean = p.strip(".")
        common = {
            "us": ["usa", "united states"], "usa": ["us", "united states"],
            "united states": ["us", "usa"], "america": ["us", "usa", "united states"],
            "uk": ["united kingdom", "england", "great britain"],
            "united kingdom": ["uk", "england", "great britain"],
            "england": ["uk", "united kingdom"], "britain": ["uk", "united kingdom"],
            "canada": ["ca"], "india": ["in"],
            "australia": ["au"], "germany": ["de", "deutschland"],
            "france": ["fr"], "japan": ["jp"], "china": ["cn"],
            "brazil": ["br"], "mexico": ["mx"],
            "netherlands": ["nl", "holland"], "switzerland": ["ch"],
            "singapore": ["sg"], "uae": ["united arab emirates", "dubai"],
        }
        terms.extend(common.get(p_clean, []))
    seen = set()
    return [t for t in terms if not (t in seen or seen.add(t))]


_COUNTRY_SUBDIVISIONS = {
    "us": {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
           "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
           "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
           "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
           "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"},
    "usa": {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
            "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
            "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
            "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
            "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"},
    "united states": {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
                      "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
                      "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
                      "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
                      "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc"},
    "canada": {"ab", "bc", "mb", "nb", "nl", "ns", "on", "pe", "qc", "sk", "nt", "nu", "yt"},
    "india": {"andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
              "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
              "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
              "nagaland", "odisha", "punjab", "rajasthan", "sikkim", "tamil nadu",
              "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
              "andaman and nicobar", "chandigarh", "dadra and nagar haveli", "daman and diu",
              "delhi", "jammu and kashmir", "ladakh", "lakshadweep", "puducherry"},
    "australia": {"nsw", "vic", "qld", "wa", "sa", "tas", "act", "nt"},
    "germany": {"bayern", "bavaria", "berlin", "hamburg", "nordrhein-westfalen",
                "north rhine-westphalia", "hessen", "baden-wurttemberg", "sachsen"},
    "france": {"ile-de-france", "paris", "lyon", "marseille", "toulouse", "bordeaux",
               "provence-alpes-cote d'azur", "auvergne-rhone-alpes", "nouvelle-aquitaine"},
    "united kingdom": {"england", "scotland", "wales", "northern ireland",
                       "london", "manchester", "birmingham", "edinburgh", "glasgow"},
    "uk": {"england", "scotland", "wales", "northern ireland",
           "london", "manchester", "birmingham", "edinburgh", "glasgow"},
}


def _matches_location(job_location: str, requested_terms: list[str]) -> bool:
    if not requested_terms:
        return True
    loc = job_location.lower().strip()
    if not loc:
        return False
    if loc == "remote":
        return True
    job_parts = [p.strip().lower() for p in loc.split(",")]
    for term in requested_terms:
        if re.search(rf'\b{re.escape(term)}\b', loc):
            return True
        if term in _COUNTRY_SUBDIVISIONS:
            if any(jp in _COUNTRY_SUBDIVISIONS[term] for jp in job_parts):
                return True
    return False


def _format_salary(min_val, max_val, currency, interval):
    if min_val is None and max_val is None:
        return None
    try:
        sym = "$"
        if currency and isinstance(currency, str):
            sym = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(currency.upper(), "$")
        def _fmt(v):
            if v is None:
                return ""
            if isinstance(v, (int, float)) and v >= 1000:
                return sym + str(int(v // 1000)) + "K"
            return sym + str(int(v))
        ival = (interval or "")[:3].lower() if interval and isinstance(interval, str) else ""
        period = {"yea": "/yr", "ann": "/yr", "hou": "/hr", "mon": "/mo", "wee": "/wk"}.get(ival, "")
        if min_val is not None and max_val is not None:
            return f"{_fmt(min_val)} - {_fmt(max_val)}{period}"
        elif min_val is not None:
            return f"From {_fmt(min_val)}{period}"
        elif max_val is not None:
            return f"Up to {_fmt(max_val)}{period}"
    except Exception:
        pass
    return None


def _extract_job_id(url: str) -> str:
    """Extract numeric job ID from LinkedIn job URL."""
    m = re.search(r'/jobs/view/(?:\S+-)?(\d+)$', url)
    return m.group(1) if m else ""


def _build_search_params(keywords: str, location: str, start: int = 0, hours_old: int = 0):
    params = {
        "keywords": keywords,
        "location": location,
        "start": start,
    }
    if hours_old > 0:
        if hours_old <= 24:
            params["f_TPR"] = "r86400"
        elif hours_old <= 168:
            params["f_TPR"] = "r604800"
        else:
            params["f_TPR"] = "r2592000"
    return params


def _get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.linkedin.com/jobs",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _request_with_retry(url, *, params=None, headers=None, timeout=20, max_retries=2, circuit=None):
    if circuit is not None and circuit.tripped:
        raise LinkedInRateLimited("circuit open: LinkedIn is rate-limiting us, skipping request")

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code != 429:
                if circuit is not None:
                    circuit.record_success()
                return resp
        except requests.RequestException:
            if attempt == max_retries - 1:
                raise
            delay(2 + attempt * 2, 4 + attempt * 2)
            continue
        if attempt < max_retries - 1:
            delay(2 + attempt * 2, 4 + attempt * 2)

    if circuit is not None:
        circuit.record_exhausted()
    return None


def _fetch_search_page(keywords: str, location: str, start: int = 0, hours_old: int = 0, circuit=None) -> list[dict]:
    params = _build_search_params(keywords, location, start, hours_old)
    try:
        resp = _request_with_retry(LINKEDIN_SEARCH_URL, params=params, headers=_get_headers(), timeout=20, circuit=circuit)
        if resp is None:
            print(f"[LINKEDIN] Search '{keywords}' still rate-limited after retries")
            return []
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("li")
        if not cards:
            return []
        jobs = []
        for card in cards:
            try:
                title_el = card.select_one(".base-search-card__title")
                company_el = card.select_one(".base-search-card__subtitle")
                location_el = card.select_one(".job-search-card__location")
                date_el = card.select_one("time")
                link_el = card.select_one("a.base-card__full-link")
                salary_el = card.select_one(".job-search-card__salary-info")

                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                company_url = ""
                if company_el:
                    company_link = company_el.select_one("a")
                    if company_link:
                        company_url = (company_link.get("href", "") or "").split("?")[0]
                location = location_el.get_text(strip=True) if location_el else ""
                posted_at = date_el.get("datetime", "") if date_el else ""
                url = (link_el.get("href", "") or "").split("?")[0] if link_el else ""

                if not title or not company:
                    continue

                salary_text = salary_el.get_text(strip=True) if salary_el else ""
                salary = salary_text.replace("\n", " ").strip() if salary_text else None

                jobs.append({
                    "title": title,
                    "company": company,
                    "company_url": company_url,
                    "location": location,
                    "url": url,
                    "posted_at": posted_at,
                    "salary": salary,
                    "job_id": _extract_job_id(url),
                })
            except Exception:
                continue
        return jobs
    except requests.RequestException as e:
        print(f"[LINKEDIN] Request failed for search '{keywords}': {e}")
        return []


def _fetch_linkedin_batch(search_term: str, location: str, start: int, hours_old: int, target_batch_size: int = LINKEDIN_BATCH_SIZE, circuit=None):
    jobs = []
    empty_pages = 0
    
    while len(jobs) < target_batch_size:
        page_jobs = _fetch_search_page(search_term, location, start, hours_old, circuit=circuit)
        
        if not page_jobs:
            empty_pages += 1
            if empty_pages >= 3:
                break
        else:
            empty_pages = 0
            jobs.extend(page_jobs)
            
        if page_jobs and len(page_jobs) < 5 and start > 0: 
            break
            
        start += LINKEDIN_PAGE_SIZE 
        
        if len(jobs) < target_batch_size:
            delay(1, 2)
            
    return jobs, start


def _filter_linkedin_jobs(raw_jobs: list[dict], loc_terms: list[str], seen_urls: set) -> list[dict]:
    filtered = []
    for job in raw_jobs:
        url = job.get("url", "")
        if not url or url in seen_urls:
            continue
        if not _matches_location(job.get("location", ""), loc_terms):
            continue
        title_lower = (job.get("title", "") or "").lower()
        if title_lower.startswith("general interest") or title_lower.startswith("internship application"):
            continue
        seen_urls.add(url)
        filtered.append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "company_url": job.get("company_url", ""),
            "location": job.get("location", ""),
            "url": url,
            "description": job.get("description", ""),
            "tags": ["linkedin"],
            "salary": job.get("salary"),
            "posted_at": job.get("posted_at", ""),
        })
    return filtered


def _fetch_description(job_id: str, circuit=None) -> tuple:
    """Fetch job description and job_level from LinkedIn's guest job API."""
    if not job_id:
        return "", ""
    try:
        resp = _request_with_retry(f"{LINKEDIN_JOB_API}/{job_id}", headers=_get_headers(), timeout=10, circuit=circuit)
        if resp is None:
            return "", ""
        if resp.status_code != 200:
            return "", ""
        soup = BeautifulSoup(resp.text, "lxml")
        desc_el = soup.select_one(".show-more-less-html__markup")
        description = desc_el.get_text(strip=True) if desc_el else ""
        job_level = ""
        criteria_headers = soup.select("h3.description__job-criteria-subheader")
        for header in criteria_headers:
            if "seniority" in header.get_text(strip=True).lower():
                value_el = header.find_next_sibling("span")
                if value_el:
                    job_level = value_el.get_text(strip=True)
                break
        return description, job_level
    except requests.RequestException:
        return "", ""


def scrape_linkedin(roles=None, location="", internship_mode=False, results_wanted=20, hours_old=72, fetch_descriptions=True):
    """Scrape LinkedIn jobs using HTTP requests (fast).
    Falls back to Playwright-based scraper on failure.
    Now yields batches of jobs for streaming.
    """
    try:
        yield from _scrape_http(roles, location, internship_mode, results_wanted, hours_old, fetch_descriptions)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[LINKEDIN] HTTP scraper failed: {e}, falling back to Playwright")
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(DEBUG_DIR, f"{ts}_crash.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Error: {e}\n\nTraceback:\n{tb}\n\n")
                f.write(f"Roles: {roles}\n")
                f.write(f"Location: {location}\n")
        except Exception:
            pass
            
        from scrapers.linkedin_scraper_playwright import scrape_linkedin as pw_scrape
        fallback_jobs = pw_scrape(roles, location, internship_mode, results_wanted, hours_old)
        
        # If the Playwright scraper isn't a generator yet, yield its entire result as a single batch
        if fallback_jobs:
            import types
            if isinstance(fallback_jobs, types.GeneratorType):
                yield from fallback_jobs
            else:
                yield fallback_jobs


def _scrape_http(roles=None, location="", internship_mode=False, results_wanted=20, hours_old=72, fetch_descriptions=True):
    if not roles:
        yield []
        return

    loc_terms = _parse_location_terms(location)
    seen_urls = set()
    total_yielded = 0
    circuit = _RateLimitCircuit(trip_after=2)

    results_wanted = int(results_wanted * 1.5) if internship_mode else int(results_wanted)
    per_role = max(1, results_wanted // len(roles))

    try:
        for i, role in enumerate(roles):
            if i > 0:
                delay(2, 4)

            search_terms = [f"{role} intern", role] if internship_mode else [role]

            for search_term in search_terms:
                start = 0
                collected_for_term = 0
                
                while collected_for_term < per_role:
                    raw_jobs, start = _fetch_linkedin_batch(
                        search_term, location, start, hours_old,
                        target_batch_size=LINKEDIN_BATCH_SIZE, circuit=circuit
                    )
                    
                    if not raw_jobs:
                        print(f"[LINKEDIN] search_term='{search_term}' no raw jobs returned, stopping search")
                        break

                    filtered = _filter_linkedin_jobs(raw_jobs, loc_terms, seen_urls)
                    
                    needed = per_role - collected_for_term
                    batch_to_process = filtered[:needed]
                    
                    if not batch_to_process:
                        # Even if this batch yielded no usable jobs (e.g., all duplicates), check if we hit the end
                        if len(raw_jobs) < 5 and start > LINKEDIN_PAGE_SIZE:
                            break
                        continue
                        
                    print(f"[LINKEDIN] search_term='{search_term}' yielding batch of {len(batch_to_process)} jobs")
                    
                    if fetch_descriptions:
                        enrich_descriptions(batch_to_process)
                        
                    collected_for_term += len(batch_to_process)
                    total_yielded += len(batch_to_process)
                    
                    # YIELD the enriched batch back to the router
                    yield batch_to_process

                    if len(raw_jobs) < 5 and start > 0:
                        print(f"[LINKEDIN] search_term='{search_term}' reached page limit end")
                        break
                        
                    delay(1, 2)

        if internship_mode:
            role_words = set()
            for r in roles:
                for w in r.lower().split():
                    if len(w) > 2:
                        role_words.add(w)
            tech_words = role_words | {"software", "developer", "data", "it", "support",
                                       "infrastructure", "platform", "system", "tech",
                                       "cyber", "security", "analyst", "devops",
                                       "backend", "frontend", "full stack", "fullstack",
                                       "site reliability", "sre", "cloud", "network",
                                       "database", "linux", "dev", "programmer",
                                       "quality", "qa", "test", "automation",
                                       "engineering", "application", "ml", "ai",
                                       "artificial", "machine learning", "solutions",
                                       "architecture", "technical"}
            delay(2, 4)
            fallback_jobs, _ = _fetch_linkedin_batch(
                "intern", location, 0, hours_old,
                target_batch_size=LINKEDIN_BATCH_SIZE, circuit=circuit
            )
            
            if fallback_jobs:
                fallback_batch = []
                for job in fallback_jobs:
                    url = job.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    job_location = job.get("location", "")
                    if not _matches_location(job_location, loc_terms):
                        continue
                    title_lower = job.get("title", "").lower()
                    if title_lower.startswith("general interest"):
                        continue
                    if not any((re.search(rf'\b{re.escape(tw)}\b', title_lower) if len(tw) <= 3 else tw in title_lower) for tw in tech_words):
                        continue
                        
                    seen_urls.add(url)
                    fallback_batch.append({
                        "title": job.get("title", ""),
                        "company": job.get("company", ""),
                        "company_url": job.get("company_url", ""),
                        "location": job_location,
                        "url": url,
                        "description": job.get("description", ""),
                        "tags": ["linkedin"],
                        "salary": job.get("salary"),
                        "posted_at": job.get("posted_at", ""),
                    })
                    
                if fallback_batch:
                    if fetch_descriptions:
                        enrich_descriptions(fallback_batch)
                    total_yielded += len(fallback_batch)
                    yield fallback_batch

    except LinkedInRateLimited:
        print(f"[LINKEDIN] Circuit tripped after repeated 429s — bailing early with {total_yielded} jobs collected.")

    print(f"[LINKEDIN] {total_yielded} total jobs yielded from {len(roles)} roles + fallback")


def enrich_descriptions(jobs: list[dict], max_workers: int = 3):
    """Fetch job descriptions and job_level in parallel for jobs that don't have one."""
    need_fetch = [j for j in jobs if (not j.get("description") or not j.get("job_level")) and j.get("url")]
    if not need_fetch:
        return

    circuit = _RateLimitCircuit(trip_after=3)

    def _get_desc(job):
        delay(1, 2)
        job_id = _extract_job_id(job["url"])
        if job_id:
            try:
                desc, level = _fetch_description(job_id, circuit=circuit)
            except LinkedInRateLimited:
                return
            if desc and not job.get("description"):
                job["description"] = desc
            if level and not job.get("job_level"):
                job["job_level"] = level

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_get_desc, j) for j in need_fetch]
        for _ in as_completed(futures):
            pass

    filled = sum(1 for j in need_fetch if j.get("description"))
    print(f"[LINKEDIN] Fetched {filled}/{len(need_fetch)} descriptions for current batch")