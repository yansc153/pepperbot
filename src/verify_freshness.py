#!/usr/bin/env python3
"""
Verify that an article was published recently enough to post.
Usage: python3 verify_freshness.py <url> [target_hours=4] [max_hours=48]

Output:
  FRESH: Xh ago (...)      — within target window, use it
  STALE: Xh ago (...)      — older than target but within max, prefer a newer one
  TOO_OLD: Xh ago (...)    — beyond max, must replace
  NO_DATE: cannot verify   — no date found, allowed with warning
  FETCH_FAILED: ...        — network error, allowed with warning

Exit code: 0 = usable, 1 = must replace
"""

import re
import sys
import urllib.request
from datetime import datetime, timezone


def fetch_html(url: str) -> str | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def parse_date(html: str) -> datetime | None:
    patterns = [
        r'property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time',
        r'<time[^>]+datetime=["\']([^"\'Z][^"\']+)',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"publishedAt"\s*:\s*"([^"]+)"',
        r'name=["\']publishdate["\'][^>]+content=["\']([^"\']+)',
        r'content=["\']([^"\']+)["\'][^>]+name=["\']publishdate',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if not m:
            continue
        raw = m.group(1).strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def check(url: str, target_hours: int = 4, max_hours: int = 48) -> tuple[str, int]:
    html = fetch_html(url)
    if html is None:
        return "FETCH_FAILED: network error — allowed with warning", 0

    pub_time = parse_date(html)
    if pub_time is None:
        return "NO_DATE: cannot verify — allowed but prefer articles with clear timestamps", 0

    now = datetime.now(timezone.utc)
    age_hours = (now - pub_time).total_seconds() / 3600
    pub_str = pub_time.strftime("%Y-%m-%d %H:%M UTC")

    if age_hours <= target_hours:
        return f"FRESH: {age_hours:.1f}h ago ({pub_str})", 0
    elif age_hours <= max_hours:
        return f"STALE: {age_hours:.1f}h ago ({pub_str}) — 可用但优先找更新文章", 0
    else:
        return f"TOO_OLD: {age_hours:.1f}h ago ({pub_str}) — 超过{max_hours}小时，必须换一篇", 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: verify_freshness.py <url> [target_hours=4] [max_hours=48]")
        sys.exit(1)

    url = sys.argv[1]
    target_hours = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    max_hours = int(sys.argv[3]) if len(sys.argv) > 3 else 48

    msg, code = check(url, target_hours, max_hours)
    print(msg)
    sys.exit(code)
