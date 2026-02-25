# A-03: results[] Field Accuracy Verification

**Date:** 2026-02-25
**Auditor:** Claude Opus 4.6
**Scope:** `score_with_body()` data flow -> `retrieval.search` logging -> PoC #5 data quality
**Files examined:**
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_search_engine.py`
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_logger.py`
- `/home/idnotbe/projects/claude-memory/temp/p2-logger-schema.md`

---

## 1. Complete Data Flow Trace Through `score_with_body()`

### Step 1: Initial FTS5 Query (line 212)

```python
initial = query_fts(conn, fts_query, limit=top_k_paths * 3)
```

`query_fts()` (search_engine.py:244-265) returns a list of dicts, each with:
- `title` (str), `tags` (set), `path` (str), `category` (str), `score` (float -- BM25 rank, more negative = better)

At this point: **no `body_bonus`, no `raw_bm25`, no `_data`, no `_retired`** on any entry.

### Step 2: Path Containment Filter (lines 222-225)

```python
initial = [r for r in initial if _check_path_containment(...)]
```

Pure filter. No fields added or modified.

### Step 3: Retired Check + File Read Loop (lines 230-245)

This is the critical loop. It iterates over **ALL** remaining entries in `initial`:

```python
for result in initial:
    json_path = project_root / result["path"]
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if data.get("record_status") in ("retired", "archived"):
            result["_retired"] = True
            result["body_bonus"] = 0      # <-- body_bonus SET for retired
            continue
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Can't read file -- assume not retired, no body bonus
        result["body_bonus"] = 0          # <-- body_bonus SET for file-read failures
        continue

    # Successfully read, not retired
    result["_data"] = data                # <-- _data SET (body_bonus NOT set yet)
```

**After this loop, each entry in `initial` is in one of 3 states:**

| State | `body_bonus` | `_data` | `_retired` |
|-------|-------------|---------|------------|
| A: Retired/archived | `0` (set) | not set | `True` |
| B: File-read failure | `0` (set) | not set | not set |
| C: Active, file read OK | **NOT SET** | set (JSON data) | not set |

### Step 4: Filter Retired Entries (line 248)

```python
initial = [r for r in initial if not r.get("_retired")]
```

After this, only states B and C remain. The list is now re-indexed.

### Step 5: Body Extraction for Top-K (lines 252-259)

```python
for result in initial[:top_k_paths]:
    data = result.pop("_data", None)
    if data is not None:
        body_text = extract_body_text(data)
        body_tokens = tokenize(body_text)
        body_matches = query_tokens & body_tokens
        result["body_bonus"] = min(3, len(body_matches))
    # body_bonus already set to 0 for file-read failures above
```

For entries at index `0..top_k_paths-1`:

| Prior State | `data` from pop | Result |
|-------------|----------------|--------|
| B (file-read failure) | `None` (no `_data` was set) | `body_bonus` remains `0` (set in Step 3) |
| C (active, file OK) | JSON data object | `body_bonus` set to `min(3, len(body_matches))` -- could be 0, 1, 2, or 3 |

**All entries in `initial[:top_k_paths]` now have `body_bonus` set.** Correct.

### Step 6: Cleanup for Remaining Entries (lines 262-263)

```python
for result in initial[top_k_paths:]:
    result.pop("_data", None)
```

For entries at index `top_k_paths..end`:

| Prior State | What happens |
|-------------|-------------|
| B (file-read failure) | `_data` was never set; `pop("_data", None)` is a no-op. `body_bonus` = `0` (set in Step 3) |
| C (active, file OK) | `_data` is popped (removed). **`body_bonus` was NEVER set.** |

**THIS IS THE KEY FINDING.** Entries beyond `top_k_paths` that are in state C (active, file read succeeded) exit this block with **no `body_bonus` field at all**.

### Step 7: Re-rank With Body Bonus (lines 266-268)

```python
for r in initial:
    r["raw_bm25"] = r["score"]
    r["score"] = r["score"] - r.get("body_bonus", 0)  # More negative = better
```

- `raw_bm25` is set for **all** entries. Always accurate (copy of original BM25 score).
- `r.get("body_bonus", 0)` -- for state-C entries beyond `top_k_paths`, this returns `0` (the default), which is **functionally correct** (no body analysis was performed, so no bonus should be applied). But the field itself is **absent from the dict**.

### Step 8: apply_threshold() (line 270)

`apply_threshold()` (search_engine.py:272-300) sorts by `score` then applies noise floor (25% of best abs score). It does **not** add, remove, or modify `body_bonus` or `raw_bm25`. Results that survive the threshold retain whatever fields they had.

---

## 2. Analysis of body_bonus Correctness Per Entry Position

### Entries at index 0..top_k_paths-1 (after retired filter)

| Scenario | `body_bonus` present? | Value | Accurate? |
|----------|----------------------|-------|-----------|
| File read OK, body matches found | Yes | 1-3 | Yes -- reflects actual body keyword matches |
| File read OK, no body matches | Yes | 0 | Yes -- body was analyzed, no matches |
| File read failed (OSError, etc.) | Yes | 0 | **Ambiguous** -- indistinguishable from "analyzed, no matches" |

### Entries at index top_k_paths..end (after retired filter)

| Scenario | `body_bonus` present? | Value | Accurate? |
|----------|----------------------|-------|-----------|
| File read failed | Yes | 0 | **Ambiguous** -- same as above |
| File read OK (state C) | **NO** -- field absent | N/A | N/A |

When `r.get("body_bonus", 0)` is called at the logging site, absent fields default to `0`. So the **logged value** is `0`, which is **correct in the sense that no body bonus was applied** but **semantically ambiguous** (was body analyzed and found nothing, or was body never analyzed?).

---

## 3. Logging Call-Site Verification

### FTS5 Path: retrieval.search (lines 471-485)

```python
emit_event("retrieval.search", {
    "results": [
        {"path": r["path"], "score": r.get("score", 0),
         "raw_bm25": r.get("raw_bm25", r.get("score", 0)),
         "body_bonus": r.get("body_bonus", 0),
         "confidence": confidence_label(r.get("score", 0), _best_score)}
        for r in results
    ],
}, ...)
```

**Field-by-field analysis:**

#### `r.get("score", 0)` -- ALWAYS ACCURATE

After Step 7, every entry in `initial` (and therefore `results` after threshold) has `score` explicitly set. The `.get("score", 0)` default is never reached. Score = `raw_bm25 - body_bonus_applied`.

#### `r.get("raw_bm25", r.get("score", 0))` -- ALWAYS ACCURATE

After Step 7, every entry has `raw_bm25` explicitly set. The fallback chain `raw_bm25 -> score -> 0` is defensive but the first lookup always succeeds. `raw_bm25` = original BM25 rank from FTS5.

#### `r.get("body_bonus", 0)` -- CONDITIONALLY ACCURATE

Three cases in the output `results`:

1. **Entries that were in initial[:top_k_paths]**: `body_bonus` is explicitly set (0-3). Logged value matches reality. **Accurate.**

2. **Entries that were in initial[top_k_paths:] with file-read failure (state B)**: `body_bonus` is explicitly `0`. Logged value is `0`. **Accurate** (body was not analyzed due to failure, so 0 bonus is correct).

3. **Entries that were in initial[top_k_paths:] with successful file read (state C)**: `body_bonus` is **absent**. `r.get("body_bonus", 0)` returns `0`. **Functionally correct** (no bonus was applied in the score calculation), but **semantically misleading** for PoC analysis.

#### Can state-C entries beyond top_k_paths survive threshold and reach logging?

**YES.** Here's the reasoning:

- `top_k_paths` is set to `max(10, effective_inject)` (line 462). With default `max_inject=3` and no judge, `effective_inject=3`, so `top_k_paths=10`.
- `query_fts()` is called with `limit=top_k_paths * 3` = 30 entries.
- After path containment and retired filtering, there could be entries at positions 10-29.
- The noise floor in `apply_threshold()` keeps entries with `abs(score) >= 25% * abs(best_score)`. For a tight cluster of BM25 scores (common with OR queries on related terms), many entries beyond position 10 can survive.
- `apply_threshold()` caps results at `max_inject` (or `effective_inject` when judge is enabled), which is typically 3-15.
- **Crucially**: body bonus modifies `score` for top-K entries only. After re-ranking (Step 7), an entry originally at position 12 (no body bonus) could outrank an entry originally at position 5 (which got body bonus but still scored worse overall). But wait -- body bonus makes score **more negative** (better), so body-boosted entries can only move **up**. Entries without body analysis keep their raw BM25 score as their final score.

**Scenario where state-C entry reaches logging**: If `effective_inject > top_k_paths` (when judge `candidate_pool_size` exceeds the `max(10, effective_inject)` calculation -- but actually `top_k_paths` IS `max(10, effective_inject)`, so this only happens if... wait, let me re-check.)

```python
effective_inject = max(max_inject, judge_pool_size) if judge_enabled else max_inject
# ...
results = score_with_body(conn, fts_query, user_prompt,
                          max(10, effective_inject), memory_root, "auto",
                          max_inject=effective_inject)
```

So `top_k_paths = max(10, effective_inject)` and `max_inject = effective_inject`. The `apply_threshold` inside `score_with_body` limits results to `effective_inject`. Since `top_k_paths >= effective_inject`, threshold should never return more entries than `top_k_paths`.

**But there's an edge case**: `apply_threshold` also applies the noise floor **before** the limit. If fewer entries survive the noise floor than `effective_inject`, and the surviving entries are all within `top_k_paths`, then no state-C-beyond-top_k entries reach logging.

**However**, consider this: after re-ranking in Step 7, the sort order changes. Entries originally at index `top_k_paths` or beyond (with `body_bonus` absent, so score = raw_bm25 unchanged) could end up in the final top-N if their raw BM25 was strong. But apply_threshold sorts by the **modified score**, and the modified score for beyond-top_k entries equals their raw BM25 (since body_bonus defaults to 0 in the subtraction). For top-K entries, their score = raw_bm25 - body_bonus, which is more negative (better) when body_bonus > 0. So body-boosted entries always rank ahead of or equal to their original position. Non-body-analyzed entries keep their original relative ranking.

**The question is**: can an entry originally at position `top_k_paths` (e.g., 10) survive the noise floor and land within the `effective_inject` cap?

If `effective_inject = top_k_paths` (the common case), then `apply_threshold` returns at most `effective_inject = top_k_paths` entries. After re-ranking, the top `top_k_paths` entries would include all body-analyzed entries that got boosted, potentially pushing some originally-within-top_k entries down. But entries beyond original-top_k can only enter the final list if they displace entries that had their body analyzed.

Actually, wait. Let me think about this more carefully. After Step 7:
- Entries at original positions 0..9 have body_bonus applied (score = raw_bm25 - body_bonus)
- Entries at original positions 10+ have score = raw_bm25 (unchanged)

After `apply_threshold` sorts by score (most negative first):
- An entry at original position 11 with raw_bm25 = -5.0 (score = -5.0) would rank above an entry at original position 3 with raw_bm25 = -4.0 and body_bonus = 0 (score = -4.0).
- This is **expected** -- the entry at position 11 simply has a better BM25 match.

But wait, that can't happen -- the original FTS5 query was `ORDER BY rank LIMIT 30`, so entry at original FTS5 position 11 must have a worse (less negative) BM25 rank than entry at position 3. Unless...

**No.** The FTS5 results come back ordered by BM25 rank. The path containment filter and retired filter can remove entries, shifting indices. So after filtering:
- Original FTS5 position 3 might be retired (removed)
- Original FTS5 position 11 is now at position 8 in `initial` after filtering

This means entries that were originally beyond `top_k_paths` in FTS5 output could be within `top_k_paths` after retired filtering. But in the code, body extraction uses the **post-filter** index:

```python
initial = [r for r in initial if not r.get("_retired")]  # line 248
for result in initial[:top_k_paths]:  # line 252 -- uses post-filter index
```

So this is actually handled correctly. The index used for body extraction is the post-filter list, not the original FTS5 ranking.

**However**, there's still a subtle issue. In Step 3 (lines 230-245), `_data` is set for **all** non-retired, non-error entries, regardless of their position relative to `top_k_paths`. But the position check for body extraction happens at line 252, using the post-filter index. Entries at post-filter positions `top_k_paths..end` have `_data` set but it gets popped at line 263 without body analysis. These are state-C entries.

**Can state-C entries reach the final logged results?** Only if:
1. `apply_threshold` returns more than `top_k_paths` entries.
2. But `max_inject=effective_inject` and `top_k_paths=max(10, effective_inject)`, so `top_k_paths >= effective_inject`.
3. `apply_threshold` returns at most `effective_inject` entries.
4. Therefore, it returns at most `top_k_paths` entries.

**Conclusion on reachability**: Under the current calling convention (line 461-463), state-C entries beyond `top_k_paths` **cannot reach the logging call**. The `max_inject` parameter to `apply_threshold` ensures the result list is capped at `effective_inject <= top_k_paths`.

**BUT**: This is only true because of the specific relationship `max_inject=effective_inject` and `top_k_paths=max(10, effective_inject)`. If anyone changes the calling convention (e.g., passes a different `max_inject` to `score_with_body`), the invariant breaks.

---

## 4. Legacy Path Analysis (lines 668-688)

```python
top_list = []
for score, _, entry in top_entries:
    entry["score"] = score
    top_list.append(entry)

emit_event("retrieval.inject", {
    "injected_count": len(top_list),
    "engine": "title_tags",
    "results": [
        {"path": r["path"],
         "confidence": confidence_label(r.get("score", 0), _inj_best)}
        for r in top_list
    ],
}, ...)
```

The legacy path does **not** emit a `retrieval.search` event with `raw_bm25` or `body_bonus` fields. It only emits `retrieval.inject` with `path` and `confidence`. This is consistent with the legacy path not having body analysis or BM25 scoring -- no `body_bonus` or `raw_bm25` fields exist on these entries.

**However**: The legacy path is missing a `retrieval.search` event entirely. The only logging for legacy results is in `retrieval.inject`. There's a `retrieval.search` event at line 560 but it only logs `engine: "title_tags"` and `reason: "fts5_unavailable"` -- no results array. This means PoC #5 analysis is **impossible** for legacy-path queries.

This is a known limitation (FTS5 is the primary path), not a bug per se, but worth noting for completeness.

---

## 5. Assessment: Is This a Real Bug for PoC #5?

### Severity: LOW -- No Functional Bug, Minor Data Quality Concern

**The hypothesized bug does not manifest in practice** under current calling conventions because:

1. `top_k_paths >= effective_inject` is enforced by the calling code (line 461-463).
2. `apply_threshold()` caps results at `effective_inject`.
3. Therefore, all entries in the logged `results[]` array have been body-analyzed (or had file-read failures with explicit `body_bonus=0`).

### Remaining Data Quality Issues (Non-Blocking for PoC #5)

#### Issue 1: "Analyzed with 0 matches" vs "File-read failure" Ambiguity

Both cases produce `body_bonus: 0` in logged data. For PoC #5 precision analysis, this means:
- An entry with `body_bonus: 0` might have genuinely had no body keyword overlap (accurate signal)
- Or the JSON file was unreadable (no signal -- should perhaps be excluded from analysis)

**Impact on PoC #5**: Minimal. File-read failures are rare in normal operation (the file was just indexed, so it should exist). When they occur, `body_bonus: 0` is defensively correct -- no bonus should be applied for unreadable files.

**Potential improvement**: Add a `body_analyzed: true/false` field to distinguish the two cases. Estimated: ~5 LOC.

#### Issue 2: "Not analyzed (beyond top-K)" vs "Analyzed with 0 matches" Ambiguity

State-C entries beyond `top_k_paths` have no `body_bonus` field, which defaults to `0` in logging. While these entries currently don't reach the logging call (see Section 3), the structural ambiguity exists in the `score_with_body()` return value.

**Impact on PoC #5**: None currently (entries don't reach logging). Fragile invariant -- could become a real bug if calling conventions change.

**Potential improvement**: Explicitly set `body_bonus = 0` for entries beyond `top_k_paths` after popping `_data`. Estimated: ~2 LOC.

#### Issue 3: Fragile Invariant

The guarantee that state-C entries don't reach logging depends on `top_k_paths >= effective_inject`, which is currently enforced only by the specific `max(10, effective_inject)` expression at the call site. There are no assertions or documentation of this invariant.

---

## 6. Recommended Code Fixes

### Fix 1 (Defensive, ~2 LOC): Explicitly set body_bonus for beyond-top_k entries

In `score_with_body()`, after line 263:

```python
# Current:
for result in initial[top_k_paths:]:
    result.pop("_data", None)

# Proposed:
for result in initial[top_k_paths:]:
    result.pop("_data", None)
    if "body_bonus" not in result:
        result["body_bonus"] = 0
```

This makes the `body_bonus` field **always present** on every entry returned from `score_with_body()`, eliminating the `.get("body_bonus", 0)` ambiguity at the logging site.

**Priority**: LOW (defensive, no functional change under current calling conventions)

### Fix 2 (Optional, ~5 LOC): Add `body_analyzed` flag for PoC precision

For entries within `top_k_paths`:

```python
for result in initial[:top_k_paths]:
    data = result.pop("_data", None)
    if data is not None:
        body_text = extract_body_text(data)
        body_tokens = tokenize(body_text)
        body_matches = query_tokens & body_tokens
        result["body_bonus"] = min(3, len(body_matches))
        result["_body_analyzed"] = True
    else:
        result["_body_analyzed"] = False
```

And in the logging call site (optional, only if PoC #5 needs this granularity):

```python
"body_analyzed": r.get("_body_analyzed", False),
```

**Priority**: VERY LOW (PoC #5 can function without this distinction)

### Fix 3 (Documentation): Document the top_k_paths >= effective_inject invariant

Add a comment at the `score_with_body()` call site:

```python
# INVARIANT: top_k_paths >= effective_inject ensures all entries returned by
# apply_threshold() have had body analysis attempted. Do not violate this
# relationship or body_bonus values become unreliable.
```

**Priority**: LOW (prevents future regressions)

---

## 7. Summary

| Aspect | Assessment |
|--------|-----------|
| `raw_bm25` accuracy | Always correct -- explicitly set for all entries in Step 7 |
| `score` accuracy | Always correct -- raw_bm25 minus applied body_bonus |
| `body_bonus` accuracy in logged results | Correct under current calling conventions. Absent field defaults to 0 at logging site, which is functionally correct |
| State-C entries reaching logging | Cannot happen under current `top_k_paths >= effective_inject` invariant |
| PoC #5 impact | **No blocking issue.** Data quality is sufficient for BM25 precision analysis |
| Bug classification | **Not a real bug** -- defensive improvement opportunity. The hypothesized issue exists structurally but is prevented from manifesting by the calling convention |
| Legacy path | No `retrieval.search` results logging -- PoC #5 is FTS5-only by design |

**Verdict**: The A-03 hypothesis is **partially confirmed structurally** (state-C entries beyond top_k_paths do lack explicit `body_bonus`) but **does not manifest as a runtime data quality issue** due to the `top_k_paths >= effective_inject` relationship enforced at the call site. Fix 1 (2 LOC) is recommended as a defensive hardening measure.
