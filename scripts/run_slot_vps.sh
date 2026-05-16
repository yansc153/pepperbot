#!/bin/bash
# VPS / Docker entry point for cron-triggered slots.
# Called as: run_slot_vps.sh <slot_name>
set -euo pipefail

# Cron jobs do not inherit the container's env. entrypoint.sh writes
# PATH/MOONSHOT_API_KEY/LLM_BACKEND/HEADLESS/TWITTER_COOKIE_FILE into
# /etc/environment — source it so this script sees them.
if [ -f /etc/environment ]; then
    set -a
    . /etc/environment
    set +a
fi

SLOT="${1:?Usage: run_slot_vps.sh <slot1|slot2|slot3|slot4|slot5|review>}"
cd /app

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START slot=$SLOT"
python3 src/slot_runner.py --slot "$SLOT"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] DONE  slot=$SLOT"
