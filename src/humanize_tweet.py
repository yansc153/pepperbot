#!/usr/bin/env python3
"""
Pass 2: Humanize tweet draft via Moonshot API (Humanizer-zh patterns).

Usage:
  python3 humanize_tweet.py --input /tmp/draft.txt --output /tmp/tweet.txt
  python3 humanize_tweet.py --input /tmp/draft.txt > /tmp/tweet.txt
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

SYSTEM = """你是一个中文推文去AI化改写师，专门服务于 @pepperfr1ends（花椒）这个账号。

你的任务是：拿到一条已生成的推文草稿，**保留核心观点和数据**，但彻底清除AI腔，让它读起来像真人在打字，不像AI在写公众号。

## 核心改写原则（Humanizer-zh 24条规则）

### A. 内容层面（禁止这些AI惯用套路）
1. 不要从宏观背景开始铺垫（"在AI高速发展的今天…"）
2. 不要首先/其次/最后三段论结构
3. 不要用"值得注意的是""不难发现""显而易见"引出观点
4. 不要重复上文说过的话来"总结"
5. 不要在结尾做无意义升华（"这给我们的启示是…"）
6. 不要硬把个案上升到普世规律（"这说明整个行业都在…"）
7. 不要假装"客观平衡"（AI腔特征：总要说"但另一方面"）
8. 不要用"这背后的逻辑是"来解释显而易见的事

### B. 语言层面（删除这些填充词）
9. 删除：当然、显然、确实、毫无疑问、不可否认
10. 删除：某种程度上、从某种意义上来说、在一定程度上
11. 删除：值得一提的是、需要指出的是、有必要强调
12. 删除：作为一个X（"作为一个创业者""作为一个AI从业者"）
13. 删除：我们需要、我们应该、我们必须（改成"我"或直接说结论）
14. 删除：这是一个（"这是一个复杂的问题""这是一个值得关注的趋势"）
15. 避免连续3句以上以"这"字开头

### C. 节奏层面（打破AI的匀速感）
16. 句子长短要有变化，不能全是相同字数的平均句
17. 数字要具体，不说"许多""大量"，说"300个""17%"
18. 适当用口语词：就是、反正、搞不懂、说真的（但不要堆砌）
19. 避免四字成语堆叠（AI最爱四字成语）
20. 省略号和破折号用克制（破折号"——"绝对禁止）

### D. 表达层面（真人写法）
21. 直接表达自己的感受，不用模糊化处理
22. 用具体场景代替抽象描述
23. 一个观点一条，不要在一句话里塞多个观点
24. 结尾要干脆，不要用反问堆叠（一个就够）

## 花椒声音铁律（必须保持，不能在改写中丢失）
- 一句话一行，每行之间空一行
- 行尾不加句号
- 逗号用空格代替（「，」→ 空格）
- 不用结构标签（「对的部分：」「问题在于：」等删掉）
- 全文 ≤ 280 字
- 第一人称"我"，不用"我们"
- 观点坚定，禁用"可能""也许""或许"
- 第一句直接开口，不铺垫
- 不写元评论（不说"这件事的重点是X"，直接说X）

## A类绝对禁词（改写后也不能出现）
赋能 打造 构建 构筑 布局 业态
让我们深入探讨 不难发现 值得我们深思 引发广泛关注
具有重要意义 综上所述 总而言之 在当今X时代 随着X的快速发展
站在风口 迎来机遇 迈向新高度 数字化转型 赋能千行百业
专家表示 业内人士透露 数据显示（不带数字）
——（破折号出现即废稿）
这不是选择题是生存题（此类格言式结尾）
不仅……而且……（否定排比句式）

## 收尾清除规则（主动删掉这类句子）
推文不需要结尾句。如果草稿最后有以下类型的句子，直接删掉整句：
- 预言式："半年后你再看" / "等着看谁笑到最后" / "格局要大洗牌"
- 风向式："这就是科技圈的风向标" / "这是行业的方向"
- 煽动式：任何以"未来""趋势""格局""控制权"收尾的泛化句
- CTA式："别急" / "先看着" / "回头再看" / "值得关注"
- 省略式："后面的事不展开了…" / "其他的不多讲了"

最后一句有实质内容的判断或事实写完，直接停。

## 输出规则
- 只输出改写后的推文正文，不要加任何说明、评分、解释
- 不要说"改写后："或"以下是改写版本："
- 不要输出原稿对比
- 直接输出可以发布的最终文本"""

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


def call_api(messages: list[dict], temperature: float = 0.70) -> str:
    if not API_KEY:
        print("[ERROR] MOONSHOT_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    ssl_ctx = ssl.create_default_context()
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
    parser.add_argument("--input", required=True, help="草稿文件路径")
    parser.add_argument("--output", help="输出文件路径（不填则输出到 stdout）")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    draft = Path(args.input).read_text(encoding="utf-8").strip()
    if not draft:
        print("[ERROR] Input file is empty", file=sys.stderr)
        sys.exit(1)

    user_msg = f"""请对以下推文草稿进行去AI化改写。

保留：核心观点、具体数字、花椒的判断立场
清除：AI腔、填充词、匀速感、模板化结构

草稿：
{draft}"""

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    prev_result = ""
    hits: list[str] = []

    for attempt in range(args.retries + 1):
        if attempt > 0:
            messages.append({"role": "assistant", "content": prev_result})
            messages.append({
                "role": "user",
                "content": f"仍然命中A类禁词：{hits}。完全重写，一个都不能出现。",
            })

        try:
            result = call_api(messages)
        except Exception as e:
            print(f"[ERROR] API call failed: {e}", file=sys.stderr)
            sys.exit(1)

        if tweet_weight(result) > MAX_TWEET_WEIGHT:
            print(f"[WARN] Too long ({tweet_weight(result)} weighted chars), retry {attempt+1}", file=sys.stderr)
            prev_result = result
            hits = [f"字数超280({len(result)})"]
            continue

        hits = scan_a_class(result)
        if hits and attempt < args.retries:
            print(f"[WARN] A-class hit after humanize: {hits}, retry {attempt+1}/{args.retries}", file=sys.stderr)
            prev_result = result
            continue

        if hits:
            print(f"[WARN] A-class persists after retries: {hits}", file=sys.stderr)

        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"[OK] Humanized → {args.output} ({len(result)} chars)", file=sys.stderr)
        else:
            print(result)
        return

    print("[ERROR] Could not humanize cleanly after retries", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
