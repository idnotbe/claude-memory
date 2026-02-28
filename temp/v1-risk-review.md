# V1 Risk & UX Review: Memory Save UI Noise Reduction Action Plan

**Reviewer:** risk-verifier
**Date:** 2026-02-28
**Target:** `temp/action-plan-draft-v1.md`
**Cross-validation:** Gemini 3.1 Pro (via PAL clink), vibe-check metacognitive review

---

## Executive Summary

The action plan is well-structured and incorporates findings from all prior verification rounds (security-ops, arch-UX, contrarian, feasibility). The Phase 0 -> Fix A+B ordering is sound. However, the plan has **three significant gaps**: (1) no explicit deployment ordering or rollback strategy between Phases 1 and 2, (2) the Phase 2 CUD resolution handoff to a subagent risks data loss if not constrained to imperative execution, and (3) the 85% noise reduction estimate is contingent on subagent transcript isolation that the plan itself flags as unreliable.

---

## 1. Risk Completeness

### Risks Properly Covered (6 in table)
The risk table covers: agent hook isolation, CUD resolution integrity, venv bootstrap, SessionStart hook, context file staleness, subagent transcript leakage. These are the right risks for the scope.

### Missing Risks

| Missing Risk | Severity | Phase | Details |
|-------------|----------|-------|---------|
| **Deployment ordering within Phase 1** | HIGH | Phase 1 | If `memory_triage.py` is updated BEFORE `SKILL.md`, the old SKILL.md will search for the removed inline `<triage_data>` tag, fail to find it, and silently skip memory saves. The backwards-compatibility fallback is in the NEW SKILL.md, which means the fallback only works if SKILL.md is deployed first. **The plan does not specify intra-phase deployment order.** |
| **Subagent CUD hallucination** | HIGH | Phase 2 | The plan says the Task subagent "Receives: Phase 1/2 results summary, CUD resolution table, draft file paths." But CUD resolution is the most critical decision in the pipeline (create vs. update vs. retire). A subagent with a fresh context window interpreting a CUD table via prompt text may hallucinate actions. An UPDATE could become a CREATE (duplicate), or worse, a RETIRE could be skipped. |
| **No inter-phase rollback strategy** | MEDIUM | All | If Phase 1 is deployed but Phase 2 implementation stalls, the system runs with file-based triage data + old SKILL.md Phase 3 (main agent save). This works but is not explicitly tested. If Phase 2 is partially deployed (SKILL.md half-rewritten), the system could be in an inconsistent state. |
| **Phase 3 `last-save-result.json` persistence** | LOW | Phase 3 | The SessionStart confirmation relies on `last-save-result.json` existing when the next session starts. If the system crashes BETWEEN writing the result file and the session ending cleanly, the file may contain stale data. The plan says "1-time display then delete" but doesn't handle the case where the file persists across multiple sessions due to the delete failing. |

### Risks from Research NOT in the Plan's Risk Table (but addressed in plan body)
- Deferred mode ~5-10% save rate: Addressed by making Phase 4 error-fallback-only (not primary).
- API key exposure chain: Not relevant since the plan does NOT use inline API (Solutions 5/6 rejected).
- Cross-project pending saves: Acknowledged in Phase 4 as a known limitation.

**Assessment: The risk table is adequate for the chosen approach (Fix A+B), but should add deployment ordering and CUD hallucination risks.**

---

## 2. UX Impact: Are Noise Reduction Estimates Realistic?

### Fix A (Phase 1): triage_data externalization
- **Claim:** ~25 lines -> ~5 lines
- **Assessment: Realistic.** The `<triage_data>` JSON block (lines 950-953 in `memory_triage.py`) is a `json.dumps(triage_data, indent=2)` output embedded in the reason string. This JSON includes per-category scores, context file paths, and parallel config -- easily 20-25 lines. Replacing with a single `<triage_data_file>` tag line is a genuine reduction. The remaining ~5 lines are the category list and instruction text.

### Fix B (Phase 2): Phase 3 single Task subagent
- **Claim:** ~30-50 lines -> ~3 lines
- **Assessment: Optimistic, contingent on isolation.** Task subagent internals ARE generally isolated from the parent context (this is documented Claude Code behavior). However:
  - The plan's own risk table lists "Subagent transcript leakage (#14118, #18351)" as MEDIUM severity
  - If leakage occurs, the estimate collapses from 3 lines back to 30-50 lines
  - The 85% combined estimate should be presented as a **range**: best-case 85% (3 lines from Phase 3), worst-case ~60% (Phase 3 leaks but Phase 1 savings hold)

### Combined estimate
- **Best case:** 50-100+ lines -> 8-12 lines (85% reduction) -- realistic IF subagent isolation holds
- **Worst case:** 50-100+ lines -> 25-35 lines (60% reduction) -- if Phase 3 subagent leaks
- **Context token savings (1,000-1,500 from 7,000-20,000):** This is the more impactful metric for /compact prevention and is realistic even in the worst case, since subagent tokens are billed but not added to the main context window

**Recommendation: Present the estimate as a range (60-85%) rather than a single point (85%). Add a 5-minute isolation validation test at the start of Phase 2 before committing to the SKILL.md refactoring.**

---

## 3. Silent Failure Modes

### Addressed by the plan
- **Save failures:** Phase 4 deferred sentinel catches inline save failures
- **Success confirmation:** Phase 3 SessionStart hook confirms saves to user

### Not addressed

| Failure Mode | Phase | Impact | Likelihood |
|-------------|-------|--------|-----------|
| **SKILL.md fails to read triage-data.json** | Phase 1 | Main agent cannot parse triage data, may skip all saves or error out. User sees confusing error instead of memory save. | LOW -- the hook blocks until file is written, and the hook stdout includes the file path. But if the file path has special characters or the file is deleted between hook return and SKILL.md execution (unlikely but possible), this fails. |
| **Phase 2 subagent hallucinates success** | Phase 2 | Subagent reports "Saved: Title1, Title2" but actually failed one or more writes. Main agent passes the summary through. User believes saves succeeded. | MEDIUM -- LLM subagents can summarize optimistically. The `memory_write.py` exit code would indicate failure, but the subagent may not propagate it. |
| **SessionStart hook + pending sentinel both fire** | Phase 3+4 | If a save partially succeeds (2 of 3 categories), both the confirmation AND the pending-save notification appear in the next session. User sees contradictory messages: "2 memories saved" AND "1 unsaved memory from last session." | LOW but confusing -- the plan doesn't address partial save scenarios. |
| **`last-save-result.json` delete failure** | Phase 3 | Stale confirmation appears in every new session indefinitely. "Previous session: 2 memories saved" repeats forever. | VERY LOW -- filesystem delete rarely fails, but the plan should add a timestamp check (e.g., ignore results older than 24 hours). |

**Gemini cross-validation confirms:** The file write failure (3a) will NOT be silent -- `os.write`/`os.replace` throws on failure, crashing the hook script. The race condition (3d) is also not a real risk because the hook blocks synchronously. The `.tmp` file accumulation (3c) is not a risk because the static filename overwrites on each run.

**Assessment: The plan's Phase 3+4 combination adequately covers the primary silent failure path. The partial-save scenario (some categories succeed, others fail) deserves a brief note in the plan.**

---

## 4. Rollback Plan

### Current state: NO explicit rollback strategy

The plan has no section on rollback. Each phase modifies different files:

| Phase | Files Modified | Rollback Mechanism |
|-------|---------------|-------------------|
| Phase 0 | `hooks/hooks.json` (branch-isolated) | `git checkout main` -- safe, branch isolation is explicit |
| Phase 1 | `memory_triage.py`, `SKILL.md` | `git revert` -- but deployment order matters (see below) |
| Phase 2 | `SKILL.md` | `git revert` -- but Phase 1 changes to SKILL.md must be preserved |
| Phase 3 | New file `memory_session_confirm.py`, `hooks.json` | Remove hook entry + delete script -- clean |
| Phase 4 | `memory_retrieve.py`, SKILL.md | `git revert` the retrieve changes -- clean |

### Critical deployment ordering issue (confirmed by Gemini)

**Phase 1 has a hidden deployment dependency:**
1. The NEW `SKILL.md` supports BOTH inline `<triage_data>` AND file-based `<triage_data_file>` (backwards compatible)
2. The NEW `memory_triage.py` ONLY outputs `<triage_data_file>` (not inline)

If `memory_triage.py` is deployed BEFORE `SKILL.md`:
- The OLD `SKILL.md` searches for `<triage_data>` tag
- The NEW `memory_triage.py` outputs `<triage_data_file>` instead
- Result: **SKILL.md finds no triage data, silently skips all memory saves**

**Required deployment order: SKILL.md first, then memory_triage.py.** This must be documented in the plan.

**Recommendation: Add a "Rollback & Deployment Order" section to the plan with:**
1. Explicit intra-phase deployment order for Phase 1 (SKILL.md first)
2. Git revert commands for each phase
3. Compatibility matrix showing which combinations of old/new files work

---

## 5. Security Concerns

### No new security vulnerabilities introduced

The action plan deliberately avoids Solutions 5 (inline API) and 6 (detached process), which were the primary security concerns from the security-ops verifier. The chosen approach (Fix A+B) stays within the existing SKILL.md architecture:

- No API keys in hook scripts
- No transcript parsing for memory content (triage only does keyword scoring)
- No detached processes
- `memory_write.py` schema validation still fires via PostToolUse hook
- Write guards still active (PreToolUse:Write, PreToolUse:Bash)

### Minor concern: triage-data.json in .staging/

Phase 1 writes `triage-data.json` to `.staging/`. This file contains per-category scores, context file paths, and parallel config. It does NOT contain memory content or user conversation text. The staging guard (`memory_staging_guard.py`) blocks heredoc writes to `.staging/` but allows Python-generated files. This is consistent with the existing context file pattern.

**Assessment: No new security surface. The plan correctly avoids the high-risk approaches.**

---

## 6. Operational Concerns

### Timeouts
- **Phase 0 agent hook timeout:** The plan notes 60s default, configurable. The contrarian correctly flags that running the full SKILL.md pipeline in 60s is tight. The plan addresses this by time-boxing the experiment and noting 120-180s timeout for Phase 5.
- **Phase 1 triage hook timeout:** Unchanged at 30s. The new file write adds ~1ms. No concern.
- **Phase 2 subagent timeout:** Task subagents have their own timeout (not the hook timeout). The hook's 30s timeout only covers triage; the save operations happen AFTER the hook returns. No new timeout risk.

### Race conditions
- **triage-data.json write vs. read:** Not a real race condition. The hook script writes the file synchronously before printing the block decision. The agent only receives the decision after the file is fully written and closed. Confirmed by Gemini.
- **Concurrent Claude Code instances:** Not addressed by the plan, but this is a pre-existing issue (mentioned in security-ops Finding 2). Fix A+B does not worsen it.

### Error handling
- **Phase 1 file write failure:** Python `os.open()`/`os.write()` will throw on failure, crashing the hook script. Claude Code will report the hook failure. This is loud, not silent. However, the user's session will proceed without memory saves. The plan should note that a triage-data.json write failure should fall back to inline `<triage_data>` output (graceful degradation).
- **Phase 2 subagent failure:** If the Task subagent crashes or times out, the main agent should detect this and report it. The plan should specify what the main agent does when the Phase 3 subagent fails (retry? deferred sentinel? just report?).

**Recommendation: Add error handling specifications for Phase 1 file write failure (fallback to inline) and Phase 2 subagent failure (deferred sentinel).**

---

## 7. User Communication

### What the plan gets right
- **Phase 3 SessionStart confirmation:** "Previous session: 2 memories saved (session_summary, decision)." -- Clear, concise, non-intrusive.
- **Phase 4 pending notification:** "N unsaved memories from last session. Use /memory:save to save them." -- Actionable.

### What's missing
- **No user communication during save (Phase 2).** When the Phase 3 Task subagent is running, the user sees a Task spawn line and a "Done" line. There is no indication of what was saved or whether it succeeded DURING the current session. The user must wait until the NEXT session's SessionStart hook to see confirmation.
- **No error message specification.** If Phase 2 subagent fails, what does the user see? The plan should define the error messages.
- **No communication about Phase 0 experiment.** If the user is on the `exp/agent-hook-stop` branch, they should see a clear indication that this is experimental behavior.

**Recommendation: Add a "User-Facing Messages" appendix defining all confirmation, error, and notification messages across all phases.**

---

## 8. Cross-Model Validation Summary (Gemini 3.1 Pro)

Gemini independently identified and prioritized:

1. **CRITICAL: Deployment ordering within Phase 1.** SKILL.md must be updated before `memory_triage.py`. The backwards-compatibility fallback only exists in the new SKILL.md, not the old one. (Aligns with my Finding #4.)

2. **HIGH: CUD resolution in subagent.** The subagent should NOT be a decision-maker. CUD actions should be computed by the main agent or Python script, and the subagent should execute pre-determined commands. (Aligns with my Finding #1, Missing Risk #2.)

3. **MEDIUM: 85% estimate is best-case.** Structurally accurate but contingent on subagent isolation. Recommend a dummy subagent test before committing to Phase 2. (Aligns with my Finding #2.)

4. **LOW: Silent failure modes mostly addressed.** File write failure is loud (not silent). `.tmp` accumulation is not a risk (static filename). Race condition is not a risk (synchronous blocking). Only subagent hallucinated success is a real concern.

5. **VALIDATED: Phase 0 time-boxed spike ordering is sound.** Standard agile practice for high-reward unknowns.

---

## 9. Vibe Check Results

### Quick Assessment
The plan is solid and addresses the right problems. The primary risk is not in the approach itself but in the deployment mechanics (ordering, rollback) and the CUD resolution handoff to subagents.

### Pattern Watch
- **Confirmation bias risk:** This review (and the plan) builds on 4 prior verification rounds. Most risks have already been found. The novel contributions here are deployment ordering and CUD subagent constraints.
- **Over-verification:** This is the 5th review layer. Diminishing returns are real. The plan should be finalized and executed rather than reviewed further.

---

## Final Verdict

### Plan Quality: GOOD -- proceed with amendments

The plan is well-researched, correctly prioritized, and avoids the dangerous approaches (inline API, detached processes). The Phase 0 -> Fix A+B ordering is sound.

### Required Amendments Before Execution

| # | Amendment | Severity | Phase |
|---|-----------|----------|-------|
| 1 | Add explicit deployment order: SKILL.md first, then memory_triage.py | HIGH | Phase 1 |
| 2 | Constrain Phase 2 subagent to imperative execution (not CUD decision-making). Main agent or Python computes the exact action list; subagent runs commands. | HIGH | Phase 2 |
| 3 | Present noise reduction as a range (60-85%) with subagent isolation as the variable | MEDIUM | Phase 2 |
| 4 | Add 5-minute subagent isolation validation test at start of Phase 2 | MEDIUM | Phase 2 |
| 5 | Add error handling: Phase 1 file write failure falls back to inline `<triage_data>` | MEDIUM | Phase 1 |
| 6 | Add error handling: Phase 2 subagent failure triggers deferred sentinel (Phase 4) | MEDIUM | Phase 2 |
| 7 | Add "Rollback & Deployment Order" section | MEDIUM | All |
| 8 | Add "User-Facing Messages" appendix | LOW | All |
| 9 | Add timestamp check for `last-save-result.json` (ignore if > 24h old) | LOW | Phase 3 |
| 10 | Note partial-save scenario (some categories succeed, others fail) | LOW | Phase 3+4 |
