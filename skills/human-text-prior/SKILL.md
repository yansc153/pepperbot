---
name: human-text-prior
description: Calibrate Chinese writing toward how modern humans actually write before or after persona-specific or platform-specific writing skills. Use when drafts feel AI-generated, over-explained, over-complete, too symmetric, too polished, too teacherly, or disconnected from contemporary real-world text behavior. Best for copywriting, social posts, hooks, comments, intros, rewrites, and voice audits.
---

# Human Text Prior

This skill is a human-text calibration layer.

It does not tell the model to imitate a specific WeChat group. It extracts deeper priors from real contemporary chat text, then uses those priors to correct drafts that feel too model-native.

## First Rule

Use this skill to learn how humans organize text, not to cosplay any one crowd.

Keep the task's real domain, audience, risk level, and persona. Import only the human texture:

- compression
- uneven pacing
- stance before exposition
- selective omission
- local self-repair
- lower explanation density

Do not import unrelated slang, profanity, market jargon, or group-specific references unless the user task already lives in that world.

## What To Read

Always read:

1. `references/human-core.md`
2. `references/anti-ai-failures.md`

Read `references/corpus-biases.md` when:

- the task is formal, regulated, or brand-sensitive
- you are tempted to make the text more aggressive or more slang-heavy
- you are modifying this skill

Read `references/example-bank.md` when:

- you need concrete rewrite patterns
- you want to see how the priors change sentence behavior

Read `references/news-rewrite.md` when:

- the source material is a news report, press release, or article summary
- you need to rewrite news into something that feels human without drifting on facts
- you want a safer "真人味" workflow for current events

Read `references/integration-contract.md` when:

- another writing skill should call this skill before or after drafting
- you need a structured handoff

Read `references/source-profile.md` only when:

- you are auditing or extending the skill itself
- you need to verify what this corpus can and cannot support

## Modes

Choose exactly one mode for the current task.

### 1. `prewrite`

Use before a downstream writing skill drafts the text.

Goal:

- inject a human writing prior without forcing final wording too early

Output:

- `human_prior_level`: `clean-human` | `natural-human` | `colloquial-human`
- `keep`: 3 to 5 constraints that must stay true
- `avoid`: 3 to 5 model-native failures to avoid
- `cadence_notes`: how dense, fast, or incomplete the text should feel
- `context_assumptions`: what can stay implicit

### 2. `rewrite`

Use when a draft already exists and feels too AI-native.

Goal:

- preserve meaning
- reduce model smell
- increase human textual plausibility

Output:

- `revised_text`
- `edits_made`: short list
- `intent_preserved`: one-line check

If the source is news:

- first separate immutable facts from rewriteable framing
- preserve names, dates, numbers, causal claims, and attribution
- rewrite the delivery, not the facts

### 3. `audit`

Use when the user asks why a draft still feels AI-generated.

Goal:

- diagnose the actual failure mode instead of blindly rephrasing

Output:

- `verdict`
- `why_it_reads_ai`
- `surgical_fixes`

## Strength Levels

Choose the weakest level that still fixes the problem.

### `clean-human`

Use for product copy, summaries, explainers, and safer brand text.

Behavior:

- keep grammar clean
- keep vocabulary modern
- remove lecture voice and report voice
- do not introduce obvious slang

### `natural-human`

Default.

Behavior:

- allow stance-first openings
- allow uneven sentence lengths
- allow selective omission where context is obvious
- keep the text sounding written by a real person, not a template

### `colloquial-human`

Use only when the target surface can carry it, such as comments, casual posts, conversational hooks, or chat-like copy.

Behavior:

- allow sharper turns
- allow more implied context
- allow lighter spoken syntax

Do not use this level for legal, medical, enterprise, or high-trust explanatory text unless the user explicitly wants it.

## Integration Order

When another writing skill is involved, use this precedence:

1. facts and safety
2. task format
3. domain constraints
4. persona or platform voice
5. human text prior
6. local flourish

If a persona skill conflicts with this skill:

- the persona skill owns worldview, boundaries, and domain vocabulary
- this skill owns pacing, compression, and anti-AI texture

## Hard Rules

- Do not turn every output into chat.
- Do not deliberately make the writing dumber to seem human.
- Do not force typos.
- Do not force profanity.
- Do not inject crypto, AI, Web3, or trading slang into unrelated topics.
- Do not replace specific facts with vibes.
- Do not preserve a sentence just because it sounds polished.
- Do not flatten the entire piece into one register. Humans shift.

## Quick Rewrite Heuristic

When a sentence feels fake, check in this order:

1. Is it explaining too much too early?
2. Is it smoother than a real person would bother to be?
3. Is every sentence carrying equal weight?
4. Is the stance delayed until after background?
5. Is the wording abstract where a person would get concrete?

If yes, cut, compress, or reorder before you start synonym-swapping.

## If You Are Extending This Skill

Use the scripts in `scripts/` against the raw corpus at `/Users/oxjames/Downloads/texts`.

Recommended order:

1. `parse_wechat_exports.py`
2. `filter_corpus.py`
3. `distill_human_prior.py`
4. `build_example_bank.py`

Treat the corpus as evidence, not gospel.

For a more general-purpose human prior, prefer rebuilding with domain exclusions:

```bash
python3 scripts/filter_corpus.py /Users/oxjames/Downloads/texts \
  -o /tmp/human-text-prior.jsonl \
  --exclude-domain ai \
  --exclude-domain crypto \
  --exclude-domain web3
```
