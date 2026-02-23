# Engineering Review: 3 Draft Plans

**Reviewer:** reviewer-eng (Engineering Perspective)
**Date:** 2026-02-22
**External Verification:** Codex 5.3 (codereviewer), Gemini 3 Pro (codereviewer), Vibe-check
**Files Verified:** memory_retrieve.py, memory_search_engine.py, memory-config.default.json, test_memory_retrieve.py (lines 493-690), test_v2_adversarial_fts5.py (lines 1050-1099), hooks.json, memory_triage.py (lines 990-1015)

---

## Plan #1: Actions #1-#4 Implementation Plan

### Issues Found

#### MEDIUM -- Briefing vs. Plan Discrepancy on `output_mode` Default

The briefing document (`plan-team-briefing.md:48`) specifies `output_mode` default as `"tiered"`, while the plan itself (`draft-plan-actions.md:157`) specifies `"legacy"`. The plan is correct -- both Codex and Gemini recommended `"legacy"` default for backwards compatibility, and the plan documents this consensus. However, the briefing is now stale and should be updated to avoid confusion during implementation.

**Suggestion:** Add a note at the top of the plan explicitly calling out this deviation from the briefing.

#### MEDIUM -- Cluster Detection Should Be Configurable (Codex + Gemini Agree)

The plan proposes always-on cluster detection (no config toggle) with the rationale "this is a bug fix, not a preference" (`draft-plan-actions.md:66`). Both Codex and Gemini disagree:

- **Codex:** "Legitimately strong clusters (3 related memories) get forced to medium. No rollback except code revert is operationally brittle. Add `retrieval.cluster_cap_enabled` default `true`."
- **Gemini:** "BM25 scores are unbounded and non-linear. A strict 0.90 ratio is a heuristic, risks falsely demoting 3 legitimately distinct and highly relevant memories."

The plan acknowledges this split (`draft-plan-actions.md:68`) and notes Gemini's concern, but chose always-on. Given that:
1. Rollback for `abs_floor` has a config key but cluster detection does not -- asymmetry
2. The plan itself says "toggle may be added later if false demotions observed"
3. Adding `retrieval.cluster_cap_enabled: true` costs ~3 LOC and follows the existing `dict.get()` pattern

**Suggestion:** Add `retrieval.cluster_cap_enabled` (default `true`) now. Cost is negligible. Provides symmetry with `confidence_abs_floor` rollback. Makes rollback count 3 config changes (not 2), all trivial.

#### LOW -- LOC Estimates Are Reasonable

Verified against actual code:
- `confidence_label()` is 14 lines (lines 161-174). Adding 2 params + floor check + cluster check = ~15-20 LOC code change. Plan says ~20-35. **Confirmed reasonable.**
- `_output_results()` is 40 lines (lines 262-301). Adding tiered branching + config guard = ~35-50 LOC. Plan says ~40-60. **Confirmed reasonable.**
- Hint changes: 3 occurrences at lines 458, 495, 560. Plan correctly identifies all 3. **Confirmed accurate.**
- Plan total: ~66-105 code + ~130-240 tests = ~196-345 total. **Realistic upper bound.**

#### LOW -- Function Signature Design is Clean

The proposed `confidence_label()` signature change:
```python
def confidence_label(score: float, best_score: float,
                     abs_floor: float = 0.0,
                     cluster_count: int = 0) -> str:
```
Uses default values that preserve existing behavior. All existing 2-arg call sites remain valid. **Confirmed backwards-compatible.**

### Verification Results

| Claim | Verified Against | Result |
|-------|-----------------|--------|
| `confidence_label()` at lines 161-174 | `memory_retrieve.py:161-174` | CONFIRMED -- exactly 14 lines, ratio-only logic |
| Single result always "high" | `memory_retrieve.py:169` -- `ratio = abs(score)/abs(best_score)` = 1.0 for single result | CONFIRMED |
| `_output_results()` at lines 262-301 | `memory_retrieve.py:262-301` | CONFIRMED -- 40 lines |
| Hint at line 458 | `memory_retrieve.py:458` | CONFIRMED -- HTML comment format |
| Hint at line 495 | `memory_retrieve.py:494-495` | CONFIRMED |
| Hint at line 560 | `memory_retrieve.py:560` | CONFIRMED |
| `TestConfidenceLabel` 17 tests at 493-562 | `test_memory_retrieve.py:493-562` | CONFIRMED -- 17 test methods |
| `test_single_result_always_high` at line 535 | `test_memory_retrieve.py:535-536` | CONFIRMED |
| `test_all_same_score_all_high` at line 539 | `test_memory_retrieve.py:539-541` | CONFIRMED |
| `test_confidence_label_in_output` at line 618 | `test_memory_retrieve.py:618-629` | CONFIRMED -- asserts `confidence="low"` in output |
| `test_no_score_defaults_low` at line 649 | `test_memory_retrieve.py:649-656` | CONFIRMED |
| `test_result_element_format` at line 658 | `test_memory_retrieve.py:658-668` | CONFIRMED |
| `test_output_results_captures_all_paths` at 1063 | `test_v2_adversarial_fts5.py:1063-1077` | CONFIRMED |
| `test_output_results_description_injection` at 1079 | `test_v2_adversarial_fts5.py:1079-1097` | CONFIRMED |
| Config uses `dict.get()` pattern | `memory_retrieve.py:353-384` | CONFIRMED -- safe default pattern throughout |
| `apply_threshold()` 25% noise floor | `memory_search_engine.py:283-288` | CONFIRMED -- independent from confidence_label |
| Rollback is 2 config changes, not 1 | Plan correctly states 2 | CONFIRMED -- `confidence_abs_floor` + `output_mode` |
| `apply_threshold()` and `confidence_label()` are independent | Code paths verified | CONFIRMED -- threshold filters selection, label is display-only |

### Test Impact Assessment

Plan claims ~5-8 existing tests need modification for tiered mode. Verified:
- `test_confidence_label_in_output` (line 618): asserts `confidence="low"` in `<result>` -- tiered mode silences LOW. **Needs branch.**
- `test_no_score_defaults_low` (line 649): asserts `confidence="low"` exists -- tiered mode silences LOW. **Needs branch.**
- `test_result_element_format` (line 658): asserts `<result ...>` pattern -- still valid for HIGH. **No change needed in legacy mode.**
- `test_output_results_captures_all_paths` (line 1063): asserts `<result>` format. **Needs tiered mode branch.**
- `test_output_results_description_injection` (line 1079): asserts output format. **Needs tiered mode branch.**

Count: 4 tests need modification (not 5-8). However, the plan's estimate includes tests that need additional test cases for both modes, which is fair. **Estimate is slightly conservative but acceptable.**

### Overall Assessment: APPROVE WITH CHANGES

Changes required:
1. Add `retrieval.cluster_cap_enabled` config key (default `true`)
2. Note the briefing vs. plan discrepancy on `output_mode` default

---

## Plan #2: Logging Infrastructure

### Issues Found

#### HIGH -- Atomic Write Implementation Must Use `os.write()`, Not `os.fdopen()`

The plan references the existing `memory_triage.py` pattern (`os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` + `os.fdopen()` at lines 1000-1007). I verified this code:

```python
# memory_triage.py:1000-1007
fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
try:
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")
```

**Problem:** `os.fdopen()` creates a buffered file object. Python's buffered I/O may split a single `f.write()` into multiple underlying `write()` syscalls, breaking POSIX `O_APPEND` atomicity. Both Codex and Gemini flagged this independently:

- **Codex:** "`fdopen(...).write(...)` pattern seen in existing code does not guarantee one syscall."
- **Gemini:** "Atomicity is broken if you use Python's buffered I/O. Explicitly encode the JSON string and use `os.write(fd, line_bytes)`."

The plan says "Claude Code doesn't run the same hook concurrently" -- but this is insufficient. Multiple Claude Code instances can run on different projects simultaneously, and if the user opens two terminals on the same project, two hooks could append to the same daily JSONL file concurrently.

**Fix:** The `memory_logger.py` implementation MUST use raw `os.write()`:
```python
line_bytes = (json.dumps(event) + "\n").encode("utf-8")
fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, line_bytes)
finally:
    os.close(fd)
```

This is a deviation from the existing `memory_triage.py` pattern. The plan should explicitly note this and explain why.

#### MEDIUM -- LOC Estimate Disagreement Between External Models

- **Codex:** "80-120 LOC is optimistic. Budget ~140-200 LOC for robust stdlib-only implementation."
- **Gemini:** "80-120 LOC is highly accurate and realistic."

After analyzing the planned feature set:
- `emit_event()`: open + encode + write + close + error handling = ~20-25 LOC
- `get_session_id()`: path parsing = ~8-10 LOC
- `cleanup_old_logs()`: last_cleanup check + directory walk + file deletion = ~25-35 LOC
- `parse_logging_config()`: dict.get() chain + validation = ~10-15 LOC
- Level constants + filtering logic: ~8-10 LOC
- Module docstring + imports: ~10-12 LOC

**Total estimate: ~85-110 LOC for core implementation, ~120-160 with thorough docstrings and edge-case handling.**

The 80-120 range is tight but achievable for a minimal implementation. If the implementation includes all the robustness features described (fail-open wrappers at every call site, proper short-write handling), 120-160 LOC is more realistic.

**Suggestion:** Revise estimate to 100-160 LOC.

#### MEDIUM -- `logging.enabled` Default `true` Needs Design Note

The plan sets `logging.enabled: true` by default. Log files will be written to `<memory_root>/logs/`. The project has a `PreToolUse:Write` guard (`memory_write_guard.py`) that blocks direct writes to the memory directory. The logging module uses `os.write()` (not the Write tool), so it bypasses the guard entirely. However, this should be documented as a design note to prevent future confusion -- the write guard only blocks Claude's Write tool, not Python scripts doing filesystem I/O.

#### LOW -- Existing Triage Scores Migration Is Under-Specified

The plan mentions migrating `.staging/.triage-scores.log` to the new logging system with a "dual write" period. But it doesn't specify:
1. How long the dual-write period lasts
2. What triggers removal of the old path
3. Whether the old log format is compatible with the new JSONL schema

**Suggestion:** Specify a concrete migration timeline (e.g., "2 releases" or "after 30 days of stable new logging").

#### LOW -- `session_id` Extraction From `transcript_path` Is Fragile

The plan relies on extracting `session_id` from `hook_input.transcript_path`. Gemini noted that CLI invocations of `memory_search_engine.py` bypass the hook context entirely, so `search.query` events from CLI will lack `session_id`.

**Suggestion:** Document this limitation. For PoC #6, it means CLI searches cannot be correlated with auto-inject nudges. This is acceptable since PoC #6 specifically measures Claude's response to auto-injected nudges (not user-initiated CLI searches).

### Verification Results

| Claim | Verified Against | Result |
|-------|-----------------|--------|
| Existing triage logging at lines 997-1015 | `memory_triage.py:994-1015` | CONFIRMED -- O_APPEND pattern at 1000-1007 |
| Uses `os.fdopen()` buffered pattern | `memory_triage.py:1006` | CONFIRMED -- `os.fdopen(fd, "a", encoding="utf-8")` |
| Existing stderr logging in memory_retrieve.py | `memory_retrieve.py:362-363, 387-388, 466` | CONFIRMED -- `[WARN]`/`[INFO]` to stderr |
| Config uses `dict.get()` pattern | `memory_retrieve.py:353-384` | CONFIRMED |
| Logs per-project (each project's .claude/memory/) | Architecture review | CONFIRMED -- memory_root is project-local |
| Event type taxonomy matches code paths | memory_retrieve.py flow analysis | CONFIRMED -- FTS5 path, legacy path, judge path all have distinct events |

### Overall Assessment: APPROVE WITH CHANGES

Changes required:
1. **CRITICAL:** Specify `os.write()` (raw syscall) instead of `os.fdopen().write()` for atomic appends
2. Revise LOC estimate to 100-160 LOC
3. Specify migration timeline for triage scores log

---

## Plan #3: PoC Experiments

### Issues Found

#### HIGH -- PoC #6 Nudge Compliance Is Correlation-Only (Both External Models Agree)

The plan acknowledges this (`draft-plan-poc.md:300-307`) but doesn't sufficiently enforce it in the methodology section. The actual measurement definition (`draft-plan-poc.md:283`) reads like a causal metric:

```
compliance_rate = (compact injection followed by /memory:search) / (total compact injections)
```

Both external models raised this:
- **Codex:** "For v1, keep it as an association KPI only (not causal). Add minimum data-quality gates: event-linkage completeness, dedupe rules (1 compliance max per inject), and baseline search-rate comparison."
- **Gemini:** "Acceptable industry standard for a v1 directional signal, but the correlation pipeline will break for CLI-initiated searches lacking session_id."

**Specific gaps in the current methodology:**
1. No baseline search rate measurement (how often does Claude use `/memory:search` without any nudge?)
2. No deduplication rule (if 3 compact injections happen in one session, does 1 search count as 3 compliances?)
3. No handling of confounders (Claude might search because the user asked about a topic, not because of the nudge)

**Suggestion:** Add to the methodology:
- Measure baseline `/memory:search` rate in sessions without compact injections
- Cap at 1 compliance event per inject event (dedupe)
- Rename from "compliance rate" to "search association rate" to avoid causal language
- Document limitations prominently in results

#### MEDIUM -- PoC #7 `matched_tokens` Field Is an Extra Feature in Plan #2

The plan recommends adding `data.results[].matched_tokens` to the `retrieval.search` event schema (`draft-plan-poc.md:229`). However, Plan #2's schema does not include this field. The plan's fallback approach (title+tags tokenization intersection at analysis time, `draft-plan-poc.md:251-256`) is sufficient for v1 and avoids scope creep in the logging module.

**Suggestion:** Remove the `matched_tokens` recommendation from Plan #3 or explicitly mark it as "nice-to-have, not blocking." The post-hoc tokenization approach is adequate.

#### MEDIUM -- PoC #5 Sample Size Escalation Is Under-Constrained

The plan says "pilot 25-30, then expand to 50+" (`draft-plan-poc.md:99`). But the expansion trigger is vague: "pilot methodology verification, then expand." What specifically constitutes "methodology verified"?

**Suggestion:** Add concrete pilot success criteria:
- Inter-annotator agreement (Cohen's kappa >= 0.6 on 20% overlap) -- already mentioned but should be a gate
- Labeling rubric stability (< 10% revision rate after pilot)
- Tool chain works end-to-end (log extraction -> labeling -> metric calculation)

#### LOW -- PoC #4 Time-Box Is Well-Defined

The 1-day time-box with explicit kill criteria (`draft-plan-poc.md:152-155`) is well-specified. The separate branch requirement is good practice. The analysis of agent hook output mechanism (`draft-plan-poc.md:146-150`) correctly identifies that context injection requires command hooks.

Verified against `hooks/hooks.json`: all 4 existing hooks are `type: "command"`. The UserPromptSubmit hook at lines 43-55 uses `python3` command with 15s timeout. An agent hook would need different semantics entirely.

#### LOW -- Cross-Plan Dependency Is Correctly Specified

Plan #3 depends on Plan #2 (logging infrastructure). This is stated explicitly (`draft-plan-poc.md:7, 27`). The dependency mapping table (`draft-plan-poc.md:62-67`) correctly maps each PoC to specific Plan #2 log event types.

Exception: PoC #4 can proceed without logging (manual measurement possible, `draft-plan-poc.md:324`). This is a good design decision -- it unblocks the highest-uncertainty experiment.

### Verification Results

| Claim | Verified Against | Result |
|-------|-----------------|--------|
| `build_fts_query()` OR combination at line 226 | `memory_search_engine.py:226` | CONFIRMED -- `" OR ".join(safe)` |
| `apply_threshold()` 25% noise floor at 283-288 | `memory_search_engine.py:283-288` | CONFIRMED |
| `confidence_label()` ratio-only at 161-174 | `memory_retrieve.py:161-174` | CONFIRMED |
| UserPromptSubmit hook is command type | `hooks/hooks.json:43-55` | CONFIRMED -- `"type": "command"` |
| Agent hook default timeout is 60s | Claude Code documentation | CANNOT VERIFY from code alone -- documentation reference |
| PoC #4 can run without logging | Plan analysis | CONFIRMED -- manual latency measurement is feasible |

### Overall Assessment: APPROVE WITH CHANGES

Changes required:
1. PoC #6: Add baseline search rate measurement, deduplication rules, rename to "search association rate"
2. PoC #7: Clarify `matched_tokens` as nice-to-have, not a Plan #2 blocker
3. PoC #5: Add concrete pilot success gate criteria

---

## Cross-Plan Issues

### Issue 1: `output_mode` Default Discrepancy (MEDIUM)

- Briefing (`plan-team-briefing.md:48`): default `"tiered"`
- Plan #1 (`draft-plan-actions.md:157`): default `"legacy"`
- Plan #1 is correct (both external models recommended `"legacy"`), but the briefing is stale.

**Recommendation:** Update the briefing or add a deviation note in Plan #1.

### Issue 2: Logging Module Should Be Built Before Action #2 Gate D (MEDIUM)

Plan #1 Action #2 introduces tiered output, but verifying its effectiveness (Gate D: "20-30 representative prompts") benefits from Plan #2's logging infrastructure. The plans don't explicitly sequence Plan #2 relative to Plan #1.

**Recommendation:** Add a note that Plan #2 Phase 2-3 (logger module + retrieval instrumentation) should be implemented before Plan #1's Gate D manual review, but Plan #1 Actions #1-#3 can proceed independently.

### Issue 3: Plan #2 Schema Needs Plan #3 Input (LOW)

Plan #3 PoC #7 recommends `matched_tokens` in the log schema, but Plan #2 doesn't include it. The plans correctly note this gap (`draft-plan-poc.md:229`) and provide a fallback approach.

**Recommendation:** No action needed -- the fallback is sufficient for v1.

---

## External Model Consensus Summary

| Topic | Codex 5.3 | Gemini 3 Pro | My Assessment |
|-------|-----------|-------------|---------------|
| Logger LOC | 140-200 (conservative) | 80-120 (accurate) | 100-160 (middle ground) |
| Cluster cap toggle | Should be configurable, default on | Should be configurable, default off | Should be configurable, default on |
| Atomic writes | Must use `os.write()` not `fdopen` | Must use `os.write()` not `fdopen` | AGREE -- critical fix |
| PoC #6 causality | Association KPI only, add data-quality gates | Acceptable v1, fix CLI session_id gap | AGREE -- rename, add baseline |
| PoC #6 session_id | Event-linkage completeness >= 95% | CLI bypasses hook context, needs fallback | Document limitation, acceptable for v1 |

---

## Summary Verdicts

| Plan | Verdict | Critical Issues | Changes Required |
|------|---------|-----------------|------------------|
| Plan #1 (Actions) | APPROVE WITH CHANGES | 0 | 2 (cluster toggle, briefing note) |
| Plan #2 (Logging) | APPROVE WITH CHANGES | 1 (atomic write pattern) | 3 (os.write, LOC estimate, migration timeline) |
| Plan #3 (PoC) | APPROVE WITH CHANGES | 0 | 3 (PoC #6 methodology, #7 scope, #5 gates) |

All plans are well-structured, code references are accurate, and dependency ordering is correct. The most significant engineering concern is the atomic write pattern in Plan #2, which should be corrected before implementation begins.
