"""Job-link resolver: paste a job URL, get a best-effort company + title.

Option 2 scope (domain-map only, no scraping). The resolver never hard-fails —
worst case it returns a company hint from the URL domain and lets the user
override manually. Scrape enhancement can be added later without touching
schema or frontend.
"""
import difflib
import re
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import get_distinct_companies, get_referrers_by_company
from utils.rate_limiter import check_rate_limit

router = APIRouter(prefix="/api/referrals", tags=["referrals"])

# Anonymous (no email) URL resolution is rate-limited by IP.
_RESOLVE_RATE = 15
_RESOLVE_WINDOW = 60

# company -> list of domain/slug aliases used in job-board URLs
_HINT_ALIASES = {
    "Google": ["google", "googlecareers"],
    "Meta": ["meta", "metacareers"],
    "Apple": ["apple", "applecareers"],
    "Amazon": ["amazon", "amazoncareers", "amazon.jobs"],
    "Microsoft": ["microsoft", "microsoftcareers"],
    "Netflix": ["netflix", "jobs.netflix"],
    "Tesla": ["tesla", "teslacareers"],
    "Nvidia": ["nvidia", "nvidia.jobs"],
    "Adobe": ["adobe", "adobecareers"],
    "Salesforce": ["salesforce", "salesforcecareers"],
    "Oracle": ["oracle", "oraclecareers"],
    "IBM": ["ibm", "ibmcareers"],
    "Intel": ["intel", "intelcareers"],
    "Cisco": ["cisco", "ciscocareers"],
    "Uber": ["uber", "ubercareers"],
    "Airbnb": ["airbnb", "airbnbcareers"],
    "Stripe": ["stripe", "stripecareers"],
    "Square": ["square", "squareup", "block"],
    "PayPal": ["paypal", "paypalcareers"],
    "Shopify": ["shopify", "shopifycareers"],
    "Spotify": ["spotify", "spotifycareers"],
    "LinkedIn": ["linkedin", "linkedincareers"],
    "Snap": ["snap", "snapcareers"],
    "Pinterest": ["pinterest", "pinterestcareers"],
    "Reddit": ["reddit", "redditinc"],
    "Zoom": ["zoom", "zoomcareers"],
    "Slack": ["slack", "slackhq"],
    "Notion": ["notion", "notionhq"],
    "Figma": ["figma", "figmacareers"],
    "Atlassian": ["atlassian", "atlassiancareers"],
    "GitLab": ["gitlab", "gitlabcareers"],
    "GitHub": ["github", "githubcareers"],
    "Datadog": ["datadog", "datadoghq"],
    "Snowflake": ["snowflake", "snowflakecareers"],
    "MongoDB": ["mongodb", "mongodbcareers"],
    "Cloudflare": ["cloudflare", "cloudflarecareers"],
    "Twilio": ["twilio", "twiliocareers"],
    "Okta": ["okta", "oktacareers"],
    "Palantir": ["palantir", "palantircareers"],
    "Coinbase": ["coinbase", "coinbasecareers"],
    "Robinhood": ["robinhood", "robinhoodcareers"],
    "Brex": ["brex", "brexcareers"],
    "Airtable": ["airtable", "airtablecareers"],
    "Asana": ["asana", "asanacareers"],
    "Canva": ["canva", "canvacareers"],
    "Vercel": ["vercel", "vercelcareers"],
    "Supabase": ["supabase", "supabasecareers"],
    "Notion": ["notion", "notionhq"],
    "Loom": ["loom", "loomcareers"],
    "Figma": ["figma", "figmacareers"],
    "Instacart": ["instacart", "instacartcareers"],
    "DoorDash": ["doordash", "doordashcareers"],
    "Lyft": ["lyft", "lyftcareers"],
    "Airbnb": ["airbnb", "airbnbcareers"],
    "JPMorgan Chase": ["jpmorganchase", "jpmc", "jpmorgan"],
    "Goldman Sachs": ["goldmansachs", "gs"],
    "Morgan Stanley": ["morganstanley"],
    "Citibank": ["citigroup", "citi", "citi.com"],
    "Bank of America": ["bankofamerica", "bankofamerica.com"],
    "Wells Fargo": ["wellsfargo"],
    "BlackRock": ["blackrock"],
    "McKinsey & Company": ["mckinsey"],
    "Boston Consulting Group": ["bostonconsultinggroup", "bcg"],
    "Bain & Company": ["bain", "bain.com"],
    "Deloitte": ["deloitte", "deloittecareers"],
    "PwC": ["pwc", "pwc.com"],
    "EY": ["ey", "ernstyoung"],
    "KPMG": ["kpmg", "kpmg.com"],
    "Accenture": ["accenture", "accenturecareers"],
    "Capgemini": ["capgemini", "capgeminicareers"],
    "Tata Consultancy Services": ["tcs", "tata", "tcs.com"],
    "Infosys": ["infosys", "infosyscareers"],
    "Wipro": ["wipro", "wiprocalways"],
    "HCL Technologies": ["hcltech", "hcl", "hcl.com"],
    "Cognizant": ["cognizant", "cognizantcareers"],
    "Tech Mahindra": ["techmahindra", "techmahindracareers"],
    "LTIMindtree": ["ltimindtree", "lti", "mindtree"],
    "WPP Media": ["wpp", "wpp.com", "wppcareers"],
    "Genpact": ["genpact", "genpactcareers"],
    "DXC Technology": ["dxc", "dxctechnology"],
    "Qualcomm": ["qualcomm", "qualcommcareers"],
    "AMD": ["amd", "amdcareers"],
    "Broadcom": ["broadcom", "broadcomcareers"],
    "NVIDIA": ["nvidia", "nvidianetwork"],
    "SAP": ["sap", "sapcareers"],
    "Workday": ["workday", "workdaycareers"],
    "ServiceNow": ["servicenow", "servicenowcareers"],
    "HubSpot": ["hubspot", "hubspotcareers"],
    "Zendesk": ["zendesk", "zendeskcareers"],
    "Intuit": ["intuit", "intuitcareers"],
    "Stripe": ["stripe", "stripecareers"],
    "Square": ["square", "squareup", "block"],
    "Walmart": ["walmart", "walmartcareers"],
    "Target": ["target", "targetcareers"],
    "Costco": ["costco", "costcocareers"],
    "McDonald's": ["mcdonalds", "mcdonaldscareers"],
    "Starbucks": ["starbucks", "starbuckscareers"],
    "Coca-Cola": ["coca-cola", "cocacola"],
    "PepsiCo": ["pepsico", "pepsico.com"],
    "Nestlé": ["nestle", "nestlecareers"],
    "Procter & Gamble": ["pg", "pandg", "proctergamble"],
    "Unilever": ["unilever", "unilevercareers"],
    "Nike": ["nike", "nikecareers"],
    "Adidas": ["adidas", "adidascareers"],
    "Disney": ["disney", "disneycareers"],
    "Boeing": ["boeing", "boeingcareers"],
    "Lockheed Martin": ["lockheedmartin", "lockheedmartin.com"],
    "SpaceX": ["spacex", "spacexcareers"],
    "Stripe": ["stripe", "stripecareers"],
    "ByteDance/TikTok": ["bytedance", "tiktok"],
    "Tencent": ["tencent", "tencentcareers"],
    "Samsung": ["samsung", "samsungcareers"],
    "Sony": ["sony", "sonycareers"],
    "Huawei": ["huawei", "huaweicareers"],
    "Toyota": ["toyota", "toyotacareers"],
    "Ford": ["ford", "fordcareers"],
    "General Motors": ["gm", "generalmotors"],
    "Rivian": ["rivian", "riviancareers"],
    "Boeing": ["boeing", "boeingcareers"],
    "Visa": ["visa", "visacareers"],
    "Mastercard": ["mastercard", "mastercardcareers"],
    "American Express": ["americanexpress", "amex"],
    "Bloomberg": ["bloomberg", "bloombergcareers"],
    "Oracle": ["oracle", "oraclecareers"],
    "SAP": ["sap", "sapcareers"],
    "Zillow": ["zillow", "zillowcareers"],
    "DocuSign": ["docusign", "docusigncareers"],
    "Dropbox": ["dropbox", "dropboxcareers"],
    "Coursera": ["coursera", "courseracareers"],
    "Duolingo": ["duolingo", "duolingocareers"],
    "T-Mobile": ["t-mobile", "tmobile"],
    "AT&T": ["att", "t-mobile"],
    "Verizon": ["verizon", "verizonwireless"],
    "Capital One": ["capitalone", "capitalonecareers"],
    "Booking.com": ["booking", "bookingcareers"],
    "Expedia": ["expedia", "expediajobs"],
    "Hilton": ["hilton", "hiltonworldwide"],
    "Marriott": ["marriott", "marriottcareers"],
    "Etsy": ["etsy", "etsycareers"],
    "eBay": ["ebay", "ebaycareers"],
    "Twitch": ["twitch", "twitchcareers"],
    "Discord": ["discord", "discordcareers"],
    "Unity Technologies": ["unity", "unitycareers"],
    "Roblox": ["roblox", "robloxcareers"],
    "Riot Games": ["riotgames", "riot"],
    "Electronic Arts": ["ea", "electronicarts"],
    "Activision Blizzard": ["actvisionblizzard", "activision"],
    "Palantir Technologies": ["palantir", "palantirtech"],
    "Snowflake": ["snowflake", "snowflakecareers"],
}


class ResolveUrlRequest(BaseModel):
    url: str = ""


def _normalize_company_slug(slug: str) -> str:
    """Strip job-board noise from an org slug, e.g. 'acme-jobs' -> 'acme'."""
    slug = (slug or "").lower().strip("/")
    slug = re.sub(r"^(www|careers|jobs|boards|recruiting|hiring|work(at)?)\s*\.", "", slug)
    slug = re.sub(r"\.(com|co|in|io|org|net|jobs|careers)$", "", slug)
    slug = re.split(r"[.\-]?(jobs|careers|board|recruiting|hiring|talent)$", slug)[0]
    slug = re.sub(r"(_|\+)+", "-", slug)
    slug = re.sub(r"[0-9]+$", "", slug)
    return slug.strip("-")


def _guess_company_from_domain(host: str) -> str:
    """Domain-only heuristic: careers.<co>.com / <co>.com/jobs -> company name."""
    m = re.match(r"^(?:careers|jobs|boards|recruiting|hiring|work(at)?)\s*\.(.*)$", host)
    if m:
        candidate = _normalize_company_slug(m.group(2))
        if candidate:
            return candidate
    return _normalize_company_slug(host)


def _fuzzy_match_company(raw: str) -> str:
    """Return a known/registered company name if raw is a close match, else raw."""
    if not raw:
        return ""
    raw_norm = raw.lower()
    known = get_distinct_companies()
    known_lower = {c.lower(): c for c in known}
    if raw_norm in known_lower:
        return known_lower[raw_norm]
    best = difflib.get_close_matches(raw.lower(), list(known_lower.keys()), n=1, cutoff=0.8)
    if best:
        return known_lower[best[0]]
    return raw


def resolve_company_from_url(url: str) -> dict:
    """Resolve (company, candidates, source) from a job URL.

    Returns {"company": str, "candidates": [str], "source": str}.
    source is one of: "domain_map" (alias match), "domain" (domain-only guess),
    "slug" (job-board org slug), or "".
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").strip("/")
    if not host:
        return {"company": "", "candidates": [], "source": ""}

    # 1) Direct alias lookup on the full host or its subdomain
    for canonical, aliases in _HINT_ALIASES.items():
        for alias in aliases:
            alias = alias.replace("http://", "").replace("https://", "").split("/")[0]
            if host == alias or host == f"www.{alias}" or host == f"careers.{alias}" or host == f"jobs.{alias}":
                return {"company": canonical, "candidates": _fuzzy_candidates(canonical), "source": "domain_map"}

    # 2) Job-board org slugs: greenhouse / lever (boards.<slug>), leverage, workable, bamboo
    path_parts = [p for p in path.split("/") if p]
    if host.endswith(".greenhouse.io") or host.endswith(".lever.co") or host.endswith(".leverhq.com"):
        slug = _normalize_company_slug(path_parts[0] if path_parts else host.split(".")[0])
        company = _match_by_slug(slug)
        return {"company": company, "candidates": _fuzzy_candidates(company or slug), "source": "slug" if company else "domain"}
    if host.endswith(".workable.com") or host.endswith(".bamboohr.com"):
        slug = _normalize_company_slug(path_parts[0] if path_parts else host.split(".")[0])
        company = _match_by_slug(slug)
        return {"company": company, "candidates": _fuzzy_candidates(company or slug), "source": "slug" if company else "domain"}

    # 3) LinkedIn company pages -> org slug in path
    if "linkedin.com" in host:
        for i, part in enumerate(path_parts):
            if part in ("company", "jobs"):
                if i + 1 < len(path_parts):
                    slug = _normalize_company_slug(path_parts[i + 1])
                    company = _match_by_slug(slug)
                    return {"company": company, "candidates": _fuzzy_candidates(company or slug), "source": "slug" if company else "domain"}
        return {"company": "", "candidates": [], "source": "domain"}

    # 5) careers.<co>.com with no direct alias (catch-all)
    if re.match(r"^careers\.", host):
        company = _guess_company_from_domain(host)
        matched = _match_by_slug(company)
        if matched:
            return {"company": matched, "candidates": _fuzzy_candidates(matched), "source": "domain_map"}
        return {"company": company, "candidates": _fuzzy_candidates(company), "source": "domain"}

    # 6) Naukri.com job slugs (company name is often embedded in the slug)
    if "naukri.com" in host:
        for part in path_parts:
            if part in ("job", "jobs", "search", "job-list", "career", "view"):
                continue
            slug = _normalize_company_slug(part)
            company = _match_by_slug(slug, substring=True)
            if company:
                return {"company": company, "candidates": _fuzzy_candidates(company), "source": "slug"}
        return {"company": "", "candidates": [], "source": "domain"}

    # 7) Final fallback: domain name -> company guess.
    base = _guess_company_from_domain(host)
    matched = _match_by_slug(base)
    return {"company": matched or base, "candidates": _fuzzy_candidates(matched or base), "source": "domain"}


def _match_by_slug(slug: str, substring: bool = False) -> str:
    """Resolve an org slug against known aliases; return canonical company or ''."""
    slug = _normalize_company_slug(slug)
    if not slug:
        return ""
    lower_slug = slug.lower()
    for canonical, aliases in _HINT_ALIASES.items():
        for a in aliases:
            a = a.lower()
            if lower_slug == a or (substring and a in lower_slug and len(a) >= 4):
                return canonical
    # Fuzzy match against registered company names
    registered = get_distinct_companies()
    best = difflib.get_close_matches(lower_slug, [c.lower() for c in registered], n=1, cutoff=0.82)
    if best:
        for c in registered:
            if c.lower() == best[0]:
                return c
    return ""


def _fuzzy_candidates(company: str) -> list[str]:
    """Up to 5 company names (registered + known list) close to `company`."""
    if not company:
        return []
    pool = set(get_distinct_companies())
    for canonical, aliases in _HINT_ALIASES.items():
        pool.add(canonical)
    pool.discard(company)
    matches = difflib.get_close_matches(company.lower(), [c.lower() for c in pool], n=5, cutoff=0.6)
    return [c for c in pool if c.lower() in matches][:5]


def _guess_job_title_from_url(url: str) -> str:
    """Best-effort title from the URL tail. Returns '' if nothing useful."""
    parsed = urlparse(url)
    tail = (parsed.path or "").strip("/").split("/")[-1]
    if not tail:
        return ""
    tail = tail.replace("-", " ").replace("_", " ").strip()
    tail = re.sub(r"[0-9]{4,}", "", tail)
    tail = re.sub(r"\s+", " ", tail).strip()
    if not tail or len(tail) > 60:
        return ""
    return tail[:60].capitalize()


@router.post("/resolve-url")
async def resolve_url(req: ResolveUrlRequest, request: Request):
    if not req.url or not req.url.strip():
        raise HTTPException(400, "url is required")
    url = req.url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise HTTPException(400, "URL must start with http:// or https://")

    client_ip = request.client.host if request.client else ""
    if not check_rate_limit(f"resolve_url:{client_ip}", _RESOLVE_RATE, _RESOLVE_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")

    result = resolve_company_from_url(url)
    return {
        "ok": True,
        "url": url,
        "company": result["company"],
        "company_candidates": result["candidates"],
        "job_title": _guess_job_title_from_url(url),
        "source": result["source"],
        "referrer_count": len(get_referrers_by_company(result["company"])) if result["company"] else 0,
    }