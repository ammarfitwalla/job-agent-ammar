import requests, sys; sys.path.insert(0, '.')
from scrapers.remoteok_scraper import scrape_remoteok

# Test API pages
headers = {"User-Agent": "Mozilla/5.0"}
for p in [1, 2, 3]:
    r = requests.get(f"https://remoteok.com/api?page={p}", headers=headers, timeout=15)
    data = r.json()
    postings = [j for j in data if isinstance(j, dict) and j.get("position")]
    print(f"Page {p}: {len(postings)} postings")

# Also try with offset
for off in [0, 40, 80]:
    r = requests.get(f"https://remoteok.com/api?offset={off}", headers=headers, timeout=15)
    data = r.json()
    postings = [j for j in data if isinstance(j, dict) and j.get("position")]
    print(f"Offset {off}: {len(postings)} postings")
