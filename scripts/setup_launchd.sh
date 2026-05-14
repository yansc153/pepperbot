#!/bin/bash
# Install or uninstall pepperbot launchd agents.
# Usage:
#   ./setup_launchd.sh install    — load all agents (runs in user session, has keychain)
#   ./setup_launchd.sh uninstall  — unload all agents
#   ./setup_launchd.sh status     — check which are loaded

set -euo pipefail

AGENTS=(
    com.pepperbot.pepperbot-slot1
    com.pepperbot.pepperbot-slot2
    com.pepperbot.pepperbot-slot3
    com.pepperbot.pepperbot-slot4
    com.pepperbot.pepperbot-slot5
    com.pepperbot.pepperbot-review
)

ACTION="${1:?Usage: $0 install|uninstall|status}"

case "$ACTION" in
    install)
        echo "Loading pepperbot launchd agents..."
        for AGENT in "${AGENTS[@]}"; do
            PLIST="$HOME/Library/LaunchAgents/${AGENT}.plist"
            if [[ ! -f "$PLIST" ]]; then
                echo "[SKIP] Not found: $PLIST"
                continue
            fi
            launchctl unload "$PLIST" 2>/dev/null || true
            launchctl load "$PLIST"
            echo "[OK] Loaded: $AGENT"
        done
        echo ""
        echo "Agents installed. Schedules (Asia/Shanghai / CST local time):"
        echo "  slot1:  07:00 daily"
        echo "  slot2:  12:00 daily"
        echo "  slot3:  16:00 daily"
        echo "  slot4:  20:00 daily"
        echo "  slot5:  23:00 daily"
        echo "  review: 00:00 daily"
        echo ""
        echo "NOTE: Remove the pepperbot cron entries to avoid double-firing:"
        echo "  crontab -e  # delete lines for pepperbot-slot* and pepperbot-review"
        ;;
    uninstall)
        echo "Unloading pepperbot launchd agents..."
        for AGENT in "${AGENTS[@]}"; do
            PLIST="$HOME/Library/LaunchAgents/${AGENT}.plist"
            launchctl unload "$PLIST" 2>/dev/null || true
            echo "[OK] Unloaded: $AGENT"
        done
        ;;
    status)
        echo "Pepperbot launchd agent status:"
        for AGENT in "${AGENTS[@]}"; do
            if launchctl list | grep -q "$AGENT"; then
                echo "  [LOADED] $AGENT"
            else
                echo "  [NOT LOADED] $AGENT"
            fi
        done
        ;;
    *)
        echo "Unknown action: $ACTION"
        exit 1
        ;;
esac
