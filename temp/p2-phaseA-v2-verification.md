# Phase A Quality Audit -- Adversarial Verification Report (V2)

**Date:** 2026-02-25
**Verifier:** Claude Opus 4.6 (adversarial perspective)
**Scope:** A-01, A-02, A-03 fixes + deferred findings assessment
**External models consulted:** Gemini 3.1 Pro (Codex 5.3 unavailable -- usage limit)

---

## Per-Fix Adversarial Assessment

### A-01: Config Loading Order Bug

**Verdict: FIX IS CORRECT, with one minor concern**

**What was verified:**
- Traced the pre-fix and post-fix control flow in `memory_retrieve.py` main()
- Checked `config_path.exists()` safety before memory_root verification
- Checked for double-load or inconsistency with settings extraction block
- Verified fail-open semantics preserved

**Assessment:**

The fix correctly moves config loading from line ~370 to line ~340, before the first `emit_event` call. The analysis is sound:

1. **`config_path.exists()` safety**: `Path.exists()` returns `False` if the parent directory does not exist. No exception is raised. This is safe. The `cwd` is provided by Claude Code's hook runner via `hook_input.get("cwd", os.getcwd())`, so if cwd is wrong, the entire retrieval pipeline is wrong -- not just the config loading. The A-01 fix does NOT introduce any new risk.

2. **No double-load**: The old code loaded config at line ~374. The new code loads it at line ~340 and the settings extraction block at line ~382 reuses `_raw_config` directly via `if _raw_config:`. There is exactly one `json.load()` call. No inconsistency.

3. **No regression on early exits**: For short prompts (< 10 chars), the pre-fix code skipped config loading entirely. The post-fix code now reads config before the short-prompt check. This adds one `exists()` + potential `json.load()` call to the short-prompt path. For a < 2KB config file, this is < 0.1ms -- negligible.

**Concern raised by Gemini 3.1 Pro:**

> "By moving the config load to before the short-prompt check, the fix incurs synchronous disk I/O on every single user interaction, even simple ones like typing 'hi'."

**My rebuttal:** This concern is overstated. The performance impact is one `stat()` syscall (for `exists()`) plus one potential `open()+read()` for a < 2KB file. On any modern filesystem with warm dentry cache, this is sub-0.1ms. The entire retrieval hook already performs much heavier I/O (reading index.md, FTS5 indexing, JSON file reads for body scoring). The marginal cost of one early config read is insignificant relative to the hook's total execution time. Furthermore, if logging is disabled (the default), `emit_event` returns immediately after `parse_logging_config` -- zero file I/O beyond the config read.

**Issue found: NONE (fix is clean)**

---

### A-02: Call-Site Schema Audit

**Verdict: FIXES APPLIED ARE CORRECT; DEFERRALS NEED RECONSIDERATION**

**What was verified:**
- F-06 fix (remove `engine` from legacy inject): CONFIRMED at line 690-692
- F-07 fix (add `duration_ms` to parallel judge.error): CONFIRMED at line 383-392
- Schema doc updates for F-01, F-04, F-05: PARTIALLY VERIFIED (see issues below)
- Reviewed all 5 deferred findings (F-01 through F-05)

**Code fixes verified:**

1. **F-06 (engine removed from legacy inject):** Line 690-692 of `memory_retrieve.py` shows the legacy `retrieval.inject` event now matches the FTS5 path -- no `engine` key. Comment documents the rationale. CORRECT.

2. **F-07 (duration_ms added to parallel judge.error):** Line 383-392 of `memory_judge.py` now passes `duration_ms=round((time.monotonic() - t0) * 1000, 2)`. The variable `t0` is in scope (set at line 356). CORRECT.

**Schema doc verification:**

3. **F-01 (candidates_post_judge, injected_count marked optional):** Schema doc line 42-43 now reads "optional" with explanatory notes. CORRECT.

4. **F-04 (reason enum updated):** Schema doc line 70 now lists the correct code values: `"short_prompt"`, `"empty_index"`, `"retrieval_disabled"`, `"max_inject_zero"`, `"no_fts5_results"`. CORRECT for the field documentation.

5. **F-05 (query_tokens added as optional to retrieval.skip):** Schema doc line 72 now documents `query_tokens` as optional. CORRECT.

**Issues found:**

| ID | Severity | Description |
|----|----------|-------------|
| V2-01 | MEDIUM | Schema doc example at line 66 still shows `"reason":"prompt_too_short"` but the field documentation at line 70 says `"short_prompt"`. **The example contradicts the field spec within the same schema doc.** This was introduced by the F-04 update -- the field list was corrected but the example JSONL was not updated. |
| V2-02 | LOW | Schema doc line 39 says `engine` can be `"fts5_bm25"` or `"legacy_keyword"`, but the actual code emits `"title_tags"` (line 573). The A-02 schema updates missed this value mismatch. |
| V2-03 | LOW | Schema doc example at line 34 still shows `candidates_post_judge` and `injected_count` as if they are always present, contradicting the field documentation at lines 42-43 that marks them as optional. Misleading for implementers. |

**Deferred Findings Assessment:**

| Finding | Deferred? | Should fix NOW? | Rationale |
|---------|-----------|-----------------|-----------|
| F-01 (missing optional fields in search) | Yes | No | Correctly architectural. Schema doc updated to mark as optional. |
| F-02 (partial debug event reuses retrieval.search) | Yes | **YES** | This WILL cause real analytics bugs. Any consumer querying `event_type=="retrieval.search"` gets inconsistent shapes. Gemini 3.1 Pro correctly identified this as HIGH severity. Should be renamed to a distinct event type like `retrieval.judge_result`. |
| F-03 (warning event reuses retrieval.search) | Yes | **YES** | Same issue as F-02. The FTS5-unavailable warning at line 572 reuses `retrieval.search` with a completely different payload shape. Should be renamed to `retrieval.fallback` or similar. |
| F-04 (reason enum mismatch) | Fixed (schema) | Partially | The field list was updated but the JSONL example was not (see V2-01). |
| F-05 (extra query_tokens in skip) | Fixed (schema) | N/A | Correctly added as optional field. |

---

### A-03: results[] Field Accuracy

**Verdict: FIX IS CORRECT BUT MARGINAL VALUE**

**What was verified:**
- Traced the complete data flow through `score_with_body()` (Steps 1-8)
- Verified the `if "body_bonus" not in result:` check handles all states correctly
- Checked whether the invariant comment was added (it was NOT)
- Assessed whether beyond-top_k entries can reach logging

**Code fix verified:**

Lines 262-268 of `memory_retrieve.py`:
```python
for result in initial[top_k_paths:]:
    result.pop("_data", None)
    if "body_bonus" not in result:
        result["body_bonus"] = 0
```

**Correctness analysis:**

The `if "body_bonus" not in result:` check at line 267 correctly handles all three entry states:

| State after Step 3 | Has body_bonus? | Check result | Action |
|-----|-----|-----|-----|
| A: Retired (filtered out at line 248) | N/A | N/A | Never reaches this code |
| B: File-read failure | Yes (set to 0 at line 240) | `"body_bonus" in result` = True | No-op (correct) |
| C: Active, file read OK | No (only `_data` was set) | `"body_bonus" not in result` = True | Sets to 0 (correct) |

**Can beyond-top_k entries reach logging?**

The A-03 report's analysis is correct: under the current calling convention at line 473-475, `top_k_paths = max(10, effective_inject)` and `max_inject = effective_inject`, so `apply_threshold` returns at most `top_k_paths` entries. Beyond-top_k entries cannot reach the logger.

However, the A-03 report recommended three fixes. Only Fix 1 was applied. The status:

| Recommendation | Applied? | Assessment |
|----------------|----------|------------|
| Fix 1: Defensive body_bonus=0 | YES | Correct but marginal value |
| Fix 2: body_analyzed flag | NO | Correctly deferred (very low priority) |
| Fix 3: Invariant comment | **NO** | Should have been added -- 1 line, zero risk |

**Issue found:**

| ID | Severity | Description |
|----|----------|-------------|
| V2-04 | LOW | The A-03 report explicitly recommended Fix 3 (invariant comment at the call site, line 473), but it was not applied. This is a 1-line comment that documents a fragile invariant (`top_k_paths >= effective_inject`). The omission is minor but the comment prevents future regressions. |

---

## Cross-Cutting Concerns

### NEW Schema Inconsistencies Introduced by Fixes

| ID | Severity | Description |
|----|----------|-------------|
| V2-01 | MEDIUM | (Covered above) Schema doc example contradicts field spec for `retrieval.skip` reason values |
| V2-02 | LOW | (Covered above) Schema doc says `"legacy_keyword"` but code emits `"title_tags"` |
| V2-03 | LOW | (Covered above) Schema doc example shows always-present fields that are documented as optional |

### Deferred Item Tracking

The A-02 report identified findings F-01 through F-07 (confusingly, the report also contains an "F-08" for query_tokens in skip and an "F-09" for parallel judge.error duration_ms, though these are numbered F-07 and F-08 in the summary table but F-05 and F-07 in the fix recommendations). F-06 and F-07 were fixed inline. F-01, F-04, F-05 were addressed via schema doc updates.

**Remaining unresolved (should be tracked):**
- F-02: Partial debug event reusing `retrieval.search` type -- **SHOULD FIX**
- F-03: Warning event reusing `retrieval.search` type -- **SHOULD FIX**
- D-01: `retrieval.inject` missing `output_mode` (pre-existing)
- D-02: `candidates_found == candidates_post_threshold` (pre-existing)
- D-03: No global payload size limit (pre-existing)
- D-05: No `matched_tokens` field (pre-existing)

### Test Suite Adequacy

- `test_memory_logger.py`: 33 tests covering emit_event, parse_logging_config, cleanup, symlink protection, concurrency, NaN handling. **Adequate for the logger module itself.**
- `test_memory_retrieve.py`: Exists but was NOT read in this verification (not directly modified by the fixes). The A-01 fix changes control flow in `main()`, which is tested via integration-style tests in `test_memory_retrieve.py`.
- `test_memory_judge.py`: 78 tests including parallel batching. **Adequate for the F-07 duration_ms fix.**

**Gap:** No specific test verifies that early `emit_event` calls (short_prompt, empty_index) receive the correct config after the A-01 fix. This would require a test that mocks `emit_event` and asserts `config` is not None/empty when logging is enabled. LOW priority -- the fix is simple enough that visual code review suffices.

---

## External Model Challenges

### Gemini 3.1 Pro (Devil's Advocate)

**Key challenges and rebuttals:**

| Challenge | Severity | Rebuttal |
|-----------|----------|----------|
| A-01 causes unconditional file I/O on every prompt | MEDIUM | Overstated. One `stat()` + potential `json.load()` of <2KB file is <0.1ms. The hook already performs much heavier I/O. The marginal cost is negligible. However, the critique is directionally correct -- if this were a hot path (1000s of calls/sec), it would matter. For a Claude Code hook (called once per user prompt), it does not. |
| F-02/F-03 will break analytics pipelines | HIGH | **Agree.** This is the strongest external challenge. Reusing `retrieval.search` for partial debug/warning payloads is a schema design flaw that should be fixed, not deferred. |
| F-04 reason enum mismatch means schema lies to analysts | MEDIUM | **Agree partially.** The field list was updated but the JSONL example was not (V2-01). So the schema still partially lies. |
| A-03 is dead code guarding impossible state | LOW | Partially agree. The code is technically reachable if calling conventions change. The fix is 2 lines and harmless. Defensive programming is acceptable here, but the missing invariant comment (V2-04) means future maintainers won't understand WHY it exists. |
| Recommend Event Builder pattern | N/A (architectural) | Interesting but out of scope for Phase A. This is a Phase B+ architectural consideration. The current scattered-emit pattern is adequate for the system's maturity level. |

### Codex 5.3

**Unavailable** (usage limit reached). No challenge obtained.

---

## Issues Summary (Severity-Rated)

| ID | Severity | Category | Description | Action |
|----|----------|----------|-------------|--------|
| V2-01 | MEDIUM | Schema doc | Example JSONL at schema line 66 shows `"prompt_too_short"` but field spec at line 70 says `"short_prompt"`. Internal contradiction. | Fix example to match field spec |
| V2-05 | MEDIUM | Deferred risk | F-02 and F-03 (partial events reusing `retrieval.search` type) create real analytics risk. Deferral is not safe. | Rename to distinct event types |
| V2-02 | LOW | Schema doc | Engine value mismatch: schema says `"legacy_keyword"`, code says `"title_tags"` | Update schema |
| V2-03 | LOW | Schema doc | Example shows always-present fields documented as optional | Update example |
| V2-04 | LOW | Missing comment | A-03 Fix 3 (invariant comment) was not applied | Add 1-line comment |
| V2-06 | LOW | Test gap | No test specifically verifies A-01 early config delivery to emit_event | Consider adding |

---

## Overall Verdict: CONDITIONAL PASS

The three code fixes (A-01, A-02 inline fixes, A-03) are **technically correct** and introduce no regressions (201/201 tests pass, all scripts compile clean). The core bugs identified were real and the fixes address them properly.

**However**, the Phase A audit as a whole earns a CONDITIONAL PASS rather than full PASS due to:

1. **V2-01 (MEDIUM):** The schema doc update for F-04 was incomplete -- the JSONL example still contradicts the field specification. This means the schema doc, which is supposed to be the output of the audit, contains an internal inconsistency.

2. **V2-05 (MEDIUM):** F-02 and F-03 were incorrectly classified as safe to defer. Reusing the same `event_type` for events with radically different payload shapes is a schema design flaw that will cause real issues for any downstream consumer filtering by event type. Both Gemini 3.1 Pro and this verifier independently flagged this as the highest-priority remaining issue.

3. **V2-04 (LOW):** The A-03 report recommended an invariant comment that was not applied. This is a 1-line change that prevents future regressions and should have been included.

**Conditions for full PASS:**
- Fix V2-01 (update JSONL example in schema doc)
- Fix V2-02 (correct engine enum in schema doc)
- Either fix F-02/F-03 now (rename partial events) or explicitly document the decision to defer with a tracking item and risk acceptance note
- Add the invariant comment from A-03 Fix 3

---

## Appendix: Vibe Check Summary

The Phase A approach is fundamentally sound but shows signs of **premature observability optimization** -- investing significant effort in logging correctness before the logging system has proven its value to any consumer. The 5 deferred findings + 4 pre-existing deferred items = 9 known issues across 13 call sites (69% defect rate by count) suggests the architecture may benefit from a structural simplification (e.g., the "Event Builder" pattern suggested by Gemini) rather than incremental patching. This is a Phase B+ consideration, not a blocker for Phase A.
