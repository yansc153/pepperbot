#!/bin/bash
# VPS / Docker entry point for cron-triggered slots.
# Called as: run_slot_vps.sh <slot_name>
# Available: periodic2h, slot1, slot2, slot3, slot4, slot5, observe, review
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

load_cron_environment() {
    if [[ ! -f /etc/environment ]]; then
        return
    fi

    while IFS='=' read -r name value; do
        case "$name" in
            HEADLESS|LLM_BACKEND|MOONSHOT_API_KEY|TWITTER_COOKIE_FILE)
                export "$name=$value"
                ;;
        esac
    done < /etc/environment
}

SLOT="${1:?Usage: run_slot_vps.sh <periodic2h|slot1|slot2|slot3|slot4|slot5|observe|review>}"
cd /app
load_cron_environment
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"

if [[ -z "$PYTHON_BIN" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR python3 not found PATH=$PATH" >&2
    exit 127
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START slot=$SLOT"
"$PYTHON_BIN" src/slot_runner.py --slot "$SLOT"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] DONE  slot=$SLOT"
