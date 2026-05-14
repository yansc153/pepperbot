"""Shared utilities for the pepperbot pipeline."""


def tweet_weight(text: str) -> int:
    """Twitter weighted character count. CJK characters count as 2, others as 1.

    Twitter's limit is 280 weighted units. A 140-char Chinese tweet hits the limit.
    Reference: https://developer.twitter.com/en/docs/counting-characters
    """
    weight = 0
    for ch in text:
        cp = ord(ch)
        # CJK Unified Ideographs and extensions, Hiragana, Katakana,
        # Hangul, CJK Compatibility, Fullwidth, and other wide ranges
        if (
            0x1100 <= cp <= 0x115F   # Hangul Jamo
            or 0x2E80 <= cp <= 0x9FFF  # CJK, Kangxi, Hiragana, Katakana, Bopomofo
            or 0xA000 <= cp <= 0xA4CF  # Yi
            or 0xA960 <= cp <= 0xA97F  # Hangul Jamo Extended-A
            or 0xAC00 <= cp <= 0xD7FF  # Hangul Syllables + Jamo Extended-B
            or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility Ideographs
            or 0xFE10 <= cp <= 0xFE1F  # Vertical Forms
            or 0xFE30 <= cp <= 0xFE6F  # CJK Compatibility Forms, Small Forms
            or 0xFF00 <= cp <= 0xFFEF  # Halfwidth/Fullwidth Forms
            or 0x1B000 <= cp <= 0x1B0FF  # Kana Supplement
            or 0x1F004 <= cp <= 0x1F0CF  # Mahjong / Playing Cards (wide emoji)
            or 0x20000 <= cp <= 0x2FA1F  # CJK Extension B-F, Compat Supplement
        ):
            weight += 2
        else:
            weight += 1
    return weight


MAX_TWEET_WEIGHT = 280
