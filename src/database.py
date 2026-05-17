"""
SQLite database layer.
Schema: posts, kol_comments, engagement_log, learning_log, strategy_weights.
All writes use transactions. Backup before schema changes.
"""

import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from config import DB_PATH


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database(db_path: Path = DB_PATH) -> None:
    """Create all tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    with conn:
        conn.executescript(SCHEMA_SQL)
    conn.close()


SCHEMA_SQL = """
-- Published posts
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL,  -- ai_hot_take / ai_tool_review / startup_cognition / controversy / kol_interaction
    image_prompt TEXT,
    image_path TEXT,
    score_stance INTEGER DEFAULT 0,
    score_receipts INTEGER DEFAULT 0,
    score_counter INTEGER DEFAULT 0,
    score_audience INTEGER DEFAULT 0,
    score_total INTEGER DEFAULT 0,
    source_url TEXT,
    source_title TEXT,
    tweet_url TEXT,              -- URL of published tweet (for metrics scraping)
    published_at TEXT,
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    is_viral INTEGER DEFAULT 0,
    viral_techniques TEXT,  -- JSON list of techniques attributed to this post
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- KOL comments we posted
CREATE TABLE IF NOT EXISTS kol_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kol_handle TEXT NOT NULL,
    kol_tier TEXT NOT NULL,
    original_post_url TEXT NOT NULL,
    original_post_snippet TEXT,
    comment_text TEXT NOT NULL,
    content_hash TEXT UNIQUE NOT NULL,
    commented_at TEXT,
    likes_received INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Engagement actions (likes, follows, retweets)
CREATE TABLE IF NOT EXISTS engagement_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,  -- like / follow / retweet
    target_handle TEXT,
    target_url TEXT,
    executed_at TEXT DEFAULT (datetime('now'))
);

-- Self-learning log
CREATE TABLE IF NOT EXISTS learning_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_type TEXT NOT NULL,  -- own_post_analysis / kol_viral_extraction
    source_post_id INTEGER,  -- FK to posts.id (for own_post_analysis)
    kol_handle TEXT,          -- (for kol_viral_extraction)
    kol_post_url TEXT,
    techniques_extracted TEXT,  -- JSON
    strategy_adjustment TEXT,  -- JSON describing what changed
    applied_at TEXT DEFAULT (datetime('now'))
);

-- Strategy weights over time
CREATE TABLE IF NOT EXISTS strategy_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ai_hot_take REAL NOT NULL,
    ai_tool_review REAL NOT NULL,
    startup_cognition REAL NOT NULL,
    controversy REAL NOT NULL,
    kol_interaction REAL NOT NULL,
    reason TEXT,
    recorded_at TEXT DEFAULT (datetime('now'))
);

-- Daily stats
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    posts_count INTEGER DEFAULT 0,
    comments_count INTEGER DEFAULT 0,
    likes_given INTEGER DEFAULT 0,
    follows_given INTEGER DEFAULT 0,
    total_impressions INTEGER DEFAULT 0,
    total_likes_received INTEGER DEFAULT 0,
    total_retweets_received INTEGER DEFAULT 0,
    follower_count INTEGER DEFAULT 0,
    best_post_id INTEGER,
    worst_post_id INTEGER,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Circuit breaker state
CREATE TABLE IF NOT EXISTS circuit_breaker (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    consecutive_zero_interaction INTEGER DEFAULT 0,
    is_paused INTEGER DEFAULT 0,
    paused_at TEXT,
    resumed_at TEXT,
    last_checked_at TEXT
);

-- Slop dictionary (learnable, append-only)
CREATE TABLE IF NOT EXISTS slop_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT UNIQUE NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('A', 'B', 'C')),
    added_at TEXT DEFAULT (datetime('now'))
);

-- Technique library (from KOL viral learning)
CREATE TABLE IF NOT EXISTS technique_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    technique_name TEXT NOT NULL,
    description TEXT NOT NULL,
    example_text TEXT,
    source_kol TEXT,
    source_url TEXT,
    times_used INTEGER DEFAULT 0,
    success_rate REAL DEFAULT 0.0,
    added_at TEXT DEFAULT (datetime('now'))
);

-- Continuous KOL reaction observation (read-only learning input)
CREATE TABLE IF NOT EXISTS reaction_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url TEXT UNIQUE NOT NULL,
    kol_handle TEXT NOT NULL,
    post_text TEXT NOT NULL,
    posted_at TEXT,
    observed_at TEXT DEFAULT (datetime('now')),
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0
);

-- Initialize circuit breaker row
INSERT OR IGNORE INTO circuit_breaker (id, consecutive_zero_interaction, is_paused)
VALUES (1, 0, 0);
"""


def content_hash(text: str) -> str:
    """SHA256 hash for dedup."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:32]


# ── Post operations ──

def insert_post(
    conn: sqlite3.Connection,
    content: str,
    content_type: str,
    image_prompt: str = "",
    scores: Optional[dict[str, int]] = None,
    source_url: str = "",
    source_title: str = "",
) -> int:
    """Insert a new post. Returns post id."""
    scores = scores or {}
    chash = content_hash(content)
    with conn:
        cursor = conn.execute(
            """INSERT INTO posts (content_hash, content, content_type, image_prompt,
               score_stance, score_receipts, score_counter, score_audience, score_total,
               source_url, source_title)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chash, content, content_type, image_prompt,
                scores.get("stance", 0), scores.get("receipts", 0),
                scores.get("counter", 0), scores.get("audience", 0),
                scores.get("total", 0),
                source_url, source_title,
            ),
        )
    return cursor.lastrowid


def mark_post_published(conn: sqlite3.Connection, post_id: int, tweet_url: str | None = "") -> None:
    with conn:
        conn.execute(
            "UPDATE posts SET published_at = ?, tweet_url = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), tweet_url or "", post_id),
        )


def update_post_metrics(
    conn: sqlite3.Connection,
    post_id: int,
    likes: int,
    retweets: int,
    replies: int,
    impressions: int,
) -> None:
    with conn:
        conn.execute(
            """UPDATE posts SET likes = ?, retweets = ?, replies = ?,
               impressions = ?, updated_at = datetime('now') WHERE id = ?""",
            (likes, retweets, replies, impressions, post_id),
        )


def is_duplicate(conn: sqlite3.Connection, content: str) -> bool:
    chash = content_hash(content)
    row = conn.execute(
        "SELECT 1 FROM posts WHERE content_hash = ? LIMIT 1", (chash,)
    ).fetchone()
    return row is not None


def get_recent_posts(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_today_post_count(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE published_at LIKE ?", (f"{today}%",)
    ).fetchone()
    return row[0] if row else 0


def get_posts_needing_metrics(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Get published posts that have a tweet_url, for metrics scraping."""
    rows = conn.execute(
        """SELECT * FROM posts
           WHERE published_at IS NOT NULL
             AND tweet_url IS NOT NULL
             AND tweet_url != ''
           ORDER BY published_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Reaction observations ──

def insert_reaction_observation(
    conn: sqlite3.Connection,
    kol_handle: str,
    post_url: str,
    post_text: str,
    posted_at: str = "",
    likes: int = 0,
    retweets: int = 0,
    replies: int = 0,
) -> int:
    """Insert a raw KOL reaction sample. Duplicate post URLs are ignored."""
    with conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO reaction_observations
               (post_url, kol_handle, post_text, posted_at, likes, retweets, replies)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (post_url, kol_handle, post_text, posted_at, likes, retweets, replies),
        )
    return cursor.lastrowid


def get_recent_reaction_observations(
    conn: sqlite3.Connection,
    since_hours: int = 8,
    limit: int = 60,
) -> list[dict]:
    """Get recent KOL reactions for reaction-pack distillation."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    rows = conn.execute(
        """SELECT * FROM reaction_observations
           WHERE COALESCE(posted_at, observed_at) >= ?
           ORDER BY COALESCE(posted_at, observed_at) DESC
           LIMIT ?""",
        (cutoff, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── KOL comment operations ──

def insert_kol_comment(
    conn: sqlite3.Connection,
    kol_handle: str,
    kol_tier: str,
    original_post_url: str,
    original_post_snippet: str,
    comment_text: str,
) -> int:
    chash = content_hash(f"{kol_handle}:{comment_text}")
    with conn:
        cursor = conn.execute(
            """INSERT INTO kol_comments
               (kol_handle, kol_tier, original_post_url, original_post_snippet,
                comment_text, content_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (kol_handle, kol_tier, original_post_url, original_post_snippet,
             comment_text, chash),
        )
    return cursor.lastrowid


def get_today_comment_count(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) FROM kol_comments WHERE created_at LIKE ?", (f"{today}%",)
    ).fetchone()
    return row[0] if row else 0


# ── Circuit breaker ──

def get_circuit_breaker(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT * FROM circuit_breaker WHERE id = 1").fetchone()
    return dict(row) if row else {"consecutive_zero_interaction": 0, "is_paused": False}


def update_circuit_breaker(
    conn: sqlite3.Connection,
    consecutive_zeros: int,
    is_paused: bool,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """UPDATE circuit_breaker SET
               consecutive_zero_interaction = ?,
               is_paused = ?,
               paused_at = CASE WHEN ? = 1 THEN ? ELSE paused_at END,
               resumed_at = CASE WHEN ? = 0 AND is_paused = 1 THEN ? ELSE resumed_at END,
               last_checked_at = ?
               WHERE id = 1""",
            (consecutive_zeros, int(is_paused),
             int(is_paused), now,
             int(is_paused), now, now),
        )


# ── Strategy weights ──

def save_strategy_weights(
    conn: sqlite3.Connection,
    weights: dict[str, float],
    reason: str = "",
) -> None:
    with conn:
        conn.execute(
            """INSERT INTO strategy_weights
               (ai_hot_take, ai_tool_review, startup_cognition, controversy, kol_interaction, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                weights["ai_hot_take"], weights["ai_tool_review"],
                weights["startup_cognition"], weights["controversy"],
                weights["kol_interaction"], reason,
            ),
        )


def get_latest_weights(conn: sqlite3.Connection) -> Optional[dict[str, float]]:
    row = conn.execute(
        "SELECT * FROM strategy_weights ORDER BY recorded_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return {
        "ai_hot_take": row["ai_hot_take"],
        "ai_tool_review": row["ai_tool_review"],
        "startup_cognition": row["startup_cognition"],
        "controversy": row["controversy"],
        "kol_interaction": row["kol_interaction"],
    }


# ── Engagement log ──

def log_engagement(
    conn: sqlite3.Connection,
    action_type: str,
    target_handle: str = "",
    target_url: str = "",
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO engagement_log (action_type, target_handle, target_url) VALUES (?, ?, ?)",
            (action_type, target_handle, target_url),
        )


def get_today_engagement_count(conn: sqlite3.Connection, action_type: str) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) FROM engagement_log WHERE action_type = ? AND executed_at LIKE ?",
        (action_type, f"{today}%"),
    ).fetchone()
    return row[0] if row else 0


# ── Technique library ──

def insert_technique(
    conn: sqlite3.Connection,
    technique_name: str,
    description: str,
    example_text: str = "",
    source_kol: str = "",
    source_url: str = "",
) -> int:
    with conn:
        cursor = conn.execute(
            """INSERT INTO technique_library
               (technique_name, description, example_text, source_kol, source_url)
               VALUES (?, ?, ?, ?, ?)""",
            (technique_name, description, example_text, source_kol, source_url),
        )
    return cursor.lastrowid


def get_all_techniques(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM technique_library ORDER BY success_rate DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Learning log ──

def insert_learning_log(
    conn: sqlite3.Connection,
    learning_type: str,
    source_post_id: int | None = None,
    kol_handle: str = "",
    kol_post_url: str = "",
    techniques_extracted: str = "",
    strategy_adjustment: str = "",
) -> int:
    with conn:
        cursor = conn.execute(
            """INSERT INTO learning_log
               (learning_type, source_post_id, kol_handle, kol_post_url,
                techniques_extracted, strategy_adjustment)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                learning_type,
                source_post_id,
                kol_handle,
                kol_post_url,
                techniques_extracted,
                strategy_adjustment,
            ),
        )
    return cursor.lastrowid


# ── Daily stats ──

def upsert_daily_stats(conn: sqlite3.Connection, stats: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with conn:
        conn.execute(
            """INSERT INTO daily_stats (date, posts_count, comments_count,
               likes_given, follows_given, total_impressions, total_likes_received,
               total_retweets_received, follower_count, best_post_id, worst_post_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               posts_count = excluded.posts_count,
               comments_count = excluded.comments_count,
               likes_given = excluded.likes_given,
               follows_given = excluded.follows_given,
               total_impressions = excluded.total_impressions,
               total_likes_received = excluded.total_likes_received,
               total_retweets_received = excluded.total_retweets_received,
               follower_count = excluded.follower_count,
               best_post_id = excluded.best_post_id,
               worst_post_id = excluded.worst_post_id,
               notes = excluded.notes""",
            (
                today,
                stats.get("posts_count", 0),
                stats.get("comments_count", 0),
                stats.get("likes_given", 0),
                stats.get("follows_given", 0),
                stats.get("total_impressions", 0),
                stats.get("total_likes_received", 0),
                stats.get("total_retweets_received", 0),
                stats.get("follower_count", 0),
                stats.get("best_post_id"),
                stats.get("worst_post_id"),
                stats.get("notes", ""),
            ),
        )
