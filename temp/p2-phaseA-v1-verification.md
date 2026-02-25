# Phase A Quality Audit -- Verification Report (V1)

**Date:** 2026-02-25
**Verifier:** Claude Opus 4.6 (independent verification agent)
**Scope:** A-01, A-02, A-03 fix correctness and completeness
**Test suite:** 852/852 PASS | Compile check: 13/13 scripts OK

---

## 1. A-01 Fix Verification: Config Loading Order Bug

**Verdict: PASS**

### What was checked

Read `memory_retrieve.py` lines 320-429, tracing the full `main()` control flow from stdin parsing through config loading to the first emit_event calls.

### Findings

1. **Config loaded before first emit_event:** Lines 340-348 now load `memory_root` and `_raw_config` immediately after extracting `user_prompt`, `cwd`, and `_session_id`. This is BEFORE the first `emit_event()` call at line 352. Confirmed correct.

2. **Both early skip events pass config=_raw_config:**
   - Line 352-357: `emit_event("retrieval.skip", {"reason": "short_prompt", ...}, config=_raw_config)` -- CONFIRMED
   - Line 376-378: `emit_event("retrieval.skip", {"reason": "empty_index"}, ..., config=_raw_config)` -- CONFIRMED

3. **Fail-open semantics preserved:** Lines 343-348 wrap config loading in `config_path.exists()` + `try/except (json.JSONDecodeError, OSError): pass`. On failure, `_raw_config` remains `{}`, and `parse_logging_config({})` returns `enabled: False`. This is the correct default behavior -- logging is disabled when config is absent or unreadable. No crash possible.

4. **No unintended side effects:** The config load at line 342-348 is a pure read operation (JSON parse from disk). It does not modify any state used by subsequent retrieval logic. The settings extraction block at line 387+ references `if _raw_config:` directly, avoiding the previous redundant file read. Net effect: config is loaded exactly once instead of the previous pattern where it was loaded only at line ~370 (after the early exit points).

5. **All subsequent emit_event calls also verified:** Lines 391, 431, 449, 483, 531, 545, 559, 572, 692 -- all pass `config=_raw_config`. No `config=None` remains anywhere in the file.

### Edge cases considered

- Config file missing: `_raw_config = {}` -> logging disabled. Correct.
- Config file malformed JSON: `JSONDecodeError` caught -> `_raw_config = {}`. Correct.
- Config exists but no `logging` key: `parse_logging_config({"retrieval": ...})` -> `enabled: False`. Correct.
- Performance: one additional `json.load()` for the short-prompt exit path. Config is typically <2KB, overhead negligible (<0.1ms).

---

## 2. A-02 Fixes Verification: Call-Site Schema Audit

### 2a. F-06 Fix: Legacy `retrieval.inject` engine key removed

**Verdict: PASS**

Read `memory_retrieve.py` lines 688-701. The legacy path `retrieval.inject` event now contains:

```python
emit_event("retrieval.inject", {
    "injected_count": len(top_list),
    "results": [
        {"path": r["path"],
         "confidence": confidence_label(r.get("score", 0), _inj_best)}
        for r in top_list
    ],
}, ...)
```

The `"engine": "title_tags"` key that was documented in the A-02 audit (original line ~684 in the pre-fix code) is confirmed REMOVED. The FTS5 path inject event (line 545-554) also does not include `engine`. Both inject events now have consistent shapes: `{injected_count, results[{path, confidence}]}`. Comment at line 690 documents the rationale: "engine is already captured in the preceding retrieval.search event."

### 2b. F-07 Fix: judge.error parallel failure now has duration_ms

**Verdict: PASS**

Read `memory_judge.py` lines 383-392. The parallel failure emit now includes:

```python
emit_event("judge.error", {
    "error_type": "parallel_failure",
    "message": "Parallel judge failed, falling back to sequential",
    "fallback": "sequential",
    "candidate_count": len(candidates),
    "model": model,
}, level="warning", hook="UserPromptSubmit", script="memory_judge.py",
   session_id=session_id, duration_ms=round((time.monotonic() - t0) * 1000, 2),
   memory_root=memory_root, config=config)
```

Confirmed: `duration_ms=round((time.monotonic() - t0) * 1000, 2)` is present. `t0` is set at line 356 (`t0 = time.monotonic()`), which is in scope at line 391. All three `judge.error` sites (lines 384, 402, 415) now consistently pass `duration_ms`. Comment at line 383 documents this as the "A-02 F-07 fix."

Cross-verified the other two `judge.error` sites:
- Line 402-410 (api_failure): has `duration_ms=round(elapsed * 1000, 2)` where `elapsed = time.monotonic() - t0`. CONSISTENT.
- Line 415-423 (parse_failure): has `duration_ms=round(elapsed * 1000, 2)`. CONSISTENT.

### 2c. F-04 Fix: Reason enum updated in schema doc

**Verdict: CONDITIONAL PASS -- one residual inconsistency**

Read `temp/p2-logger-schema.md` lines 61-72. The reason enum on line 70 now correctly lists:

```
"short_prompt", "empty_index", "retrieval_disabled", "max_inject_zero", "no_fts5_results"
```

Cross-verified against actual code emit sites:
| Code line | Reason string | In schema enum? |
|-----------|--------------|-----------------|
| 352 | `"short_prompt"` | YES |
| 376 | `"empty_index"` | YES |
| 391 | `"retrieval_disabled"` | YES |
| 431 | `"max_inject_zero"` | YES |
| 449 | `"empty_index"` | YES |
| 559 | `"no_fts5_results"` | YES |

All code values match the updated schema enum. The optional fields `prompt_length` and `query_tokens` are also documented on lines 71-72.

**Residual issue (NEW-01):** The example JSON on line 66 still uses `"reason":"prompt_too_short"`:

```json
{"schema_version":1,...,"data":{"reason":"prompt_too_short","prompt_length":12},...}
```

This contradicts the corrected enum on line 70 which says `"short_prompt"`. The example should read `"reason":"short_prompt"`. This is a LOW severity documentation inconsistency in a temp file -- it does not affect any runtime behavior.

---

## 3. A-03 Fix Verification: body_bonus Field Accuracy

**Verdict: PASS**

Read `memory_retrieve.py` lines 260-274 (within `score_with_body()` in `memory_search_engine.py` -- though the search engine code is called from retrieve.py, the actual fix is in search_engine.py).

Wait -- let me re-check the actual file location of `score_with_body`.

The function `score_with_body` is defined in `memory_search_engine.py` but the code I read at lines 255-275 is from `memory_retrieve.py`. Let me verify the actual location.

After re-reading: The code at `memory_retrieve.py` lines 255-275 contains the `score_with_body` logic inline (it was moved or is defined there). The fix at lines 261-268:

```python
# A-03 fix: explicitly set body_bonus=0 for beyond-top_k entries to ensure
# the field is always present on every result (prevents ambiguity between
# "not analyzed" and "analyzed with 0 matches" at logging call sites).
for result in initial[top_k_paths:]:
    result.pop("_data", None)
    if "body_bonus" not in result:
        result["body_bonus"] = 0
```

### Verification points

1. **Beyond-top_k entries get explicit body_bonus=0:** The `if "body_bonus" not in result` guard correctly identifies state-C entries (active, file read OK, but beyond top_k so body not analyzed). These entries had `_data` cached but no `body_bonus` set. The fix explicitly sets `body_bonus = 0`. CONFIRMED.

2. **Existing entries with body_bonus NOT overwritten:** The `if "body_bonus" not in result` check ensures that state-B entries (file-read failures, where `body_bonus = 0` was set at line 240) are NOT modified. Only entries that genuinely lack the field get it added. CONFIRMED.

3. **The re-rank step at line 271-273 still works correctly:**

```python
for r in initial:
    r["raw_bm25"] = r["score"]
    r["score"] = r["score"] - r.get("body_bonus", 0)
```

Since `body_bonus` is now guaranteed to be present on ALL entries (set to 0 for beyond-top_k and file-read failures, set to 0-3 for analyzed entries), the `.get("body_bonus", 0)` fallback is technically redundant but defensively correct. The scoring calculation is unaffected -- entries that were not body-analyzed get `score = raw_bm25 - 0 = raw_bm25`, same as before.

4. **Logging call site behavior unchanged:** At `memory_retrieve.py` line 491, `r.get("body_bonus", 0)` will now always find the field explicitly set, so the default is never reached. The logged value is semantically more accurate: it reflects an explicit decision rather than a missing-field default.

---

## 4. Self-Critique: Issues the Fixes Missed or Could Improve

### NEW-01 (LOW): Schema doc example JSON still uses old reason string

**File:** `temp/p2-logger-schema.md`, line 66
**Issue:** Example JSON shows `"reason":"prompt_too_short"` but the corrected enum on line 70 says `"short_prompt"`.
**Impact:** Misleading for anyone copy-pasting the example. No runtime impact.
**Recommended fix:** Change `"prompt_too_short"` to `"short_prompt"` on line 66.

### NEW-02 (LOW): Schema doc retrieval.inject specifies output_mode not emitted by code

**File:** `temp/p2-logger-schema.md`, line 59
**Issue:** The `retrieval.inject` schema documents an `output_mode` field (`"full"`, `"compact"`, `"silent"`) but no code path emits this field. This is already tracked as D-01 (DEFERRED) in the A-02 audit report, but the schema doc still presents it as part of the active schema contract.
**Impact:** Downstream consumers expecting `output_mode` in every inject event will find it absent. The D-01 deferral is acceptable, but the schema doc should either mark it as "planned/optional" or remove it until implemented.

### NEW-03 (INFO): No regression tests specifically for the A-01 config ordering fix

The A-01 fix is a control flow change that moves config loading earlier. While the existing 852 tests pass, none specifically tests the scenario "logging enabled + short prompt -> skip event IS logged." This means if someone refactors `main()` and accidentally reorders the config load back below the first emit_event, no test would catch it.

**Recommendation:** Consider adding an integration test that pipes a short prompt (<10 chars) into `memory_retrieve.py` with a config that has `logging.enabled: true`, then verifies a JSONL file was created in `logs/retrieval/`. This would lock in the A-01 fix against future regressions.

### NEW-04 (INFO): body_bonus semantic ambiguity persists at a lower level

The A-03 fix ensures `body_bonus` is always present, but the distinction between "body analyzed, 0 matches" (state within top_k) and "body not analyzed" (state beyond top_k or file-read failure) is still lost. Both produce `body_bonus: 0`. The A-03 audit report recommended an optional `body_analyzed: true/false` flag (Fix 2 in the report). This was not implemented, which is acceptable for current PoC #5 needs but limits future analytical granularity.

### Edge cases not explicitly considered in the fixes

1. **A-01: Symlink at config_path.** If `.claude/memory/memory-config.json` is a symlink, `config_path.exists()` follows it. This is consistent with how Python's `Path.exists()` works and is not a new risk introduced by the fix -- the original code also used `config_path.exists()`.

2. **A-03: Empty initial list.** If `initial` is empty after retired filtering, `initial[top_k_paths:]` is an empty slice, so the fix loop body never executes. Correct -- no entries to set `body_bonus` on.

3. **A-02 F-07: Timer precision.** The parallel failure `duration_ms` uses `time.monotonic()` while the search pipeline uses `time.perf_counter()`. This is pre-existing (not introduced by the fix) and is an accepted inconsistency noted in the original V1 review (Finding F-09: "monotonic vs perf_counter -- ACCEPTED (pre-existing)").

---

## 5. External Model Opinions

### Codex 5.3

**Status:** UNAVAILABLE -- rate limit exceeded. Codex returned: "You've hit your usage limit. Upgrade to Pro or try again at Feb 28th, 2026."

### Gemini 3.1 Pro

**Status:** Review completed (460s, 30 API requests, 738K total tokens).

**Summary of Gemini's assessment:**

1. **A-01 (Config loading order):** "Correct and Complete." Confirmed the `_raw_config` loading was cleanly moved above initial `emit_event` calls with proper fail-open fallback. Noted that all 6 `retrieval.skip` events now correctly receive `config=_raw_config`.

2. **A-02 (Call-site schema audit):**
   - F-06: "Correct." Confirmed `engine` key successfully removed from legacy inject emit.
   - F-07: "Correct." Confirmed `duration_ms` added with correct `t0` reference.
   - F-04: **"Mostly Correct, but Incomplete."** Independently identified the same issue as my NEW-01: the example JSON on line 66 still uses `"prompt_too_short"` instead of the corrected `"short_prompt"`. Gemini classified this as LOW severity.

3. **A-03 (body_bonus field):** "Correct and Complete." Confirmed the conditional assignment (`if "body_bonus" not in result`) safely patches missing keys without overwriting upstream exception-handling assignments.

**Gemini's overall verdict:** "The Phase A code modifications are functionally sound, secure, and fully address the underlying logging configuration and metric accuracy issues."

**Gemini's recommended fix:** Update `temp/p2-logger-schema.md` line 66 to change `"prompt_too_short"` to `"short_prompt"`.

### Vibe Check (Metacognitive)

Confirmed CONDITIONAL PASS is appropriate. Noted the two residual issues (NEW-01 and NEW-02) are LOW severity documentation items in a temp file, not blocking conditions. Suggested these could be framed as "documentation cleanup" rather than conditions that block Phase B.

---

## 6. Test Results

```
Compile check: 13/13 hook scripts -- ALL PASSED
pytest tests/ -v: 852/852 PASSED in 40.64s -- ZERO regressions
```

---

## 7. Overall Verdict

### CONDITIONAL PASS

All three Phase A fixes (A-01, A-02 partial, A-03) are **correctly implemented** and introduce no regressions. The fixes address real issues: A-01 was a genuine data completeness bug, A-02 resolved schema drift and event consistency gaps, and A-03 hardened a fragile structural invariant.

### Conditions for Full PASS

1. **NEW-01 (trivial):** Fix the example JSON on `temp/p2-logger-schema.md` line 66 to use `"short_prompt"` instead of `"prompt_too_short"`. This is a ~10 character edit.

2. **NEW-02 (documentation):** Either mark `output_mode` as "planned/not yet emitted" in the `retrieval.inject` schema section, or remove it until D-01 is implemented. This is a schema accuracy issue -- the doc promises a field the code does not provide.

### Items noted but NOT blocking

- NEW-03: No specific regression test for A-01 fix (recommended for future hardening)
- NEW-04: body_bonus semantic ambiguity persists (accepted per A-03 audit recommendation)
- Codex 5.3 review unavailable due to rate limiting (Gemini 3.1 Pro review independently confirms findings)
- All deferred items (D-01 through D-05, F-01/F-02/F-03/F-05) properly tracked in A-02 audit report

---

## Appendix: Files Examined

| File | Lines Read | Purpose |
|------|-----------|---------|
| `hooks/scripts/memory_retrieve.py` | 1-50, 230-275, 310-430, 430-566, 550-704 | A-01, A-02, A-03 fix verification |
| `hooks/scripts/memory_judge.py` | 1-50, 340-440 | A-02 F-07 fix verification |
| `hooks/scripts/memory_logger.py` | 1-324 (full) | Config parsing, emit_event behavior |
| `temp/p2-logger-schema.md` | 1-221 (full) | Schema contract cross-reference |
| `temp/p2-a01-config-race.md` | 1-150 (full) | A-01 audit report context |
| `temp/p2-a02-schema-audit.md` | 1-369 (full) | A-02 audit report context |
| `temp/p2-a03-results-accuracy.md` | 1-390 (full) | A-03 audit report context |
| `temp/p2-audit-execution-plan.md` | 1-58 (full) | Phase structure context |
| `temp/p2-fixes-summary.md` | 1-65 (full) | Prior fix summary |
| `temp/p2-phase5-self-review.md` | 1-74 (full) | Test coverage context |
