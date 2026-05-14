#!/bin/bash
# Runs a pepperbot slot by reading its SKILL.md and passing it to local claude CLI.
# Usage: ./run_slot.sh <slot_name>
# Example: ./run_slot.sh pepperbot-slot1

set -uo pipefail

SLOT_NAME="${1:?Usage: $0 <slot_name>}"
SKILL_FILE="/Users/oxjames/Documents/Claude/Scheduled/${SLOT_NAME}/SKILL.md"
LOG_DIR="/Users/oxjames/Downloads/CC_testing/花椒创业板/logs"
LOG_FILE="${LOG_DIR}/${SLOT_NAME}-$(date '+%Y-%m-%d').log"
CLAUDE_BIN="/Users/oxjames/.npm-global/bin/claude"
PROJECT_DIR="/Users/oxjames/Downloads/CC_testing/花椒创业板"

if [[ ! -f "$SKILL_FILE" ]]; then
    echo "[ERROR] SKILL.md not found: $SKILL_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

mkdir -p "$LOG_DIR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ${SLOT_NAME} START ===" >> "$LOG_FILE"

# Load user shell environment
export PATH="/Users/oxjames/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/Users/oxjames"

# Load secrets from env file (do not hardcode keys)
SECRETS_FILE="$HOME/.config/pepperbot/secrets.env"
if [[ -f "$SECRETS_FILE" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_FILE"
    set +a
fi

# Strip YAML frontmatter (--- ... ---) — claude CLI rejects it as an unknown option.
# Uses a temp file to avoid any stdin/option ambiguity.
PROMPT_FILE=$(mktemp /tmp/pepperbot-prompt-XXXXXX.txt)
python3 - "$SKILL_FILE" > "$PROMPT_FILE" <<'PYEOF'
import sys

skill_path = sys.argv[1]
with open(skill_path, encoding="utf-8") as f:
    content = f.read()

if content.startswith("---"):
    end = content.find("\n---\n", 3)
    if end != -1:
        content = content[end + 5:]

sys.stdout.write(content)
PYEOF

# Run claude CLI in non-interactive print mode.
# Uses --add-dir so Claude can read project files even under launchd.
EXIT_CODE=0
"$CLAUDE_BIN" --print \
    --add-dir "$PROJECT_DIR" \
    < "$PROMPT_FILE" >> "$LOG_FILE" 2>&1 || EXIT_CODE=$?

rm -f "$PROMPT_FILE"

# Rotate logs older than 30 days
find "$LOG_DIR" -name "pepperbot-*.log" -mtime +30 -delete 2>/dev/null || true

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ${SLOT_NAME} END (exit ${EXIT_CODE}) ===" >> "$LOG_FILE"
exit $EXIT_CODE
