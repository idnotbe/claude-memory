# Architecture & UX Verification: Memory Save Noise

**Verifier:** arch-ux-verifier (Task #10)
**Date:** 2026-02-28
**Status:** Critical findings -- several assumptions underlying the 3-tier proposal need challenge

---

## 1. Does It Solve BOTH Problems?

The user has two distinct complaints:
- **(a) Visible noise** pushing content off-screen
- **(b) /compact triggered by save noise**

Let's score each proposed tier:

| Tier | Solves (a): Visible Noise | Solves (b): /compact | Notes |
|------|--------------------------|---------------------|-------|
| Tier 1: SKILL.md optimization (externalize JSON + single save agent) | Partial (~60%) | Partial | Still 8-12 visible lines + subagent spawns. /compact risk reduced but not eliminated. |
| Tier 2: Agent hook investigation | Potentially yes, if isolated | Potentially yes | UNKNOWN. Entire tier is conditional on an empirical test that hasn't been run. |
| Tier 3: Inline API save in hook | Yes (~0 lines) | Yes | Full solution. But loses SKILL.md quality pipeline. |

**Critical finding**: Only Tier 3 definitively solves both problems. Tier 1 helps but doesn't fix /compact for complex sessions. Tier 2 is speculative. The "3-tier" framing presents an incomplete solution as a complete one.

---

## 2. Simpler Alternatives Being Overlooked

### The Elephant in the Room: Just Don't Block

The Stop hook currently returns `{"decision": "block", "reason": "..."}`. What if it returned `{"decision": "allow"}` with a very short `systemMessage` like "2 memories pending -- run /memory:save to capture"?

This approach:
- Eliminates ALL auto-save noise (zero lines)
- Preserves full SKILL.md quality for explicit saves
- Preserves user agency (they choose when to save)
- Requires zero architectural change

**Trade-off**: Memories are not auto-captured. But the current system already has "silent operation" as a design goal (SKILL.md Rule #2). Auto-capture is a feature, not a requirement. If the noise is bad enough that users hate it, opt-in explicit save may be better than opt-out auto-capture.

**This option is completely absent from all research documents.** Nobody asked: "Should auto-capture exist at all in its current form?"

### The "One-Line Block" Option

What if the Stop hook blocked with a single flat string: "Save 2 memories. Run memory-management skill."? No JSON, no triage_data, no categories. The agent reads this, runs the skill, and we get the current SKILL.md flow.

The 25+ lines of JSON in the reason field is a separate problem from the 30-50 lines of Phase 3 tool output. Fix A from minimal-fix-analysis already covers this (externalize triage_data to a file). That alone reduces Source 1 noise from ~25 lines to ~3 lines.

Combined with Fix B (single consolidated save agent for Phase 3), we get ~8-12 total visible lines. Is that good enough? The research never asks whether the user would accept 8-12 lines as tolerable.

### "Quiet Mode" Config Flag

Add `triage.quiet_mode: true` to config. When enabled:
- Stop hook writes to a `.deferred-saves.json` file, exits with `{"decision": "allow"}`
- Next session's UserPromptSubmit hook checks for the file and injects "Last session had 2 unsaved memories. Run /memory:save to capture them."
- User can then explicitly trigger the full SKILL.md flow with full quality

This is essentially the "Next-Session Queue" approach from cross-model-validation-r1.md, but it deserves more prominence as a practical UX pattern.

---

## 3. Is the 3-Tier Architecture Over-Engineered?

**Yes. The tiered model has structural problems:**

### Problem A: Tier 2 is a blocking dependency, not a parallel track

The synthesis-draft.md presents 3 tiers as if they can be pursued independently. But Tier 2 (agent hook investigation) is a binary decision point that should precede any implementation. If agent hook subagents ARE isolated, Tier 3 is unnecessary. If they're NOT isolated, Tier 2 is dead.

A better framing: **test Tier 2 first (low effort), then implement the winner.** The current proposal has teams potentially building Tier 3 (high effort) before knowing whether Tier 2 works.

### Problem B: Tier 1 creates false comfort

Tier 1 (SKILL.md optimization) reduces noise from 70-100+ to 8-12 lines. This will feel like "problem solved" and deprioritize Tiers 2 and 3. But /compact is triggered by token count, not line count. Even 8-12 visible lines with 40k tokens of subagent context adds up. If the user is in a long session, Tier 1 does NOT prevent /compact.

### Problem C: Maintenance burden is real

Three approaches to maintain means three sets of tests, docs, and bug surfaces. Alt 4 (inline API) needs its own drafting logic (minus ACE candidate selection). Alt 6 (agent hook) needs a new agent prompt maintained separately from SKILL.md. If they diverge in behavior, users face inconsistent memory quality depending on which tier fires.

**Recommendation**: Pick one primary approach (Tier 2 if it works, Tier 3 as fallback), not three.

---

## 4. Quality Trade-offs: What We Lose Without SKILL.md

This is the most underexamined issue in all research documents. The SKILL.md pipeline has:

1. **ACE candidate selection** (`memory_candidate.py`): Finds existing memories to update vs. create new. Without this, every save creates a duplicate if the topic was covered before.
2. **2-layer CUD verification**: Python mechanical veto + LLM semantic decision. Without this, the LLM may create when it should update, delete when it should update, etc.
3. **OCC (Optimistic Concurrency Control)**: Prevents write conflicts on concurrent updates.
4. **Content verification subagent** (Phase 2): Checks for hallucination and factual errors before saving.
5. **Rolling window enforcement** (`memory_enforce.py`): Prevents session_summary category from growing unbounded.

If we adopt Tier 3 (Inline API Save in Stop Hook), we lose ALL of these. The inline API call would need to replicate ACE candidate lookup (a python script that reads the index), CUD resolution logic, and verification -- all in a single hook script.

This is not "good quality" -- it's fundamentally degraded quality. Research documents say "Good (LLM drafting preserved, but without candidate lookup for updates)." This dramatically undersells the loss. **Duplicate memories accumulate** without candidate lookup. This erodes retrieval quality over time as the index fills with redundant entries.

**The quality trade-off is serious enough to reconsider whether noise elimination is worth it**, unless we replicate the candidate lookup in the hook script.

---

## 5. User Mental Model

What does the user expect? The current behavior:
- User ends session
- Session "stops"
- Suddenly 50-100 lines of tool calls appear
- /compact fires destroying context
- User is confused and frustrated

What the user WANTS:
- Session ends
- Some brief indication memories were saved (or nothing at all)
- Context is preserved for next session

The key insight: **the user expects "it happened" not "watch it happen."** This is the mental model of any background save operation (Word autosave, git hooks, etc.). You don't watch a progress bar for every autosave.

SKILL.md Rule #2 even says: "Silent operation: Do NOT mention memory operations in visible output during auto-capture." The current architecture violates its own stated design goal.

The UX failure is architectural, not cosmetic. Any solution that keeps the work inside the main LLM tool loop will violate the user's mental model. You cannot solve a "watch it happen" problem by making "watching it happen" slightly shorter.

**This strongly favors moving work out of Claude Code's main context entirely** -- not SKILL.md optimization.

---

## 6. Failure UX: Silent Failure vs. Noisy Success

This is the most underaddressed risk in all research.

If Tier 3 (Inline API Save) silently fails:
- Hook times out at 30s: session ends, memories lost, user never knows
- API key missing: save fails silently, memories lost
- JSON parsing error: save fails silently
- File write error: save fails silently

The current "noisy success" is actually the system working correctly and being honest about it. The user sees the work happening because the work IS happening in their session context. Making it silent trades observability for comfort.

**Proposed mitigation** (not addressed in any research doc): The Stop hook should write a completion marker file after successful save. The next SessionStart hook reads this file and injects a brief: "Note: 2 memories were saved from last session (decision, preference)." This gives the user:
- Zero noise during save
- Confirmation the save happened
- Visibility into what was saved
- Discovery of silent failures (if the note never appears)

Without this, silent failure is indistinguishable from silent success. A user relying on auto-capture who never sees the confirmation note will eventually discover they've lost months of accumulated context. That UX failure is worse than the current visible noise.

---

## Most Controversial Finding

**The most controversial finding**: The 3-tier proposal is wrong about the order of operations. Tier 2 (agent hook investigation) should be the FIRST thing tested, not a "medium-term" investigation. It requires almost no implementation -- just change `type: "command"` to `type: "agent"` in hooks.json and write a simple agent prompt. If it works (subagent output is isolated), we get the BEST possible solution (full quality + zero noise) for minimal effort. If it fails, we proceed to Tier 3 with full confidence.

The research team has it backwards: they propose building incrementally toward silence (Tier 1 -> Tier 2 -> Tier 3) when the logical order is test-the-cheapest-full-solution first (Tier 2), then optimize.

---

## Summary of Findings

| Concern | Finding | Severity |
|---------|---------|---------|
| Solves both problems? | Only Tier 3 definitively does | High |
| Simpler alternatives? | "No auto-capture" option not considered; quiet mode config absent | Medium |
| 3-tier over-engineering? | Yes -- Tier 2 is a blocking gate not a parallel track | High |
| Quality without SKILL.md? | Duplicate accumulation risk is serious and understated | High |
| User mental model | Favors "watch it happen" elimination entirely, not reduction | Medium |
| Silent failure UX | No completion feedback mechanism proposed | High |
| Implementation order | Test Tier 2 first (cheapest full solution), not last | High |

---

## Recommendations

1. **Test Tier 2 first** (agent hook isolation) before building anything. Change one line in hooks.json, test in a real session. This is a 10-minute experiment that determines the entire architecture.

2. **If Tier 2 works**: Implement it as the sole primary approach. Optimize SKILL.md for the agent hook context. Archive Tier 3 design docs.

3. **If Tier 2 fails**: Implement Tier 3 (Inline API Save) but add the ACE candidate lookup step (call `memory_candidate.py` as a subprocess within the hook script). Accept the loss of Phase 2 verification as a reasonable trade-off.

4. **Add completion feedback**: Regardless of approach chosen, implement a SessionStart notification hook that reports what was saved in the previous session. Silent saves without any confirmation feedback will erode user trust.

5. **Consider "quiet mode" as an opt-in config**: For users who prefer explicit saves, add `triage.auto_save: false` to config. Stop hook fires triage, writes deferred JSON, exits without blocking. User manually triggers /memory:save when they want. This eliminates noise entirely without any architectural change.

---

## Cross-Model Validation (Gemini 3.1 Pro via PAL clink)

The most controversial finding (implementation order is backwards -- test Tier 2 first) was validated by Gemini 3.1 Pro with one critical addition.

**Validated**: The tier-progression approach is driven by "Certainty Bias" -- teams schedule what they know how to build (Tier 1) to guarantee forward motion, which is an architectural anti-pattern when a cheap full-solution spike (Tier 2) is available. This matches Lean architecture principles: unknown with massive potential upside and trivial testing cost demands an immediate Technical Spike.

**Validated with nuance**: Tier 1 creates false comfort specifically because compaction is driven by token thresholds, not visible UI lines. Even 8-12 visible lines can include 40k+ tokens of subagent context, still triggering /compact.

**Critical addition from Gemini**: The 30-second Stop hook timeout may make Tier 2 non-viable for the full SKILL.md pipeline regardless of output isolation. An `agent` hook operating within the 30-second boundary cannot run multi-phase deduplication + CUD verification + content verification without timing out. This creates a paradox: **if Tier 2 works for output isolation, Tier 1's token/agent consolidation may become a prerequisite to making Tier 2 viable within the timeout**, not an alternative to it.

This strengthens the recommended action sequence: test Tier 2 output isolation first (10-minute spike), then measure actual agent hook execution time, then decide if Tier 1 optimization is needed to fit within the timeout window before deploying Tier 2 at scale.

**Platform Volatility risk** (Gemini-identified): Relying on `agent` hooks hiding tool calls in the UI is an undocumented UX dependency. If Anthropic changes the CLI to stream hook subagent thoughts for transparency, Tier 2 breaks instantly. Tier 1's approach (reduce actual token bloat) is platform-stable by design.
