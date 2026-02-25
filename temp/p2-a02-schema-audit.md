# A-02: Call-Site Schema Audit Report

**Date:** 2026-02-25
**Auditor:** Claude Opus 4.6
**Schema baseline:** `temp/p2-logger-schema.md` (v1)
**Consumer scripts audited:** 4 scripts, 13 `emit_event()` call sites

---

## Summary

| Metric | Count |
|--------|-------|
| Total call sites | 13 |
| Fully conformant | 5 |
| Gaps (known DEFERRED) | 3 |
| NEW findings | 5 |
| Severity: HIGH | 1 |
| Severity: MEDIUM | 2 |
| Severity: LOW | 2 |

---

## Complete Comparison Table

### 1. `retrieval.search` (3 call sites)

#### 1a. FTS5 primary search -- `memory_retrieve.py:471`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `query_tokens` | list[str] | `prompt_tokens` (list[str]) | OK |
| `engine` | str | `"fts5_bm25"` | OK |
| `candidates_found` | int | `_candidates_post_threshold` (= len(results)) | **D-02 (DEFERRED)**: Same value as `candidates_post_threshold`. These should differ -- `candidates_found` should be the raw FTS5 count before threshold. |
| `candidates_post_threshold` | int | `_candidates_post_threshold` (= len(results)) | OK (structurally) |
| `candidates_post_judge` | int | **MISSING** | **NEW F-01**: Key entirely absent. Schema requires it. At this logging point the judge hasn't run yet, so the field can't be known. See F-01 below. |
| `injected_count` | int | **MISSING** | **NEW F-02**: Key absent. Same rationale -- injection count unknown at search time. See F-02 below. |
| `results` | list[object] with `{path, score, raw_bm25, body_bonus, confidence}` | Matches: `path`, `score`, `raw_bm25`, `body_bonus`, `confidence` | OK |

#### 1b. Post-judge debug log -- `memory_retrieve.py:519`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `event_type` | `"retrieval.search"` | `"retrieval.search"` | OK (reuses same event_type) |
| `level` | (schema shows info) | `"debug"` | OK (schema allows any level) |
| `candidates_post_judge` | int | `_candidates_post_judge` (int) | OK |
| `judge_active` | **not in schema** | `True` (bool) | **NEW F-03**: Extra key not documented in schema. |
| All other `retrieval.search` keys | present | **MISSING** | **NEW F-04**: This is a partial-data debug emit. Missing: `query_tokens`, `engine`, `candidates_found`, `candidates_post_threshold`, `results`. This is a supplementary debug event, not a full search event. |

#### 1c. Legacy fallback warning -- `memory_retrieve.py:560`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `event_type` | `"retrieval.search"` | `"retrieval.search"` | OK |
| `level` | (info) | `"warning"` | OK |
| `engine` | str | `"title_tags"` | OK |
| `reason` | **not in schema** | `"fts5_unavailable"` (str) | **NEW F-05**: Extra key. Schema has no `reason` field for `retrieval.search`. |
| `query_tokens` | list[str] | **MISSING** | Absent (partial emit for warning) |
| `candidates_found` | int | **MISSING** | Absent |
| `candidates_post_threshold` | int | **MISSING** | Absent |
| `candidates_post_judge` | int | **MISSING** | Absent |
| `injected_count` | int | **MISSING** | Absent |
| `results` | list[object] | **MISSING** | Absent |

---

### 2. `retrieval.inject` (2 call sites)

#### 2a. FTS5 path injection -- `memory_retrieve.py:533`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `injected_count` | int | `len(top)` | OK |
| `results` | list[object] `{path, confidence}` | `[{path, confidence}]` | OK |
| `output_mode` | str (`"full"`, `"compact"`, `"silent"`) | **MISSING** | **D-01 (DEFERRED)** |

#### 2b. Legacy path injection -- `memory_retrieve.py:678`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `injected_count` | int | `len(top_list)` | OK |
| `results` | list[object] `{path, confidence}` | `[{path, confidence}]` | OK |
| `output_mode` | str | **MISSING** | **D-01 (DEFERRED)** |
| `engine` | **not in schema** | `"title_tags"` (str) | **NEW F-06**: Extra key not in `retrieval.inject` schema. Schema only defines `injected_count`, `results`, `output_mode`. |

---

### 3. `retrieval.skip` (5 call sites)

#### 3a. Short prompt -- `memory_retrieve.py:333`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `reason` | str | `"short_prompt"` | OK (note: schema says `"prompt_too_short"`, code says `"short_prompt"`) -- **NEW F-07** |
| `prompt_length` | int (optional) | `len(user_prompt.strip())` (int) | OK |

#### 3b. Empty index (pre-config) -- `memory_retrieve.py:359`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `reason` | str | `"empty_index"` | OK (note: schema says `"no_index"` or `"no_memories"`, code says `"empty_index"`) -- **NEW F-07** |
| `prompt_length` | int (optional) | **ABSENT** | OK (optional) |

#### 3c. Retrieval disabled -- `memory_retrieve.py:379`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `reason` | str | `"retrieval_disabled"` | OK (matches schema) |

#### 3d. Max inject zero -- `memory_retrieve.py:419`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `reason` | str | `"max_inject_zero"` | **NEW F-07**: Not in schema's enumerated reason values |

#### 3e. Empty index (post-parse) -- `memory_retrieve.py:437`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `reason` | str | `"empty_index"` | Same as 3b -- **F-07** |

#### 3f. No FTS5 results -- `memory_retrieve.py:547`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `reason` | str | `"no_fts5_results"` | **NEW F-07**: Not in schema's enumerated values |
| `query_tokens` | **not in schema** | `prompt_tokens` (list[str]) | **NEW F-08**: Extra key not documented for `retrieval.skip` |

---

### 4. `judge.evaluate` (2 call sites)

#### 4a. Parallel path -- `memory_judge.py:368`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `candidate_count` | int | `len(candidates)` | OK |
| `model` | str | `model` (str) | OK |
| `batch_count` | int | `2` | OK |
| `mode` | str | `"parallel"` | OK |
| `accepted_indices` | list[int] | `_kept_sorted` (sorted list[int]) | OK |
| `rejected_indices` | list[int] | `_rejected` (list[int]) | OK |

#### 4b. Sequential path -- `memory_judge.py:426`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `candidate_count` | int | `len(candidates)` | OK |
| `model` | str | `model` (str) | OK |
| `batch_count` | int | `1` | OK |
| `mode` | str | `"sequential"` | OK |
| `accepted_indices` | list[int] | `_kept_sorted` (sorted list[int]) | OK |
| `rejected_indices` | list[int] | `_rejected` (list[int]) | OK |

**Both judge.evaluate sites: FULLY CONFORMANT.**

---

### 5. `judge.error` (3 call sites)

#### 5a. Parallel failure fallback -- `memory_judge.py:383`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `error_type` | str | `"parallel_failure"` | OK |
| `message` | str | `"Parallel judge failed, falling back to sequential"` | OK |
| `fallback` | str | `"sequential"` | OK |
| `candidate_count` | int | `len(candidates)` | OK |
| `model` | str | `model` | OK |
| `duration_ms` (envelope) | float\|null | **NOT PASSED** (no `duration_ms` kwarg) | **NEW F-09**: `duration_ms` defaults to `None` in `emit_event`. The parallel failure emit does not measure elapsed time. Other judge.error sites do pass it. |

#### 5b. API failure -- `memory_judge.py:400`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `error_type` | str | `"api_failure"` | OK |
| `message` | str | `"API call returned None"` | OK |
| `fallback` | str | `"caller_fallback"` | OK |
| `candidate_count` | int | `len(candidates)` | OK |
| `model` | str | `model` | OK |

**FULLY CONFORMANT.**

#### 5c. Parse failure -- `memory_judge.py:413`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `error_type` | str | `"parse_failure"` | OK |
| `message` | str | `"Failed to parse judge response"` | OK |
| `fallback` | str | `"caller_fallback"` | OK |
| `candidate_count` | int | `len(candidates)` | OK |
| `model` | str | `model` | OK |

**FULLY CONFORMANT.**

---

### 6. `search.query` (1 call site)

#### 6a. CLI search -- `memory_search_engine.py:500`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `fts_query` | str | `_fts_query_str` (str) | OK |
| `token_count` | int | `_token_count` (int) | OK |
| `result_count` | int | `len(results)` (int) | OK |
| `top_score` | float | `round(_top_score, 4)` (float) | OK |

**FULLY CONFORMANT.**

---

### 7. `triage.score` (1 call site)

#### 7a. Triage scoring -- `memory_triage.py:1000`

| Aspect | Expected (schema) | Actual (code) | Gap |
|--------|-------------------|---------------|-----|
| `text_len` | int | `len(text)` (int) | OK |
| `exchanges` | int | `metrics.get("exchanges", 0)` (int) | OK |
| `tool_uses` | int | `metrics.get("tool_uses", 0)` (int) | OK |
| `triggered` | list[object] `{category, score}` | `[{category, score}]` | OK |

**FULLY CONFORMANT.**

---

## NEW Findings (Not in DEFERRED)

### F-01: `retrieval.search` primary emit missing `candidates_post_judge` and `injected_count`

**Severity: LOW**
**File:** `memory_retrieve.py:471`

The primary `retrieval.search` emit at line 471 fires before the judge runs and before injection count is known. The schema defines `candidates_post_judge` and `injected_count` as fields of `retrieval.search`, but these values are structurally unavailable at this logging point.

**Recommendation:** Accept as architectural -- the `retrieval.search` event captures search-phase data. `candidates_post_judge` is emitted in the debug-level supplementary event at line 519, and `injected_count` is captured in the separate `retrieval.inject` event. Update the schema to mark `candidates_post_judge` and `injected_count` as **optional** fields in `retrieval.search` (present only when judge has already run, e.g., in a combined single-emit future refactor).

---

### F-02: `retrieval.search` debug emit (line 519) is a partial/supplementary event

**Severity: LOW**
**File:** `memory_retrieve.py:519`

This debug-level emit reuses event_type `"retrieval.search"` but only contains `{candidates_post_judge, judge_active}`. It is missing all standard `retrieval.search` fields (`query_tokens`, `engine`, `candidates_found`, `candidates_post_threshold`, `results`). Additionally, `judge_active` is an undocumented extra key.

This is intentional -- it's a debug-level supplementary annotation. However, consumers parsing `retrieval.search` events will encounter inconsistent shapes.

**Options (pick one):**
1. **Rename** to a distinct event type like `"retrieval.judge_result"` (cleanest).
2. **Document** in schema that debug-level `retrieval.search` events may be partial/supplementary.
3. **Merge** the post-judge data into the `retrieval.inject` event instead (already emitted after judge).

---

### F-03: Legacy `retrieval.search` warning emit (line 560) has undocumented `reason` key

**Severity: LOW**
**File:** `memory_retrieve.py:560`

The FTS5-unavailable fallback emits `{"engine": "title_tags", "reason": "fts5_unavailable"}` under event_type `"retrieval.search"`. The `reason` field is not in the `retrieval.search` schema. This is also a partial event (no `query_tokens`, `candidates_*`, `results`).

**Recommendation:** Same as F-02 -- either rename to a distinct event type (e.g., `"retrieval.fallback"`) or document as a warning-level partial event in the schema.

---

### F-04: `retrieval.skip` reason values diverge from schema enumeration

**Severity: MEDIUM**
**File:** `memory_retrieve.py` (lines 333, 359, 419, 437, 547)

The schema enumerates `reason` values as: `"prompt_too_short"`, `"retrieval_disabled"`, `"no_index"`, `"no_memories"`.

Actual values emitted by code:
| Code value | Schema equivalent | Match? |
|-----------|-------------------|--------|
| `"short_prompt"` | `"prompt_too_short"` | MISMATCH |
| `"empty_index"` | `"no_index"` or `"no_memories"` | MISMATCH |
| `"retrieval_disabled"` | `"retrieval_disabled"` | OK |
| `"max_inject_zero"` | (not in schema) | MISSING from schema |
| `"no_fts5_results"` | (not in schema) | MISSING from schema |

**Impact:** Any downstream tooling (dashboards, alerting, jq queries) using the schema-documented reason strings will miss events.

**Recommendation:** Update the schema to match the actual code values. The code values are more descriptive (e.g., `"short_prompt"` vs `"prompt_too_short"`) and already deployed. Update schema section 3 to:
```
reason: "short_prompt" | "empty_index" | "retrieval_disabled" | "max_inject_zero" | "no_fts5_results"
```

---

### F-05: `retrieval.skip` at line 547 includes undocumented `query_tokens` key

**Severity: LOW**
**File:** `memory_retrieve.py:547`

The `no_fts5_results` skip event includes `query_tokens` which is not documented in the `retrieval.skip` schema. This is useful debug information but breaks schema expectations.

**Recommendation:** Add `query_tokens` as an optional field to the `retrieval.skip` schema: `query_tokens (list[str], optional): Present when skip occurs after tokenization.`

---

### F-06: `retrieval.inject` legacy path (line 678) includes undocumented `engine` key

**Severity: MEDIUM**
**File:** `memory_retrieve.py:678`

The legacy path's `retrieval.inject` event includes `"engine": "title_tags"` which is not in the `retrieval.inject` schema. The FTS5 path's inject event (line 533) does NOT include `engine`.

**Impact:** Inconsistent shape between the two code paths for the same event type. Downstream consumers cannot rely on `engine` being present or absent.

**Recommendation:** Either:
1. Add `engine` as an optional field to the `retrieval.inject` schema (and also emit it from the FTS5 path for consistency), OR
2. Remove it from the legacy path (the preceding `retrieval.search` event already identifies the engine).

Option 2 is cleaner -- the inject event should focus on injection results, not engine identification.

---

### F-07: `judge.error` parallel failure (line 383) missing `duration_ms`

**Severity: LOW**
**File:** `memory_judge.py:383`

The parallel failure `judge.error` emit does not pass `duration_ms`, so it defaults to `null`. The other two `judge.error` sites (lines 400, 413) correctly pass `duration_ms=round(elapsed * 1000, 2)`. This is a minor inconsistency -- the parallel failure happens mid-flow before falling through to sequential, so elapsed time is available but not captured.

**Recommendation:** Add `duration_ms=round((time.monotonic() - t0) * 1000, 2)` to the parallel failure emit for consistency. The variable `t0` is in scope at that point.

---

## Conformance Summary by Event Type

| Event Type | Call Sites | Fully Conformant | Partial/Divergent | Notes |
|-----------|-----------|-----------------|-------------------|-------|
| `retrieval.search` | 3 | 0 | 3 | Primary is near-conformant (missing optional fields); debug and warning are partial emits |
| `retrieval.inject` | 2 | 1 | 1 | FTS5 path OK (minus D-01); legacy has extra `engine` key |
| `retrieval.skip` | 5 | 1 | 4 | Reason string mismatches + extra `query_tokens` |
| `judge.evaluate` | 2 | 2 | 0 | Fully conformant |
| `judge.error` | 3 | 2 | 1 | Parallel failure missing `duration_ms` |
| `search.query` | 1 | 1 | 0 | Fully conformant |
| `triage.score` | 1 | 1 | 0 | Fully conformant |
| **TOTAL** | **13** | **8** | **5** | |

---

## Deferred Items (Confirmed Present, Not Re-Flagged)

| ID | Description | Confirmed? |
|----|-------------|-----------|
| D-01 | `retrieval.inject` missing `output_mode` field | YES -- both inject call sites (lines 533, 678) |
| D-02 | `candidates_found == candidates_post_threshold` (same value) | YES -- line 471 assigns both from `len(results)` |
| D-03 | No global payload size limit | YES -- `emit_event` has `_MAX_RESULTS=20` truncation for `results[]`, but no overall payload byte limit |
| D-05 | No `matched_tokens` field | YES -- not emitted anywhere |

---

## Prioritised Fix Recommendations

| Priority | Finding | Fix | Effort |
|----------|---------|-----|--------|
| 1 | F-04 (reason enum mismatch) | Update schema to match code values | 5 min |
| 2 | F-06 (extra `engine` in legacy inject) | Remove `engine` from legacy inject emit | 2 min |
| 3 | F-02 (partial debug search event) | Rename to `retrieval.judge_result` or merge into inject | 10 min |
| 4 | F-01 (missing optional fields in search) | Mark `candidates_post_judge` + `injected_count` as optional in schema | 5 min |
| 5 | F-05 (extra `query_tokens` in skip) | Add as optional field to skip schema | 2 min |
| 6 | F-03 (undocumented `reason` in search warning) | Rename event or document partial warning shape | 5 min |
| 7 | F-07 (missing `duration_ms` in parallel judge.error) | Add `duration_ms` kwarg at line 383 | 2 min |
