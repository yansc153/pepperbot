#!/usr/bin/env python3
"""
Generate sample tweet candidates without posting.

Usage (inside container):
  python3 /app/scripts/sample_outputs.py            # 6 samples, default mix
  python3 /app/scripts/sample_outputs.py --count 10 # 10 samples
  python3 /app/scripts/sample_outputs.py --type ai_hot_take --count 5

Scrapes today's AI HOT items, then for each one generates a tweet using
the requested content_type (or rotates through types). Prints generated
text, source URL, and guardrail violations to stdout — does not write to
the DB and does not post anything.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scraper import scrape_all_news  # noqa: E402
from writer import write_tweet  # noqa: E402
from guardrails import run_all_guardrails  # noqa: E402
from learner import get_learned_techniques  # noqa: E402
from database import init_database  # noqa: E402


CONTENT_TYPES = ["ai_hot_take", "ai_tool_review", "startup_cognition", "controversy"]


async def main(count: int, fixed_type: str | None) -> None:
    init_database()

    print(f"\n[sample_outputs] scraping AI HOT items...")
    items = await scrape_all_news()
    print(f"[sample_outputs] got {len(items)} items, generating {count} samples...\n")

    if not items:
        print("ERROR: no news items available — check AI HOT API")
        return

    techniques = get_learned_techniques()
    generated = 0

    for i, item in enumerate(items):
        if generated >= count:
            break

        ctype = fixed_type or CONTENT_TYPES[i % len(CONTENT_TYPES)]
        source = f"标题: {item.title}"
        if item.summary:
            source += f"\n摘要: {item.summary}"

        try:
            result = await write_tweet(
                content_type=ctype,
                source_material=source,
                techniques=techniques,
            )
        except Exception as exc:
            print(f"=== [{i+1}] {ctype} — GENERATION ERROR: {exc}\n")
            continue

        if not result:
            print(f"=== [{i+1}] {ctype} — write_tweet returned None\n")
            continue

        tweet = result.get("tweet", "")
        violations = run_all_guardrails(tweet)
        generated += 1

        print("=" * 70)
        print(f"#{generated}  type={ctype}  source={item.source}")
        print(f"原文: {item.title}")
        print(f"来源: {item.url}")
        print("-" * 70)
        print(tweet)
        print("-" * 70)
        if violations:
            print(f"⚠️  guardrail violations: {violations}")
        else:
            print("✅ guardrails passed")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sample tweet candidates")
    parser.add_argument("--count", type=int, default=6, help="Number of samples to generate")
    parser.add_argument(
        "--type",
        choices=CONTENT_TYPES,
        default=None,
        help="Fix content_type (default: rotate through all types)",
    )
    args = parser.parse_args()

    asyncio.run(main(args.count, args.type))
