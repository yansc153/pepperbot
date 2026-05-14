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
# slot1 07:00 CST = 23:00 UTC
# slot2 12:00 CST = 04:00 UTC
# slot3 16:00 CST = 08:00 UTC
# slot4 20:00 CST = 12:00 UTC
# slot5 23:00 CST = 15:00 UTC
# review 00:00 CST = 16:00 UTC
RUN echo '0 23 * * * root /app/scripts/run_slot_vps.sh slot1 >> /app/logs/slot1.log 2>&1\n\
0 3  * * * root /app/scripts/run_slot_vps.sh slot2 >> /app/logs/slot2.log 2>&1\n\
0 8  * * * root /app/scripts/run_slot_vps.sh slot3 >> /app/logs/slot3.log 2>&1\n\
0 12 * * * root /app/scripts/run_slot_vps.sh slot4 >> /app/logs/slot4.log 2>&1\n\
0 15 * * * root /app/scripts/run_slot_vps.sh slot5 >> /app/logs/slot5.log 2>&1\n\
0 16 * * * root /app/scripts/run_slot_vps.sh review >> /app/logs/review.log 2>&1' \
    > /etc/cron.d/pepperbot && chmod 0644 /etc/cron.d/pepperbot

RUN mkdir -p /app/logs /app/data /app/tmp_images /app/tmp_screenshots

RUN chmod +x /app/scripts/entrypoint.sh /app/scripts/run_slot_vps.sh

CMD ["/app/scripts/entrypoint.sh"]
