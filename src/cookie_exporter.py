#!/usr/bin/env python3
"""
Export Twitter cookies from a logged-in Chrome (via CDP) to Playwright-native JSON format.

Run this on Mac while Chrome is open and logged into x.com:
  python src/cookie_exporter.py

Output: secrets/twitter_cookies.json (Playwright add_cookies() compatible)

Required cookies: auth_token, ct0 (CSRF token), twid, guest_id
Refresh when: ct0 rotates (causes 403s) or auth_token expires (~30 days)
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

CHROME_CDP = os.environ.get("CHROME_CDP_URL", "http://localhost:9222")
OUTPUT_PATH = Path(os.environ.get(
    "TWITTER_COOKIE_FILE",
    str(Path(__file__).resolve().parent.parent / "secrets" / "twitter_cookies.json"),
))

TWITTER_DOMAINS = {".x.com", ".twitter.com", "x.com", "twitter.com"}
REQUIRED_COOKIES = {"auth_token", "ct0"}


async def export_cookies() -> None:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CHROME_CDP)
        except Exception as exc:
            print(f"[ERROR] Cannot connect to Chrome at {CHROME_CDP}: {exc}", file=sys.stderr)
            print("[ERROR] Start Chrome with:", file=sys.stderr)
            print("  open -a 'Google Chrome' --args --remote-debugging-port=9222", file=sys.stderr)
            sys.exit(1)

        contexts = browser.contexts
        if not contexts:
            print("[ERROR] No browser contexts found", file=sys.stderr)
            sys.exit(1)

        # Collect all cookies from all Twitter-related domains
        all_cookies = await contexts[0].cookies()
        twitter_cookies = [
            c for c in all_cookies
            if any(domain in c.get("domain", "") for domain in TWITTER_DOMAINS)
        ]

        if not twitter_cookies:
            print("[ERROR] No Twitter cookies found — make sure you're logged into x.com", file=sys.stderr)
            sys.exit(1)

        # Verify required cookies are present
        found_names = {c["name"] for c in twitter_cookies}
        missing = REQUIRED_COOKIES - found_names
        if missing:
            print(f"[WARN] Missing critical cookies: {missing}", file=sys.stderr)
            print("[WARN] You may need to log in to x.com first", file=sys.stderr)

        # Playwright add_cookies() requires these fields; fill in defaults for optional ones
        normalized = []
        for cookie in twitter_cookies:
            normalized.append({
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie.get("path", "/"),
                "expires": cookie.get("expires", -1),
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", False),
                "sameSite": cookie.get("sameSite", "None"),
            })

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")

        auth_token = next((c for c in twitter_cookies if c["name"] == "auth_token"), None)
        expires_ts = auth_token.get("expires", -1) if auth_token else -1
        if expires_ts > 0:
            expires_dt = datetime.fromtimestamp(expires_ts).strftime("%Y-%m-%d")
            print(f"[OK] auth_token expires: {expires_dt}")
        else:
            print("[OK] auth_token: session cookie (no expiry stored)")

        print(f"[OK] Exported {len(normalized)} cookies → {OUTPUT_PATH}")
        print(f"[OK] Found: {sorted(found_names)}")


def main() -> None:
    asyncio.run(export_cookies())


if __name__ == "__main__":
    main()
