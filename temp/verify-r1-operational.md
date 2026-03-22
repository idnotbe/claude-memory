# Verification Round 1: Operational Viability & UX Impact

**Reviewer:** Claude Opus 4.6 (1M context)
**Date:** 2026-03-22
**Focus:** Operational viability, UX impact, platform constraints, edge cases

---

## 1. fix-stop-hook-refire.md — PASS

**UX Impact:** Directly eliminates the most severe UX problem (2-3x re-fire producing ~78+ visible items). The three-fix approach in Phase 1 is sound: removing `.triage-handled` from cleanup patterns, extending TTL, and adding the save-result guard creates triple redundancy.

**Execution Order:** Correctly identified as P0. This MUST land before any other plan because re-fire amplifies all other noise and popup problems.

**Risk Assessment:** Accurate. Low risk -- all three Phase 1 changes are conservative defensive additions, not behavioral changes to the scoring logic.

**Specific Findings:**

- **RC-1 fix is correct.** Confirmed: `_STAGING_CLEANUP_PATTERNS` at `memory_write.py:506` includes `.triage-handled`. Removing it is safe because the sentinel has its own TTL-based self-cleanup.
- **RC-2 fix is correct.** `FLAG_TTL_SECONDS = 300` at `memory_triage.py:49` is genuinely too short for a 17-28 min save flow. 1800s (30 min) covers the observed worst case.
- **RC-3 (SESSION_SUMMARY always re-triggers) is correctly identified but underaddressed.** The plan does not directly fix this -- it relies on the idempotency guards to prevent re-evaluation entirely. This is sufficient IF the guards work, but if any guard fails, SESSION_SUMMARY will still always trigger because `score_session_summary()` (line 408-429) uses cumulative activity metrics that only grow as the save flow adds more tool calls. The session-scoped sentinel in Phase 3 is the real fix for this.
- **Phase 2 RUNBOOK threshold increase (0.4 -> 0.5) is reasonable** but Step 2.2 (negative filter for instructional text) is vaguely specified. Needs concrete implementation: which patterns, where in the pipeline, how to avoid suppressing legitimate RUNBOOK triggers.
- **Phase 3 session-scoped sentinel is well-designed.** Using `get_session_id(transcript_path)` to key the sentinel is the correct long-term solution. The `check_stop_flag()` function (line 522-538) currently consumes the flag on read (`flag_path.unlink(missing_ok=True)` at line 535), which is the "consumed on check = fragile" pattern correctly identified for replacement.

**Edge Cases:**
- Multiple Claude Code sessions: Session-scoped sentinel keyed by `session_id` handles this correctly -- different sessions have different IDs.
- Crash mid-save: Save-result guard (Step 1.3) only blocks if `last-save-result.json` is fresh. A crash won't produce this file, so next session starts clean. Correct.

**Verdict: PASS.** All fixes are mechanically sound and directly address observed root causes.

---

## 2. eliminate-all-popups.md — PASS WITH CONCERNS

**UX Impact:** If fully implemented, this would achieve zero popups during auto-capture. That is the single most impactful UX improvement possible.

**Execution Order:** Correctly P0 alongside re-fire fix. Popups are the primary user frustration.

**Risk Assessment:** Phase 1 and Phase 2 risks are accurately assessed (low). Phase 3 risk is UNDERESTIMATED.

**Specific Findings:**

### Phase 1 (Fix P1: python3 -c replacement) -- Sound
- Adding `--action cleanup-intents` to `memory_write.py` is clean and follows existing patterns. No concerns.

### Phase 2 (Fix P2: Haiku heredoc prevention) -- Sound with caveat
- `--action write-save-result-direct` taking CLI args is correct.
- **Concern:** The current SKILL.md Phase 3 (lines 294-298) already instructs the save subagent to use Write tool for the result JSON, then call `memory_write.py --action write-save-result`. The `write-save-result-direct` action would bypass the Write step, but the subagent still needs to pass structured data (categories list, titles list, timestamps). CLI args for lists are fragile with haiku -- quoting, escaping, and shell interpolation. Consider accepting a simple comma-separated format rather than JSON on the command line.

### Phase 3 (Fix P3: Eliminate Write tool for staging) -- CONCERNS

**Concern 1: memory-drafter return-JSON feasibility.**
The plan proposes changing the drafter from writing a file via Write tool to "returning JSON as stdout." This requires the Agent tool to capture subagent output as text the main agent can parse. Current behavior: Agent subagents run autonomously and their final response is returned to the parent. The parent agent receives this as conversational text, not structured data. Key issues:

- **Parsing reliability:** The main agent must extract JSON from the drafter's conversational response. Drafters may wrap JSON in explanation text ("Here is the intent JSON: {...}"), making extraction fragile.
- **Size limits:** Intent JSONs are typically 500-2000 bytes. This is well within Agent response limits. Not a concern.
- **Current drafter instructions** (agents/memory-drafter.md line 34) say "Write raw JSON only." If the drafter instead outputs raw JSON as its response (no file write), the main agent receives it. This is feasible but requires careful prompt engineering to prevent wrapping text.
- **Alternative (more robust):** Keep the drafter writing to a file, but use `memory_write.py --action write-staging` to route the write through Python `open()`. The drafter would call a Bash command instead of Write tool. But wait -- the drafter has `tools: Read, Write` only (no Bash). So the drafter cannot call scripts directly.
- **Better alternative:** Give the drafter `tools: Read, Bash` instead of `tools: Read, Write`. The drafter calls `python3 memory_write.py --action write-staging --filename intent-<cat>.json --content-stdin` and pipes the JSON. But this reintroduces Guardian risk (the whole reason for Write-only).
- **Best alternative (recommended):** The drafter outputs JSON as its response text. The main agent parses it and writes it to staging via `memory_write.py --action write-staging`. This works if the drafter prompt explicitly says "Output ONLY raw JSON, no surrounding text." The current drafter already has "Write raw JSON only" (line 34) which can be adapted.

**Verdict on return-JSON:** Feasible but the plan underestimates the prompt engineering needed and should include a fallback (e.g., if the response doesn't parse as JSON, try extracting from code fences). The plan should explicitly describe the main agent's JSON extraction step.

**Concern 2: Option C (PermissionRequest hook) dismissal may be premature.**
The hook-format-investigation.md (Workaround A) identifies this as the cleanest approach but notes it "needs testing." The plan lists it as "INVESTIGATE FIRST" but then recommends Option A (script routing) without resolving whether PermissionRequest works. If PermissionRequest works for the protected directory check, it would be dramatically simpler than rearchitecting all staging writes through Python scripts. **Recommendation: Test PermissionRequest BEFORE committing to Option A.**

**Concern 3: Removing staging auto-approve from write_guard.py (Step 3.4).**
If the plan is only partially implemented (Phases 1-2 done, Phase 3 deferred), removing the auto-approve breaks the existing flow. Step 3.4 should be gated on Phase 3 completion, not listed as a Phase 3 step that might be done independently.

**Edge Cases:**
- Drafter returns malformed JSON: Plan does not specify fallback. SKILL.md already handles this ("If a subagent fails or writes invalid JSON, skip that category"), so the existing error path works. But the failure mode changes -- instead of "file not written," it becomes "response text not parseable." Same outcome (skip category), different detection.
- Guardian not installed: No impact on this plan. The plan reduces Guardian surface area, which is correct.

**Backwards Compatibility:** The `--action cleanup-intents` and `--action write-staging` additions to `memory_write.py` are additive. Existing actions are unaffected.

**Verdict: PASS WITH CONCERNS.** Phase 3 is feasible but needs: (1) explicit JSON extraction strategy for drafter output, (2) PermissionRequest hook tested before committing to full script routing, (3) Step 3.4 gated on Phase 3 completion.

---

## 3. observability-and-logging.md — PASS

**UX Impact:** Indirect -- improves debuggability, not direct user experience. But critical for validating the other plans' effectiveness.

**Execution Order:** Correctly P1. Should follow the P0 fixes so that logging can measure their impact.

**Risk Assessment:** Accurate. Logging changes are the lowest risk category. The existing `memory_logger.py` uses fail-open design (JSONL append, never blocks main flow).

**Specific Findings:**

- **Phase 1 (triage observability):** Fire count via a counter file (`.triage-fire-count`) is a good approach. Using the existing `get_session_id()` for session correlation is clean.
- **Phase 2 (save flow timing):** Putting start timestamp in `triage-data.json` is logical since that file is already written by the triage hook at flow start. Computing duration in `write-save-result` captures end-to-end time accurately.
- **Phase 3 (metrics dashboard):** `memory_log_analyzer.py` already exists. Extending with `--metrics` and `--watch` modes is reasonable scope.
- **Minor concern:** The `save.start` event (Step 2.2) is listed as "via a script call or SKILL.md instruction to log." If implemented as a SKILL.md instruction, it depends on the LLM actually emitting the log call, which is unreliable. Better to emit `save.start` deterministically from a script (e.g., at the top of `memory_detect.py` if the architecture simplification plan lands, or from a new Phase 0 script step).

**Edge Cases:**
- Counter file corruption: `.triage-fire-count` is a simple integer file. If corrupted, the counter resets. Non-critical.
- Concurrent sessions writing to the same log file: `memory_logger.py` uses atomic append, so interleaved JSONL lines from different sessions are safe. Session ID distinguishes them.

**Verdict: PASS.** Low risk, high diagnostic value. No blocking concerns.

---

## 4. screen-noise-reduction.md — PASS WITH CONCERNS

**UX Impact:** Targets the right problem (26 visible items -> ~4). The noise inventory is thorough and the useful/not-useful classification is accurate.

**Execution Order:** Correctly P1. Should follow P0 fixes. Some items (Phase 1 Step 1.3 removing inline `<triage_data>`) could be bundled with the P0 work since they touch `memory_triage.py` already.

**Risk Assessment:** Mostly accurate. Phase 3 risk is underestimated.

**Specific Findings:**

### Phase 1 (Quick Wins) -- Sound
- Suppressing CUD narration and intermediate status via SKILL.md instructions is zero-risk. The LLM follows explicit suppression instructions reliably.
- Removing inline `<triage_data>` from block message is correct. The `<triage_data_file>` reference is the primary mechanism; inline JSON is a backwards-compatibility fallback that is no longer needed if the file write succeeds.

### Phase 2 (Consolidate Tool Calls) -- Sound
- Combining multiple independent Bash calls with `;` separators is a mechanical improvement. Each `memory_candidate.py` run is independent.
- If the popup fix plan's `write-staging` action lands, combining multiple write-staging calls into one Bash call is correct.

### Phase 3 (Reduce Subagent Visibility) -- CONCERNS

**Concern 1: `run_in_background: true` for Agent tool.**
Step 3.1 proposes running Phase 1 drafters with `run_in_background`. This is speculative -- the Claude Code Agent tool may not support `run_in_background` the same way the Bash tool does. The Agent tool spawns a subagent that runs to completion and returns its response. If `run_in_background` is supported, the main agent would need a mechanism to collect results later (analogous to TaskOutput for Bash). The plan does not address how to collect drafter outputs from background agents. **This needs platform verification.**

**Concern 2: Making verification optional (Step 3.2).**
Config flag `triage.parallel.verification_enabled` defaulting to `true` is safe. But the plan then suggests skipping verification for session_summary (Step 3.3) by default. This creates an implicit category-level verification config that is NOT reflected in the config schema. Either make it explicit in config (`triage.parallel.verification_categories`) or keep it all-or-nothing.

Note: The architecture-simplification plan also proposes `triage.parallel.verification_categories` with the same default. These two plans should be coordinated to avoid config duplication.

**Metrics target (< 10 visible items):**
The estimated ~4 items (triage message, skill load, drafter spawn, save summary) is optimistic. Actual count depends on:
- Whether `run_in_background` works for Agent (if not, drafter spawn + completion = 2 items per category)
- Whether the main agent's own Phase 1.5 tool calls are suppressible (they show up as individual tool call blocks in the UI)
- Skill load message is platform-controlled and cannot be eliminated

Realistic estimate without `run_in_background`: ~8-12 items. Still a major improvement from 26.

**Verdict: PASS WITH CONCERNS.** Phase 1-2 are solid quick wins. Phase 3 requires platform verification for `run_in_background` on Agent tool, and verification config needs coordination with architecture-simplification plan.

---

## 5. architecture-simplification.md — PASS WITH CONCERNS

**UX Impact:** The most ambitious plan with the highest potential payoff (17-28 min -> 3-8 min, 26 -> 6-8 visible items, 220k -> 80k tokens). If successful, this subsumes much of what plans 3 and 4 achieve.

**Execution Order:** Correctly P2. Depends on P0 fixes landing first. The plan correctly lists fix-stop-hook-refire and eliminate-all-popups as dependencies.

**Risk Assessment:** UNDERESTIMATED. This is a major architectural rewrite that touches the most complex part of the system.

**Specific Findings:**

### Phase 1: DETECT (deterministic script) -- Sound in concept, challenging in practice

**Concern 1: CUD resolution in Python.**
Currently, CUD resolution is performed by the main agent following the CUD Verification Rules table in SKILL.md (lines 337-348). This is a lookup table with 7 rules + special cases (vetoes, absent intended_action). Porting to Python is feasible but requires:
- Faithfully replicating all 7 CUD rules
- Handling the veto special case (veto restricts specific actions, not the whole category -- SKILL.md lines 172-177)
- Handling absent `intended_action` (default to UPDATE -- SKILL.md line 178)
- Handling lifecycle_hints propagation

The plan says "Port exact same logic from SKILL.md" but underestimates the number of edge cases in CUD resolution. This is the highest-risk component of the entire architecture change.

**Concern 2: Candidate selection timing.**
Currently, candidate selection runs AFTER intent drafting (Phase 1.5 Step 2), because it needs the `new_info_summary` from the drafter to compute similarity. In the proposed flow, DETECT runs BEFORE drafting. This means DETECT cannot use `new_info_summary` for candidate selection, because it does not exist yet.

This is a **critical sequencing issue**. Options:
- Run candidate selection without `new_info_summary` (weaker matching, may miss update candidates)
- Run candidate selection AFTER drafting (breaks the DETECT-DRAFT-COMMIT linearity)
- Pass the triage context snippets instead of drafter summary (different quality, needs testing)

The plan does not address this dependency.

### Phase 2: DRAFT -- Sound
Unchanged from current drafter architecture. Uses the same `memory-drafter` agent. The return-JSON approach (from eliminate-all-popups Phase 3) feeds in naturally.

### Phase 3: COMMIT (deterministic script) -- Sound
Chaining `memory_draft.py -> memory_write.py -> memory_enforce.py` in a single script is straightforward. All three scripts already have CLI interfaces. The main benefit is eliminating the haiku save subagent entirely, which removes the model compliance risk.

### Performance target (3-8 min) -- OPTIMISTIC

Current breakdown (estimated from synthesis):
- Triage hook: ~5s (deterministic, stays same)
- Skill load + Phase 0 parsing: ~10s (stays same)
- Drafter subagents: ~2-5 min per category (LLM cold start + generation)
- Phase 1.5 CUD: ~1-2 min (main agent reading + running scripts)
- Verification: ~2-5 min per category
- Save subagent: ~1-2 min

Proposed:
- DETECT script: ~2-5s (deterministic)
- Drafter subagents: ~2-5 min (unchanged -- still LLM)
- COMMIT script: ~2-5s (deterministic)

The 3-8 min target is achievable IF verification is disabled for most categories. With verification enabled for decision + constraint, add ~2-5 min. So: 3-8 min without verification, 5-13 min with partial verification. Still a major improvement from 17-28 min. The plan's performance claims are achievable but the range should be 3-13 min depending on verification config.

### Risk: "Breaking change to SKILL.md"
Mitigation says "Version the SKILL.md and test before deploying." This is insufficient. SKILL.md is loaded by the skill system and there is no versioning mechanism. A bad SKILL.md breaks all memory saves with no rollback path except git revert. **Recommendation: Keep the old SKILL.md as `SKILL-v1.md` alongside the new `SKILL.md` during transition, with a config flag to select which flow to use.**

**Edge Cases:**
- `memory_detect.py` crashes: Entire save flow fails. Current architecture has the same SPOF at the triage hook level, so this is not a regression. But the DETECT script should have the same fail-open pattern as `memory_triage.py`.
- `memory_commit.py` crashes mid-way: Partial saves are possible (some categories written, others not). This is the same as the current architecture where the haiku subagent can fail mid-sequence. The staging files are preserved for retry. Acceptable.
- Missing or corrupt config: The DETECT script should inherit the same `load_config()` + defaults pattern used by `memory_triage.py`. Not mentioned in the plan.

**Backwards Compatibility:**
- Memory data format: Unchanged. All existing memories remain valid.
- Config format: New keys added (`triage.parallel.verification_enabled`, `triage.parallel.verification_categories`). Old configs without these keys use defaults. Compatible.
- SKILL.md: Major rewrite. Not backwards compatible, but this is the point.

**Verdict: PASS WITH CONCERNS.** The architecture direction is correct and the expected improvements are real. Three concerns need resolution: (1) candidate selection sequencing with `new_info_summary` dependency, (2) CUD resolution edge cases need exhaustive test coverage, (3) SKILL.md rollback strategy needed.

---

## Cross-Plan Analysis

### Execution Order Verification

The proposed order is:
1. P0: fix-stop-hook-refire (independent)
2. P0: eliminate-all-popups (independent of #1)
3. P1: observability-and-logging (benefits from #1 and #2 being done)
4. P1: screen-noise-reduction (some steps share files with #2)
5. P2: architecture-simplification (depends on #1 and #2)

**Assessment: Correct.** Plans 1 and 2 can be executed in parallel (they touch different parts of `memory_triage.py` and `memory_write.py` with non-overlapping changes). Plan 3 and 4 can also be parallelized. Plan 5 should wait for all others.

**Potential merge conflict:** Plans 1 and 2 both modify `memory_write.py`. Plan 1 removes `.triage-handled` from `_STAGING_CLEANUP_PATTERNS`. Plan 2 adds `--action cleanup-intents` and `--action write-staging`. These are non-overlapping changes to different sections of the file. No conflict expected.

**Potential conflict between plans 4 and 5:** Both plan 4 (screen-noise-reduction Phase 3) and plan 5 (architecture-simplification) propose making verification optional via config flags. They should agree on the same config key name and defaults. Currently both mention `triage.parallel.verification_enabled` and `triage.parallel.verification_categories`, so they are aligned.

### Platform Constraint Verification

**PermissionRequest hook:** Plans 2 and the hook investigation document both reference this as a potential solution. Neither confirms it works for the protected directory check. This is a **critical unknown** that should be resolved before implementing Phase 3 of plan 2. A 30-minute test (add PermissionRequest hook, trigger a Write to `.claude/memory/.staging/`, observe behavior) would resolve this.

**`run_in_background` for Agent tool:** Plan 4 assumes this works. This should be tested before relying on it. If it does not work, the noise reduction from ~26 to ~4 items becomes ~26 to ~8-12 items (still worthwhile but the plan's metrics need adjustment).

**`--dangerously-skip-permissions` does not bypass protected directory:** Confirmed by the hook investigation and GitHub issues #35646, #35718. Plans correctly work around this rather than depending on it.

### Edge Case Summary

| Scenario | Impact | Covered? |
|----------|--------|----------|
| Save flow crashes mid-way | Staging files preserved, next session detects `.triage-pending.json` | Yes (SKILL.md Phase 3 Step 3) |
| Multiple concurrent sessions | Session-scoped sentinel (plan 1 Phase 3) handles correctly | Yes |
| Missing memory config | `load_config()` falls back to defaults in all scripts | Yes (existing behavior) |
| Corrupt memory config | JSON parse error in `load_config()` falls back to defaults | Yes (existing behavior) |
| Guardian not installed | All plans reduce Guardian surface area; no plan depends on Guardian | Yes |
| Drafter returns non-JSON | Skip category (existing error path in SKILL.md) | Partially (plan 2 Phase 3 changes the failure mode) |
| `memory_detect.py` crash (plan 5) | Save flow aborts; same as current triage crash behavior | Not addressed -- needs fail-open design |
| Candidate selection without `new_info_summary` (plan 5) | Weaker matching, may miss update candidates | NOT COVERED -- critical gap |

---

## Summary Table

| Plan | Verdict | Key Concerns |
|------|---------|--------------|
| fix-stop-hook-refire | **PASS** | SESSION_SUMMARY cumulative scoring not directly fixed (mitigated by idempotency guards) |
| eliminate-all-popups | **PASS WITH CONCERNS** | Phase 3 return-JSON needs extraction strategy; PermissionRequest hook should be tested first; Step 3.4 ordering |
| observability-and-logging | **PASS** | `save.start` event should be script-emitted, not LLM-instructed |
| screen-noise-reduction | **PASS WITH CONCERNS** | `run_in_background` for Agent needs platform verification; verification config coordination with plan 5 |
| architecture-simplification | **PASS WITH CONCERNS** | Candidate selection sequencing gap (`new_info_summary` dependency); CUD edge case coverage; SKILL.md rollback strategy |
