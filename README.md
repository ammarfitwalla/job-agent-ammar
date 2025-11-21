# 🤖 JOB-AGENT-AMMAR

An automated job application system that scrapes job listings from multiple platforms and manages the application process with AI-powered customization.

## 📋 Overview

This project automates the job search and application process by:
- Scraping job listings from various platforms (Remoteok, WeWorkRemotely, Eurojobs, Naukri, Gulftalent)
- Matching job requirements with resume data
- Generating customized cover letters and emails
- Managing application tracking and daily reports

## Project Structure

```
JOB-AGENT-AMMAR/
├── auto_apply/          # Main application logic
│   ├── base_apply.py
│   └── remoteok_apply.py
├── cover_letters/       # Generated cover letters
├── emails/              # Email templates and management
│   └── daily_report.py
├── llm/                 # AI/LLM integration
│   ├── ollama_client.py
│   └── prompts.py
├── match_engine/        # Job matching logic
│   ├── relevance_engine.py
│   └── resume_data.py
├── scrapers/            # Web scrapers for job sites
│   ├── init_scraper.py
│   ├── eurojobs_scraper.py
│   ├── gulftalent_scraper.py
│   ├── naukri_scraper.py
│   ├── remoteok_scraper.py
│   └── weworkremotely_scraper.py
├── sheets/              # Google Sheets integration
│   └── sheets_writer.py
├── utils/               # Utility functions
│   ├── logger.py
│   ├── browser.py
│   └── config.py
├── main.py              # Main entry point
├── test_selenium.py     # Selenium tests
└── requirements.txt     # Python dependencies
```

## Features

### Job Scraping
- **Multiple Platforms**: Supports Remoteok, WeWorkRemotely, Eurojobs, Naukri, and Gulftalent
- **Automated Data Collection**: Extracts job titles, descriptions, requirements, and application links
- **Intelligent Filtering**: Matches jobs based on skills and experience

### Application Management
- **AI-Powered Customization**: Generates personalized cover letters using LLM
- **Email Automation**: Creates and sends customized application emails
- **Application Tracking**: Records all applications in Google Sheets
- **Daily Reports**: Summarizes daily application activity

### Matching Engine
- **Resume Analysis**: Parses and structures resume data
- **Relevance Scoring**: Ranks jobs based on skill match and requirements
- **Smart Filtering**: Prioritizes best-fit opportunities

## ⚙️ Setup

### Prerequisites
- Python 3.8+
- Chrome/Chromium browser
- Google Sheets API credentials
- Ollama (for local LLM) or API access to AI services

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd JOB-AGENT-AMMAR
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure settings in `utils/config.py`:
- Set up Google Sheets API credentials
- Configure email settings
- Add resume data path
- Set LLM preferences

4. Set up environment variables (if needed):
```bash
export GOOGLE_SHEETS_CREDENTIALS_PATH=/path/to/credentials.json
export EMAIL_SENDER=your-email@example.com
export EMAIL_PASSWORD=your-app-password
```

## 🚀 Usage

### Run the complete job application pipeline:
```bash
python main.py
```

### Run individual components:

**Scrape jobs from a specific platform:**
```bash
python scrapers/remoteok_scraper.py
```

**Generate a cover letter:**
```bash
python cover_letters/generate_cover_letter.py
```

**Send daily report:**
```bash
python emails/daily_report.py
```

**Test Selenium setup:**
```bash
python test_selenium.py
```

## Configuration

Edit `utils/config.py` to customize:
- Job search keywords and filters
- Application limits per day
- Email templates
- LLM prompts and models
- Scraping intervals

## Google Sheets Integration

The system tracks applications in Google Sheets with columns:
- Date Applied
- Company Name
- Job Title
- Platform
- Application Link
- Status
- Match Score
- Notes

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Specify your license here]

## ⚠️ Disclaimer

This tool is for personal use only. Please respect the terms of service of job platforms and apply responsibly. Ensure compliance with anti-scraping policies and rate limits.

## Troubleshooting

- **Selenium issues**: Ensure ChromeDriver matches your Chrome version
- **API rate limits**: Adjust scraping intervals in config
- **Authentication errors**: Verify Google Sheets credentials
- **LLM connection**: Check Ollama is running locally or API keys are valid

## Contact

For questions or support, please open an issue on GitHub.
