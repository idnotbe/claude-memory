# Session 2 Architecture Review: FTS5 Engine Core

**Reviewer:** arch-reviewer (Claude Opus 4.6)
**Date:** 2026-02-21
**File:** `hooks/scripts/memory_retrieve.py` (lines 264-633)
**Verdict:** APPROVE WITH CHANGES

---

## Overall Assessment

The FTS5 engine implementation is well-structured, closely follows the plan, and preserves all security invariants. The code is clean, the function boundaries are clear, and the legacy fallback path is untouched. Two medium-severity issues and several minor items warrant attention before merging.

---

## 1. Plan Alignment

### Checklist Coverage

| Plan Item | Status | Notes |
|-----------|--------|-------|
| `build_fts_index_from_index()` | DONE | Lines 268-286. Matches plan spec. |
| `build_fts_query()` | DONE | Lines 289-310. Smart wildcard per Decision #3. |
| `query_fts()` | DONE | Lines 313-334. Clean executor. |
| `apply_threshold()` | DONE | Lines 337-360. Pure Top-K with 25% noise floor. |
| `score_with_body()` | DONE | Lines 363-412. Hybrid scoring with path containment. |
| FTS5 fallback routing | DONE | Line 535: `if HAS_FTS5 and match_strategy == "fts5_bm25"` |
| Config branch (`match_strategy`) | DONE | Lines 484, 503. Defaults to `"fts5_bm25"`. |
| Config default update | DONE | `assets/memory-config.default.json` updated. |
| Preserve `score_entry()` | DONE | Unchanged at line 94. |
| Preserve path containment checks | DONE | Both FTS5 (line 388) and legacy (line 596) paths. |
| Smoke test | DONE | 5/5 FTS5 + 5/5 legacy queries pass. |

### Deviations from Plan (all justified)

1. **Path resolution fix** (line 380): Plan had `memory_root / result["path"]` which would double paths. Implementation correctly uses `project_root = memory_root.parent.parent`. This is a bug fix.

2. **Retired entry check** (lines 395-397): Not in plan but adds defensive filtering of retired entries in the FTS5 path. Good improvement.

3. **`_output_results` extraction** (lines 415-441): Plan suggested "extract if possible." Implemented as shared function eliminating output format divergence risk. Good.

4. **Score key naming**: Plan used `r["final_score"]`; implementation mutates `r["score"]` in-place (line 410). Functionally equivalent but loses the original BM25 score for debugging. Minor.

**Verdict: Full plan alignment. No unauthorized deviations.**

---

## 2. Code Quality

### Strengths
- Clean function boundaries with single responsibilities
- Docstrings on all new functions explaining purpose, inputs, outputs
- Consistent use of type hints (`Path`, `sqlite3.Connection`, `list[dict]`)
- `try/finally` for connection cleanup (line 543-544)
- Security comments inline at every containment check

### Issues

**[M1] In-place mutation of result dicts in `score_with_body`** (line 410)
```python
r["score"] = r["score"] - r.get("body_bonus", 0)  # More negative = better
```
This mutates the original dict, losing the raw BM25 score. For Session 6 benchmarking and debugging, preserving the original score would be valuable. The plan specified `r["final_score"]` as a separate key.

**Recommendation:** Store as `r["raw_bm25"] = r["score"]` before mutation, or use a separate key `r["final_score"]`. Low priority -- acceptable for S2, worth fixing in S3 extraction.

**[L1] `FileNotFoundError` is redundant** (line 404)
```python
except (FileNotFoundError, json.JSONDecodeError, OSError):
```
`FileNotFoundError` is a subclass of `OSError`. Harmless but slightly noisy. Not worth changing.

---

## 3. Edge Cases

### Tested via code inspection and SQLite probes:

| Scenario | Handling | Verdict |
|----------|----------|---------|
| Empty index.md | `entries` list empty -> `sys.exit(0)` at line 529 | OK |
| No FTS5 matches | `query_fts` returns empty list -> `apply_threshold` returns `[]` -> no output | OK |
| All results below noise floor | `apply_threshold` filters all -> empty list | OK |
| `max_inject == 0` | Exits at line 515-516 | OK |
| Invalid `match_strategy` | Falls through to legacy path (neither `fts5_bm25` match nor `HAS_FTS5` true) | OK |
| No valid query tokens | `build_fts_query` returns `None` -> `sys.exit(0)` at line 550 | OK |
| Malformed index lines | `parse_index_line` returns `None` -> skipped | OK |
| JSON file missing | `FileNotFoundError` caught -> `body_bonus = 0` | OK |
| Corrupt JSON file | `json.JSONDecodeError` caught -> `body_bonus = 0` | OK |

### Edge case concern: **[M2] Retired entries beyond `top_k_paths`**

In `score_with_body()`, only the top `top_k_paths` (10) entries get JSON-read for retired status checks (line 384). Entries ranked 11-30 from the initial FTS5 results skip this check. If several top candidates are retired and filtered out at line 408, unchecked entries can slide into the final results via `apply_threshold`.

**Severity:** Medium. In practice, index.md is rebuilt from active entries only, so stale retired entries in the index are rare. But if the index is stale (e.g., manual edit, failed rebuild), retired memories could leak into context.

**Recommendation:** Either:
- (a) Expand the JSON loop to cover all `initial` results (reads ~30 small JSON files, adds ~5-10ms), or
- (b) Document as accepted limitation and rely on index rebuild to keep index clean.

**My recommendation: (b) for S2, (a) for S3** when the function is extracted and can be tuned per mode (auto=strict, search=lenient).

---

## 4. Config Migration

| Scenario | Behavior | Verdict |
|----------|----------|---------|
| No config file | Defaults: `max_inject=3`, `match_strategy="fts5_bm25"` | OK |
| Config without `match_strategy` | `retrieval.get("match_strategy", "fts5_bm25")` -> FTS5 | OK (silent upgrade) |
| Config with `match_strategy: "title_tags"` | Routes to legacy path | OK (explicit revert) |
| Config with `max_inject: 5` (old default) | Honored, clamped to [0,20] | OK |
| Config with `max_inject: 3` (new default) | Honored | OK |
| Config with invalid `max_inject` | Falls back to 3 with stderr warning | OK |

**Verdict: Clean migration path. Existing users get silent upgrade. Explicit revert supported.**

---

## 5. Fallback Path

The legacy keyword path (lines 552-629) is preserved unchanged from the pre-FTS5 implementation. Verified:

- `tokenize(user_prompt, legacy=True)` at line 556 uses `_LEGACY_TOKEN_RE`
- `score_entry()` and `score_description()` called at lines 569, 575
- `check_recency()` called at line 599
- Path containment checks at lines 596-598
- Output via shared `_output_results()` at line 629

**No risk of regression.** The only change to the legacy path is using `_output_results()` instead of inline output, which is a pure refactoring (same logic extracted to function).

**Fallback triggers correctly:**
- `HAS_FTS5 == False` -> legacy path
- `match_strategy == "title_tags"` -> legacy path
- `match_strategy == "fts5_bm25"` but `HAS_FTS5 == False` -> legacy path (correct, both conditions must be true)

---

## 6. API Consistency for S3+

### Function signatures assessment for extraction to `memory_search_engine.py`:

| Function | Signature | S3 Reusability |
|----------|-----------|----------------|
| `build_fts_index_from_index(index_path: Path) -> Connection` | Coupled to file format | REFACTOR in S3 |
| `build_fts_query(tokens: list[str]) -> str \| None` | Pure, reusable | GOOD |
| `query_fts(conn, fts_query, limit) -> list[dict]` | Pure, reusable | GOOD |
| `apply_threshold(results, mode) -> list[dict]` | Pure, reusable | GOOD |
| `score_with_body(conn, fts_query, user_prompt, top_k_paths, memory_root, mode)` | Coupled to memory_root path resolution | REFACTOR in S3 |

**S3 extraction plan:**
- `build_fts_index_from_index` should be refactored to `build_fts_index(entries: list[dict]) -> Connection` -- the caller parses index.md and passes structured data. This also resolves the double-read issue.
- `score_with_body` needs the path resolution decoupled. S3 can pass `project_root` explicitly.
- `build_fts_query`, `query_fts`, `apply_threshold` are ready for extraction as-is.

**S5 (confidence annotations):** `apply_threshold` returns dicts with `score` key. Confidence annotations can be computed from the score distribution. No blocking issues.

---

## 7. Performance

### Double-read of index.md

The FTS5 path reads index.md twice:
1. Lines 519-526: Parsed into `entries` list (only used for emptiness check at line 529)
2. Line 539: `build_fts_index_from_index(index_path)` reads and parses again

The `entries` list is never used in the FTS5 branch.

**Impact:** For a 500-entry index (~25KB), the extra read adds <1ms. The OS page cache ensures the second read hits memory. Negligible in practice.

**Recommendation:** Defer to S3 extraction. When `build_fts_index_from_index` is refactored to accept `list[dict]`, the caller can parse once and route to either FTS5 or legacy.

### Estimated latency (500 entries)

| Phase | Estimated Time |
|-------|---------------|
| Read + parse index.md | ~2ms |
| Build FTS5 in-memory table | ~3ms |
| FTS5 MATCH query | ~1ms |
| Read 10 JSON files (body scoring) | ~10ms |
| Threshold + output | ~1ms |
| **Total** | **~17ms** |

Well within the ~50ms budget for auto-inject.

---

## 8. External Model Opinions

### Gemini (via pal clink)

**High severity:**
1. Compound token wildcard logic -- claims `"user_id"` without wildcard breaks partial matches. **My assessment: DISAGREE.** This is intentional design (Decision #3). Users search for `user_id`, not `user_i`. The plan explicitly chose exact phrase for compounds to avoid the false positive rate that R2-adversarial found (75% false positives with `"user_id"*` matching "user identity"). Gemini's suggestion to apply wildcards uniformly contradicts the plan's design decision.

2. Retired entry leak beyond `top_k_paths` -- **AGREE.** This is [M2] above. Worth tracking.

**Medium severity:**
3. Double-read of index.md -- **AGREE.** This is the performance issue above. Defer to S3.
4. Module extraction readiness -- **AGREE.** Refactor `build_fts_index_from_index` to accept `list[dict]` in S3.

**Low severity:**
5. BM25 noise floor with outlier scores -- **PARTIALLY AGREE.** The concern about outlier best scores aggressively pruning partial matches is valid in theory, but with Top-K=3 and max 30 candidates, the noise floor is a safety net, not the primary filter. Session 6 benchmarks will reveal if this needs adjustment.

### Codex (via pal clink)

**Medium severity:**
1. FTS5 tokenizer splits on `_`, `.`, `-` -- **ACKNOWLEDGED.** This is Known Limitation #1 in the implementation report. The plan explicitly documented this as accepted behavior. However, Codex raises a valid point about setting `tokenchars` in the FTS5 table definition. This would make compound matching truly exact but changes tokenization behavior globally. **Recommendation: Evaluate in S6 benchmarks.**

2. Noise floor edge cases -- Same as Gemini's #5. **PARTIALLY AGREE.**

**Low severity:**
3. Double-read -- Same as Gemini's #3. **AGREE.**
4. In-place mutation -- Same as my [M1]. **AGREE.**
5. `memory_root.parent.parent` brittleness -- **AGREE** in principle, but this pattern is used identically in the legacy path (line 588) and throughout the codebase. Changing it would be a cross-cutting concern, not an S2 issue.

### Vibe Check Results

The vibe check confirmed the implementation is well-aligned with the plan. Key agreement points:
- Double-read is negligible, defer to S3
- Retired entry gap is real but low-risk given index rebuild guarantees
- Function signatures are clean enough for S3 extraction
- No feature creep or over-engineering detected

---

## 9. Summary of Findings

### Must-fix (before merge): None

### Should-fix (before S3):

| ID | Severity | Issue | Location | Recommendation |
|----|----------|-------|----------|----------------|
| M1 | Medium | In-place score mutation loses raw BM25 | Line 410 | Preserve `r["raw_bm25"]` before mutation |
| M2 | Medium | Retired entries beyond `top_k_paths` unchecked | Lines 384, 408 | Expand loop or document as limitation |

### Nice-to-have (S3 or later):

| ID | Severity | Issue | Location | Recommendation |
|----|----------|-------|----------|----------------|
| L1 | Low | Double-read of index.md | Lines 519-526, 539 | Refactor in S3: parse once, pass `list[dict]` |
| L2 | Low | `build_fts_index_from_index` coupled to file format | Line 268 | Refactor to `build_fts_index(entries)` in S3 |
| L3 | Low | FTS5 tokenchars for true compound matching | Line 276 | Evaluate adding `tokenchars` in S6 benchmarks |
| L4 | Low | Noise floor could over-prune with outlier scores | Line 357 | Monitor in S6; add absolute floor if needed |

---

## 10. Final Verdict

**APPROVE WITH CHANGES**

The implementation is solid, well-aligned with the plan, and preserves all security invariants. The two medium-severity items (M1, M2) should be tracked for S3 but do not block S2 merge. The FTS5 engine functions have clean boundaries that will extract well into `memory_search_engine.py`. No regressions to the legacy path. Config migration is seamless.

The external model reviews (Gemini, Codex) raised valid concerns about FTS5 tokenizer behavior and retired entry leakage, but the tokenizer concern was already documented as a known limitation in the plan, and the retired entry issue is mitigated by index rebuild guarantees. Both items should be revisited in S6 benchmarking.
