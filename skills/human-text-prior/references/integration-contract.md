# Integration Contract

Use this file when another writing skill should work with `human-text-prior`.

## Purpose

`human-text-prior` is not the final persona.

It is the layer that fixes model-native writing habits before or after the persona, platform, or domain skill does its job.

## Recommended Ordering

### Pattern A: prewrite plus final pass

Use when the downstream skill generates the main draft.

1. run `human-text-prior` in `prewrite`
2. run the downstream persona or platform skill
3. run `human-text-prior` in `rewrite`

This is the default pattern.

### Pattern B: audit after drafting

Use when a draft already exists and the user says it still feels AI-generated.

1. run the downstream skill if needed
2. run `human-text-prior` in `audit`
3. apply only the fixes that improve realism without breaking the target register

## Handoff Format

### `prewrite` handoff

Pass these fields downstream:

- `human_prior_level`
- `keep`
- `avoid`
- `cadence_notes`
- `context_assumptions`

Example:

```yaml
human_prior_level: natural-human
keep:
  - Lead with the take, not the full background.
  - Keep one sentence visibly plainer than the others.
  - Preserve technical accuracy.
avoid:
  - Thesis-essay scaffolding.
  - Over-symmetry.
  - Fake all-sides neutrality.
cadence_notes:
  - Short opening, medium explanation, short landing.
context_assumptions:
  - Audience already knows the broad topic category.
```

### `rewrite` output

Return:

- `revised_text`
- `edits_made`
- `intent_preserved`

### `audit` output

Return:

- `verdict`
- `why_it_reads_ai`
- `surgical_fixes`

## Role Separation

If combined with a stronger persona skill:

- persona skill decides worldview, domain references, platform shape
- `human-text-prior` decides pacing, compression, and anti-AI texture

If combined with `humanizer-zh`:

- use `human-text-prior` first for structural correction
- use `humanizer-zh` last for cleanup if the draft still has obvious stock AI markers

## Integration Examples

### With `huajiao-social-voice`

Recommended:

1. `human-text-prior` `prewrite`
2. `huajiao-social-voice`
3. `human-text-prior` `rewrite`

Reason:

- the persona should stay intact
- the final pass prevents the persona from drifting into over-scripted output

### With generic writing skills

Recommended:

1. ask what the text is for
2. choose strength level
3. apply `prewrite`
4. draft
5. apply `rewrite`

### With news or article sources

Recommended:

1. extract a `fact_spine`
2. choose `straight-human`, `observational-human`, or `judgment-human`
3. run `human-text-prior` in `rewrite`
4. run a drift check against the source

Reason:

- news needs human delivery without factual drift

## Non Goals

This skill should not:

- force chat slang into formal copy
- replace domain expertise
- override safety or factual precision
- turn every output into a hot take
