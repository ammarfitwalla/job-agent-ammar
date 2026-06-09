import re
import requests
from utils.logger import log
from config import SCRAPE_LIMIT, ADZUNA_APP_ID, ADZUNA_KEY, ROLES_BY_CATEGORY

GENERIC_WORDS = {"senior", "lead", "staff", "founding", "junior", "mid", "remote"}


def _fmt_k(val):
    if val is None:
        return "0"
    if val >= 1000:
        return f"{int(val // 1000)}K"
    return str(int(val))

CATEGORY_QUERIES = {
    "tech": "software engineer developer data",
    "sales": "sales account executive business development",
    "media": "marketing content social media digital",
    "healthcare": "healthcare medical nurse doctor",
    "finance": "accountant finance analyst auditor",
    "admin": "administrative assistant office manager hr",
    "legal": "legal lawyer paralegal compliance",
    "education": "teacher professor education tutor",
    "civil": "civil engineer structural construction infrastructure",
}


def _sig_words(role: str) -> set:
    return {w for w in role.lower().split() if len(w) >= 3 and w not in GENERIC_WORDS}


def _role_matches(position_lower: str, role: str) -> bool:
    role_lower = role.lower()
    sig = _sig_words(role)

    if role_lower in position_lower:
        return True

    if sig:
        title_words = set(re.findall(r'[a-z]{3,}', position_lower))
        matched_count = len(sig & title_words)
        threshold = len(sig) if len(sig) <= 2 else max(2, len(sig) // 2)
        if matched_count >= threshold:
            return True
        for tw in title_words:
            matched_count += sum(1 for w in sig if w not in title_words and w in tw)
        if matched_count >= threshold:
            return True

    return False


ADZUNA_COUNTRIES = {
    "us": "United States", "gb": "United Kingdom", "ca": "Canada",
    "au": "Australia", "de": "Germany", "fr": "France",
    "nl": "Netherlands", "in": "India", "ae": "UAE",
    "sg": "Singapore", "br": "Brazil", "nz": "New Zealand",
    "za": "South Africa", "ie": "Ireland", "pl": "Poland",
    "at": "Austria", "ch": "Switzerland", "be": "Belgium",
    "my": "Malaysia", "ph": "Philippines", "qa": "Qatar",
    "sa": "Saudi Arabia", "se": "Sweden", "cn": "China",
    "hk": "Hong Kong", "lu": "Luxembourg",
}


def scrape_adzuna(roles=None, country="us", internship_mode=False):
    log(f"[SCRAPER] Adzuna started (country: {country}, internship_mode={internship_mode})")
    jobs = []
    seen_urls = set()

    if not ADZUNA_APP_ID or ADZUNA_APP_ID == "your_adzuna_app_id":
        log("[SCRAPER] Adzuna skipped: no API credentials configured")
        return jobs

    active_roles = roles if roles else []
    if not active_roles:
        return jobs

    active_cats = set()
    for cat, cat_roles in ROLES_BY_CATEGORY.items():
        if any(r in active_roles for r in cat_roles):
            active_cats.add(cat)

    queries = [CATEGORY_QUERIES.get(c, c) for c in active_cats] or ["job"]
    if internship_mode:
        queries = [f"{q} intern" for q in queries]

    for query in queries:
        if len(jobs) >= SCRAPE_LIMIT:
            break

        for page in range(1, 10):
            if len(jobs) >= SCRAPE_LIMIT:
                break

            try:
                r = requests.get(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                    params={
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_KEY,
                        "what": query,
                        "results_per_page": 50,
                        "content-type": "application/json",
                    },
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
                results = data.get("results", [])
                if not results:
                    break

                log(f"[ADZUNA] Query '{query}' page {page}: {len(results)} results")

                for job in results:
                    if len(jobs) >= SCRAPE_LIMIT:
                        break

                    title = (job.get("title") or "").strip()
                    url = (job.get("redirect_url") or "").strip()

                    if not title or url in seen_urls:
                        continue

                    position_lower = title.lower()

                    matched_role = next(
                        (role for role in active_roles if _role_matches(position_lower, role)),
                        None
                    )
                    if not matched_role:
                        continue

                    seen_urls.add(url)

                    company = ""
                    company_data = job.get("company")
                    if isinstance(company_data, dict):
                        company = (company_data.get("display_name") or "").strip()

                    location = ""
                    loc_data = job.get("location")
                    if isinstance(loc_data, dict):
                        location = (loc_data.get("display_name") or "").strip()

                    description = (job.get("description") or "").strip()
                    description = re.sub(r"<[^>]+>", "", description)

                    category = ""
                    cat_data = job.get("category")
                    if isinstance(cat_data, dict):
                        category = (cat_data.get("label") or "").strip()

                    tags = []
                    if category:
                        tags.append(category.lower())
                    salary_min = job.get("salary_min")
                    salary_max = job.get("salary_max")
                    salary = None
                    if salary_min is not None or salary_max is not None:
                        sym = "$"
                        if salary_min is not None and salary_max is not None:
                            salary = f"{sym}{_fmt_k(salary_min)} - {sym}{_fmt_k(salary_max)}/yr"
                        elif salary_min is not None:
                            salary = f"From {sym}{_fmt_k(salary_min)}/yr"
                        elif salary_max is not None:
                            salary = f"Up to {sym}{_fmt_k(salary_max)}/yr"

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": url,
                        "description": description,
                        "tags": tags,
                        "matched_role": matched_role,
                        "salary": salary,
                    })

                    log(f"[ADZUNA] Match '{matched_role}': {title} @ {company}")

            except requests.RequestException as e:
                log(f"[ADZUNA ERROR] Query '{query}' page {page}: {e}")
                break

    log(f"[SCRAPER] Adzuna done: {len(jobs)} jobs")
    return jobs
