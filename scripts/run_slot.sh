#!/bin/bash
# Linux cron entry point for pepperbot slots.
# Usage: /opt/pepperbot/scripts/run_slot.sh <slot_name>
# Example: /opt/pepperbot/scripts/run_slot.sh slot1
#
# Crontab (Asia/Shanghai):
#   CRON_TZ=Asia/Shanghai
#   0 */2 * * *  /opt/pepperbot/scripts/run_slot.sh observe
#   0  7 * * *  /opt/pepperbot/scripts/run_slot.sh slot1
#   0 11 * * *  /opt/pepperbot/scripts/run_slot.sh slot2
#   0 16 * * *  /opt/pepperbot/scripts/run_slot.sh slot3
#   0 20 * * *  /opt/pepperbot/scripts/run_slot.sh slot4
#   0 23 * * *  /opt/pepperbot/scripts/run_slot.sh slot5
#   0  0 * * *  /opt/pepperbot/scripts/run_slot.sh review

set -euo pipefail

SLOT_NAME="${1:?Usage: $0 <slot_name>}"
PEPPERBOT_ROOT="${PEPPERBOT_ROOT:-/opt/pepperbot}"
LOG_DIR="${PEPPERBOT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/pepperbot-${SLOT_NAME}-$(date '+%Y-%m-%d').log"
SECRETS_FILE="${PEPPERBOT_ROOT}/secrets/secrets.env"

mkdir -p "$LOG_DIR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ${SLOT_NAME} START ===" >> "$LOG_FILE"

# Load secrets (MOONSHOT_API_KEY, etc.)
if [[ -f "$SECRETS_FILE" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_FILE"
    set +a
else
    echo "[WARN] secrets.env not found at $SECRETS_FILE" >> "$LOG_FILE"
fi

export HEADLESS=true
export LLM_BACKEND=moonshot
export PEPPERBOT_ROOT
export TWITTER_COOKIE_FILE="${PEPPERBOT_ROOT}/secrets/twitter_cookies.json"

EXIT_CODE=0
cd "$PEPPERBOT_ROOT"
python3 src/slot_runner.py --slot "$SLOT_NAME" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

# Rotate logs older than 30 days
find "$LOG_DIR" -name "pepperbot-*.log" -mtime +30 -delete 2>/dev/null || true

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ${SLOT_NAME} END (exit ${EXIT_CODE}) ===" >> "$LOG_FILE"
exit $EXIT_CODE
