# Post-Verification Round 1 Synthesis

## Critical Corrections Applied

### From Security Verifier:
- API key exposure is CRITICAL risk for inline API approaches
- ACE candidate bypass = data integrity problem (duplicates accumulate)
- Hook timeout behavior undefined — could lock user out
- PostToolUse validation bypassed in non-tool-call paths

### From Arch/UX Verifier:
- "Just don't block" option completely absent from all research
- Test agent hook (Tier 2) FIRST — cheapest full-solution test
- 3-tier model is over-engineered — pick one primary approach
- Silent failure needs SessionStart confirmation mechanism
- Quality loss without SKILL.md is understated

### From Gemini R2:
- Background agent lifecycle concern: agents killed on session exit
- BUT: Stop hook block keeps session alive during foreground Task execution
- "Foreground single Task" is viable middle ground

## Revised Architecture: Decision Tree (NOT Tiers)

```
Step 1: Test Agent Hook Isolation (10 min experiment)
  ├── Agent hook subagents ARE isolated → DONE. Use agent hook.
  └── Agent hook subagents are NOT isolated → Step 2

Step 2: Implement Dual-Mode Config
  ├── save_mode: "optimized" (default) — Fix A + Fix B (current flow, less noise)
  ├── save_mode: "deferred" — no block, next-session save
  └── save_mode: "api" — inline API save (requires safety work, opt-in)

Regardless of mode: Add SessionStart confirmation hook
```

## The "Deferred" Mode (New Insight)

The arch-verifier's "quiet mode" suggestion is brilliant:
- Stop hook writes triage data + context files to disk, exits WITHOUT blocking
- Next session's UserPromptSubmit hook detects pending saves
- Injects: "2 unsaved memories from last session. Use /memory:save."
- User explicitly runs the skill → FULL QUALITY SKILL.md flow
- Context files persist on disk, so the next session CAN draft from them

### Why this works:
- Zero noise in current session (no block, no tool calls)
- Full SKILL.md quality (ACE, CUD, verification) when user saves
- No API key needed, no timeout risk, no race conditions
- User agency preserved (they choose when to save)

### Trade-off:
- Memories are delayed by one session
- User must explicitly trigger save (might forget)
- Context files may become stale if user waits too long
- If user never opens a new session, memories are lost

## Revised Solution Rankings

| Rank | Approach | Risk | Quality | Noise | Effort |
|------|----------|------|---------|-------|--------|
| 1 | Agent hook (if isolated) | Low | Full | Zero | Low |
| 2 | Deferred mode | Low | Full | Zero | Low |
| 3 | Optimized inline (Fix A+B) | Low | Full | Low (~8-12 lines) | Low |
| 4 | Foreground single Task | Low | Full | Very low (~3-5 lines) | Medium |
| 5 | Inline API save | HIGH | Degraded | Zero | High |
| 6 | Detached process | HIGH | Degraded | Zero | High |

## Key Decision: What to Test First
1. Agent hook isolation (10 min — change 1 line in hooks.json)
2. If that fails: Implement deferred mode + optimized inline as dual config
