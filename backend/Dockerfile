FROM python:3.11-slim

# Install Chromium for undetected-chromedriver + Playwright
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libnss3 \
    libnspr4 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium

WORKDIR /app

COPY backend/ backend/
COPY frontend/ frontend/

# config.py is gitignored, so generate from the example for deployment
RUN cp backend/config.example.py backend/config.py

WORKDIR /app/backend

RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright system deps + Chromium browser
RUN playwright install chromium
RUN playwright install-deps chromium

EXPOSE 8000

CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
