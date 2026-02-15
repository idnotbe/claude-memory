# Best Solution Analysis: Claude Code Prompt-Type Stop Hook Failures

**Date:** 2026-02-16
**Author:** Multi-model analysis (Claude Opus 4.6 + Gemini 3 Pro + Vibe-Check metacognitive review)

---

## Problem Statement

The claude-memory plugin uses 6 parallel prompt-type Stop hooks -- one per memory category (SESSION_SUMMARY, DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE). These hooks fail more often as conversations grow longer.

## Root Cause Analysis

### How Prompt-Type Stop Hooks Work (from source code analysis)

When Claude Code executes a prompt-type hook, it:

1. Sends the **full conversation history as messages** to the hook model (debug log: "Querying model with 11 messages")
2. Includes a system prompt instructing the model to return `{"ok": true/false, "reason": "..."}`
3. Passes `outputFormat: {type: "json_schema", schema: ...}` for constrained decoding
4. Extracts `content[0].text`, parses as JSON, and validates with Zod
5. If any step fails: `non_blocking_error` -- the hook is skipped and Claude stops normally

### Why Longer Conversations Cause More Failures

**Factor 1: Token volume scaling.**
Each prompt hook receives the full conversation as messages. A 10-turn conversation might be ~5K tokens. A 50-turn conversation with tool use can easily reach 50-100K tokens. All of this is sent as input to each of the 6 Haiku calls. While Haiku supports a 200K context window, larger inputs increase:
- API latency (more tokens to process)
- Probability of hitting the 30-second timeout
- Probability of the model producing degraded output quality
- Cost (input tokens are billed per-call)

**Factor 2: 6x failure probability amplification.**
This is the dominant factor. If each individual hook call has a failure probability `p`, the probability that at least one of 6 independent parallel calls fails is:

```
P(at least one failure) = 1 - (1 - p)^6
```

| Per-call failure rate | 1 hook | 6 hooks |
|----------------------|--------|---------|
| 1% | 1.0% | 5.9% |
| 3% | 3.0% | 16.7% |
| 5% | 5.0% | 26.5% |
| 10% | 10.0% | 46.9% |

Even a modest 3% per-call failure rate (reasonable for long contexts + Haiku + 30s timeout) produces a 17% chance of at least one hook failing per stop event.

**Factor 3: Failure modes specific to prompt hooks.**
From the structured output analysis (`temp/structured-output-analysis.md`):
- Empty responses (safety refusals, token limits, API errors) -> `"JSON validation failed"`
- Model compatibility issues (some Haiku snapshots may not fully support `outputFormat`)
- `additionalProperties: false` constraint blocking extra fields (already fixed in commit b99323e)
- The belt-and-suspenders parsing pipeline (text extraction -> JSON parse -> Zod validation) has multiple failure points

**Factor 4: Cost amplification.**
With a 50K-token conversation, 6 parallel Haiku calls = 300K input tokens per stop event. At Haiku pricing ($0.80/MTok input), that is $0.24 per stop event just for the hooks. Over a long session with multiple stop/continue cycles, this adds up.

### What Failure Looks Like

When a prompt hook fails, Claude Code logs a `non_blocking_error` and proceeds. Since these are Stop hooks:
- `ok: true` -> Claude stops (the action proceeds)
- Hook failure -> Claude stops (non-blocking errors default to allowing the action)
- `ok: false` -> Claude continues and saves the memory

Therefore, **hook failures cause missed memory saves**, not stuck loops. This is important for the risk assessment.

---

## Option Analysis

### Option A: Switch to Sonnet Model

**Change:** Add `"model": "claude-sonnet-4-5-20250929"` to each hook definition.

| Dimension | Assessment |
|-----------|-----------|
| Reliability | Moderate improvement. Sonnet handles long context more reliably and produces higher-quality structured output, but 6x amplification persists |
| Cost | Severe increase. Sonnet is ~15x more expensive than Haiku per token. 6 parallel Sonnet calls on a 50K-token conversation = significant cost |
| Development effort | Trivial. One field change per hook |
| Maintenance | None. Same architecture |

**Verdict:** Addresses symptom (model quality) but not root cause (6x amplification). Expensive for marginal improvement.

### Option B: Convert to Command-Type Hooks

**Change:** Replace all 6 prompt hooks with a single Python command hook that: reads the conversation from stdin/transcript, truncates context intelligently, calls the Anthropic API directly with retry logic, and evaluates all 6 categories.

| Dimension | Assessment |
|-----------|-----------|
| Reliability | Highest possible. Full control over context truncation, retry logic, timeout handling, error recovery |
| Cost | Lowest possible. Can truncate to only last N messages, batch all categories into one API call |
| Development effort | High. Must implement: API client, context truncation, prompt engineering, JSON response parsing, error handling, retry logic, API key management |
| Maintenance | High. Must maintain API client code, handle API changes, manage dependencies (requests/httpx), keep API keys configured |

**Verdict:** Most technically capable but massive overengineering for an advisory system. Essentially reimplements what Claude Code's prompt hook system already provides.

### Option C: Consolidate into 1 Hook (RECOMMENDED)

**Change:** Replace 6 separate prompt hooks with 1 prompt hook that evaluates all 6 categories in a single call.

| Dimension | Assessment |
|-----------|-----------|
| Reliability | Major improvement. Eliminates 6x failure amplification entirely. Single call has base failure rate only |
| Cost | ~83% reduction. 1 API call instead of 6, same input tokens |
| Development effort | Low. Rewrite one prompt, update hooks.json |
| Maintenance | Minimal. Same architecture, fewer moving parts |

**Mathematical impact:**

| Per-call failure rate | 6 hooks (current) | 1 hook (Option C) | Improvement |
|----------------------|-------------------|-------------------|-------------|
| 3% | 16.7% | 3.0% | 5.6x better |
| 5% | 26.5% | 5.0% | 5.3x better |
| 10% | 46.9% | 10.0% | 4.7x better |

**UX improvement:** Currently, if both a DECISION and TECH_DEBT are detected, the user must handle two separate stop-and-continue cycles. With a consolidated hook, both are reported in a single block action, and the user handles them in one pass.

**Risk:** Haiku might not evaluate all 6 categories equally well in a single prompt. A structured checklist prompt format mitigates this (see Implementation section below).

**Verdict:** Best risk-adjusted outcome. Eliminates the dominant failure factor (6x amplification) with minimal effort and reduced cost.

### Option D: Hybrid Command-Type + Prompt

**Change:** Single Python command hook that truncates context, calls API with retry, evaluates all categories.

| Dimension | Assessment |
|-----------|-----------|
| Reliability | Highest. Context truncation + retry + single call |
| Cost | Lowest. Truncated context + single call |
| Development effort | High. Same as Option B |
| Maintenance | High. Same as Option B |

**Verdict:** "Best of both worlds" in theory, but the development cost is unjustified given that Option C achieves most of the reliability benefit with near-zero effort. Reserve as escalation path if Option C proves insufficient.

---

## Consensus Recommendation

All three analysis sources (Vibe-Check metacognitive review, Gemini 3 Pro architectural analysis, and primary research) independently converged on the same answer:

### Primary: Option C -- Consolidate to 1 Hook

This is the clear winner for an advisory (non-critical) system:
- Eliminates the 6x failure amplification (the dominant failure factor)
- Reduces cost by ~83%
- Improves UX (single consolidated report)
- Minimal development effort (rewrite one prompt)
- No new dependencies or infrastructure

### Escalation Path

If Option C still shows unacceptable failure rates after deployment:

1. **Step 2: Add Sonnet model** (Option A on top of C). Add `"model": "claude-sonnet-4-5-20250929"` to the single consolidated hook. Net cost with 1 Sonnet call may be comparable to or less than 6 Haiku calls. This is a 10-second configuration change.

2. **Step 3: Hybrid** (Option D). Only if both C and C+Sonnet fail. At that point you have data proving simpler approaches are insufficient, and the development effort is justified.

### Do NOT Do

- **Option A alone** (Sonnet on 6 hooks): Treats the symptom, not the cause. Expensive.
- **Option B/D first**: Over-engineering. The Claude Code team may improve prompt hook reliability in future versions, making custom API implementations redundant.

---

## Implementation Plan for Option C

### Consolidated Triage Prompt

Replace the 6 Stop hook entries in `hooks/hooks.json` (lines 4-71) with:

```json
{
  "matcher": "*",
  "hooks": [
    {
      "type": "prompt",
      "timeout": 45,
      "statusMessage": "Triaging conversation for memories...",
      "prompt": "Evaluate this conversation for items worth saving as structured memories.\n\nContext: $ARGUMENTS\n\nIf stop_hook_active is true in the context above, allow stopping.\n\nCheck EACH category independently using these definitions:\n\n1. SESSION_SUMMARY: Was meaningful work completed? (tasks done, files modified with intent, project decisions made -- not greetings or simple Q&A)\n2. DECISION: Was a choice made between alternatives with stated rationale? (a clear 'chose X because Y' pattern)\n3. RUNBOOK: Was an error fully resolved? (root cause diagnosed AND fix applied AND verified working -- all three required)\n4. CONSTRAINT: Was a persistent external limitation discovered? (API limits, platform restrictions, legal requirements -- not temporary blockers)\n5. TECH_DEBT: Was work explicitly deferred? (a clear 'deferring X because Y' pattern with acknowledged cost -- not simple TODOs)\n6. PREFERENCE: Was a new convention established? (style, tool, or workflow choice for future consistency -- not following an existing convention)\n\nIf NONE of these categories apply, allow stopping.\n\nIf ANY category applies, do not allow stopping. For each applicable category, output a line with:\n[CUD:CREATE|EVENT:none] CATEGORY: description of what should be saved\n\nCheck .claude/memory/index.md for existing entries. Use UPDATE instead of CREATE when modifying existing entries, and DELETE with appropriate EVENT (resolved, removed, reversed, superseded, deprecated) when removing entries. Use memory-management skill for file format and paths."
    }
  ]
}
```

### Key Design Decisions

1. **Timeout increased to 45s** (from 30s): The single hook does more work and the prompt is longer. A 45-second timeout gives adequate margin without being excessive.

2. **Structured checklist format**: Each category is numbered and precisely defined with pass/fail criteria. This forces the model to evaluate each one independently rather than fixating on the first match.

3. **Preserved CUD/EVENT prefix format**: The output format matches what the existing memory-write pipeline expects, so downstream processing does not need changes.

4. **stop_hook_active check preserved**: Prevents infinite continuation loops, same as current implementation.

5. **Single statusMessage**: Instead of 6 different "Checking for X..." messages, one clear "Triaging conversation for memories..." message.

### Testing Plan

1. **Short conversation test**: Verify the hook correctly returns `ok: true` for trivial conversations (greetings, simple Q&A).
2. **Multi-category test**: Verify that when both a DECISION and TECH_DEBT exist, both are reported in a single response.
3. **Long conversation test**: Verify reliability with 50+ turn conversations.
4. **Baseline measurement**: Before switching, log current failure rate for one week to have a comparison point.

### Rollback Plan

If the consolidated hook performs worse than expected, the original 6-hook configuration is preserved in git history (current `hooks/hooks.json`). Reverting is a single `git checkout` of that file.

---

## Appendix: Sources and Cross-References

### Primary Sources
- [Hooks Reference - Claude Code Docs](https://code.claude.com/docs/en/hooks)
- [Automate Workflows with Hooks - Claude Code Docs](https://code.claude.com/docs/en/hooks-guide)
- [Context Windows - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Pricing - Claude API Docs](https://platform.claude.com/docs/en/about-claude/pricing)
- [Claude Code Issue #11786: Stop hooks receive only metadata](https://github.com/anthropics/claude-code/issues/11786)
- [Claude Code Issue #11947: Prompt-based Stop hook JSON errors](https://github.com/anthropics/claude-code/issues/11947)

### Plugin Source Files
- `/home/idnotbe/projects/claude-memory/hooks/hooks.json` -- Current 6-hook configuration
- `/home/idnotbe/projects/claude-memory/temp/structured-output-analysis.md` -- Structured output deep-dive

### Cross-Model Analysis
- **Vibe-Check (metacognitive review)**: Identified Complex Solution Bias toward Option D. Recommended C-first with escalation path. Flagged that without failure rate measurements, optimization is premature.
- **Gemini 3 Pro (architectural analysis)**: Independently recommended Option C. Provided the probability math ($P = 1-(1-p)^6$), the UX improvement analysis (single-pass vs multi-pass stop/continue cycles), and the structured checklist prompt pattern.
- **Codex / OpenAI**: Unavailable (quota exhausted). Analysis proceeded with 2/3 external opinions.

### Key Insight

The problem was never about model capability (Haiku vs Sonnet) or infrastructure sophistication (custom API clients). The problem is purely **architectural**: running 6 independent probabilistic operations when 1 would suffice. The fix is architectural, not technological.
