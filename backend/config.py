# Global configs — copy this to config.py and fill in your values
import os

# ==============
# LLM SETTINGS
# ==============
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")  # "groq" or "ollama"

# Groq (fallback)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")
GROQ_KEYWORDS_MODEL = os.environ.get("GROQ_KEYWORDS_MODEL", "openai/gpt-oss-20b")

# Ollama (local fallback)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/v1/chat/completions")

# ==============
# REFERRAL MARKETPLACE
# ==============
COMPANIES = sorted(set([
    "Google", "Meta", "Apple", "Amazon", "0.Microsoft", "Netflix", "Tesla", "Nvidia",
    "Adobe", "Salesforce", "Oracle", "IBM", "Intel", "Cisco", "Uber", "Airbnb",
    "Stripe", "Square", "PayPal", "Shopify", "Spotify", "Twitter/X", "LinkedIn",
    "Snap", "Pinterest", "Reddit", "Zoom", "Slack", "Notion", "Figma",
    "Atlassian", "GitLab", "GitHub", "Datadog", "Snowflake", "MongoDB",
    "Cloudflare", "Twilio", "Okta", "Palantir", "Coinbase", "Robinhood",
    "Block", "Plaid", "Brex", "Rippling", "Deel", "Airtable", "Asana",
    "Canva", "Vercel", "Railway", "Supabase", "Render", "Linear",
    "JPMorgan Chase", "Goldman Sachs", "Morgan Stanley", "Citibank",
    "Bank of America", "Wells Fargo", "BlackRock", "Vanguard", "Fidelity",
    "McKinsey & Company", "Boston Consulting Group", "Bain & Company",
    "Deloitte", "PwC", "EY", "KPMG", "Accenture", "Capgemini",
    "Tata Consultancy Services", "TCS", "Infosys", "Wipro", "HCL Technologies",
    "Cognizant", "Tech Mahindra", "LTIMindtree", "Mphasis", "Hexaware",
    "DXC Technology", "Atos", "LTI", "Persistent Systems", "Coforge",
    "Zensar Technologies", "KPIT", "Birlasoft", "Cyient",
    "Genpact", "WNS", "EXL Service",
    "Microsoft Research", "DeepMind", "OpenAI", "Anthropic", "Cohere",
    "Hugging Face", "Scale AI", "Midjourney", "Runway", "Replicate",
    "Johnson & Johnson", "Pfizer", "Moderna", "Merck", "AbbVie",
    "UnitedHealth Group", "Kaiser Permanente", "CVS Health", "Cigna",
    "ByteDance/TikTok", "Tencent", "Alibaba", "Samsung", "Sony", "Huawei",
    "Toyota", "Ford", "General Motors", "Rivian", "Lucid", "SpaceX",
    "Boeing", "Lockheed Martin", "Northrop Grumman", "Raytheon",
    "Walmart", "Target", "Costco", "Home Depot", "Lowe's",
    "McDonald's", "Starbucks", "Coca-Cola", "PepsiCo", "Nestlé",
    "Procter & Gamble", "Unilever", "L'Oréal", "Nike", "Adidas",
    "LVMH", "Hermès", "Chanel", "Disney", "Warner Bros. Discovery",
    "Comcast/NBCUniversal", "Paramount", "Netflix", "HBO", "BBC",
    "Harvard University", "Stanford University", "MIT", "Yale University",
    "Princeton University", "Columbia University", "UC Berkeley",
    "Uber", "Lyft", "DoorDash", "Instacart", "Postmates",
    "Oracle", "SAP", "Workday", "ServiceNow", "HubSpot", "Zendesk",
    "Palantir Technologies", "Qualcomm", "AMD", "Broadcom", "Texas Instruments",
    "Alphabet/Google", "Waymo", "Wing", "Verily", "Calico",
    "Siemens", "GE", "Honeywell", "3M", "Caterpillar", "John Deere",
    "Chevron", "ExxonMobil", "Shell", "BP", "TotalEnergies",
    "Visa", "Mastercard", "American Express", "Discover",
    "Bloomberg", "Reuters", "The New York Times", "The Wall Street Journal",
    "Spotify", "Apple Music", "SoundCloud", "BandLab",
    "Electronic Arts", "Activision Blizzard", "Ubisoft", "Epic Games",
    "Unity Technologies", "Roblox", "Riot Games", "Valve",
    "Palantir", "Anduril", "Shield AI", "HawkEye 360",
    "Coursera", "Udemy", "Duolingo", "Khan Academy", "Chegg",
    "T-Mobile", "AT&T", "Verizon", "Comcast", "Charter",
    "Capital One", "American Express", "SoFi", "Chime", "Wise",
    "Zillow", "Redfin", "Opendoor", "Compass", "Realtor.com",
    "Booking.com", "Expedia", "Tripadvisor", "Skyscanner", "Hopper",
    "Hilton", "Marriott", "Hyatt", "Airbnb",
    "WeWork", "IWG/Regus", "Flexspace",
    "PayPal", "Venmo", "Affirm", "Klarna", "Afterpay",
    "DocuSign", "Dropbox", "Box", "Egnyte",
    "Okta", "CrowdStrike", "Palo Alto Networks", "Fortinet", "Zscaler",
    "Dell", "HP", "Lenovo", "ASUS", "Razer",
    "AMD", "ARM", "Qualcomm", "MediaTek", "NVIDIA",
    "SAP", "Salesforce", "Adobe", "ServiceNow", "Workday", "Intuit",
    "Uber", "Lyft", "DoorDash", "Instacart", "Grubhub",
    "Twitch", "Discord", "Telegram", "Signal",
    "Etsy", "eBay", "Shopify", "Mercado Libre",     "Rakuten",
]))

# ==============
# ADZUNA API
# ==============
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_KEY = os.environ.get("ADZUNA_KEY", "")

# ==============
# JOB SEARCH SETTINGS
# ==============
ROLES_BY_CATEGORY = {
    "tech": [
        "AI Engineer", "Machine Learning Engineer", "MLOps Engineer",
        "Computer Vision Engineer", "NLP Engineer", "Prompt Engineer",
        "Data Scientist", "Data Analyst", "Business Intelligence Analyst",
        "Data Engineer", "Big Data Engineer", "ETL Developer",
        "Python Developer", "Java Developer", ".NET Developer", "C# Developer",
        "C++ Developer", "PHP Developer", "Ruby Developer", "Ruby on Rails Developer",
        "Go Developer", "Rust Developer", "Kotlin Developer", "Swift Developer",
        "JavaScript Developer", "TypeScript Developer", "Node.js Developer",
        "React Developer", "Angular Developer", "Vue.js Developer",
        "WordPress Developer", "Salesforce Developer",
        "Backend Developer", "Frontend Developer", "Backend Engineer", "Frontend Engineer",
        "Full Stack Developer", "Full Stack Engineer", "Software Engineer",
        "Software Developer", "iOS Developer", "Android Developer",
        "Game Developer", "Embedded Systems Engineer", "DevOps Engineer",
        "Site Reliability Engineer", "Cloud Engineer",
        "Cloud Architect", "Solutions Architect", "Software Architect",
        "Security Engineer", "Cybersecurity Analyst", "Security Analyst",
        "Database Administrator", "SQL Developer",
        "Database Developer", "QA Engineer", "Test Automation Engineer",
        "Automation Engineer", "Systems Administrator",
        "Network Engineer", "IT Support Specialist",
        "Blockchain Developer",
        "Technical Writer", "SAP Consultant", "IT Project Manager",
    ],
    "sales": [
        "Sales Representative", "Sales Development Representative",
        "Account Executive", "Key Account Manager", "Sales Manager",
        "Regional Sales Manager", "Sales Director",
        "Business Development Manager", "Business Development Representative",
        "Account Manager", "Sales Operations Analyst", "Presales Consultant", "Sales Engineer",
    ],
    "media": [
        "Content Writer", "Copywriter", "Editor", "Content Strategist",
        "Social Media Manager", "Digital Marketing Specialist", "SEO Specialist",
        "Performance Marketing Manager", "Email Marketing Specialist", "Media Buyer",
        "Marketing Analyst", "Marketing Manager", "Product Marketing Manager",
        "Brand Manager", "Brand Strategist", "PR Specialist",
        "Graphic Designer", "Video Editor", "Photographer", "Art Director",
        "Motion Designer", "Illustrator", "3D Artist",
    ],
    "healthcare": [
        "Doctor", "Physician Assistant", "Nurse", "Registered Nurse",
        "Pharmacist", "Pharmacy Technician", "Medical Assistant",
        "Healthcare Administrator", "Physical Therapist",
        "Dentist", "Lab Technician", "Veterinarian",
        "Radiologist", "Speech Therapist", "Dietitian", "Nutritionist",
        "Optometrist", "Chiropractor",
        "Clinical Research Coordinator", "Emergency Medical Technician",
    ],
    "finance": [
        "Accountant", "Bookkeeper", "Accounting Manager",
        "Financial Analyst", "FP&A Analyst", "Finance Manager",
        "Auditor", "Internal Auditor", "Tax Specialist",
        "Financial Advisor", "Wealth Manager", "Risk Analyst",
        "Investment Analyst", "Equity Research Analyst", "Underwriter", "Credit Analyst",
        "Treasury Analyst", "Actuary", "Quantitative Analyst",
        "Accounts Payable Specialist", "Accounts Receivable Specialist",
    ],
    "admin": [
        "Administrative Assistant", "Administrative Coordinator",
        "Office Coordinator", "Virtual Assistant", "Executive Assistant",
        "Human Resources Manager", "Human Resources Specialist", "HR Generalist",
        "Recruiter", "Talent Acquisition Specialist",
        "Learning and Development Specialist", "Training Coordinator",
        "Compensation and Benefits Analyst", "Operations Manager", "Operations Coordinator",
        "Receptionist", "Payroll Specialist", "Data Entry Clerk",
        "Customer Service Representative", "Call Center Agent",
        "Technical Support Specialist",
    ],
    "legal": [
        "Lawyer", "Paralegal", "Legal Assistant", "Legal Secretary"
    ],
    "education": [
        "Teacher", "Elementary School Teacher", "Middle School Teacher", "High School Teacher",
        "Professor", "University Lecturer", "Tutor", "Instructional Designer",
        "Curriculum Designer", "Education Administrator", "Education Consultant",
    ],
    "civil": [
        "Civil Engineer", "Structural Engineer", "Construction Manager",
        "Construction Superintendent", "Construction Estimator", "Construction Project Manager",
        "Site Engineer", "Quantity Surveyor", "Infrastructure Engineer",
        "Urban Planner", "Surveyor",
        "Geotechnical Engineer", "Transportation Engineer", "Water Resources Engineer",
        "Building Inspector", "Real Estate Agent", "Facilities Manager",
    ],
    "engineering": [
        "Electrical Engineer", "Mechanical Engineer", "Chemical Engineer",
        "Biomedical Engineer", "Industrial Engineer", "Aerospace Engineer",
        "Automotive Engineer", "Robotics Engineer", "Materials Engineer",
        "Petroleum Engineer", "Mining Engineer", "Marine Engineer",
        "Electronics Engineer", "Instrumentation Engineer",
        "CAD Designer",
    ],
    "design": [
        "UI/UX Designer", "UX Designer", "UI Designer", "UX Researcher",
        "Product Designer", "Interaction Designer", "Visual Designer",
        "Web Designer", "Brand Designer", "Interior Designer",
        "Fashion Designer"
    ],
    "product": [
        "Product Manager", "Product Owner", "Technical Product Manager",
        "Growth Product Manager", "Product Analyst", "Product Operations Manager",
        "Business Analyst", "Scrum Master", "Agile Coach",
        "Program Manager",
    ],
}

# Flat list of all roles (for scraper fallback if user picks none)
TARGET_ROLES = []
for roles in ROLES_BY_CATEGORY.values():
    TARGET_ROLES.extend(roles)

KEYWORDS_INCLUDE = []

KEYWORDS_EXCLUDE = [
    "senior manager",
    "sales",
    "hr",
    "accounting",
    "non technical",
    "non-technical",
    "media",
    "marketing",
    
]

INTERNSHIP_KEYWORDS = [
    "internship", "intern", "entry level", "fresher", "graduate",
    "trainee", "junior", "apprentice", "graduate trainee",
]

# Scrape limits per site
SCRAPE_LIMIT = 1000

# ==============
# JOB CACHE + PREWARM SCHEDULER
# ==============
CACHE_ENABLED = True
CACHE_TTL_HOURS = 12.0                                    # fresh until 12h old
CACHE_MIN_VOLUME = 10                                     # min jobs for an entry to be "fresh"
CACHE_HOURS_OLD = 168                                     # posting window used by scrapers
CACHE_PREWARM_LIMIT = 30                                  # prewarm fetch/store per combo
CACHE_MAX_JOBS_PER_ENTRY = 500                            # live-search cache write cap
CACHE_MAX_AGE_HOURS = 336                                 # delete cache rows older than 14 days
CACHE_MAX_ENTRIES = 50000                                 # row-count safety cap

CACHE_ROLES = ["Full Stack Developer", "Backend Developer", "Frontend Developer",
    "Data Scientist", "Data Analyst", "AI Engineer", "Machine Learning Engineer",
    "Data Engineer", "DevOps Engineer", "Cloud Engineer", "Python Developer",
    "QA Engineer", "iOS Developer", "Android Developer", "Network Engineer",
    "Sales Development Representative"
]

# Countries to prewarm (countrystatecity ISO2 codes). CACHE_INCLUDE_ALL_STATES expands every state/region.
CACHE_COUNTRIES = ["in", "us", "ie", "ae"]
CACHE_INCLUDE_ALL_STATES = True
# Optional curated states per country (used when CACHE_INCLUDE_ALL_STATES is false)
CACHE_STATES_OVERRIDE = {}  # e.g. {"us": ["California", "Texas"]}
# State names excluded from the prewarm grid (military/territory codes with no job market)
CACHE_STATES_EXCLUDE = [
    "Armed Forces Europe",
    "Armed Forces of the Americas",
    "Armed Forces Pacific",
    "United States Minor Outlying Islands",
]

# Naukri matches location tokens by city, not state, so each state combo loops
# the state's major cities and merges results under the state cache key.
CACHE_CITIES_PER_STATE = 5
CACHE_CITY_RESULTS_WANTED = 30  # per-city fetch cap inside the city loop
CACHE_CITY_INCLUDE_STATE_TERM = True  # also run the plain state-name search
CACHE_STATE_CITIES = {
    "Andaman and Nicobar Islands": ["Port Blair", "Bamboo Flat", "Diglipur", "Rangat", "Mayabunder"],
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Tirupati"],
    "Arunachal Pradesh": ["Itanagar", "Pasighat", "Naharlagun", "Tawang", "Bomdila"],
    "Assam": ["Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Tezpur"],
    "Bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Darbhanga"],
    "Chandigarh": ["Chandigarh"],
    "Chhattisgarh": ["Raipur", "Bhilai", "Bilaspur", "Korba", "Durg"],
    "Dadra and Nagar Haveli and Daman and Diu": ["Silvassa", "Daman", "Diu"],
    "Delhi": ["New Delhi", "Delhi", "Gurugram", "Noida", "Faridabad"],
    "Goa": ["Panaji", "Vasco da Gama", "Madgaon", "Mapusa", "Ponda"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar"],
    "Haryana": ["Gurugram", "Faridabad", "Rohtak", "Karnal", "Panipat"],
    "Himachal Pradesh": ["Shimla", "Solan", "Dharamshala", "Mandi", "Baddi"],
    "Jammu and Kashmir": ["Srinagar", "Jammu", "Anantnag", "Baramula", "Kathua"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar"],
    "Karnataka": ["Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi"],
    "Kerala": ["Kochi", "Thiruvananthapuram", "Kozhikode", "Thrissur", "Kollam"],
    "Ladakh": ["Leh", "Kargil"],
    "Lakshadweep": ["Kavaratti"],
    "Madhya Pradesh": ["Indore", "Bhopal", "Jabalpur", "Gwalior", "Ujjain"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Thane"],
    "Manipur": ["Imphal", "Thoubal", "Churachandpur", "Kakching", "Bishnupur"],
    "Meghalaya": ["Shillong", "Tura", "Cherrapunji", "Nongstoin", "Mairang"],
    "Mizoram": ["Aizawl", "Lunglei", "Champhai", "Kolasib", "Serchhip"],
    "Nagaland": ["Kohima", "Dimapur", "Mokokchung", "Wokha", "Tuensang"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur"],
    "Puducherry": ["Puducherry", "Karaikal", "Mahe", "Yanam"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Mohali"],
    "Rajasthan": ["Jaipur", "Udaipur", "Jodhpur", "Kota", "Bikaner"],
    "Sikkim": ["Gangtok", "Namchi", "Singtam", "Rangpo", "Jorethang"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Khammam"],
    "Tripura": ["Agartala", "Udaipur", "Dharmanagar", "Kailashahar", "Sonamura"],
    "Uttar Pradesh": ["Noida", "Lucknow", "Kanpur", "Varanasi", "Ghaziabad"],
    "Uttarakhand": ["Dehradun", "Haridwar", "Haldwani", "Rudrapur", "Roorkee"],
    "West Bengal": ["Kolkata", "Howrah", "Siliguri", "Durgapur", "Asansol"],
}

# Boards: naukri is India-only; other countries default to indeed + linkedin
CACHE_SITES_INDIA = ["indeed", "linkedin", "naukri"]
CACHE_SITES_DEFAULT = ["indeed", "linkedin"]

PREWARM_WORKERS = 7
MAX_CONCURRENT_PER_BOARD = {"linkedin": 1, "indeed": 2, "naukri": 2}   # prewarm-only concurrency caps
PREWARM_DELAY_SECONDS = 5.0
NAUKRI_USE_PROXY = True                  # route Naukri through free proxies (ProxyScrape)
PREWARM_MAX_COMBOS_PER_RUN = 500

SCHEDULER_ENABLED = True
SCHEDULER_INTERVAL_MINUTES = 180

# ==============
# GOOGLE SHEETS 
# ==============
GOOGLE_SHEET_NAME = "Ammar Job Tracker"

# ==============
# EMAIL SETTINGS
# ==============
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "yourmail@gmail.com")
DAILY_EMAIL_SUBJECT = "Daily Job Application Summary"

# ==============
# SYSTEM SETTINGS
# ==============
RESUME_PATH = "resume.txt"
AUTO_APPLY = False
CHROME_PROFILE_PATH = ""

EMAIL_HOST=os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT=int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USER=os.environ.get("EMAIL_USER", "")
EMAIL_PASSWORD=os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO=os.environ.get("EMAIL_TO", "")