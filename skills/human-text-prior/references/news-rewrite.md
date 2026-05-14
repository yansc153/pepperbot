# News Rewrite

Use this file when the source material is news and the target is "reads like a real person wrote or reposted it" without corrupting the facts.

This is the highest-risk use of `human-text-prior` because news writing can become fake-human very easily:

- too dramatic
- too casual
- too opinionated too early
- or factually blurry

The fix is to split the task into two layers.

## Rule Zero

Do not humanize the facts. Humanize the delivery.

Keep fixed:

- names
- dates
- time order
- quantities
- quotes when quoted
- attribution
- uncertainty level

Allowed to change:

- opening shape
- sentence pacing
- where the reaction appears
- how much obvious background is omitted
- how much of the summary sounds like a person talking instead of a wire service

## Safe Workflow

### Step 1. Extract the fact spine

Before rewriting, write a compact internal fact spine:

- what happened
- to whom
- when
- with what evidence or attribution
- what is still uncertain

If the source does not support a claim, do not upgrade it during rewrite.

### Step 2. Choose the news posture

Pick one.

#### `straight-human`

Use when you want a human tone but minimal added attitude.

Good for:

- newsletter blurbs
- neutral reposts
- summaries

#### `observational-human`

Use when you want a visible point of view, but still grounded.

Good for:

- social posts
- commentary intros
- "我刚看到这个" style sharing

#### `judgment-human`

Use only when the user explicitly wants a stronger stance and the source supports it.

Good for:

- opinionated tweets
- hot takes with receipts

Do not use for unclear or weakly sourced reporting.

### Step 3. Rewrite around the spine

Apply the human prior to:

- move the point earlier
- reduce briefing language
- remove thesis-essay framing
- vary sentence length
- let one sentence carry the reaction instead of making every sentence "interesting"

### Step 4. Run the drift check

After rewriting, compare the new text against the fact spine.

Check:

1. Did any fact get stronger?
2. Did any uncertainty disappear?
3. Did any causal link get invented?
4. Did any quote become paraphrase without signal?
5. Did the new tone imply more confidence than the source supports?

If yes, pull it back.

## Recommended Output Format

When the input is news, return:

### `fact_spine`

3 to 6 bullets.

### `rewrite_posture`

One of:

- `straight-human`
- `observational-human`
- `judgment-human`

### `revised_text`

The actual rewrite.

### `drift_check`

- `safe` or `needs_pullback`
- one-line explanation

## What Makes News Feel AI-Written

### 1. Wire-service stiffness

Example symptom:

> 据报道，该公司于周二正式宣布了一项新的战略调整计划。

Better:

> 这家公司周二把方向改了，而且不是小修小补。

Why:

- the sentence sounds like a person relaying the development

### 2. Generic significance inflation

Example symptom:

> 这一举措标志着行业正在进入新的发展阶段。

Better:

> 这事值不值得看，不在口号，在它会不会逼同行跟进。

Why:

- keeps the importance test concrete

### 3. Mechanical neutrality

Example symptom:

> 业内对此看法不一，后续影响仍有待观察。

Better:

> 现在分歧挺大。看多的人盯着增长，看空的人盯着成本，短期还不会有共识。

Why:

- still balanced, but not vague

### 4. Over-explaining obvious context

Example symptom:

> OpenAI 是一家人工智能公司，近年来在生成式人工智能领域受到广泛关注。

Better:

> OpenAI 这次改动，真正该看的不是发布会词，而是它后面要吞掉哪些使用场景。

Why:

- assumes the reader already knows the broad context

## Style Guardrails

- Do not add fake excitement.
- Do not add slang unless the target surface already uses it.
- Do not add certainty to weak reporting.
- Do not convert every news item into a hot take.
- Do not remove attribution if the claim depends on attribution.

## Fast Prompt Pattern

Use this structure:

> Rewrite this news item with `human-text-prior`.
> Keep all facts, names, dates, numbers, and uncertainty intact.
> First give `fact_spine`, then choose a `rewrite_posture`, then give `revised_text`, then give `drift_check`.

## Tiny Example

Source:

> 某公司周三宣布裁员 8%，并表示此次调整将集中在销售与运营团队。

Bad fake-human:

> 这家公司又开始疯狂裁员了，内部估计已经乱成一团。

Better:

> 这家公司周三裁了 8%，主要动的是销售和运营。表面上是组织调整，实际上传递出来的信号很直接，增长压力已经摆到台面上了。

Why:

- the tone is more human
- the fact remains bounded by the source
- the interpretation stays close to the evidence
