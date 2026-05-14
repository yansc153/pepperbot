#!/usr/bin/env python3
"""
Extract og:image URL from a web article.

Usage:
  python3 extract_ogimage.py "https://techcrunch.com/..."

Output:
  Prints the og:image URL to stdout.
  Prints "NO_IMAGE" if not found or fetch fails.
"""

import re
import ssl
import sys
import urllib.request
from urllib.parse import urljoin, urlparse


def fetch_html(url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as r:
        charset = "utf-8"
        content_type = r.headers.get("Content-Type", "")
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].strip()
        return r.read().decode(charset, errors="replace")


def extract_og_image(html: str, base_url: str) -> str | None:
    # Try og:image first
    m = re.search(
        r'<meta\s[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    )
    if not m:
        # Some sites put content before property
        m = re.search(
            r'<meta\s[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
            html, re.IGNORECASE
        )
    if not m:
        # twitter:image as fallback
        m = re.search(
            r'<meta\s[^>]*name=["\']twitter:image["\'][^>]*content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
    if not m:
        m = re.search(
            r'<meta\s[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']twitter:image["\']',
            html, re.IGNORECASE
        )

    if m:
        img_url = m.group(1).strip()
        # Resolve relative URLs
        if img_url.startswith("//"):
            parsed = urlparse(base_url)
            img_url = f"{parsed.scheme}:{img_url}"
        elif img_url.startswith("/"):
            img_url = urljoin(base_url, img_url)
        return img_url
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 extract_ogimage.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1].strip()

    try:
        html = fetch_html(url)
        img_url = extract_og_image(html, url)
        if img_url:
            print(img_url)
        else:
            print("NO_IMAGE")
    except Exception as e:
        print(f"[WARN] fetch failed: {e}", file=sys.stderr)
        print("NO_IMAGE")


if __name__ == "__main__":
    main()
