#!/bin/bash
# Docker entrypoint: export env vars for cron, then start cron.
# Cron reads /etc/environment but does not inherit the container's env.
set -euo pipefail

# Write runtime env vars that cron jobs need into /etc/environment
printenv | grep -E "^(HEADLESS|LLM_BACKEND|MOONSHOT_API_KEY|TWITTER_COOKIE_FILE)=" \
    >> /etc/environment

mkdir -p /app/logs /app/data /app/tmp_images /app/tmp_screenshots

exec cron -f
