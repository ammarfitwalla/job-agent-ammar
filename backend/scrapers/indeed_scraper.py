from jobspy import scrape_jobs
from utils.rate_limiter import delay


def scrape_indeed(roles=None, location="", country_indeed="USA", results_wanted=20, hours_old=72):
    try:
        if not roles:
            return []
        seen_urls = set()
        all_jobs = []
        per_role = max(1, results_wanted // len(roles))
        for i, role in enumerate(roles):
            if i > 0:
                delay(2, 4)
            try:
                jobs_df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=role,
                    location=location,
                    results_wanted=per_role,
                    hours_old=hours_old,
                    country_indeed=country_indeed,
                    verbose=0,
                )
                if jobs_df.empty:
                    continue
                for _, row in jobs_df.iterrows():
                    url = row.get("job_url", "") or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    all_jobs.append({
                        "title": row.get("title", "") or "",
                        "company": str(row.get("company", "") or ""),
                        "location": row.get("location", "") or "",
                        "url": url,
                        "description": row.get("description", "") or "",
                        "tags": ["indeed"],
                    })
            except Exception as e:
                print(f"[INDEED] Role '{role}' failed: {e}")
        print(f"[INDEED] {len(all_jobs)} unique jobs from {len(roles)} roles")
        return all_jobs
    except Exception as e:
        print(f"[INDEED] Error: {e}")
        return []
