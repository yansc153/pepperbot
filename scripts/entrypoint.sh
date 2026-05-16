#!/bin/bash
# Docker entrypoint: export env vars for cron, then start cron.
# Cron reads /etc/environment but does not inherit the container's env.
set -euo pipefail

# Write runtime env vars that cron jobs need into /etc/environment.
# PATH must be included — cron's default PATH (/usr/bin:/bin) does not
# contain /usr/local/bin where python3 lives in python:3.12-slim.
printenv | grep -E "^(PATH|HEADLESS|LLM_BACKEND|MOONSHOT_API_KEY|TWITTER_COOKIE_FILE)=" \
    >> /etc/environment

mkdir -p /app/logs /app/data /app/tmp_images /app/tmp_screenshots

exec cron -f
