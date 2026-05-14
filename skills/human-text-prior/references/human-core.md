# Human Core

This file defines the underlying text behavior the skill should transfer.

The target is not "sounds casual." The target is "reads like a real person produced it under real attention constraints."

## Core Model

Real human text is usually shaped by:

- incomplete attention
- local intent
- uneven urgency
- context sharing
- imperfect but meaningful compression

That means the writing often feels:

- more selective
- less tutorialized
- less symmetrical
- more positional
- more rhythmically uneven

## What Humans Commonly Do

### 1. Lead with stance, not briefing

Humans often react first, then explain only as much as needed.

Prefer:

- "这事我不太信。"
- "这个方向我觉得行。"
- "我第一反应是别急。"

Over:

- "在分析这个问题之前，我们需要先理解其背景。"

### 2. Leave some context implicit

Humans do not restate every shared assumption.

Good human text often trusts that:

- the reader already knows the scene
- the title already carries some context
- the previous sentence already narrowed the scope

Use omission when it reduces drag without losing meaning.

### 3. Compress hard where the point is obvious

Humans often cut helper words, background filler, and transition padding.

They will say:

- "这票怕波动就别碰。"
- "先别下结论。"
- "这个路子我试过，不太行。"

They will not always say:

- "如果你对于波动性较为敏感，那么我不建议你参与这类标的。"

### 4. Uneven density is normal

Not every sentence deserves the same weight.

Human writing often alternates:

- one sharp sentence
- one clarifying sentence
- one throwaway bridge

That unevenness is part of the realism.

### 5. Repair locally instead of sounding pre-planned

Humans often correct themselves mid-stream:

- "我本来以为是这个问题，后来发现不是。"
- "严格说也不是不能做，是现在做太早。"
- "不是没价值，是顺序不对。"

This creates believable movement of thought.

### 6. Emotion is specific, not cinematic

Real people rarely write like every sentence is trying to become a quote card.

Prefer:

- irritation
- hesitation
- surprise
- amusement
- guarded conviction

Avoid turning ordinary points into epic declarations.

### 7. Sound spoken without becoming sloppy

Human text can carry spoken rhythm while remaining readable.

Use:

- shorter pivots
- direct verbs
- less ceremony
- more local emphasis

Do not use:

- random broken grammar
- forced slang
- fake low competence

### 8. Let sentences end without always summing up

AI text loves to close each sentence like a neat conclusion.

Humans often stop once the point lands.

That means many good endings are plain:

- "就这样。"
- "差不多这个意思。"
- "后面再看。"
- "先做到这一步。"

## What To Transfer

Transfer these mechanics:

- stance-first ordering
- selective omission
- shorter justification chains
- mixed sentence lengths
- sharper verbs
- local correction
- lower transition density
- context trust

Do not transfer:

- vulgarity by default
- chat noise
- domain slang without scene match
- spammy hype
- thread artifacts

## Strength Calibration

### `clean-human`

Use when the text must stay controlled.

Apply:

- less explanation
- less abstraction
- fewer template transitions
- more natural sentence weight

Do not apply:

- chat slang
- overtly spoken fragments

### `natural-human`

Use for most modern writing tasks.

Apply:

- stance-first openings
- occasional sentence fragments
- light self-repair
- mild compression

### `colloquial-human`

Use only when the surface welcomes informality.

Apply:

- stronger compression
- more implied context
- more visible attitude

Guardrail:

- if the text starts losing clarity, step back one level

## Rewrite Checklist

Before finalizing, ask:

1. Did the draft say the point too politely?
2. Did it over-brief the reader?
3. Did it smooth away all local thought movement?
4. Did it explain what could stay implied?
5. Did it sound like a template trying to be helpful?

If yes, rewrite structurally, not cosmetically.
