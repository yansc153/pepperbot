#!/bin/bash
# VPS / Docker entry point for cron-triggered slots.
# Called as: run_slot_vps.sh <slot_name>
# Available: periodic2h, slot1, slot2, slot3, slot4, slot5, observe, review
set -euo pipefail

SLOT="${1:?Usage: run_slot_vps.sh <periodic2h|slot1|slot2|slot3|slot4|slot5|observe|review>}"
cd /app

echo "[$(date '+%Y-%m-%d %H:%M:%S')] START slot=$SLOT"
python3 src/slot_runner.py --slot "$SLOT"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] DONE  slot=$SLOT"
