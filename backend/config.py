# Global configs — copy this to config.py and fill in your values
import os

# ==============
# LLM SETTINGS
# ==============
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "cerebras")  # "cerebras", "groq", or "ollama"

# Cerebras (primary)
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
CEREBRAS_API_URL = os.environ.get("CEREBRAS_API_URL", "https://api.cerebras.ai/v1")

# Internship Cerebras (separate key for internship mode)
INTERNSHIP_CEREBRAS_API_KEY = os.environ.get("INTERNSHIP_CEREBRAS_API_KEY", "")
INTERNSHIP_CEREBRAS_MODEL = os.environ.get("INTERNSHIP_CEREBRAS_MODEL", CEREBRAS_MODEL)
INTERNSHIP_CEREBRAS_RATE = int(os.environ.get("INTERNSHIP_CEREBRAS_RATE", "4"))

# Groq (fallback)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# Ollama (local fallback)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/v1/chat/completions")

# ==============
# REFERRAL MARKETPLACE
# ==============
COMPANIES = sorted(set([
    "Google", "Meta", "Apple", "Amazon", "Microsoft", "Netflix", "Tesla", "Nvidia",
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
        "Software Developer", "Mobile Developer", "iOS Developer", "Android Developer",
        "Game Developer", "Embedded Systems Engineer", "DevOps Engineer",
        "Platform Engineer", "Site Reliability Engineer", "Cloud Engineer",
        "Cloud Architect", "Solutions Architect", "Software Architect", "Enterprise Architect",
        "Security Engineer", "Cybersecurity Analyst", "Security Analyst",
        "Penetration Tester", "Database Administrator", "SQL Developer",
        "Database Developer", "QA Engineer", "SDET", "Test Automation Engineer",
        "Automation Engineer", "Performance Engineer", "Systems Administrator",
        "Network Engineer", "IT Support Specialist", "Technical Support Engineer",
        "Help Desk Technician", "Systems Analyst", "Blockchain Developer",
        "Technical Writer", "Salesforce Administrator", "SAP Consultant", "IT Project Manager",
    ],
    "sales": [
        "Sales Representative", "Inside Sales Representative", "Outside Sales Representative",
        "Account Executive", "Key Account Manager", "Sales Manager",
        "Regional Sales Manager", "Sales Director",
        "Business Development Manager", "Business Development Representative",
        "Sales Development Representative", "Customer Success Manager",
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
        "Healthcare Administrator", "Physical Therapist", "Occupational Therapist",
        "Dentist", "Dental Hygienist", "Lab Technician", "Veterinarian",
        "Radiologist", "Speech Therapist", "Dietitian", "Nutritionist",
        "Optometrist", "Chiropractor", "Medical Coder", "Medical Biller",
        "Clinical Research Coordinator", "Health Informatics Specialist", "Emergency Medical Technician",
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
        "Administrative Assistant", "Administrative Coordinator", "Office Manager",
        "Office Coordinator", "Virtual Assistant", "Executive Assistant",
        "Human Resources Manager", "Human Resources Specialist", "HR Generalist",
        "Recruiter", "Talent Acquisition Specialist",
        "Learning and Development Specialist", "Training Coordinator",
        "Compensation and Benefits Analyst", "Operations Manager", "Operations Coordinator",
        "Project Manager", "Receptionist", "Payroll Specialist", "Data Entry Clerk",
        "Customer Service Representative", "Call Center Agent", "Client Services Manager",
        "Technical Support Specialist",
    ],
    "legal": [
        "Lawyer", "Paralegal", "Legal Assistant", "Legal Secretary",
        "Compliance Officer", "Corporate Counsel", "Contract Manager",
        "Contract Administrator", "Patent Attorney", "Corporate Lawyer",
        "Intellectual Property Lawyer", "Immigration Lawyer", "Legal Operations Manager",
    ],
    "education": [
        "Teacher", "Elementary School Teacher", "Middle School Teacher", "High School Teacher",
        "Professor", "University Lecturer", "Tutor", "Instructional Designer",
        "Curriculum Designer", "Education Administrator", "Education Consultant",
        "Special Education Teacher", "Academic Advisor", "ESL Teacher", "School Counselor",
        "Online Instructor", "E-learning Developer", "Training Specialist",
    ],
    "civil": [
        "Civil Engineer", "Structural Engineer", "Construction Manager",
        "Construction Superintendent", "Construction Estimator", "Construction Project Manager",
        "Site Engineer", "Quantity Surveyor", "Infrastructure Engineer",
        "Urban Planner", "Surveyor", "Civil Engineering Technician",
        "Geotechnical Engineer", "Transportation Engineer", "Water Resources Engineer",
        "Building Inspector", "Real Estate Agent", "Property Manager", "Facilities Manager",
    ],
    "engineering": [
        "Electrical Engineer", "Mechanical Engineer", "Chemical Engineer",
        "Biomedical Engineer", "Industrial Engineer", "Aerospace Engineer",
        "Automotive Engineer", "Robotics Engineer", "Materials Engineer",
        "Environmental Engineer", "Petroleum Engineer", "Mining Engineer",
        "Marine Engineer", "Power Engineer", "HVAC Engineer",
        "Manufacturing Engineer", "Process Engineer", "Quality Engineer",
        "Electronics Engineer", "Instrumentation Engineer", "Control Systems Engineer", "CAD Designer",
    ],
    "design": [
        "UI/UX Designer", "UX Designer", "UI Designer", "UX Researcher",
        "Product Designer", "Interaction Designer", "Visual Designer",
        "Web Designer", "Brand Designer", "Interior Designer",
        "Fashion Designer", "Industrial Designer",
    ],
    "product": [
        "Product Manager", "Product Owner", "Technical Product Manager",
        "Growth Product Manager", "Product Analyst", "Product Operations Manager",
        "Business Analyst", "Scrum Master", "Agile Coach",
        "Program Manager", "Delivery Manager",
    ],
    "supply_chain": [
        "Supply Chain Manager", "Supply Chain Analyst", "Demand Planner",
        "Logistics Coordinator", "Logistics Analyst", "Procurement Specialist",
        "Purchasing Manager", "Inventory Manager", "Warehouse Manager",
        "Warehouse Supervisor", "Distribution Manager", "Freight Forwarder", "Customs Broker",
    ],
    "hospitality": [
        "Chef", "Executive Chef", "Sous Chef", "Pastry Chef",
        "Restaurant Manager", "Hotel Manager", "Front Desk Agent",
        "Front Office Manager", "Guest Services Manager", "Housekeeping Manager",
        "Event Coordinator", "Event Manager", "Banquet Manager",
        "Bartender", "Barista", "Concierge", "Travel Consultant", "Tour Guide",
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