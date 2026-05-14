#!/usr/bin/env python3
"""
Pass 2: Subtraction-only structural cleanup via Moonshot API.

Deletes background/setup/redundant sentences from Pass 1 output.
Never rewrites, never reorders — only removes.
Pass 3 (humanize_tweet.py) handles surface patterns and formatting.

Usage:
  python3 human_prior_tweet.py --input /tmp/draft.txt --output /tmp/struct.txt
  python3 human_prior_tweet.py --input /tmp/draft.txt > /tmp/struct.txt
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

API_KEY = os.environ.get("MOONSHOT_API_KEY", "")
BASE_URL = "https://api.moonshot.cn/v1/chat/completions"
MODEL = "moonshot-v1-8k"

SYSTEM = """你是一个推文**删除编辑**，专为 @pepperfr1ends（花椒）服务。

你只做一件事：**删句子**。不改词，不改顺序，不加新内容。

---

## 删除对象（符合以下任一条件的整句删掉）

1. **背景铺垫句** — 对理解核心判断没有必要的铺垫
   - "随着AI的快速发展…"
   - "近年来，越来越多的企业…"
   - "在当前的市场环境下…"

2. **重复解释句** — 把已说过的观点换个说法再说一遍
   - 如果第二句只是把第一句"换了个角度说"，删第二句

3. **预言/总结结尾句** — 最后一句是预言、风向、总结、CTA
   - "半年后你再看"
   - "这就是行业的方向"
   - "等着看谁笑到最后"
   - "格局即将大洗牌"
   - "这值得每个创业者关注"
   - 任何以"未来""趋势""格局""方向"收尾的泛化句

4. **客套/过渡句** — "这是一个复杂的问题" / "当然，也要看具体情况"

---

## 绝对不能做的事

- 不能改写任何留下的句子的措辞
- 不能改变句子顺序
- 不能添加任何原文没有的内容
- 不能合并句子（两句变一句）
- 不能把"可能"改成"一定"或反过来

---

## 安全规则

保留所有：人名、公司名、数字、时间、具体事实、直接判断句。

删完后自查：删掉的句子是否让核心判断变得难以理解？如果是，把那句话加回来。

---

## 输出规则

- 只输出删改后的推文正文
- 不要写"删除了第X句"之类的说明
- 不要输出原文对比
- 保持原文的行格式（一句话一行，行间空行）
- 直接给结果"""


def call_api(messages: list[dict]) -> str:
    if not API_KEY:
        print("[ERROR] MOONSHOT_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.30,
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Pass 1 草稿文件路径")
    parser.add_argument("--output", help="输出文件路径（不填则输出到 stdout）")
    args = parser.parse_args()

    draft = Path(args.input).read_text(encoding="utf-8").strip()
    if not draft:
        print("[ERROR] Input file is empty", file=sys.stderr)
        sys.exit(1)

    user_msg = f"""请删掉以下推文草稿中的冗余句子。

只删，不改，不加。

草稿：
{draft}"""

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    try:
        result = call_api(messages)
    except Exception as e:
        print(f"[ERROR] API call failed: {e}", file=sys.stderr)
        sys.exit(1)

    if len(result) > 280:
        print(f"[WARN] Still over 280 after subtraction ({len(result)} chars)", file=sys.stderr)

    hits = scan_a_class(result)
    if hits:
        print(f"[WARN] A-class present after subtraction pass: {hits}", file=sys.stderr)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"[OK] Subtracted → {args.output} ({len(result)} chars)", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
