#!/bin/bash
# Open Chrome with remote debugging port for pepperbot automation
pkill -9 -f "Google Chrome" 2>/dev/null || true
sleep 2
rm -f "$HOME/.pepperbot-chrome/SingletonLock" "$HOME/.pepperbot-chrome/SingletonCookie" 2>/dev/null
nohup /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --remote-allow-origins='*' \
  --user-data-dir="$HOME/.pepperbot-chrome" \
  --no-first-run \
  > /tmp/chrome_pepperbot.log 2>&1 &
echo "Chrome started (PID $!), debug port 9222 ready in ~10s"
