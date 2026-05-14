"""
Central configuration for @pepperfr1ends automation system.
All constants, paths, and environment variable loading.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field

# ── Project root ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Directory paths ──
CONFIG_DIR = PROJECT_ROOT / "config"
VOICE_DIR = PROJECT_ROOT / "voice"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
OPS_DIR = PROJECT_ROOT / "ops"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
SRC_DIR = PROJECT_ROOT / "src"

# ── Key files ──
DB_PATH = DATA_DIR / "pepperbot.db"
MEMORY_PATH = PROJECT_ROOT / "MEMORY.md"
KOL_LIST_PATH = CONFIG_DIR / "kol_list.md"
PERSONA_PATH = CONFIG_DIR / "persona.md"
FILTER_RULES_PATH = CONFIG_DIR / "filter_rules.md"
AVOID_SLOP_PATH = VOICE_DIR / "avoid_slop.md"
VOICE_PROFILE_PATH = VOICE_DIR / "voice_profile.md"
VOICE_RULES_PATH = VOICE_DIR / "voice_rules.md"
MEMENG_PATH = VOICE_DIR / "memeng_techniques.md"
HOOKS_PATH = TEMPLATES_DIR / "hooks_ai.md"
TEMPLATE_AI_PATH = TEMPLATES_DIR / "template_ai.md"
PLAYWRIGHT_RULES_PATH = OPS_DIR / "playwright_rules.md"

# ── LLM (local Claude CLI) ──
# 不用 API Key，直接调本地 claude 命令行
CLAUDE_CLI_PATH = "claude"  # 如果不在 PATH 里，改成绝对路径
CLAUDE_MODEL = "claude-sonnet-4-6"  # 本地 CLI 用的模型
CLAUDE_MAX_TOKENS = 1024

# ── Twitter account ──
TWITTER_HANDLE = "@pepperfr1ends"
TWITTER_URL = "https://x.com"
TWITTER_HOME = f"{TWITTER_URL}/home"
TWITTER_LOGIN = f"{TWITTER_URL}/login"

# ── Schedule (24h format, Asia/Shanghai) ──
SCHEDULE_TIMEZONE = "Asia/Shanghai"
MORNING_HOUR = 7
NOON_HOUR = 13
EVENING_HOUR = 19
REVIEW_HOUR = 23

# ── Content limits ──
MAX_TWEET_LENGTH = 280
MAX_POSTS_PER_DAY = 20  # hard cap (rate limit guardrail)
MIN_POSTS_PER_DAY = 10
MAX_KOL_COMMENTS_PER_DAY = 15
MIN_KOL_COMMENTS_PER_DAY = 10
MAX_LIKES_PER_DAY = 50
MAX_FOLLOWS_PER_DAY = 10
FILTER_PASS_THRESHOLD = 55
FILTER_REVIEW_THRESHOLD = 40

# ── Content mix weights (initial, learner.py adjusts these) ──
@dataclass
class ContentWeights:
    ai_hot_take: float = 0.35       # AI行业热点快评
    ai_tool_review: float = 0.25    # AI工具实测
    startup_cognition: float = 0.15 # 创业认知
    controversy: float = 0.15      # 争议观点
    kol_interaction: float = 0.10  # KOL互动

    def as_dict(self) -> dict[str, float]:
        return {
            "ai_hot_take": self.ai_hot_take,
            "ai_tool_review": self.ai_tool_review,
            "startup_cognition": self.startup_cognition,
            "controversy": self.controversy,
            "kol_interaction": self.kol_interaction,
        }

    def normalize(self) -> None:
        total = sum(self.as_dict().values())
        if total <= 0:
            return
        self.ai_hot_take /= total
        self.ai_tool_review /= total
        self.startup_cognition /= total
        self.controversy /= total
        self.kol_interaction /= total

DEFAULT_WEIGHTS = ContentWeights()

# ── Self-learning ──
CIRCUIT_BREAKER_THRESHOLD = 5  # consecutive 0-interaction posts → pause
VIRAL_THRESHOLD_LIKES = 50     # post considered "viral" if likes >= this
VIRAL_THRESHOLD_RETWEETS = 20
KOL_VIRAL_THRESHOLD_LIKES = 200  # KOL post considered "viral"

# ── Review/backtest windows ──
REVIEW_WINDOWS_HOURS = [24, 72]  # check post performance at 24h and 72h marks

# ── Browser (Chrome CDP) ──
# 连接已登录的 Chrome 浏览器，不用 Playwright 单独启动
# 启动 Chrome 时加参数: --remote-debugging-port=9222
CHROME_CDP_URL = "http://localhost:9222"
SCREENSHOT_DIR = PROJECT_ROOT / "tmp_screenshots"

# ── AI HOT API (primary news source) ──
AIHOT_BASE_URL = "https://aihot.virxact.com"
AIHOT_ITEMS_URL = f"{AIHOT_BASE_URL}/api/public/items"
AIHOT_DAILY_URL = f"{AIHOT_BASE_URL}/api/public/daily"
AIHOT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) aihot-skill/0.2.0"
AIHOT_MAX_ITEMS = 50  # per request
AIHOT_LOOKBACK_HOURS = 6  # each batch only pulls last 6 hours, avoid repeats

# Category → content_type mapping
AIHOT_CATEGORY_MAP = {
    "ai-models": "ai_hot_take",
    "ai-products": "ai_tool_review",
    "industry": "ai_hot_take",
    "paper": "ai_hot_take",
    "tip": "startup_cognition",
}

# ── Image download ──
IMAGE_CACHE_DIR = PROJECT_ROOT / "tmp_images"
MAX_IMAGE_SIZE_MB = 5  # skip images larger than this

# ── Twitter List for KOL monitoring ──
KOL_LIST_NAME = "AI-KOL-Monitor"  # private list name
KOL_LIST_URL = "https://x.com/i/lists/2034170120671793445"  # 实际 KOL 监控列表

# ── KOL tiers ──
@dataclass
class KOLTier:
    name: str
    priority: int  # 1=highest
    daily_comment_quota: int
    handles: list[str] = field(default_factory=list)

KOL_TIERS = [
    KOLTier(name="tier1", priority=1, daily_comment_quota=5),
    KOLTier(name="tier2", priority=2, daily_comment_quota=3),
    KOLTier(name="tier3", priority=3, daily_comment_quota=2),
]

# ── Logging ──
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
