# Verification Round 1: Correctness & Completeness

**Reviewer:** Opus 4.6 (1M context)
**Date:** 2026-03-22
**Scope:** 5 action plans verified against actual codebase

---

## Plan 1: fix-stop-hook-refire.md

**Verdict: PASS WITH CONCERNS**

### Code Location Accuracy

| Reference | Claimed | Actual | Status |
|-----------|---------|--------|--------|
| `.triage-handled` in cleanup patterns | `memory_write.py:506` | Line 506 confirmed: `".triage-handled"` in `_STAGING_CLEANUP_PATTERNS` | CORRECT |
| `FLAG_TTL_SECONDS = 300` | `memory_triage.py:49` | Line 49 confirmed: `FLAG_TTL_SECONDS = 300  # 5 minutes` | CORRECT |
| SESSION_SUMMARY scoring | `memory_triage.py:408-429` | Lines 408-429 confirmed: `score_session_summary()` with cumulative metric formula | CORRECT |
| RUNBOOK patterns | `memory_triage.py:114-124` | Lines 113-131 confirmed: RUNBOOK primary patterns (line 114-118) and boosters (line 120-124). Slight line offset -- primary starts at 114 not 113 but range is inclusive | CORRECT |
| Sentinel check in `_run_triage()` | `~line 1084` | Lines 1078-1084 confirmed | CORRECT |
| `_run_triage()` sentinel check | `~line 1084` | Lines 1078-1084 confirmed | CORRECT |
| Phase 3 cleanup call | `SKILL.md:290` | Line 290 confirmed: `cleanup-staging --staging-dir .claude/memory/.staging` | CORRECT |
| RUNBOOK threshold | `memory_triage.py:57` | Line 57 confirmed: `"RUNBOOK": 0.4` in `DEFAULT_THRESHOLDS` | CORRECT |
| `check_stop_flag()` | `memory_triage.py:522-548` | Lines 522-548 confirmed: reads flag, checks age, deletes file, returns bool | CORRECT |
| `set_stop_flag()` | `memory_triage.py:541` | Lines 541-548 confirmed | CORRECT |
| Flag consumed (deleted) on check | `memory_triage.py:535` | Line 535 confirmed: `flag_path.unlink(missing_ok=True)` | CORRECT |

### Root Cause Accuracy

- **RC-1 (sentinel deleted by cleanup):** CONFIRMED. `_STAGING_CLEANUP_PATTERNS` at line 499-508 includes `.triage-handled`. `cleanup_staging()` at line 511-548 iterates patterns and deletes matches.
- **RC-2 (FLAG_TTL too short):** CONFIRMED. 300s = 5 min vs 17-28 min save flow.
- **RC-3 (SESSION_SUMMARY cumulative):** CONFIRMED. `score_session_summary()` uses cumulative metrics that can only increase as transcript grows with save flow activity.
- **RC-4 (RUNBOOK false positive):** CONFIRMED. RUNBOOK primary_weight=0.2, boosted_weight=0.6, threshold=0.4, denominator=1.8. Math: `(1*0.2 + 1*0.6) / 1.8 = 0.44 > 0.4`. SKILL.md loads into transcript on fire 1 response and contains "Error Handling" (line 310), "fails" (lines 120, 163), etc.

### Fix Completeness

- **Phase 1 (P0 Hotfix):** Sound. Step 1.1 (remove from cleanup) is a one-line fix. Step 1.2 (increase TTL to 1800) covers the save flow window. Step 1.3 (last-save-result.json guard) is defense-in-depth; confirmed `last-save-result.json` is NOT in `_STAGING_CLEANUP_PATTERNS`.
- **Phase 2 (RUNBOOK threshold):** Sound. Raising from 0.4 to 0.5 eliminates the marginal false positive (0.44 < 0.5).
- **Phase 3 (Session-scoped sentinel):** Sound conceptually. `get_session_id()` exists (imported from `memory_logger.py`, used at line 1108).

### Concerns

1. **Step 1.3 (last-save-result.json guard):** The action plan says to check `last-save-result.json` mtime with `< FLAG_TTL_SECONDS` comparison. But after Phase 1, `FLAG_TTL_SECONDS` = 1800. If a user starts a new session within 30 min, the stale save-result from the previous session would block triage. This is acknowledged in Phase 3 (session-scoped sentinel) but creates a window of incorrect behavior between Phase 1 and Phase 3.

2. **Phase 2 Step 2.2 (negative filter):** Vaguely specified. "Consider adding negative filter for instructional text patterns" has no concrete implementation spec.

---

## Plan 2: eliminate-all-popups.md

**Verdict: PASS WITH CONCERNS**

### Code Location Accuracy

| Reference | Claimed | Actual | Status |
|-----------|---------|--------|--------|
| Phase 0 `python3 -c` intent cleanup | SKILL.md Phase 0 Step 0 | SKILL.md lines 58-63 confirmed: `python3 -c "import glob,os\nfor f in glob.glob(...)..."` | CORRECT |
| Write tool popups for `.staging/` | `.claude/memory/.staging/*` | Confirmed: `memory_write_guard.py` outputs `permissionDecision: "allow"` at lines 123-128, but `.claude/memory/` is NOT in the Claude Code exempt list for protected directories | CORRECT |
| Protected directory exemptions | `.claude/commands/`, `.claude/agents/`, `.claude/skills/` | Matches `hook-format-investigation.md` findings; `.claude/memory/` NOT exempted | CORRECT |
| `memory_write_guard.py` staging auto-approve | Lines 123-128 | Confirmed: outputs `permissionDecision: "allow"` for staging paths | CORRECT |

### Root Cause Accuracy

- **P1 (python3 -c Guardian trigger):** CONFIRMED per guardian-analysis.md. The F1 safety net fires ASK when `check_interpreter_payload()` finds `os.remove` in the `-c` payload and glob resolution fails.
- **P2 (Haiku heredoc):** CONFIRMED as a model compliance risk. SKILL.md Rule 0 (line 433) forbids heredoc.
- **P3 (.claude/ protected directory):** CONFIRMED per hook-format-investigation.md. This is a Claude Code platform limitation. PreToolUse `allow` does not bypass the protected directory check.

### Fix Completeness

- **Phase 1 (P1 fix):** Sound. `--action cleanup-intents` eliminates `python3 -c` entirely. The `cleanup-intents` action does NOT currently exist in `memory_write.py` (confirmed by grep: no matches for `cleanup-intents`), so it must be created.
- **Phase 2 (P2 fix):** Partially addresses the issue. Step 2.1 strengthens the prompt. Step 2.2 (`--action write-save-result-direct`) does NOT exist yet (confirmed by grep: no matches for `write-save-result-direct` or `write-staging`). Steps 2.2-2.3 are new features.
- **Phase 3 (P3 fix):** Option A is the recommended approach. `--action write-staging` does NOT exist yet. Correctly identifies that routing all staging writes through Python `open()` bypasses the Write tool's protected directory check.

### Concerns

1. **Phase 3 Option A Step 3.2 (drafter returns JSON as stdout):** The memory-drafter agent (`agents/memory-drafter.md`) currently has `tools: Read, Write` and is instructed to write intent JSON via the Write tool (line 24: "Write an intent JSON file to the given output path using the Write tool"). Changing the drafter to return JSON as stdout is a significant architectural change. The agent file format supports this via the agent's response, but the SKILL.md orchestration would need to capture agent output and pipe it through a script. This is feasible but non-trivial.

2. **Phase 3 Option C (PermissionRequest hook):** The plan correctly flags uncertainty about whether `PermissionRequest` intercepts protected directory prompts. This needs testing first. However, the plan does NOT include a concrete test step for this option.

3. **Phase 3 Step 3.4 (remove staging auto-approve):** If `write_guard.py` auto-approve is removed, but the Write tool is still used for OTHER staging files (e.g., `last-save-result-input.json` in SKILL.md line 295), those writes would start prompting. The plan should ensure ALL Write tool staging writes are migrated before removing auto-approve.

4. **Dependency gap:** Phase 2 Step 2.2 introduces `--action write-save-result-direct` with `--categories` and `--titles` CLI args, but the existing `write_save_result()` function (line 558 of `memory_write.py`) takes a `result_json` string and validates structure. The new action would need different validation logic.

---

## Plan 3: observability-and-logging.md

**Verdict: PASS**

### Code Location Accuracy

- `get_session_id()`: Confirmed available via `memory_logger.py` import (line 31 of `memory_triage.py`), used at line 1108.
- `memory_log_analyzer.py`: Confirmed to exist at `hooks/scripts/memory_log_analyzer.py`.

### Root Cause Accuracy

- All listed logging gaps are accurate. The current `emit_event("triage.score", ...)` at line 1119-1131 logs scores but not fire_count, idempotency_skip, or timing.

### Fix Completeness

- **Phase 1 (Triage observability):** Sound. Fire count, session_id, and idempotency skip events are well-defined.
- **Phase 2 (Save flow timing):** Sound. Timestamps and duration calculation are straightforward.
- **Phase 3 (Dashboard):** `memory_log_analyzer.py` exists but does NOT currently have `--metrics` or `--watch` modes (confirmed by grep). These are new features.

### Concerns

- Minor: The plan references `memory_logger.py` for session_id propagation but doesn't specify what changes are needed. The current `emit_event()` already accepts a `session_id` kwarg.

---

## Plan 4: screen-noise-reduction.md

**Verdict: PASS WITH CONCERNS**

### Code Location Accuracy

| Reference | Claimed | Actual | Status |
|-----------|---------|--------|--------|
| `<triage_data>` inline JSON in block message | `memory_triage.py` format_block_message() | Lines 1007-1019 confirmed: inline `<triage_data>` JSON is included when `triage_data_path` is None (fallback). When path IS available, only `<triage_data_file>` tag is emitted (line 1008-1010). | PARTIALLY CORRECT -- see concern |
| CUD resolution reasoning | Phase 1.5 | SKILL.md lines 165-169 confirmed: CUD resolution instructions exist, but there is no explicit "output your reasoning" instruction. The noise comes from the LLM naturally narrating its reasoning, not from an explicit instruction. | CORRECT (noise is LLM behavior, not instruction) |
| SKILL.md Rule 2 | "Silent operation" | Line 435 confirmed: "Silent operation: Do NOT mention memory operations in visible output during auto-capture" | CORRECT |

### Fix Completeness

- **Phase 1 (Quick wins):** Sound. Suppressing CUD narration and intermediate status via SKILL.md instructions is low-risk.
- **Phase 2 (Consolidate tool calls):** Sound in principle. Combining Bash calls with `;` separators is already the pattern used in Phase 3 save commands.
- **Phase 3 (Reduce subagent visibility):** Step 3.1 references `run_in_background: true` for Agent tools. This is NOT currently used anywhere in SKILL.md (confirmed by grep). Whether Claude Code supports `run_in_background` for Agent tool calls is unclear -- this is a platform capability question.

### Concerns

1. **Step 1.3 (remove inline `<triage_data>`):** The plan says "Remove inline `<triage_data>` from block message." But the current code at lines 1007-1019 already uses `<triage_data_file>` when the file write succeeds and only falls back to inline `<triage_data>` when the file write fails (line 1195: `triage_data_path = None`). So the inline JSON is ALREADY a fallback-only path. The plan's characterization suggests inline is always present, which is inaccurate. Removing the fallback entirely could lose triage data when the file write fails. Better fix: keep the fallback but suppress it from the block message (write to a separate file or log instead).

2. **Step 3.1 (`run_in_background` for Agent):** This is speculative. Claude Code's Agent tool may not support `run_in_background`. The plan should have a fallback if this is not supported.

3. **Step 3.2-3.3 (verification config):** References `triage.parallel.verification_enabled` and `triage.parallel.verification_categories` config keys. These do NOT currently exist in the config schema (confirmed by grep: only found in the action plans themselves). They would need to be added to `memory-config.default.json` and documented.

4. **Metrics target (< 10 visible items):** The plan targets ~4 visible items. This assumes `run_in_background` works for Agent tools (Step 3.1). Without it, the actual count would be higher (~8-10) since subagent spawn/completion messages are still visible.

---

## Plan 5: architecture-simplification.md

**Verdict: PASS WITH CONCERNS**

### Code Location Accuracy

- References to current 5-phase architecture in SKILL.md: CONFIRMED. Phases are Pre-Phase, Phase 0, Phase 1, Phase 1.5, Phase 2, Phase 3 (SKILL.md confirmed with 456 lines).
- `memory_detect.py`: Does NOT exist yet (confirmed by glob). This is a NEW file.
- `memory_commit.py`: Does NOT exist yet (confirmed by glob). This is a NEW file.

### Root Cause Accuracy

- All stated architecture problems are accurately characterized based on the codebase analysis.

### Fix Completeness

- **DETECT phase:** Absorbing Phase 0 cleanup + Phase 1.5 Steps 1-4 into a single deterministic Python script is sound. The CUD resolution rules in SKILL.md Step 3 (lines 165-169+) are mechanical and can be ported to Python.
- **DRAFT phase:** Keeping the same memory-drafter agent is appropriate. Routing output through scripts aligns with the popup fix plan.
- **COMMIT phase:** Chaining `memory_draft.py` -> `memory_write.py` -> `memory_enforce.py` -> cleanup in a single script is sound.

### Concerns

1. **CUD resolution complexity:** The CUD resolution rules in SKILL.md (Step 3, lines 165+) involve a 2-layer verification table with ~12 rule combinations. Porting this accurately to Python requires careful testing. The plan acknowledges this risk ("Port exact same logic from SKILL.md") but underestimates the complexity -- the current rules include edge cases like "L1 says CREATE but L2 says UPDATE" that require nuanced handling.

2. **Dependency sequencing:** The plan says dependencies are `fix-stop-hook-refire.md` (Phase 1) and `eliminate-all-popups.md` (write-staging approach). This is correct but incomplete. The `screen-noise-reduction.md` plan's Phase 1 changes (SKILL.md modifications) would conflict with this plan's Phase 4 (SKILL.md rewrite). These plans cannot be done in parallel.

3. **Performance targets:** The plan targets 3-8 min save time (from 17-28 min). The primary speedup comes from eliminating Phase 2 verification and the Phase 3 Task subagent. However, the bottleneck is Phase 1 drafting (Agent subagent cold-start + LLM inference). Unless draft count is reduced, the 3-min target may be optimistic for multi-category saves.

4. **Save time claims (17-28 min):** This is asserted without a measurement mechanism. The observability plan would provide this data. Architecture simplification should ideally wait for observability data to establish a baseline.

5. **SKILL.md "~300 lines" claim:** Current SKILL.md is 456 lines. "~300 lines" is close but understates the current size by ~50%.

---

## Cross-Plan Dependency Analysis

### Correctly Identified Dependencies

- `architecture-simplification.md` depends on `fix-stop-hook-refire.md` Phase 1: CORRECT (re-fire fix must land first or the simplified architecture will still re-fire).
- `architecture-simplification.md` depends on `eliminate-all-popups.md` (write-staging approach): CORRECT (the script-based staging write pattern feeds into the new architecture).

### Missing Dependencies

1. **`screen-noise-reduction.md` Phase 1 vs `architecture-simplification.md` Phase 4:** Both modify SKILL.md. The noise reduction SKILL.md changes (suppress CUD narration, intermediate status) would be thrown away when architecture-simplification rewrites SKILL.md. The plans should note this conflict -- either do noise reduction first and accept the throwaway work, or skip noise reduction SKILL.md changes and let architecture-simplification subsume them.

2. **`eliminate-all-popups.md` Phase 3 vs `architecture-simplification.md`:** Both change how staging writes work. If the popup plan routes ALL staging writes through Python scripts, the architecture plan's DETECT/COMMIT scripts should inherit this pattern. This is implicitly compatible but not explicitly stated.

3. **`observability-and-logging.md` vs `architecture-simplification.md`:** The observability plan adds timing events keyed to current phases (Phase 0, 1, 1.5, 2, 3). If architecture-simplification replaces these phases, the timing events would need to be redesigned. The observability plan should note this or use phase-agnostic event names.

### Contradictions

1. **`screen-noise-reduction.md` Step 1.3** says "Remove `<triage_data>` inline JSON from block message when file path is available." But the code already does this -- inline JSON is the FALLBACK when file write fails. The plan's Step 1.3 is either redundant or misunderstands the current behavior.

2. **`eliminate-all-popups.md` Phase 3 Option A Step 3.4** says "Remove `permissionDecision: 'allow'` logic from `memory_write_guard.py` (staging auto-approve no longer needed since Write tool is never used for staging)." But SKILL.md line 295 still uses the Write tool for `last-save-result-input.json`: `Write(file_path='.claude/memory/.staging/last-save-result-input.json', ...)`. If `write-save-result-direct` (Phase 2) eliminates this, then Step 3.4 is correct. But Phase 2 and Phase 3 are presented as somewhat independent -- the plan should make explicit that Step 3.4 requires Phase 2 to be complete first.

---

## Missing Items Check

### Popup sources not covered

All 3 popup types from the synthesis are covered:
- P1 (python3 -c Guardian): Covered in `eliminate-all-popups.md` Phase 1
- P2 (Haiku heredoc): Covered in `eliminate-all-popups.md` Phase 2
- P3 (.claude/ protected directory): Covered in `eliminate-all-popups.md` Phase 3

No missing popup sources detected.

### Screen noise items not covered

- **Retrieval hook output:** The retrieval hook (`memory_retrieve.py`) fires on UserPromptSubmit and injects context. This output is not in the noise inventory. However, it runs at the START of sessions (not at stop/save time), so it is outside scope.
- **PostToolUse validation messages:** `memory_validate_hook.py` fires on Write tool calls and may produce validation messages. These are not in the noise inventory, but they are detection-only and may not produce visible output (they write to stderr, not stdout). Low concern.

---

## Summary Table

| Plan | Verdict | Critical Issues | Minor Issues |
|------|---------|----------------|--------------|
| 1. fix-stop-hook-refire | PASS WITH CONCERNS | Step 1.3 stale save-result may block new sessions before Phase 3 | Phase 2 Step 2.2 vague |
| 2. eliminate-all-popups | PASS WITH CONCERNS | Phase 3 Step 3.4 premature if Phase 2 incomplete; drafter stdout capture non-trivial | New actions need creation |
| 3. observability-and-logging | PASS | None | Phase-keyed events may conflict with architecture-simplification |
| 4. screen-noise-reduction | PASS WITH CONCERNS | Step 1.3 mischaracterizes current inline `<triage_data>` behavior (already fallback-only); Step 3.1 `run_in_background` for Agent unverified | Missing dependency on architecture-simplification |
| 5. architecture-simplification | PASS WITH CONCERNS | Missing dependency conflict with screen-noise-reduction; CUD port complexity underestimated; SKILL.md line count understated | Save time baseline not yet measurable |
