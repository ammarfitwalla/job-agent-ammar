import sys
sys.path.insert(0, '.')

from scrapers import remoteok_scraper, weworkremotely_scraper, naukri_scraper, gulftalent_scraper, eurojobs_scraper

results = {}

print('=== RemoteOK ===')
try:
    jobs = remoteok_scraper.scrape_remoteok()
    results['RemoteOK'] = f'OK - {len(jobs)} jobs'
    for j in jobs[:3]:
        print(f'  - {j["title"]} @ {j["company"]}')
except Exception as e:
    results['RemoteOK'] = f'FAIL - {e}'
    print(f'  ERROR: {e}')

print()
print('=== WeWorkRemotely ===')
try:
    jobs = weworkremotely_scraper.scrape_wwr()
    results['WeWorkRemotely'] = f'OK - {len(jobs)} jobs'
    for j in jobs[:3]:
        print(f'  - {j["title"]} @ {j["company"]}')
except Exception as e:
    results['WeWorkRemotely'] = f'FAIL - {e}'
    print(f'  ERROR: {e}')

print()
print('=== Naukri ===')
try:
    jobs = naukri_scraper.scrape_naukri()
    results['Naukri'] = f'OK - {len(jobs)} jobs'
    for j in jobs[:3]:
        print(f'  - {j["title"]} @ {j["company"]}')
except Exception as e:
    results['Naukri'] = f'FAIL - {e}'
    print(f'  ERROR: {e}')

print()
print('=== GulfTalent ===')
try:
    jobs = gulftalent_scraper.scrape_gulftalent()
    results['GulfTalent'] = f'OK - {len(jobs)} jobs'
    for j in jobs[:3]:
        print(f'  - {j["title"]} @ {j["company"]}')
except Exception as e:
    results['GulfTalent'] = f'FAIL - {e}'
    print(f'  ERROR: {e}')

print()
print('=== EuroJobs ===')
try:
    jobs = eurojobs_scraper.scrape_eurojobs()
    results['EuroJobs'] = f'OK - {len(jobs)} jobs'
    for j in jobs[:3]:
        print(f'  - {j["title"]} @ {j["company"]}')
except Exception as e:
    results['EuroJobs'] = f'FAIL - {e}'
    print(f'  ERROR: {e}')

print()
print('=' * 40)
print('SUMMARY')
print('=' * 40)
for site, status in results.items():
    print(f'{site}: {status}')
