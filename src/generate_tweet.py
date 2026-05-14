#!/usr/bin/env python3
"""
Pass 1: Generate tweet draft via Moonshot API.

Usage:
  python3 generate_tweet.py --type "AI热点快评" --facts "GM裁600人..." --output /tmp/draft.txt
  python3 generate_tweet.py --type "创业认知" --facts "..." > /tmp/draft.txt
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from tweet_utils import tweet_weight, MAX_TWEET_WEIGHT

API_KEY = os.environ.get("MOONSHOT_API_KEY", "")
BASE_URL = "https://api.moonshot.cn/v1/chat/completions"
MODEL = "moonshot-v1-8k"

SYSTEM = """你是 @pepperfr1ends，网名花椒，中文 Twitter 创业博主，专注 AI 创业 / OPC 赛道。

## 排版铁律（违反即废稿）
- 一句话一行，每行之间空一行
- 行尾不加句号
- 逗号用空格代替（中文「，」→ 空格）
- 不用结构标签（「对的部分：」「问题在于：」等删掉）
- 全文 ≤ 280 字
- 不写元评论（不说「这件事的重点不是X而是Y」，直接说Y）
- 不强行往 OPC/一人公司上拉

## 语气铁律
- 观点坚定，禁用"可能""也许""或许"
- 第一人称"我"，不用"我们"
- 第一句直接开口，不铺垫
- 像隔壁工位刚干完一件事的哥们在说话，不是新闻稿

## A类绝对禁词（出现一次即废稿重写）
赋能 打造 构建 构筑 布局 业态
让我们深入探讨 不难发现 值得我们深思 引发广泛关注
具有重要意义 综上所述 总而言之 在当今X时代 随着X的快速发展
站在风口 迎来机遇 迈向新高度 数字化转型 赋能千行百业
专家表示 业内人士透露 数据显示（不带数字）
——（破折号出现即废稿）
这不是选择题是生存题（此类格言式结尾）
不仅……而且……（否定排比句式）

## 推文类型与要求
- AI热点快评：直接判断，有具体数字，观点不平衡
- AI工具实测：工具名 + 一句话结论 + 必须说缺点
- 创业认知：自嘲 + 踩坑 + 不装大师，第一人称 receipts
- 争议观点：尖锐但不人身攻击，设计成能引发讨论

## 收尾铁律（不需要结尾）
- 推文不需要结尾句。最后一个有意思的判断或事实写完就停
- 禁止任何 CTA、总结句、预言句
- 以下句式直接删掉，不是改写，是删：
  "半年后你再看" / "没跑了" / "等着看谁笑到最后"
  "这就是科技圈的风向标" / "后面的事不展开了"
  "控制权的搏斗会更激烈" / "这趋势半年后你再看"
  任何以"未来""格局""趋势""风向"收尾的句子
- 结尾突然停掉比硬加一句总结强

## 真实推文参考
示例A（AI热点）:
GM 裁了 600 名 IT 员工

不是成本削减

是把 IT 部门整个换血 换成会用 AI 的人

这个信号很清楚：会用 AI 工具的人 > 懂传统 IT 的人

不会是 GM 一家

示例B（工具）:
用了 Claude Code 整整 30 天

结论就一个：它不是工具 是第一个让我觉得"这就是未来"的东西

缺点：贵 不稳定 context 打满就拉跨

但我还是在用"""

A_CLASS = [
    r"赋能", r"打造", r"构建", r"构筑", r"布局", r"业态",
    r"让我们深入探讨", r"不难发现", r"值得我们深思", r"引发广泛关注",
    r"具有重要意义", r"综上所述", r"总而言之",
    r"在当今.{1,10}时代", r"随着.{1,20}的快速发展",
    r"站在风口", r"迎来机遇", r"迈向新高度", r"数字化转型",
    r"专家表示", r"业内人士透露",
    r"——",
    r"这不是选择题",
    r"不仅.{1,30}而且",
]


def scan_a_class(text: str) -> list[str]:
    return [p for p in A_CLASS if re.search(p, text)]


def call_api(messages: list[dict], temperature: float = 0.85) -> str:
    if not API_KEY:
        print("[ERROR] MOONSHOT_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 600,
    }
    req = urllib.request.Request(
        BASE_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())
        return resp["choices"][0]["message"]["content"].strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True, help="推文类型：AI热点快评 / AI工具实测 / 创业认知 / 争议观点")
    parser.add_argument("--facts", required=True, help="今日素材（事实、数据、新闻摘要）")
    parser.add_argument("--output", help="输出文件路径（不填则输出到 stdout）")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    user_msg = f"""写一条【{args.type}】推文。

今日素材：
{args.facts}

要求：
- 写出花椒看完这件事后脑子里的真实反应，不是转述新闻
- 落地到具体后果或具体判断，不说抽象结论
- 用真实推文示例的风格和节奏
- 严格遵守所有排版和语气铁律"""

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    prev_draft = ""
    hits: list[str] = []

    for attempt in range(args.retries + 1):
        if attempt > 0:
            messages.append({"role": "assistant", "content": prev_draft})
            messages.append({
                "role": "user",
                "content": f"命中A类禁词：{hits}。完全重写，这些词一个不能出现。",
            })

        try:
            draft = call_api(messages)
        except Exception as e:
            print(f"[ERROR] API call failed: {e}", file=sys.stderr)
            sys.exit(1)

        if tweet_weight(draft) > MAX_TWEET_WEIGHT:
            print(f"[WARN] Too long ({tweet_weight(draft)} weighted chars), retry {attempt+1}", file=sys.stderr)
            prev_draft = draft
            hits = [f"字数超280({len(draft)})"]
            continue

        hits = scan_a_class(draft)
        if hits and attempt < args.retries:
            print(f"[WARN] A-class hit: {hits}, retry {attempt+1}/{args.retries}", file=sys.stderr)
            prev_draft = draft
            continue

        if hits:
            print(f"[WARN] A-class persists after retries: {hits}", file=sys.stderr)

        if args.output:
            Path(args.output).write_text(draft, encoding="utf-8")
            print(f"[OK] Draft → {args.output} ({len(draft)} chars)", file=sys.stderr)
        else:
            print(draft)
        return

    print("[ERROR] Could not generate clean draft after retries", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
