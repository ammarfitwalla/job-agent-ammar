"""Naukri scraper using Naukri's internal /jobapi/v3/search API.

Naukri rejects plain sessions (HTTP 406 "recaptcha required") unless the request
carries a freshly RSA-signed `nkparam` header and a Chrome TLS fingerprint.
jobspy's built-in Naukri scraper ships a stale static token and is currently
broken upstream, so this module signs the token itself via tls-client.
"""
import base64
import time

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

from utils.delay import delay

JOB_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"
MAX_PAGES = 5
PAGE_SIZE = 20

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALrlQ+djR0RjJwBF1xuisHmdFv334MIm
K6LgzJhmLhN7B5yuEyaKoasgXQk3+OQglsOaBxEJ0j5PcTL3nbOvt80CAwEAAQ==
-----END PUBLIC KEY-----"""

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


def _generate_nkparam(page_type: str = "srp") -> str:
    timestamp = int(time.time() * 1000)
    plaintext = f"v0|{timestamp}|121_{page_type}".encode("utf-8")
    cipher = PKCS1_v1_5.new(RSA.import_key(PUBLIC_KEY))
    return base64.b64encode(cipher.encrypt(plaintext)).decode("utf-8")


def _build_session():
    try:
        import tls_client
        s = tls_client.Session(client_identifier="chrome_125")
        s.headers.update({"user-agent": UA, "accept-language": "en-US,en;q=0.9"})
        return s, True
    except ImportError:
        import requests
        s = requests.Session()
        s.headers.update({"user-agent": UA, "accept-language": "en-US,en;q=0.9"})
        return s, False


def _naukri_location(location: str) -> str:
    """Naukri's API expects a city or state name, not 'City, State, Country'.

    'Bengaluru, Karnataka, India' -> 'Bengaluru'; 'India' stays 'India'.
    """
    loc = (location or "").strip()
    if not loc:
        return ""
    return loc.split(",")[0].strip()


def _warm_up(session, location: str):
    """Hit the Naukri homepage + a search page to obtain session cookies."""
    try:
        session.get("https://www.naukri.com/", timeout_seconds=25)
    except Exception:
        try:
            session.get("https://www.naukri.com/", timeout=25)
        except Exception:
            pass
    if location.strip():
        slug = location.strip().lower().replace(" ", "-")
        try:
            session.get(f"https://www.naukri.com/cloud-engineer-jobs?l={slug}", timeout_seconds=25)
        except Exception:
            pass


def _search_headers():
    return {
        "authority": "www.naukri.com",
        "accept": "application/json",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "appid": "109",
        "systemid": "Naukri",
        "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
        "nkparam": _generate_nkparam("srp"),
        "referer": "https://www.naukri.com/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": UA,
    }


def _get(session, url, headers, params, tls):
    if tls:
        return session.get(url, headers=headers, params=params, timeout_seconds=20)
    return session.get(url, headers=headers, params=params, timeout=20)


def _parse_search_response(data: dict) -> list[dict]:
    jobs = []
    for raw in data.get("jobDetails") or []:
        if not raw.get("jobId"):
            continue
        placeholders = raw.get("placeholders") or []
        location = next((p["label"] for p in placeholders if p.get("type") == "location"), "")
        experience = next((p["label"] for p in placeholders if p.get("type") == "experience"), "")
        salary_label = next((p["label"] for p in placeholders if p.get("type") == "salary"), "")
        job_url = raw.get("jdURL") or ""
        if job_url and not job_url.startswith("http"):
            job_url = "https://www.naukri.com" + job_url
        jobs.append({
            "title": raw.get("title", ""),
            "company": raw.get("companyName", ""),
            "company_url": "",
            "location": location,
            "url": job_url,
            "description": raw.get("jobDescription") or "",
            "tags": ["naukri"],
            "salary": salary_label or None,
            "salary_text": salary_label,
            "experience_range": experience,
            "posted_at": raw.get("footerPlaceholderLabel") or "",
            "job_id": str(raw.get("jobId")),
        })
    return jobs


def _search_term(session, term, location, job_age, term_wanted, tls, seen):
    jobs = []
    got = 0
    for page in range(1, MAX_PAGES + 1):
        seo_slug = term.strip().lower().replace(".", "-dot-").replace(" ", "-").strip("-")
        loc_slug = location.strip().lower().replace(" ", "-") if location.strip() else ""
        seo_key = f"{seo_slug}-jobs-in-{loc_slug}-{page}" if loc_slug else f"{seo_slug}-jobs-{page}"
        params = {
            "noOfResults": PAGE_SIZE,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": term,
            "k": term,
            "pageNo": page,
            "jobAge": job_age,
            "nignbevent_src": "jobsearchDeskGNB",
            "seoKey": seo_key,
            "src": "jobsearchDesk",
            "latLong": "",
            "location": location,
        }
        params = {k: v for k, v in params.items() if v not in (None, "")}

        try:
            resp = _get(session, JOB_SEARCH_URL, _search_headers(), params, tls)
        except Exception as e:
            print(f"[NAUKRI] Search '{term}' page {page} failed: {e}")
            break

        if resp.status_code == 406:
            print(f"[NAUKRI] Search '{term}' rate-limited (406): {resp.text[:120]}")
            break
        if resp.status_code != 200:
            print(f"[NAUKRI] Search '{term}' page {page}: HTTP {resp.status_code}")
            break

        batch = _parse_search_response(resp.json())
        if not batch:
            break
        for j in batch:
            key = j["url"] or j["job_id"]
            if key in seen:
                continue
            seen.add(key)
            jobs.append(j)
            got += 1
        if got >= term_wanted:
            break
        delay(1, 2)
    return jobs


def scrape_naukri(roles=None, location="", internship_mode=False, results_wanted=20, hours_old=72):
    """Scrape Naukri jobs via its internal search API."""
    try:
        if not roles:
            return []

        session, tls = _build_session()
        loc = _naukri_location(location)
        _warm_up(session, loc)

        results_wanted = results_wanted * 2 if internship_mode else results_wanted
        per_role = max(1, results_wanted // len(roles))
        term_wanted = min(per_role, PAGE_SIZE * 2)
        job_age = max(1, hours_old // 24) if hours_old else 1

        seen_urls = set()
        all_jobs = []

        for i, role in enumerate(roles):
            if i > 0:
                delay(2, 4)
            role_lower = role.lower()
            if "intern" in role_lower:
                search_terms = [role]
            elif internship_mode:
                search_terms = [f"{role} intern", role]
            else:
                search_terms = [role]

            for term in search_terms:
                jobs = _search_term(session, term, loc, job_age, term_wanted, tls, seen_urls)
                all_jobs.extend(jobs)
                print(f"[NAUKRI] '{term}': {len(jobs)} new unique jobs")

        print(f"[NAUKRI] {len(all_jobs)} unique jobs from {len(roles)} roles")
        return all_jobs
    except Exception as e:
        print(f"[NAUKRI] Error: {e}")
        return []
