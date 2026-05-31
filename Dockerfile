FROM python:3.11-slim

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
ENV PYTHONUNBUFFERED=1

RUN useradd -m -u 1000 user

WORKDIR /app

COPY --chown=user backend/ backend/
COPY --chown=user frontend/ frontend/

# config.py is gitignored, create from example
RUN cp backend/config.example.py backend/config.py && chown user:user backend/config.py

USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app/backend

RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install chromium

EXPOSE 7860

CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-7860}
