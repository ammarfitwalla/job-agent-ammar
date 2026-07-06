import re
from jobspy import scrape_jobs
from utils.rate_limiter import delay


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


def scrape_linkedin(roles=None, location="", internship_mode=False, results_wanted=20, hours_old=72):
    try:
        if not roles:
            return []
        loc_terms = _parse_location_terms(location)
        seen_urls = set()
        all_jobs = []
        results_wanted = results_wanted * 2 if internship_mode else results_wanted
        per_role = max(1, results_wanted // len(roles))

        for i, role in enumerate(roles):
            if i > 0:
                delay(2, 4)
            try:
                search_terms = [f"{role} intern", role] if internship_mode else [role]
                for search_term in search_terms:
                    jobs_df = scrape_jobs(
                        site_name=["linkedin"],
                        search_term=search_term,
                        location=location,
                        results_wanted=per_role,
                        hours_old=hours_old,
                        linkedin_fetch_description=True,
                        verbose=0,
                    )
                    if jobs_df.empty:
                        continue
                    for _, row in jobs_df.iterrows():
                        title = row.get("title", "") or ""
                        url = row.get("job_url", "") or ""
                        if url in seen_urls:
                            continue
                        job_location = row.get("location", "") or ""
                        if not _matches_location(job_location, loc_terms):
                            continue
                        title_lower = title.lower()
                        if title_lower.startswith("general interest") or title_lower.startswith("internship application"):
                            continue
                        seen_urls.add(url)
                        all_jobs.append({
                            "title": title,
                            "company": str(row.get("company", "") or ""),
                            "location": job_location,
                            "url": url,
                            "description": row.get("description", "") or "",
                            "tags": ["linkedin"],
                            "salary": _format_salary(row),
                        })
                    if not jobs_df.empty:
                        break
            except Exception as e:
                print(f"[LINKEDIN] Role '{role}' failed: {e}")

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
            try:
                delay(2, 4)
            except Exception:
                pass
            try:
                jobs_df = scrape_jobs(
                    site_name=["linkedin"],
                    search_term="intern",
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    linkedin_fetch_description=True,
                    verbose=0,
                )
                if not jobs_df.empty:
                    for _, row in jobs_df.iterrows():
                        title = row.get("title", "") or ""
                        url = row.get("job_url", "") or ""
                        if url in seen_urls:
                            continue
                        job_location = row.get("location", "") or ""
                        if not _matches_location(job_location, loc_terms):
                            continue
                        title_lower = title.lower()
                        if title_lower.startswith("general interest"):
                            continue
                        if not any((re.search(rf'\b{re.escape(tw)}\b', title_lower) if len(tw) <= 3 else tw in title_lower) for tw in tech_words):
                            continue
                        seen_urls.add(url)
                        all_jobs.append({
                            "title": title,
                            "company": str(row.get("company", "") or ""),
                            "location": job_location,
                            "url": url,
                            "description": row.get("description", "") or "",
                            "tags": ["linkedin"],
                            "salary": _format_salary(row),
                        })
            except Exception as e:
                print(f"[LINKEDIN] Fallback intern search failed: {e}")

        print(f"[LINKEDIN] {len(all_jobs)} unique jobs from {len(roles)} roles + fallback")
        return all_jobs
    except Exception as e:
        print(f"[LINKEDIN] Error: {e}")
        return []


def _format_salary(row):
    min_val = row.get("min_amount")
    max_val = row.get("max_amount")
    currency = row.get("currency")
    interval = row.get("interval")
    if min_val is None and max_val is None:
        return None
    try:
        sym = "$"
        if currency and isinstance(currency, str):
            sym = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(currency.upper(), "$")
        def _fmt(v):
            if v is None or (isinstance(v, float) and v != v):
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
