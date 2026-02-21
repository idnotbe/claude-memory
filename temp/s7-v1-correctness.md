# S7 Verification Round 1: Correctness Review

**Reviewer:** v1-correctness
**Date:** 2026-02-21
**Scope:** memory_judge.py, memory_retrieve.py (judge integration), memory-config.default.json, hooks.json, CLAUDE.md
**Reference:** rd-08-final-plan.md lines 573-959
**Test suite:** 683 passed, 0 failed (no regressions)

---

## Overall Verdict: PASS (with 2 MEDIUM issues, 2 LOW issues)

The implementation is faithful to the spec with well-justified deviations. No critical or high-severity issues found.

---

## 1. Pseudocode Fidelity

### PASS -- memory_judge.py

| Spec Element | Implementation | Match? | Notes |
|-------------|---------------|--------|-------|
| `call_api()` signature | `(system, user_msg, model, timeout)` | YES | Exact match |
| `call_api()` returns None on all errors | Lines 86-90 catch all relevant exceptions | YES | |
| `call_api()` no API key -> None | Line 60-61 | YES | |
| `extract_recent_context()` | Lines 93-133 | YES | |
| `format_judge_input()` return type | `tuple[str, list[int]]` | YES | |
| `parse_response()` with fallback JSON extraction | Lines 171-192 | YES | Uses find/rfind as spec requires |
| `_extract_indices()` string coercion | Lines 200-208 | YES | |
| `judge_candidates()` returns None on failure | Lines 237-242 | YES | |
| `judge_candidates()` returns [] for empty candidates | Line 223 | YES | |
| `JUDGE_SYSTEM` prompt text | Lines 29-53 | YES | Exact match to spec |
| `_API_URL`, `_API_VERSION`, `_DEFAULT_MODEL` | Lines 25-27 | YES | |

### Deviations Found (All Justified)

**D1: `random.Random(seed)` instance vs `random.seed(seed)` + `random.shuffle()`**
- **Spec (line 714):** `random.seed(seed)` then `random.shuffle(order)` (mutates global state)
- **Implementation (lines 152-153):** `rng = random.Random(seed)` then `rng.shuffle(order)`
- **Verdict:** IMPROVEMENT. The implementation avoids mutating global random state, which is safer in concurrent/re-entrant scenarios. Functionally equivalent shuffle behavior via dedicated Random instance.

**D2: `deque` import moved to top-level**
- **Spec (line 660):** `from collections import deque` inside `extract_recent_context()`
- **Implementation (line 23):** `from collections import deque` at module level
- **Verdict:** IMPROVEMENT. Better for repeated calls (no re-import overhead). No behavioral difference.

**D3: `import time` moved to top-level**
- **Spec (line 795):** `import time` inside `judge_candidates()`
- **Implementation (line 20):** `import time` at module level
- **Verdict:** IMPROVEMENT. Standard Python practice.

**D4: Boolean rejection in `_extract_indices()`**
- **Spec (lines 761-772):** No boolean check
- **Implementation (lines 201-203):** Explicit `isinstance(di, bool)` check with `continue`
- **Verdict:** IMPROVEMENT. In Python, `bool` is a subclass of `int`, so `True` would pass `isinstance(di, int)` and be treated as index 1. This is defensive hardening against malformed LLM output like `{"keep": [true, false, 2]}`.

### PASS -- Integration in memory_retrieve.py

| Spec Element | Implementation Location | Match? |
|-------------|------------------------|--------|
| Config parsing `judge_cfg = config.get(...)` | Lines 367-374 | YES (slightly restructured, see below) |
| `judge_enabled` with API key check | Lines 369-372 | YES |
| Stderr info when enabled but no key | Lines 386-388 | YES |
| FTS5 path judge integration | Lines 423-448 | YES |
| Legacy path judge integration | Lines 497-520 | YES |
| `pool_size` from config | Lines 427, 500-501 | YES |
| `transcript_path` from hook_input | Lines 429, 502 | YES |
| All 7 judge config keys passed | Lines 431-438, 504-511 | YES |
| `filtered_paths` set intersection | Lines 442-443, 514-516 | YES |
| Fallback to `fallback_top_k` | Lines 446-447, 519-520 | YES |

**Deviation: Config parsing location**
- **Spec:** Config parsing is shown as a separate block "After BM25 scoring, before output"
- **Implementation:** judge_cfg/judge_enabled are parsed during the main config loading block (lines 367-374), not as a separate post-scoring block
- **Verdict:** ACCEPTABLE. The config values are read once during startup and used at the correct point in both FTS5 and legacy paths. Moving config parsing to a single location is cleaner.

---

## 2. Edge Cases

### PASS

| Edge Case | Handling | Location |
|-----------|----------|----------|
| Empty candidates | Returns `[]` | judge.py:223 |
| No API key | `call_api` returns None, `judge_candidates` returns None -> fallback | judge.py:60-61 |
| API timeout | Caught by `TimeoutError, OSError` | judge.py:87 |
| Malformed JSON response | `parse_response` returns None | judge.py:178-192 |
| All candidates filtered by judge | Returns `[]` (empty list, not None) -> output empty | judge.py:244 |
| Non-integer indices in response | String coercion ("2" -> 2) | judge.py:204-205 |
| Out-of-range indices | Bounds check `0 <= di < len(order_map)` | judge.py:207 |
| Boolean indices | Rejected explicitly | judge.py:201-203 |
| Judge returns None (API fail) | FTS5 path: fallback_top_k (line 446-447). Legacy path: same (519-520) | PASS |
| Judge returns None (parse fail) | Same fallback behavior | PASS |
| Missing transcript file | `extract_recent_context` returns "" | judge.py:113-114 |
| Empty transcript | Returns "" | judge.py:116-133 |
| `include_context=False` | Context extraction skipped | judge.py:227-228 |

---

## 3. Function Signatures

### PASS

| Function | Spec Signature | Implementation | Match? |
|----------|---------------|----------------|--------|
| `call_api` | `(system, user_msg, model, timeout) -> str \| None` | Line 56-57 | YES |
| `extract_recent_context` | `(transcript_path, max_turns) -> str` | Line 93 | YES |
| `format_judge_input` | `(user_prompt, candidates, conversation_context) -> tuple[str, list[int]]` | Lines 136-140 | YES |
| `parse_response` | `(text, order_map, n_candidates) -> list[int] \| None` | Line 171 | YES |
| `_extract_indices` | `(display_indices, order_map, n_candidates) -> list[int]` | Line 195 | YES |
| `judge_candidates` | `(user_prompt, candidates, transcript_path, model, timeout, include_context, context_turns) -> list[dict] \| None` | Lines 212-220 | YES |

---

## 4. Error Handling

### PASS

All error paths return None for fallback, as specified:

| Error Path | Returns | Fallback Effect |
|------------|---------|-----------------|
| No API key | None (call_api) -> None (judge_candidates) | Uses fallback_top_k |
| HTTP error | None (call_api) -> None (judge_candidates) | Uses fallback_top_k |
| Timeout | None (call_api) -> None (judge_candidates) | Uses fallback_top_k |
| JSON decode error in response | None (parse_response) -> None (judge_candidates) | Uses fallback_top_k |
| No "keep" key in response | None (parse_response) -> None (judge_candidates) | Uses fallback_top_k |
| File read error in transcript | "" (extract_recent_context) -> continues with no context | Judge still runs |

---

## 5. Data Flow (order_map)

### PASS

The order_map flow is correct:

1. `format_judge_input()` creates `order` list where `order[display_idx] = real_idx`
2. Candidates are displayed in shuffled order: `candidates[order[display_idx]]` for display index `display_idx`
3. LLM returns `{"keep": [display_idx_0, display_idx_1, ...]}`
4. `parse_response()` calls `_extract_indices(display_indices, order_map, n)`
5. `_extract_indices()` maps each `di` to `order_map[di]` which gives the real index
6. `judge_candidates()` uses real indices to select from original `candidates` list: `candidates[i] for i in sorted(set(kept_indices))`

**Verified: The mapping is correct.** If candidate at real index 3 is displayed at position 1, and the LLM keeps position 1, then `order_map[1] = 3`, giving real index 3. Correct.

---

## 6. Config Parsing (7 Judge Config Keys)

### PASS

| Config Key | Default in Spec | Default in Code | Read At |
|-----------|----------------|-----------------|---------|
| `judge.enabled` | `false` | `false` (line 369) | retrieve.py:369 |
| `judge.model` | `"claude-haiku-4-5-20251001"` | `"claude-haiku-4-5-20251001"` (line 435) | retrieve.py:435, 508 |
| `judge.timeout_per_call` | `3.0` | `3.0` (line 436) | retrieve.py:436, 509 |
| `judge.fallback_top_k` | `2` | `2` (line 446) | retrieve.py:446, 519 |
| `judge.candidate_pool_size` | `15` | `15` (line 427) | retrieve.py:427, 500 |
| `judge.include_conversation_context` | `true` | `True` (line 437) | retrieve.py:437, 510 |
| `judge.context_turns` | `5` | `5` (line 438) | retrieve.py:438, 511 |

All 7 keys match spec defaults. The `dual_verification` key is in config (line 59 of default config) but not read by code, which is correct since dual verification is Phase 4 (not implemented yet).

The `modes` object from the spec config schema (lines 892-901) is NOT present in the default config. This is acceptable since `modes` is documented as a Phase 4 feature. No code reads it.

---

## 7. Integration Correctness

### PASS (with notes)

**FTS5 path (lines 423-451):**
- Judge is called AFTER `score_with_body()` returns `results` and BEFORE `_output_results()`
- Candidates passed to judge are `results[:pool_size]` -- these are already sorted by BM25+body score
- After filtering, `results` is filtered to keep only judge-approved paths, preserving BM25 order
- On failure, `results[:fallback_top_k]` is used

**Legacy path (lines 497-520):**
- Judge is called AFTER scoring and sorting (line 494) and BEFORE deep check (line 522)
- Candidates are extracted from `scored[:pool_size]` tuples
- After filtering, `scored` tuples are filtered by path match, preserving score order
- On failure, `scored[:fallback_top_k]` is used

**IMPORTANT NOTE:** In the FTS5 path, the judge is called on `results` which have already been threshold-filtered and capped by `apply_threshold()`. In the legacy path, the judge is called on `scored` which is the full scored list (before deep check / max_inject capping). This means:
- FTS5: judge sees at most `max_inject` candidates (typically 3). With `pool_size=15`, it will see min(len(results), 15) which is at most 3 in auto mode.
- Legacy: judge sees up to `pool_size=15` from the full scored list, which could be much larger.

This asymmetry is worth noting but not necessarily a bug -- the FTS5 path has better precision from BM25+body scoring, so fewer candidates need judging.

---

## 8. Issues Found

### MEDIUM-1: FTS5 path judge pool is effectively capped at max_inject, not candidate_pool_size

**Location:** memory_retrieve.py lines 417-419 and 427-428

**Problem:** In the FTS5 path, `results` comes from `score_with_body()` which calls `apply_threshold()` internally. `apply_threshold()` caps results at `max_inject` (default 3 in auto mode). So `candidates_for_judge = results[:pool_size]` where `pool_size=15` will only ever see at most 3 candidates (since `results` has at most 3 entries after threshold).

The judge was designed to evaluate a larger pool (15) and select the best ones, but in the FTS5 path it only ever sees the already-capped results.

**Impact:** The judge in FTS5 mode acts as a post-filter on an already-small set rather than the intended pre-filter on a larger candidate pool. It can still remove irrelevant results (improving precision), but it cannot surface relevant results that were already cut by the threshold.

**Spec comparison:** The spec shows the integration as "After BM25 scoring, before output" with `scored[:pool_size]` (legacy path, 15 candidates). The FTS5 path was not explicitly specified but should logically follow the same pattern.

**Recommended fix:** In the FTS5 path, call `score_with_body()` with a larger `max_inject` (e.g., `pool_size`) when judge is enabled, then let the judge filter, then apply the original `max_inject` cap:
```python
effective_max = pool_size if judge_enabled else max_inject
results = score_with_body(conn, fts_query, user_prompt,
                          max(10, effective_max), memory_root, "auto",
                          max_inject=effective_max)
```

### MEDIUM-2: No sanitization of candidate titles passed to judge

**Location:** memory_judge.py lines 156-161

**Problem:** `format_judge_input()` directly uses `c.get("title", "untitled")` without sanitization. While the spec mentions "Write-side sanitization strips control chars" and "Read-side re-sanitization as defense-in-depth," the titles in the FTS5 path come from `parse_index_line()` which reads from index.md. The index could contain unsanitized titles if rebuilt from JSON that somehow bypassed write-side sanitization.

The `_sanitize_title()` function exists in `memory_retrieve.py` and is used in `_output_results()`, but it is not applied to titles sent to the judge LLM.

**Impact:** A crafted title in index.md could potentially inject instructions into the judge prompt. The `<memory_data>` tags and system prompt provide some protection, but defense-in-depth suggests sanitizing before sending to the LLM.

**Severity:** MEDIUM (not HIGH because: judge output is JSON indices only, the system prompt explicitly warns about injection, and write-side sanitization should prevent this in normal operation).

**Recommended fix:** Either import and apply `_sanitize_title()` in `format_judge_input()`, or add a simpler sanitization (strip control chars, truncate).

### LOW-1: `n_candidates` parameter in `parse_response` is unused

**Location:** memory_judge.py line 171

**Problem:** `parse_response(text, order_map, n_candidates)` accepts `n_candidates` but never uses it. The bounds check in `_extract_indices()` uses `len(order_map)` instead of `n_candidates`. Since `len(order_map) == n_candidates` in all current call sites, this has no practical impact.

**Spec (line 733):** The spec also passes `n_candidates` but only uses it in `_extract_indices` (line 761) where `n_candidates` is also unused in the spec pseudocode (bounds check uses `len(order_map)`).

**Impact:** Dead parameter. No functional issue, but could confuse future maintainers.

### LOW-2: `dual_verification` config key present but entirely unused

**Location:** memory-config.default.json line 59

**Problem:** `"dual_verification": false` is in the default config but no code reads it. This is documented as Phase 4 in the spec (lines 907-919). Having the key present may confuse users who set it to `true` expecting behavior.

**Impact:** Minimal. The spec explicitly labels this as Phase 4.

---

## 9. hooks.json Timeout

### PASS

**Spec (line 936):** "Update `hooks/hooks.json` timeout from 10 to 15 seconds"
**Implementation:** hooks.json line 52 shows `"timeout": 15` for UserPromptSubmit
**Verified:** The timeout was changed. This accommodates the ~3s judge API call within the 15s hook budget.

---

## 10. CLAUDE.md Documentation

### PASS

Changes verified:
1. **Architecture table (line 18):** Updated to mention "optional LLM judge layer filters false positives" -- Correct
2. **Key Files table (line 47):** `memory_judge.py` added with correct description and "stdlib only (urllib.request)" -- Correct
3. **Config Architecture (line 64):** `retrieval.judge.*` keys listed in Script-read category -- Correct
4. **Security Considerations (line 124):** New item #6 for LLM judge prompt injection -- Correct and comprehensive
5. **Quick Smoke Check (line 137):** `py_compile` for memory_judge.py added -- Correct

---

## 11. Test Compatibility

### PASS

- `pytest tests/ -v`: **683 passed, 0 failed** (36.19s)
- `python3 -m py_compile hooks/scripts/memory_judge.py`: Clean (no errors)
- No test file exists for memory_judge.py yet (Phase 3b per spec -- not yet implemented)

---

## Summary Table

| Check Area | Verdict | Issues |
|-----------|---------|--------|
| Pseudocode fidelity | PASS | 4 deviations, all improvements |
| Edge cases | PASS | All covered |
| Function signatures | PASS | Exact match |
| Error handling | PASS | All errors -> None -> fallback |
| Data flow (order_map) | PASS | Correctly maps display -> real indices |
| Config parsing (7 keys) | PASS | All keys read with correct defaults |
| Integration correctness | PASS | Both FTS5 and legacy paths correct |
| hooks.json timeout | PASS | 10 -> 15 seconds |
| CLAUDE.md documentation | PASS | All 5 update areas covered |
| Test compatibility | PASS | 683/683 tests pass |

| Issue | Severity | Functional Impact |
|-------|----------|-------------------|
| FTS5 judge pool capped at max_inject, not pool_size | MEDIUM | Judge sees fewer candidates than intended in FTS5 path |
| No title sanitization in judge input | MEDIUM | Defense-in-depth gap for prompt injection |
| `n_candidates` parameter unused | LOW | Dead parameter, no functional impact |
| `dual_verification` config unused | LOW | Phase 4 placeholder, documented |
