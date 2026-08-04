from jobspy import scrape_jobs
from utils.delay import delay


def _valid_num(val):
    return val is not None and isinstance(val, (int, float)) and val == val  # NaN != NaN

def _format_salary(min_val, max_val, currency, interval):
    if not _valid_num(min_val) and not _valid_num(max_val):
        return None
    fmt = ""
    sym = _currency_sym(currency)
    if _valid_num(min_val) and _valid_num(max_val):
        fmt = _fmt_amount(min_val, sym) + " - " + _fmt_amount(max_val, sym)
    elif _valid_num(min_val):
        fmt = "From " + _fmt_amount(min_val, sym)
    elif _valid_num(max_val):
        fmt = "Up to " + _fmt_amount(max_val, sym)
    if interval and isinstance(interval, str):
        ival = interval.lower()[:3]
        if ival in ("yea", "ann"):
            fmt += "/yr"
        elif ival == "hou":
            fmt += "/hr"
        elif ival == "mon":
            fmt += "/mo"
        elif ival == "wee":
            fmt += "/wk"
    return fmt


def _currency_sym(currency):
    if not currency or not isinstance(currency, str):
        return "$"
    return {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "AED": "د.إ", "SAR": "﷼"}.get(currency.upper(), "$")


def _fmt_amount(val, sym):
    if not _valid_num(val):
        return ""
    if val >= 1000:
        return sym + str(int(val // 1000)) + "K"
    return sym + str(int(val))


_INDEED_COUNTRY_MAP = {
    "ae": "united arab emirates", "uae": "united arab emirates",
    "gb": "uk", "uk": "uk", "united kingdom": "uk",
    "us": "usa", "usa": "usa", "united states": "usa",
}

def _normalize_indeed_country(country):
    if not country:
        return "usa"
    key = country.strip().lower()
    return _INDEED_COUNTRY_MAP.get(key, key)


def scrape_indeed(roles=None, location="", country_indeed="USA", internship_mode=False, results_wanted=20, hours_old=72):
    try:
        if not roles:
            return []
        country_indeed = _normalize_indeed_country(country_indeed)
        seen_urls = set()
        all_jobs = []
        results_wanted = results_wanted * 2 if internship_mode else results_wanted
        per_role = max(1, results_wanted // len(roles))
        for i, role in enumerate(roles):
            if i > 0:
                delay(2, 4)
            try:
                # Search exactly the selected role; append "intern" in internship
                # mode unless the role already is an internship.
                role_lower = role.lower()
                if "intern" in role_lower:
                    search_terms = [role]
                elif internship_mode:
                    search_terms = [f"{role} intern", role]
                else:
                    search_terms = [role]
                for search_term in search_terms:
                    jobs_df = scrape_jobs(
                        site_name=["indeed"],
                        search_term=search_term,
                        location=location,
                        results_wanted=per_role,
                        hours_old=hours_old,
                        country_indeed=country_indeed,
                        verbose=2,
                    )
                    if jobs_df.empty:
                        continue
                    for _, row in jobs_df.iterrows():
                        title = row.get("title", "") or ""
                        url = row.get("job_url", "") or ""
                        if url in seen_urls:
                            continue
                        title_lower = title.lower()
                        if title_lower.startswith("general interest") or title_lower.startswith("internship application"):
                            continue
                        seen_urls.add(url)
                        salary = _format_salary(
                            row.get("min_amount"),
                            row.get("max_amount"),
                            row.get("currency"),
                            row.get("interval"),
                        )
                        posted = row.get("date_posted", "")
                        all_jobs.append({
                            "title": title,
                            "company": str(row.get("company", "") or ""),
                            "company_url": row.get("company_url", "") or "",
                            "location": row.get("location", "") or "",
                            "url": url,
                            "description": row.get("description", "") or "",
                            "tags": ["indeed"],
                            "salary": salary,
                            "posted_at": str(posted) if posted else "",
                        })
                    if not jobs_df.empty:
                        break
            except Exception as e:
                print(f"[INDEED] Role '{role}' failed: {e}")

        print(f"[INDEED] {len(all_jobs)} unique jobs from {len(roles)} roles")
        return all_jobs
    except Exception as e:
        print(f"[INDEED] Error: {e}")
        return []
