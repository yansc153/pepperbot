"""
Deterministic hard guardrails. Zero LLM tokens in this module.
Regex-based validators for anti-slop, banned keywords, length, dedup.
These are immutable code-level rules that LLM cannot override.
"""

import re
from dataclasses import dataclass
from enum import Enum


class SlopSeverity(Enum):
    A = "A"  # kill immediately
    B = "B"  # must rewrite
    C = "C"  # caution


@dataclass
class GuardrailResult:
    passed: bool
    severity: SlopSeverity | None = None
    matched_patterns: list[str] | None = None
    reason: str = ""


# ── A-class: kill on sight ──

A_CLASS_PATTERNS = [
    # A1: AI腔通用词
    r"赋能", r"打造", r"构建", r"构筑", r"布局", r"业态",
    r"让我们深入探讨", r"让我们一起来看看", r"不难发现",
    r"值得我们深思", r"引发广泛关注", r"具有重要意义",
    r"综上所述", r"总而言之", r"概括来说",
    r"在当今.{0,6}时代", r"随着.{0,10}的快速发展",
    r"站在风口", r"迎来机遇", r"迈向新高度",
    r"数字化转型", r"赋能千行百业", r"践行使命",
    # A2: 自杀词
    r"必涨", r"稳赚", r"无风险套利",
    r"建议买入", r"建议卖出", r"强烈推荐",
    r"内幕消息", r"跟我喊单",
    # A3: 万能模糊词 (no source)
    r"专家表示", r"业内人士透露", r"权威人士指出",
    r"相关人士", r"有关方面",
    # A4: 排版症
    r"——",  # dash
    r"！{2,}",  # consecutive exclamation marks
    # A5: v2
    r"市场已经证明",
]

# A4 special: triple staccato (X。X。X。)
TRIPLE_STACCATO_PATTERN = re.compile(
    r"[^。]{1,8}。[^。]{1,8}。[^。]{1,8}。"
)

# ── B-class: must rewrite ──

B_CLASS_PATTERNS = [
    # B1: vague quantification
    r"大幅增长", r"显著下滑", r"不少人", r"市场普遍认为",
    # B2: empty value judgments
    r"具有重大意义", r"值得关注", r"不容忽视", r"至关重要",
    # B3: generic verbs
    r"驱动", r"带动", r"引领", r"优化",
    # B4: bland subjects
    r"投资者应当", r"我们要", r"市场告诉我们",
    # B5: v2
    r"本质上", r"长期来看", r"效率提升",
]

# ── C-class: caution ──

C_CLASS_PATTERNS = [
    # C1: generic openers
    r"^最近", r"^关于.{0,10}我想说", r"^不知道大家有没有",
    # C2: internet slang
    r"家人们", r"集美们", r"友友们",
    r"真的栓Q", r"绝绝子",
    # C3: self-deprecating openers
    r"我个人比较菜", r"以下纯属个人观点", r"轻喷",
    # C4: banned emoji
    r"🔥", r"🚀", r"📈", r"📉",
]

# ── Source-post metadata (zero tolerance) ──

SOURCE_META_PATTERNS = [
    r"原帖", r"原话", r"这帖", r"文章里",
    r"\d+万浏览", r"\d+收藏", r"\d+评论",
    r"Reddit", r"掘金", r"知乎", r"Hacker\s*News", r"雪球",
    r"据.{0,10}报道", r"来源：",
]

# ── Persona hard exclusions ──

BANNED_TOPIC_PATTERNS = [
    r"习近平", r"李克强", r"共产党", r"六四", r"天安门",
    r"新疆", r"西藏", r"民主运动", r"台独",
    r"暴富", r"梭哈", r"all\s*in.*喊.*粉丝",
    r"买入价", r"目标价", r"翻倍.*保证",
    r"活在当下", r"追梦",
]

# ── Voice "never" words ──

NEVER_WORDS = [
    r"赋能", r"格局", r"综上所述", r"建议大家", r"你怎么看",
    r"宝子们", r"家人们", r"兄弟们", r"干货", r"yyds", r"绝绝子",
    r"财富自由", r"分享一下我的看法", r"个人浅见",
    r"可能.*可能.*可能",  # triple hedge
    r"也许", r"或许",
]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p) for p in patterns]


_A_COMPILED = _compile_patterns(A_CLASS_PATTERNS)
_B_COMPILED = _compile_patterns(B_CLASS_PATTERNS)
_C_COMPILED = _compile_patterns(C_CLASS_PATTERNS)
_SOURCE_COMPILED = _compile_patterns(SOURCE_META_PATTERNS)
_BANNED_COMPILED = _compile_patterns(BANNED_TOPIC_PATTERNS)
_NEVER_COMPILED = _compile_patterns(NEVER_WORDS)


def check_slop_a(text: str) -> GuardrailResult:
    """A-class scan: any match → kill."""
    matched = []
    for pattern in _A_COMPILED:
        if pattern.search(text):
            matched.append(pattern.pattern)
    if TRIPLE_STACCATO_PATTERN.search(text):
        matched.append("triple_staccato")
    if matched:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.A,
            matched_patterns=matched, reason="A-class slop detected"
        )
    return GuardrailResult(passed=True)


def check_slop_b(text: str) -> GuardrailResult:
    """B-class scan: any match → rewrite that expression."""
    matched = []
    for pattern in _B_COMPILED:
        if pattern.search(text):
            matched.append(pattern.pattern)
    if matched:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.B,
            matched_patterns=matched, reason="B-class slop: rewrite needed"
        )
    return GuardrailResult(passed=True)


def check_slop_c(text: str) -> GuardrailResult:
    """C-class scan: ≤2 matches → pass; >2 → rewrite."""
    matched = []
    for pattern in _C_COMPILED:
        if pattern.search(text):
            matched.append(pattern.pattern)
    if len(matched) > 2:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.C,
            matched_patterns=matched, reason="Too many C-class patterns (>2)"
        )
    return GuardrailResult(passed=True)


def check_source_metadata(text: str) -> GuardrailResult:
    """Source-post metadata: zero tolerance."""
    matched = []
    for pattern in _SOURCE_COMPILED:
        if pattern.search(text):
            matched.append(pattern.pattern)
    if matched:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.A,
            matched_patterns=matched, reason="Source metadata leak"
        )
    return GuardrailResult(passed=True)


def check_banned_topics(text: str) -> GuardrailResult:
    """Persona hard exclusions."""
    matched = []
    for pattern in _BANNED_COMPILED:
        if pattern.search(text):
            matched.append(pattern.pattern)
    if matched:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.A,
            matched_patterns=matched, reason="Banned topic detected"
        )
    return GuardrailResult(passed=True)


def check_never_words(text: str) -> GuardrailResult:
    """Voice profile never-use words."""
    matched = []
    for pattern in _NEVER_COMPILED:
        if pattern.search(text):
            matched.append(pattern.pattern)
    if matched:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.A,
            matched_patterns=matched, reason="Voice never-word detected"
        )
    return GuardrailResult(passed=True)


def check_length(text: str, max_length: int = 280) -> GuardrailResult:
    """Tweet must be ≤ max_length characters."""
    if len(text) > max_length:
        return GuardrailResult(
            passed=False, reason=f"Too long: {len(text)}/{max_length}"
        )
    return GuardrailResult(passed=True)


def check_emoji_count(text: str, max_emoji: int = 2) -> GuardrailResult:
    """Max 2 emoji per tweet. 🔥🚀📈📉 banned entirely."""
    import emoji as emoji_lib
    emoji_list = emoji_lib.emoji_list(text)
    if len(emoji_list) > max_emoji:
        return GuardrailResult(
            passed=False,
            reason=f"Too many emoji: {len(emoji_list)}/{max_emoji}"
        )
    return GuardrailResult(passed=True)


def check_first_line_length(text: str, max_chars: int = 20) -> GuardrailResult:
    """First line must be ≤ 20 characters."""
    first_line = text.split("\n")[0].strip()
    if len(first_line) > max_chars:
        return GuardrailResult(
            passed=False,
            reason=f"First line too long: {len(first_line)}/{max_chars} chars"
        )
    return GuardrailResult(passed=True)


def check_line_ending_periods(text: str) -> GuardrailResult:
    """Lines must not end with 。(Chinese period). A-class kill."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    bad_lines = [l for l in lines if l.endswith("。")]
    if bad_lines:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.A,
            matched_patterns=bad_lines[:3],
            reason="Lines ending with period detected"
        )
    return GuardrailResult(passed=True)


def check_structure_labels(text: str) -> GuardrailResult:
    """No structural labels like 对的部分：/ 问题在于：. A-class kill."""
    label_pattern = re.compile(
        r"(对的部分|错的部分|问题在于|值得关注|关键在于|重点是|总结|结论)[：:]"
    )
    matches = label_pattern.findall(text)
    if matches:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.A,
            matched_patterns=matches,
            reason="Structure labels detected"
        )
    return GuardrailResult(passed=True)


def check_commas(text: str) -> GuardrailResult:
    """Chinese commas should be replaced with spaces. B-class rewrite."""
    comma_count = text.count("，")
    if comma_count >= 3:
        return GuardrailResult(
            passed=False, severity=SlopSeverity.B,
            matched_patterns=[f"found {comma_count} commas"],
            reason="Too many commas — replace with spaces"
        )
    return GuardrailResult(passed=True)


def run_all_guardrails(text: str) -> list[GuardrailResult]:
    """
    Run the full guardrail pipeline.
    Returns list of all failed checks. Empty list = all passed.
    Order: A → source_meta → banned_topics → never_words → B → C → length → first_line
    """
    failures = []

    checks = [
        check_slop_a,
        check_source_metadata,
        check_banned_topics,
        check_never_words,
        check_line_ending_periods,
        check_structure_labels,
        check_slop_b,
        check_commas,
        check_slop_c,
        check_length,
        check_first_line_length,
        check_emoji_count,
    ]

    for check_fn in checks:
        result = check_fn(text)
        if not result.passed:
            failures.append(result)

    return failures


def has_kill_violation(text: str) -> bool:
    """Quick check: does this text have any A-class / kill-level violation?"""
    for check_fn in [check_slop_a, check_source_metadata, check_banned_topics, check_never_words, check_line_ending_periods, check_structure_labels]:
        if not check_fn(text).passed:
            return True
    return False
