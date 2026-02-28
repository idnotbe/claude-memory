# Memory Save UI Noise Reduction: Research Report

**Date:** 2026-02-28
**Status:** Complete (pending empirical testing of agent hook isolation)
**Research Team:** 4 research agents, 2 V1 verification agents, 2 V2 verification agents, 3 Gemini cross-validations

---

## Problem Statement

When claude-memory's Stop hook triggers, the memory save process produces 50-100+ lines of visible output in the main conversation:

1. **Stop hook triage output** (~20-30 lines): Full `<triage_data>` JSON block embedded in the `reason` field
2. **Phase 1/2 subagent spawn lines** (~2-4 lines each): Task spawning for draft/verify (minimal noise)
3. **Phase 3 save operations** (~30-50 lines): Multiple Bash calls to `memory_candidate.py`, `memory_draft.py`, `memory_write.py`, `memory_enforce.py`
4. **Error handling/retries** (variable): Unpredictable, can be very verbose

### Impact
- User must scroll past 50-100+ lines to see original conversation
- Memory save process consumes ~7,000-20,000 tokens in the main context window
- Auto-compact triggers at ~167K tokens — a 3-category save consumes ~4-12% of available buffer
- If /compact fires, earlier conversation context is permanently summarized away

---

## Root Cause Analysis

### The Fundamental Issue

The `{"decision": "block", "reason": "..."}` pattern forces the **main agent** to become the orchestrator of the save pipeline. Everything the main agent does in response — spawning subagents, reading files, running Bash commands — is:
1. **Visible to the user** (cannot be suppressed)
2. **Added to the main context window** (triggers /compact)

There is no Claude Code mechanism to make the main agent's tool calls invisible. The `suppressOutput` hook field only hides the hook's own stdout, not what the agent does afterward.

### What Does NOT Help
- `suppressOutput: true` — only hides hook stdout from verbose mode (Ctrl+O)
- `run_in_background: true` on Task tool — return values still inject into main context
- Reducing Phase 1/2 noise — subagent internals are already isolated; only the compact "Done" line shows
- Making hook stdout shorter — it goes to verbose mode, not main context

### What DOES Help
- Reducing the `reason` content (less text in the block notification)
- Reducing what the main agent does in response (fewer/simpler tool calls)
- Moving save work OUT of the main agent entirely

---

## Three Key Cost Dimensions

The research revealed an important distinction between three separate concerns:

| Dimension | What It Affects | User Impact |
|-----------|----------------|-------------|
| **UI Visibility** | Lines shown in terminal | Scroll distance, readability |
| **Main Context Tokens** | Token count toward /compact threshold | Context loss, conversation quality |
| **API Billing** | Total tokens billed (incl. subagent overhead) | Cost per session |

Solutions should be evaluated on all three, but the user's primary complaints are about **UI visibility** and **main context tokens** (which cause /compact).

---

## Solution Spectrum

### Solution 1: Quick Wins (Minimal Change)

**Fix A: Externalize triage_data to file**
- Change `format_block_message()` in `memory_triage.py` (line 870+) to write `<triage_data>` JSON to `.staging/triage-data.json` instead of embedding it inline
- Shorten reason to: `"Save N memories (categories). Read .staging/triage-data.json for details."`
- Update SKILL.md Phase 0 to read triage data from file instead of parsing inline JSON
- **Effort:** ~20 lines of Python change + SKILL.md update
- **Impact:** Reduces Source 1 noise from ~25 lines to ~3 lines

**Fix B: Consolidate Phase 3 into single subagent**
- After Phase 1/2 subagents return, spawn ONE foreground Task subagent for Phase 3
- Subagent handles all verification + save operations internally
- Returns brief summary: "Saved: Title1, Title2"
- Main agent outputs only the summary
- **Effort:** SKILL.md restructure
- **Impact:** Reduces Source 3 noise from ~30-50 lines to ~3 lines (Task spawn + Done + summary)

**Combined effect (Fix A + Fix B):**

| Metric | Before | After |
|--------|--------|-------|
| Visible lines | 50-100+ | ~8-12 |
| Main context tokens | 7,000-20,000 | ~1,000-1,500 |
| UI noise reduction | — | ~85% |
| /compact impact | Significant | Minimal |
| Quality | Full SKILL.md | Full SKILL.md |
| Effort | — | Low |

**Limitations:** Still shows 8-12 lines. Doesn't achieve "zero noise." The Stop hook block notification is still visible.

---

### Solution 2: Agent Hook for Stop Event (EXPERIMENTAL — needs testing)

**Concept:** Change the Stop hook from `type: "command"` to `type: "agent"`. Agent hooks spawn a subagent with its own context window. If this subagent's tool calls are isolated from the main transcript, it achieves full quality + near-zero noise.

**How it would work:**
1. Stop event fires
2. Agent hook spawns a dedicated "memory-save" subagent
3. Subagent reads context files, runs full SKILL.md pipeline, saves memories
4. Subagent returns `{"decision": "block"}` or `{"decision": "allow"}` with brief reason
5. Main conversation sees only the hook's decision — no tool calls visible

**Potential outcome:**
- UI: ~0-2 lines (just the hook decision)
- Main context: ~100 tokens (just the decision reason)
- Quality: Full SKILL.md (subagent has tool access)
- Effort: Low (one hooks.json change + agent prompt file)

**CRITICAL UNKNOWN:** No research source could confirm whether agent hook subagent tool calls are isolated from the main transcript. Claude Code documentation mentions agent hooks but doesn't explicitly state transcript isolation behavior. This **requires empirical testing** — a 10-minute experiment.

**Concerns from cross-validation:**
- Agent hooks may still show status indicators in the UI
- Agent hooks incur ~20K token API billing overhead (not main context)
- Stop hook agent timeout behavior needs verification
- May not support `decision: "block"` returns (undocumented for agent hooks)

**Recommendation:** Test this FIRST. If it works, it's the best solution. If not, fall back to other options.

---

### Solution 3: Deferred Save Mode (NOT RECOMMENDED as primary)

**Concept:** Stop hook writes triage data + context files to disk, exits WITHOUT blocking. Next session's UserPromptSubmit hook detects pending saves and prompts the user.

**V2 Contrarian Analysis — Fatal Flaws:**

1. **~5-10% manual trigger rate.** CLI tools with "pending task" notifications suffer >85% attrition. Users launching a new session are in problem-solving mode — the save notification competes with their actual goal.

2. **session_summary is broken by deferral.** The purpose of session_summary is to capture what happened in the session that just ended. Drafting it in a future session from truncated context files produces a reconstruction artifact, not a summary. High hallucination risk, low fidelity.

3. **Cross-project loss.** `.staging/` is project-local. If a user works on Project A (Monday) then Project B (Tuesday), they will NEVER see Project A's pending save notification. For users across 5+ projects, this is the common case, not an edge case.

4. **Terminal session loss.** The sessions most worth capturing (high-value sessions that resolve the problem completely) are often terminal — no follow-up session needed. Deferred mode fails hardest for the most valuable memories.

5. **Violates the plugin's core promise.** The plugin is auto-capture memory. Deferred mode is manual memory management with extra steps. This inverts the value proposition.

**Verdict:** Deferred mode may be offered as an opt-in `triage.save_mode: "deferred"` config for users who explicitly prefer manual control, but it MUST NOT be the default or primary approach.

**Where it IS acceptable:** As a fallback when inline save fails (API timeout, error). Write a deferred sentinel, notify next session.

**Implementation note:** Fully buildable if needed (~25 lines total across `memory_triage.py` and `memory_retrieve.py`). Staging files persist across sessions (confirmed: no auto-cleanup exists).

---

### Solution 4: Foreground Single Task (Practical Middle Ground)

**Concept:** Stop hook blocks with minimal 1-line reason. Main agent spawns ONE foreground Task subagent that handles the entire 4-phase pipeline internally and returns a brief summary.

**Visible output:**
```
● Stop hook: Save 2 memories (session_summary, decision).    (1 line)
● Task(Save memories) Haiku 4.5                               (1 line)
  ⎿  Done (12 tool uses · 60k tokens · 20s)                   (1 line)
● Memories saved: "Session summary updated", "Auth decision"  (1 line)
```

**Metrics:**
- UI: ~4-5 lines
- Main context: ~350 tokens
- API billing: ~20K base + ~40K work = ~60K tokens
- Quality: Full SKILL.md (runs inside Task subagent)
- Effort: Medium (SKILL.md restructure + 1-line reason change)

**Why this works:**
- Stop hook `decision: block` keeps session alive — no subagent lifecycle risk
- Foreground Task is synchronous — no polling, no race conditions
- Subagent internals are isolated from main context (official behavior)
- Preserves FULL SKILL.md quality including ACE candidate selection, CUD verification, OCC

**Concerns:**
- Subagent transcript leakage bugs (#14118, #18351) may occasionally expose internal tool calls — these are bugs, not designed behavior, and may be fixed
- ~20K base token overhead per save (API billing concern, not context concern)
- Still blocks session exit for 15-25 seconds

---

### Solution 5: Inline API Save in Stop Hook (HIGH RISK — last resort)

**Concept:** Stop hook Python script calls Claude API directly via urllib for drafting, then runs memory_write.py as a Python import. No main agent involvement.

**Security risks identified (from verification):**

| Risk | Severity | Details |
|------|----------|---------|
| API key exposure | CRITICAL | Chained attack: prompt injection → memory save → key exfiltration |
| Prompt injection | HIGH | Crafted `<memory_draft>` blocks in conversation → saved as memory |
| Hook timeout lockout | HIGH | 30s timeout during API call → undefined Claude Code behavior |
| ACE candidate bypass | HIGH | No dedup → duplicate memories accumulate indefinitely |
| PostToolUse validation bypass | MEDIUM | Schema validation hook won't fire for Python-internal writes |
| No error visibility | MEDIUM | Silent failures → user loses memories without knowing |

**NOT RECOMMENDED as primary approach.** The security surface is too large for the gain. Consider only after other approaches are exhausted AND with:
- Dedicated restricted API key (not user's primary)
- Per-request timeout well below hook timeout
- Candidate lookup integration
- Explicit schema validation call
- Fallback: write deferred sentinel on API failure

---

### Solution 6: External Detached Process (HIGH RISK — last resort)

**Concept:** Stop hook spawns detached Python process (`start_new_session=True`) that calls Claude API.

**Additional risks beyond Solution 5:**
- Orphan process accumulation (no kill mechanism)
- No audit trail (runs outside Claude Code event system)
- Cross-process race conditions with concurrent Claude Code instances
- No coordination between orphan process and new session hooks

**NOT RECOMMENDED.** All risks of Solution 5 plus process management complexity.

---

## Recommended Decision Tree

```
┌──────────────────────────────────────────────────────────┐
│  STEP 1: Implement Fix A + Fix B (Primary Path)          │
│                                                          │
│  Fix A: Externalize triage_data to file (~10 lines)      │
│  Fix B: Consolidate Phase 3 into single Task subagent    │
│                                                          │
│  Result: ~85% noise reduction, full quality preserved    │
│  Visible output: ~8-12 lines (from 50-100+)             │
│  Context saving: ~1,000-1,500 tokens (from 7,000-20,000)│
└────────────────────────┬─────────────────────────────────┘
                         │
              ┌──────────▼──────────────────────┐
              │  STEP 2 (parallel): Test Agent   │
              │  Hook Isolation                  │
              │                                  │
              │  Change type → "agent" in        │
              │  hooks.json. Observe:            │
              │  - Subagent tool calls visible?  │
              │  - ok:false blocks stop?         │
              │  - Timeout behavior?             │
              │                                  │
              │  NOTE: This is NOT a 10-min test │
              │  Agent hooks use different schema│
              │  (prompt, not command). Requires  │
              │  writing agent prompt + testing.  │
              │  Budget: 2-4 hours.              │
              └──────┬───────────┬───────────────┘
                     │           │
                Works ✓     Doesn't work ✗
                     │           │
           ┌─────────▼───┐  ┌───▼──────────────────┐
           │ UPGRADE to  │  │ STAY with Fix A+B.   │
           │ agent hook  │  │ Optionally add:      │
           │ as primary. │  │ - Foreground single   │
           │ Full quality│  │   Task (Solution 4)   │
           │ + zero noise│  │   for further noise   │
           │             │  │   reduction to ~4-5   │
           │             │  │   lines               │
           └──────┬──────┘  └───────────┬──────────┘
                  │                     │
                  └──────────┬──────────┘
                             │
              ┌──────────────▼─────────────────────┐
              │  REGARDLESS OF PATH:               │
              │                                    │
              │  1. Add SessionStart confirmation   │
              │     hook: "N memories saved from    │
              │     last session: [titles]"         │
              │                                    │
              │  2. Add deferred mode as OPT-IN    │
              │     config (triage.save_mode:       │
              │     "deferred") for users who       │
              │     prefer manual /memory:save      │
              │                                    │
              │  3. Add error fallback: if inline   │
              │     save fails, write deferred      │
              │     sentinel for next-session retry │
              └────────────────────────────────────┘
```

---

## Implementation Priority

| Priority | Change | Effort | Impact | Dependencies |
|----------|--------|--------|--------|-------------|
| **P0** | Fix A: externalize triage_data | ~2 hours | Eliminates ~20 lines of inline JSON noise | None |
| **P0** | Fix B: single Task subagent for Phase 3 | ~4 hours | Eliminates ~30-50 lines of tool call noise | None |
| **P1** | SessionStart confirmation hook | ~3 hours | Save feedback UX (confirms success/failure) | None |
| **P1** | Error fallback: deferred sentinel on save failure | ~2 hours | Resilience against timeout/error | Fix A |
| **P2** | Test agent hook isolation (type:"agent" on Stop) | ~4 hours | If works: upgrade to zero-noise architecture | None |
| **P2** | Foreground single Task (Solution 4) | ~6 hours | Further noise reduction to ~4-5 lines | Fix A |
| **P3** | Deferred mode as opt-in config | ~4 hours | Manual control option for power users | Fix A |
| **P3** | Agent hook full implementation (if P2 succeeds) | ~8 hours | Zero noise + full quality | P2 confirmed |

---

## Open Questions (Require Empirical Testing)

1. **Agent hook isolation**: Does `type: "agent"` on a Stop hook produce visible tool calls in the main transcript? (P0 — blocks architecture decision)

2. **Agent hook decision support**: Can an agent hook return `{"decision": "block"}` from a Stop event? Or is this only supported for `type: "command"` hooks?

3. **Hook timeout on block**: If a Stop hook times out (30s), does Claude Code (a) allow the stop, (b) retry the hook, or (c) hang indefinitely? This is critical for any approach that adds work to the Stop hook.

4. **Subagent transcript leakage**: Are GitHub issues #14118 and #18351 (subagent transcript leakage to parent context) still present in current Claude Code? If fixed, the foreground single Task approach becomes more reliable.

5. **Context file persistence**: Do `.staging/` files survive across sessions? If Claude Code cleans up `.claude/` between sessions, deferred mode won't work.

---

## V2 Verification Corrections (Post-Synthesis)

### Correction 1: Deferred mode demoted from Rank 2 to opt-in fallback
**Source:** V2 contrarian reviewer
**Reasoning:** Fatal UX flaws — ~5-10% manual save rate, session_summary category broken, cross-project memory loss, violates auto-capture promise. Viable only as opt-in config for explicit-control users.

### Correction 2: Agent hook is NOT a "10-minute experiment"
**Source:** V2 contrarian reviewer + feasibility verifier
**Reasoning:** Agent hooks use `prompt` field (not `command`), return `ok: true/false` (not `decision: block`), and require writing a full agent prompt. The hooks.json change is 2 lines, but making the full save pipeline work inside an agent hook requires significant prompt engineering. Budget 2-4 hours, not 10 minutes. However, the feasibility verifier confirmed that `type: "agent"` IS supported for Stop events and CAN return blocking decisions via `ok: false`.

### Correction 3: Fix A+B promoted from "fallback" to primary recommendation
**Source:** V2 contrarian reviewer
**Reasoning:** Fix A+B is the only approach that is (a) low risk, (b) preserves full SKILL.md quality including ACE candidate selection, (c) is immediately buildable (~10 lines + ~25 lines), and (d) addresses both UI noise (85% reduction) and context consumption (~85% reduction). Previous ranking rewarded speculative approaches for "appearing" low-risk.

### Correction 4: Silent failure requires confirmation mechanism
**Source:** V1 arch/UX verifier
**Reasoning:** Any noise-reducing approach must include a SessionStart confirmation hook. Without it, silent failures are indistinguishable from silent successes. A user relying on auto-capture who never gets confirmation will discover lost memories too late.

### Correction 5: Inline API save (Solution 5) has chained security risk
**Source:** V1 security verifier
**Reasoning:** Prompt injection → crafted memory save → API key exfiltration is a unique attack chain when hook scripts have both API key access and transcript parsing capability. This chain does not exist in the current SKILL.md architecture.

---

## Appendix: Research Sources

### Research Files (in /temp/)
| File | Author | Key Contribution |
|------|--------|-----------------|
| research-hook-api.md | hook-api-researcher | Hook API fields, suppressOutput behavior, statusMessage |
| research-background-agents.md | background-agent-researcher | Subagent context isolation bugs, agent teams analysis |
| research-alt-architectures.md | alt-arch-researcher | SessionEnd, detached process, inline API, agent hook type |
| research-context-impact.md | context-researcher | Token estimates, /compact triggers, context isolation reality |
| verification-security-ops.md | security-verifier | API key exposure, race conditions, ACE bypass risks |
| verification-arch-ux.md | arch-verifier | "Just don't block" option, quality trade-offs, silent failure UX |

### Cross-Model Validations
- **Gemini 3.1 Pro** (3 rounds via PAL clink):
  - R1: Recommended hybrid A+C; introduced Continuous Inline Memory, PreCompact piggyback, Next-Session Queue ideas
  - R2: Challenged background agent viability due to lifecycle concerns; confirmed main-agent-must-exit problem
  - R3: Confirmed conclusions 1,3,5; challenged 2 (agent hook not zero-cost) and 4 (billing vs context distinction)

### Vibe Checks (2 rounds)
- V1: Flagged over-research risk, suggested testing minimal fix first
- V2: Confirmed analysis paralysis pattern, recommended immediate synthesis

### V2 Verification Files (in /temp/)
| File | Author | Key Contribution |
|------|--------|-----------------|
| v2-contrarian.md | contrarian-verifier | Demolished deferred mode (5-10% save rate), corrected agent hook effort estimate |
| v2-feasibility.md | feasibility-verifier | Confirmed agent hook buildable for Stop, Fix A is ~10 lines, staging files persist |

### Key Claude Code Documentation
- [Hooks Reference](https://code.claude.com/docs/en/hooks) — Stop hook API, decision/reason fields, agent hook support
- [Subagents Docs](https://code.claude.com/docs/en/sub-agents) — context isolation
- [Hooks Guide](https://code.claude.com/docs/en/hooks-guide) — async hooks, agent hooks
