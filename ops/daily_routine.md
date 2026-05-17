# @pepperfr1ends Daily Routine Loop v3.0

> 当前运行版本是 posting-only + reaction-learning + human-calibration。
> 系统只做发帖、观察、复盘，不做自动评论、点赞、关注。

---

## Daily Routine Loop

```text
Every 2h ──► Observe loop
  │  ► 抓 KOL list 最新 AI 相关帖子
  │  ► 记录 reaction samples（handle / post / likes / RT / replies / posted_at）
  │  ► 不评论 不点赞 不关注
  │
07:00 ──► slot1
11:00 ──► slot2
16:00 ──► slot3
20:00 ──► slot4
23:00 ──► slot5
  │  ► 抓 AIHOT 新闻
  │  ► 发帖前增量刷新 reaction samples
  │  ► 蒸馏 reaction pack
  │  ► writer 生成推文 + human calibration
  │  ► guardrails + scorer
  │  ► 取 AIHOT 对应图片
  │  ► 发帖并写入 tweet_url
  │
00:00 ──► review
  │  ► 抓已发布帖子的 metrics
  │  ► 复盘 best / worst post
  │  ► 输出下一轮写作假设
  │
  └──► 循环
```

## 每日产出目标

| 类型 | 数量 | 说明 |
|------|------|------|
| 原创推文 | 10 | 5 个 slot × 每个 2 条 |
| KOL 观察样本 | 持续累积 | observe loop 每 2 小时抓一次 |
| 自动评论 | 0 | 已停用 |
| 自动点赞 | 0 | 已停用 |
| 自动关注 | 0 | 已停用 |

## 素材来源

1. AIHOT curated items，用于文字事实源
2. AIHOT / 原文 `og:image`，用于配图
3. X list KOL reactions，用于学习“怎么反应”，不是抄内容

## 执行 Checklist

### 每条推文发布前
- [ ] ≤ 280 字
- [ ] 有配图，无图不发
- [ ] 通过 guardrails / avoid_slop
- [ ] 有明确取向，但不是模板化暴论
- [ ] 使用了 reaction pack，但没有复用 KOL 原句

### 每次 observe
- [ ] 只抓样本，不互动
- [ ] 记录发布时间和基础互动数据
- [ ] 不重复写入相同 post_url

### 每日 review
- [ ] 更新 tweet_url 对应 metrics
- [ ] 标出 best / worst post
- [ ] 输出下一轮写作假设
- [ ] 输出 human calibration 观察

## 这版系统不做的事

- ❌ 自动 KOL 评论
- ❌ 自动点赞
- ❌ 自动关注
- ❌ 自动建列表 / 批量关注
- ❌ 自动改 strategy weights
- ❌ 从 KOL 爆款直接抽技法硬喂 writer
