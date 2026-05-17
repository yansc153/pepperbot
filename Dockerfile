FROM python:3.12-slim

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    curl \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxss1 \
    libglib2.0-0 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

# Copy all project files (secrets/ excluded via .dockerignore)
COPY . .

# Cron jobs — times are UTC
# periodic posting every 2 hours (12 posts/day) via one feedback-aware slot
# review run at 00:00 CST = 16:00 UTC
RUN echo '0 */2 * * * root /app/scripts/run_slot_vps.sh periodic2h >> /app/logs/periodic2h.log 2>&1\n\
0 16   * * * root /app/scripts/run_slot_vps.sh review >> /app/logs/review.log 2>&1' \
    > /etc/cron.d/pepperbot && chmod 0644 /etc/cron.d/pepperbot

RUN mkdir -p /app/logs /app/data /app/tmp_images /app/tmp_screenshots

RUN chmod +x /app/scripts/entrypoint.sh /app/scripts/run_slot_vps.sh

CMD ["/app/scripts/entrypoint.sh"]
