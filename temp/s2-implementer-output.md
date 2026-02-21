# Session 2: FTS5 Engine Core -- Implementation Report

**Date:** 2026-02-21
**Status:** COMPLETE
**Implementer:** Claude Opus 4.6 (implementer-v2)

---

## Summary

The FTS5 engine core was already ~95% implemented from a prior session. This session:
1. Fixed the `max_inject` default inconsistency (code had 5, config had 3)
2. Added retired entry filtering in the FTS5 path (was missing)
3. Ran comprehensive smoke tests (9 tests, all pass)
4. Verified zero regressions in the full test suite (512 tests pass)

---

## Pre-existing Implementation (from prior session)

### FTS5 Engine Functions (lines 268-406)

| Function | Lines | Purpose |
|----------|-------|---------|
| `build_fts_index_from_index()` | 268-286 | Parse index.md into FTS5 in-memory table |
| `build_fts_query()` | 289-310 | Smart wildcard (compound=phrase, single=prefix) |
| `query_fts()` | 313-334 | FTS5 MATCH query executor |
| `apply_threshold()` | 337-360 | Top-K with 25% noise floor |
| `score_with_body()` | 363-410 | Hybrid scoring with path containment check |

### Shared Output Helper (lines 408-435)
- `_output_results()` -- Shared XML output between FTS5 and legacy paths

### main() Restructuring (lines 438-633)
- Config reading with `match_strategy` (line 497)
- FTS5 BM25 branch (lines 529-544)
- Legacy keyword fallback (lines 549-628)
- Both paths feeding into `_output_results()`

### Config Defaults (`assets/memory-config.default.json`)
- `max_inject: 3` (already set)
- `match_strategy: "fts5_bm25"` (already set)

---

## Changes Made in This Session

### 1. Fixed max_inject Default (lines 477, 488, 492, 494)

The code default was 5 but the config default was 3. Aligned all code defaults to 3:

```python
# Line 477 (was: max_inject = 5)
max_inject = 3  # Reduced from 5: FTS5 BM25 is more precise, fewer results needed

# Line 488 (was: retrieval.get("max_inject", 5))
raw_inject = retrieval.get("max_inject", 3)

# Line 492 (was: max_inject = 5)
max_inject = 3

# Line 494 (was: "using default 5")
"[WARN] Invalid max_inject value: {raw_inject!r}; using default 3"
```

### 2. Retired Entry Filtering in FTS5 Path (lines 395-398, 405)

The FTS5 path was missing retired entry filtering (the legacy path had it at line 595). Added:

```python
# In score_with_body(), after reading JSON (lines 395-398):
if data.get("record_status") == "retired":
    result["_retired"] = True
    result["body_bonus"] = 0
    continue

# Filter before re-ranking (line 405):
initial = [r for r in initial if not r.get("_retired")]
```

**Design choice:** Used explicit `_retired` flag + filter instead of the plan's `body_bonus = -100` approach. The penalty approach was incorrect because `score = score - (-100) = score + 100` makes the score *less negative* (worse), but the noise floor check uses `abs(score) >= noise_floor` -- so a large positive score (+100) would still pass the threshold. Explicit filtering is correct and unambiguous.

---

## Smoke Test Results

| # | Test | Description | Result |
|---|------|-------------|--------|
| T1 | FTS5: auth query | Matches JWT entry by title+tags | PASS |
| T2 | FTS5: database query | Matches Postgres entry by title+tags | PASS |
| T3 | FTS5: no match | Unrelated query returns nothing | PASS |
| T4 | Legacy: auth query | title_tags strategy works via config override | PASS |
| T5 | FTS5: retired excluded | Retired entry not in output | PASS |
| T6 | FTS5: body-only match | No output (by design -- FTS5 queries title+tags only) | PASS |
| T7 | Short prompt | Early exit, no output | PASS |
| T8 | Disabled retrieval | Config disables retrieval, no output | PASS |
| T9 | Body bonus ranking | JWT > OAuth when "refresh" matches JWT body | PASS |

### Full Regression Suite

```
502 passed, 10 xpassed in 21.61s
```

All 512 existing tests pass. Zero regressions.

---

## Architecture

```
User prompt
    |
    v
main() reads stdin, locates memory root, reads config
    |
    +-- match_strategy == "fts5_bm25" && HAS_FTS5?
    |       |
    |       YES: tokenize(prompt) [compound] -> build_fts_query()
    |            -> build_fts_index_from_index(index_path)
    |            -> score_with_body() [FTS5 MATCH + body bonus + retired filter]
    |            -> apply_threshold() -> _output_results()
    |       |
    |       NO: tokenize(prompt, legacy=True)
    |            -> score_entry() per entry + score_description()
    |            -> check_recency() deep check -> _output_results()
    |
    v
stdout: <memory-context> XML block
```

---

## Known Limitations

1. **FTS5 phrase != exact match**: `"user_id"` matches `user id` (space-separated) too
2. **CamelCase blind spot**: `userId` tokenizes as one token; `user_id` query won't match
3. **Body-only matches invisible**: Memories matching only in body (no title/tag) won't appear in auto-inject -- deferred to Session 3 (search skill)
4. **No recency bonus in FTS5 path**: BM25 scoring replaces the legacy recency bonus

---

## Files Modified

| File | Lines Changed | Type |
|------|---------------|------|
| `hooks/scripts/memory_retrieve.py` | 8 lines (4 max_inject defaults + 4 retired filtering) | Bug fix + security hardening |

Total file: 633 lines.
