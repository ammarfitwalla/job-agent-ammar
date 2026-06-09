import sys
sys.path.insert(0, '.')

from utils.experience_level import detect_experience_level

print("=" * 60)
print("TEST 1: experience_level detection (unit tests)")
print("=" * 60)

test_cases = [
    # (title, description, expected)
    ("Software Engineer Intern", "", "internship"),
    ("Intern - Data Science", "", "internship"),
    ("Summer Internship Program 2025", "", "internship"),
    ("Marketing Intern", "", "internship"),
    ("Junior Software Engineer", "", "entry_level"),
    ("Entry Level Data Analyst", "", "entry_level"),
    ("Junior Developer", "", "entry_level"),
    ("Graduate Trainee Engineer", "", "entry_level"),
    ("Fresher - Python Developer", "", "entry_level"),
    ("Apprentice Electrician", "", "entry_level"),
    ("Senior Software Engineer", "", None),
    ("Lead DevOps Engineer", "", None),
    ("Principal Architect", "", None),
    ("Staff Data Scientist", "", None),
    ("VP of Engineering", "", None),
    ("Software Engineer", "", None),
    ("Data Analyst", "", None),
    ("Product Manager", "", None),
    # Test description-based detection
    ("Software Engineer", "Looking for a fresh graduate with no experience", "entry_level"),
    ("Associate", "Entry level position ideal for freshers", "entry_level"),
    ("Developer", "Training provided for junior candidates", "entry_level"),
    ("Accountant", "Graduate program with mentorship", "entry_level"),
    # Senior in title should override
    ("Senior Intern Coordinator", "", None),
    ("Junior Manager", "", None),
]

passed = 0
failed = 0
for title, desc, expected in test_cases:
    result = detect_experience_level(title, desc)
    status = "PASS" if result == expected else "FAIL"
    if status == "PASS":
        passed += 1
    else:
        failed += 1
    print(f"  [{status}] title='{title}' desc='{desc[:30]}' => {result} (expected {expected})")

print(f"\n  Total: {passed} passed, {failed} failed\n")


print("=" * 60)
print("TEST 2: Adzuna scraper comparison (regular vs internship mode)")
print("=" * 60)

from scrapers.adzuna_scraper import scrape_adzuna

roles_sample = ["Software Engineer", "Data Analyst", "DevOps Engineer", "Marketing Associate"]
results_wanted = 30

print(f"\nRoles: {roles_sample}")
print(f"Max results per mode: {results_wanted}")

# --- Regular mode ---
print("\n--- REGULAR MODE (no filter) ---")
try:
    regular_jobs = scrape_adzuna(roles=roles_sample, country="us")
    print(f"  Got {len(regular_jobs)} jobs\n")
    
    if regular_jobs:
        tagged_regular = []
        for j in regular_jobs:
            j["experience_level"] = detect_experience_level(j.get("title", ""), j.get("description", ""))
            tagged_regular.append(j)
        
        intern_count = sum(1 for j in tagged_regular if j["experience_level"] == "internship")
        entry_count = sum(1 for j in tagged_regular if j["experience_level"] == "entry_level")
        senior_count = sum(1 for j in tagged_regular if j["experience_level"] is None)
        print(f"  Breakdown: {intern_count} internship, {entry_count} entry-level, {senior_count} other")
        print(f"  Sample jobs:")
        for j in tagged_regular[:5]:
            badge = j["experience_level"] or "regular"
            print(f"    [{badge:>12}] {j['title']} @ {j['company']}")
except Exception as e:
    print(f"  ERROR: {e} (this may fail if Adzuna API key is invalid or rate-limited)")
    print(f"  Skipping regular mode Adzuna test\n")

# --- Internship mode ---
print("\n--- INTERNSHIP MODE (filtered) ---")
try:
    intern_jobs = scrape_adzuna(roles=roles_sample, country="us", internship_mode=True)
    print(f"  Got {len(intern_jobs)} jobs\n")
    
    if intern_jobs:
        tagged_intern = []
        for j in intern_jobs:
            j["experience_level"] = detect_experience_level(j.get("title", ""), j.get("description", ""))
            tagged_intern.append(j)
        
        intern_count = sum(1 for j in tagged_intern if j["experience_level"] == "internship")
        entry_count = sum(1 for j in tagged_intern if j["experience_level"] == "entry_level")
        other_count = sum(1 for j in tagged_intern if j["experience_level"] is None)
        
        print(f"  Breakdown: {intern_count} internship, {entry_count} entry-level, {other_count} other")
        print(f"  Is entry-level/internship dominant? {'YES' if (intern_count + entry_count) > (len(tagged_intern) * 0.5) else 'NO'}")
        
        print(f"  Sample jobs:")
        for j in tagged_intern[:10]:
            badge = j["experience_level"] or "regular"
            print(f"    [{badge:>12}] {j['title']} @ {j['company']}")
        
        if other_count > 0:
            print(f"\n  [!] Jobs that slipped through (not intern/entry):")
            for j in tagged_intern:
                if j["experience_level"] is None:
                    print(f"    {j['title']} @ {j['company']}")
except Exception as e:
    print(f"  ERROR: {e} (this may fail if Adzuna API key is invalid or rate-limited)")
    print(f"  Skipping internship mode Adzuna test\n")


print("=" * 60)
print("TEST 3: Indeed scraper comparison (regular vs internship mode)")
print("=" * 60)

from scrapers.indeed_scraper import scrape_indeed

print(f"\nRoles: {roles_sample}")
print(f"Max results per mode: {results_wanted}")

# --- Regular mode ---
print("\n--- REGULAR MODE (no filter) ---")
try:
    regular_indeed = scrape_indeed(roles=roles_sample, location="United States", country_indeed="USA", results_wanted=results_wanted)
    print(f"  Got {len(regular_indeed)} jobs\n")
    
    if regular_indeed:
        for j in regular_indeed:
            j["experience_level"] = detect_experience_level(j.get("title", ""), j.get("description", ""))
        
        intern_count = sum(1 for j in regular_indeed if j["experience_level"] == "internship")
        entry_count = sum(1 for j in regular_indeed if j["experience_level"] == "entry_level")
        senior_count = sum(1 for j in regular_indeed if j["experience_level"] is None)
        print(f"  Breakdown: {intern_count} internship, {entry_count} entry-level, {senior_count} other")
        print(f"  Sample jobs:")
        for j in regular_indeed[:5]:
            badge = j["experience_level"] or "regular"
            print(f"    [{badge:>12}] {j['title']} @ {j['company']}")
except Exception as e:
    print(f"  ERROR: {e} (Indeed may fail without valid JobSpy config or be rate-limited)")
    print(f"  Skipping regular mode Indeed test\n")

# --- Internship mode ---
print("\n--- INTERNSHIP MODE (filtered) ---")
try:
    intern_indeed = scrape_indeed(roles=roles_sample, location="United States", country_indeed="USA", internship_mode=True, results_wanted=results_wanted)
    print(f"  Got {len(intern_indeed)} jobs\n")
    
    if intern_indeed:
        for j in intern_indeed:
            j["experience_level"] = detect_experience_level(j.get("title", ""), j.get("description", ""))
        
        intern_count = sum(1 for j in intern_indeed if j["experience_level"] == "internship")
        entry_count = sum(1 for j in intern_indeed if j["experience_level"] == "entry_level")
        other_count = sum(1 for j in intern_indeed if j["experience_level"] is None)
        
        print(f"  Breakdown: {intern_count} internship, {entry_count} entry-level, {other_count} other")
        print(f"  Is entry-level/internship dominant? {'YES' if (intern_count + entry_count) > (len(intern_indeed) * 0.5) else 'NO'}")
        
        print(f"  Sample jobs:")
        for j in intern_indeed[:10]:
            badge = j["experience_level"] or "regular"
            print(f"    [{badge:>12}] {j['title']} @ {j['company']}")
        
        if other_count > 0:
            print(f"\n  [!] Jobs that slipped through (not intern/entry):")
            for j in intern_indeed:
                if j["experience_level"] is None:
                    print(f"    {j['title']} @ {j['company']}")
except Exception as e:
    print(f"  ERROR: {e} (Indeed may fail without valid JobSpy config or be rate-limited)")
    print(f"  Skipping internship mode Indeed test\n")


print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Unit tests: {passed} passed, {failed} failed")
print("See above for scraper results")
