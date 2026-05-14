"""
Obsidian-compatible daily logging.
Writes markdown logs to logs/ directory in YYYY-MM-DD.md format.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from config import LOGS_DIR

logger = logging.getLogger(__name__)


def _get_log_path(date: datetime | None = None) -> Path:
    if date is None:
        date = datetime.now()
    return LOGS_DIR / f"{date.strftime('%Y-%m-%d')}.md"


def _ensure_log_file(path: Path) -> None:
    """Create today's log file with header if it doesn't exist."""
    if not path.exists():
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        date_str = path.stem
        header = f"""# Daily Log — {date_str}

> @pepperfr1ends 自动化运营日志

---

## 发帖记录

| # | 时间 | 类型 | 内容摘要 | 分数 | 互动 |
|---|------|------|---------|------|------|

## KOL评论记录

| # | 时间 | KOL | 评论摘要 |
|---|------|-----|---------|

## 互动记录

- 点赞: 0
- 关注: 0

## 数据汇总

| 指标 | 数值 |
|------|------|
| 发帖数 | 0 |
| 评论数 | 0 |
| 总曝光 | 0 |
| 粉丝数 | - |

## 策略调整

> 无

## 学习记录

> 无

## 系统状态

> 正常运行

"""
        path.write_text(header, encoding="utf-8")


def log_post(
    content: str,
    content_type: str,
    score_total: int,
    post_number: int,
) -> None:
    """Log a published post."""
    path = _get_log_path()
    _ensure_log_file(path)

    now = datetime.now().strftime("%H:%M")
    snippet = content[:40].replace("\n", " ").replace("|", "/")

    line = f"| {post_number} | {now} | {content_type} | {snippet} | {score_total} | - |\n"

    _append_after_marker(path, "## 发帖记录", line, after_table_header=True)


def log_kol_comment(
    kol_handle: str,
    comment_text: str,
    comment_number: int,
) -> None:
    """Log a KOL comment."""
    path = _get_log_path()
    _ensure_log_file(path)

    now = datetime.now().strftime("%H:%M")
    snippet = comment_text[:40].replace("\n", " ").replace("|", "/")

    line = f"| {comment_number} | {now} | {kol_handle} | {snippet} |\n"

    _append_after_marker(path, "## KOL评论记录", line, after_table_header=True)


def log_engagement_stats(likes: int, follows: int) -> None:
    """Update engagement stats in today's log."""
    path = _get_log_path()
    _ensure_log_file(path)

    content = path.read_text(encoding="utf-8")
    content = content.replace("- 点赞: 0", f"- 点赞: {likes}")
    content = content.replace("- 关注: 0", f"- 关注: {follows}")
    path.write_text(content, encoding="utf-8")


def log_daily_summary(stats: dict) -> None:
    """Write end-of-day summary."""
    path = _get_log_path()
    _ensure_log_file(path)

    content = path.read_text(encoding="utf-8")

    # Update data summary table
    replacements = {
        "| 发帖数 | 0 |": f"| 发帖数 | {stats.get('posts_count', 0)} |",
        "| 评论数 | 0 |": f"| 评论数 | {stats.get('comments_count', 0)} |",
        "| 总曝光 | 0 |": f"| 总曝光 | {stats.get('total_impressions', 0)} |",
        "| 粉丝数 | - |": f"| 粉丝数 | {stats.get('follower_count', '-')} |",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    path.write_text(content, encoding="utf-8")


def log_strategy_change(reasoning: str) -> None:
    """Log a strategy adjustment."""
    path = _get_log_path()
    _ensure_log_file(path)

    content = path.read_text(encoding="utf-8")
    content = content.replace(
        "## 策略调整\n\n> 无",
        f"## 策略调整\n\n- {datetime.now().strftime('%H:%M')}: {reasoning}",
    )
    path.write_text(content, encoding="utf-8")


def log_learning(techniques: list[str]) -> None:
    """Log learned techniques."""
    path = _get_log_path()
    _ensure_log_file(path)

    content = path.read_text(encoding="utf-8")
    tech_str = "\n".join(f"- {t}" for t in techniques)
    content = content.replace(
        "## 学习记录\n\n> 无",
        f"## 学习记录\n\n{tech_str}",
    )
    path.write_text(content, encoding="utf-8")


def log_system_event(event: str, level: str = "INFO") -> None:
    """Log a system event (errors, circuit breaker, etc.)."""
    path = _get_log_path()
    _ensure_log_file(path)

    now = datetime.now().strftime("%H:%M")
    entry = f"\n- [{level}] {now}: {event}"

    content = path.read_text(encoding="utf-8")
    if "## 系统状态" in content:
        content = content.replace(
            "## 系统状态\n\n> 正常运行",
            f"## 系统状态{entry}",
        )
        # If already has entries, append
        if "## 系统状态" in content and "> 正常运行" not in content:
            parts = content.split("## 系统状态")
            content = f"{parts[0]}## 系统状态{parts[1]}{entry}"
    path.write_text(content, encoding="utf-8")


def _append_after_marker(
    path: Path,
    marker: str,
    line: str,
    after_table_header: bool = False,
) -> None:
    """Append a line after a section marker, optionally after table header."""
    content = path.read_text(encoding="utf-8")
    if marker not in content:
        return

    parts = content.split(marker)
    if len(parts) < 2:
        return

    section = parts[1]
    if after_table_header:
        # Find end of table header (after |---|...)
        lines = section.split("\n")
        insert_idx = 0
        for i, l in enumerate(lines):
            if l.strip().startswith("|---"):
                insert_idx = i + 1
                break
        # Find last table row (lines starting with |)
        for i in range(insert_idx, len(lines)):
            if not lines[i].strip().startswith("|") and lines[i].strip():
                insert_idx = i
                break
            elif lines[i].strip().startswith("|"):
                insert_idx = i + 1

        lines.insert(insert_idx, line.rstrip())
        parts[1] = "\n".join(lines)
    else:
        parts[1] = f"\n{line}" + parts[1]

    content = marker.join(parts)
    path.write_text(content, encoding="utf-8")
