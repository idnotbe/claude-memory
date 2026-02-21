# Verification Round 1: Practical Feasibility

**Verifier:** verifier-practical
**Date:** 2026-02-20
**Input:** rd-05-consolidated-plan.md (consolidated plan)
**Method:** Empirical testing on target WSL2 system + Gemini 3.1 Pro cross-validation

---

## Summary Verdict

The plan is **feasible with 3 blocking issues** that must be resolved before implementation. The 3-day schedule is realistic for a skilled developer IF the tokenchars issue is addressed upfront. FTS5 works well on this system, performance is better than claimed, but the tokenization strategy has a critical tradeoff the plan missed.

| Area | Rating | Notes |
|------|--------|-------|
| Schedule Reality | YELLOW | Realistic but tight; test rewrite underestimated |
| Code Snippets | RED | tokenchars strategy has critical tradeoff |
| Edge Cases | YELLOW | Most handled; 2 gaps identified |
| Test Compatibility | YELLOW | 42% of tests break; rewrite effort underestimated |
| Skill Design | GREEN | Sufficient for Claude to use |
| Migration Risk | GREEN | Low; rollback path is viable |
| Performance | GREEN | Better than claimed; validated empirically |

---

## 1. Schedule Reality Check

### Rating: YELLOW (realistic but tight)

**Is the 3-day schedule realistic?**
Yes, for the core implementation. The LOC estimates (425-475) are reasonable. However:

**Underestimated tasks:**

| Task | Plan Estimate | Realistic Estimate | Delta |
|------|--------------|-------------------|-------|
| Test rewrite | Implied "update" | 14 tests break, 6 unclear = significant rewrite | +4-6 hours |
| FTS5 query escaping edge cases | "Fixed" | Requires careful handling (see Section 2) | +2-3 hours |
| Body content extraction | ~60 LOC | Correct, but needs test coverage too | +1-2 hours |
| Phase 1 validation | "Manual 5-10 queries" | Need automated regression tests before Phase 2 | +2-3 hours |

**Hidden work not in the plan:**
1. **Tokenizer decision resolution** -- The plan says "use tokenchars" but Gemini and empirical testing both show this is wrong (see Section 2). Resolving this impacts both Phase 1 and Phase 2 code.
2. **Conftest fixtures** -- `conftest.py` helpers like `build_enriched_index()` need updating if index.md format changes.
3. **Error path for FTS5 unavailable** -- Plan says "error loudly" but no code snippet provided.

**Gemini 3.1 Pro assessment:**
> "3 days is highly realistic for replacing a ~400 LOC keyword system with FTS5. However, three things are typically underestimated: disk I/O bottleneck, FTS5 compilation availability on minimal distros, and BM25 weight tuning."

**Revised realistic schedule:**
- Day 1: Phase 1 (tokenizer + body content) -- achievable
- Day 2: Phase 2 core (FTS5 engine) -- achievable IF tokenchars decision is pre-resolved
- Day 3 AM: Test rewrite + threshold tuning -- TIGHT
- Day 3 PM: Phase 3 (search skill) -- may slip to Day 4

### Recommendation
Add a half-day buffer. Call it "3.5 focused days" or "3 full days + 1 morning."

---

## 2. Code Snippet Validation

### Rating: RED (blocking issue in tokenchars strategy)

### 2a. CRITICAL: tokenchars '_.-' Breaks Substring/Suffix Matching

**Empirical test on this system:**

| Query | With tokenchars | Without (default) | Winner |
|-------|----------------|-------------------|--------|
| `"user_identifier"` (exact) | 1 match | 1 match | TIE |
| `"identifier"` (substring) | 0 MISS | 1 match | DEFAULT |
| `"user"` (prefix) | 0 MISS | 1 match | DEFAULT |
| `"React.FC"` (exact) | 1 match | 1 match | TIE |
| `"FC"` (suffix) | 0 MISS | 1 match | DEFAULT |
| `"React"` (prefix) | 0 MISS | 1 match | DEFAULT |
| `"auth-service"` (exact) | 1 match | 1 match | TIE |
| `"service"` (suffix) | 0 MISS | 1 match | DEFAULT |
| `"auth"` (prefix) | 0 MISS | 1 match | DEFAULT |

**The tradeoff:**
- `tokenchars='_.-'` treats `user_id` as ONE token. Searching for `"id"` alone returns ZERO results. Only prefix wildcard (`"user_id"*`) works.
- Default `unicode61` splits `user_id` into `user` + `id`. Searching for either `"user"` or `"id"` works. Quoted phrase `"user_id"` also works (matches `user` immediately followed by `id`).

**Gemini 3.1 Pro independently confirmed:**
> "If you add `_.-` to tokenchars, FTS5 treats `user_identifier` as a single, monolithic token. If a developer searches for just `identifier` or `FC`, FTS5 will return ZERO results because it only matches prefixes, severely breaking expected fuzzy-search behavior for coding terms."

**Gemini's recommendation:** Drop custom tokenchars entirely. Use default `unicode61`. Quote multi-part terms as phrases instead. This gives BOTH exact compound matching AND substring matching.

**Pipeline test with default unicode61 (validated on this system):**

| User Query | FTS Query Built | Results |
|------------|----------------|---------|
| `user_id` | `"user_id"*` | doc1 (user_id doc) -- CORRECT |
| `React.FC` | `"react.fc"*` | doc2 (React.FC doc) -- CORRECT |
| `auth-service` | `"auth-service"*` | doc3 (auth-service doc) -- CORRECT |
| `authentication` | `"authentication"*` | doc1 (auth doc) -- CORRECT |
| `auth` | `"auth"*` | doc3, doc1 -- CORRECT |
| `component` | `"component"*` | doc2 -- CORRECT |

The key insight: with default `unicode61`, the Python-side tokenizer `[a-z0-9][a-z0-9_.-]*[a-z0-9]` preserves compound terms, and when quoted in FTS5, they become phrase queries that match the component parts adjacently. Best of both worlds.

### DECISION REQUIRED
**Drop `tokenchars='_.-'` from the plan. Use default `unicode61` tokenizer.** The Python-side regex still preserves compound tokens; FTS5 phrase matching (`"user_id"`) handles them correctly by matching adjacent sub-tokens.

### 2b. FTS5 Query Escaping: Works But Needs One Fix

The plan's `build_fts_query()` uses `re.sub(r'[^a-z0-9_.\-]', '', t.lower())` to clean tokens. This works for most cases BUT:

- Raw `React.FC` in a query becomes token `react.fc` via the new Python regex
- FTS5 query `"react.fc"*` works as a phrase query with default unicode61 -- VERIFIED
- Raw `auth-service` becomes token `auth-service`
- FTS5 query `"auth-service"*` works -- VERIFIED
- Raw `.env` becomes just `env` (leading dot stripped by regex) -- ACCEPTABLE

**One fix needed:** The plan's regex `[^a-z0-9_.\-]` should also strip leading/trailing delimiters to avoid empty tokens or FTS5 phrase-boundary issues: `cleaned = cleaned.strip('_.-')` after the regex.

### 2c. Proposed Code Snippets: Compile Check

```
Phase 1 tokenizer regex:   PASSES (re.compile verified, no ReDoS risk)
Phase 1 body extraction:   PASSES (dict traversal, no imports needed)
Phase 2 FTS5 CREATE:       PASSES (verified on this WSL2 system)
Phase 2 build_fts_query:   PASSES (with default unicode61)
Phase 2 query_fts:         PASSES (BM25 scores are negative, plan handles correctly with abs())
```

---

## 3. Edge Cases Missing

### Rating: YELLOW (2 gaps found)

**Tested and PASSING:**

| Edge Case | Result |
|-----------|--------|
| Empty memory corpus | FTS5 MATCH returns 0 rows. Script exits cleanly. |
| Single memory | BM25 scores work (IDF is defined for N=1). |
| All memories match | 50% relative cutoff correctly filters. With 25 docs all matching "test", score range is narrow, ~60% survive cutoff. |
| Unicode in titles/body | FTS5 unicode61 handles accented chars (cafe, resume) correctly. |
| Very long body (50KB) | INSERT succeeds. Query matches. Performance unaffected. |
| Stop-word-only query | Produces empty token list. Script exits cleanly. |

**Gaps found:**

### Gap 1: BM25 Negative Score Math (MEDIUM)
BM25 scores from SQLite are **negative** (e.g., -5.75). The plan's code uses `abs()` for comparisons but `ORDER BY score` for sorting. Since FTS5 returns lower (more negative) = better match, `ORDER BY score` works correctly (most negative first). But the 50% cutoff code has a subtle issue:

```python
best_abs = abs(results[0][5])   # e.g. abs(-5.75) = 5.75
cutoff = best_abs * 0.50        # 2.875
filtered = [r for r in results if abs(r[5]) >= cutoff]
```

This is correct, but only because `ORDER BY score` puts the most-negative (best) first. If the ORDER ever changes, this breaks silently. **Recommendation:** Add a comment explaining this invariant, or explicitly use `ORDER BY score ASC`.

### Gap 2: Corpus With Only Retired Entries (LOW)
If ALL memory files have `record_status="retired"`, the current plan reads all files for FTS5 indexing but then filters retired entries post-query. This wastes build time. **Recommendation:** Filter retired entries BEFORE inserting into FTS5.

---

## 4. Existing Test Compatibility

### Rating: YELLOW (significant rewrite needed)

**Analysis of 33 existing tests:**

| Status | Count | Percentage |
|--------|-------|-----------|
| Reusable as-is | 13 | 39% |
| Will break | 14 | 42% |
| Unclear (depends on design decisions) | 6 | 18% |

**Tests that definitely break:**
- All 6 `TestScoreEntry` tests (scoring function replaced by BM25)
- All 5 `TestDescriptionScoring` tests (function removed)
- 1 `TestParseIndexLine` test (if index.md role changes)
- 1 `TestCheckRecency` test (if recency is absorbed into FTS5)
- 1 `TestRetrieveIntegration` backward compat test

**Tests definitely reusable:**
- `TestTokenize` (3 tests) -- tokenize() stays, test assertions need minor updates
- `TestCategoryPriority` (1 test)
- Most `TestRetrieveIntegration` tests (6 tests) -- integration tests that check output format

**New tests needed:**
1. FTS5 index build + query (unit)
2. `build_fts_query()` escaping edge cases (unit)
3. BM25 scoring threshold/cutoff behavior (unit)
4. Body content extraction per category (unit)
5. End-to-end with FTS5 replacing keyword scoring (integration)
6. Fallback behavior when FTS5 unavailable (integration)
7. Performance regression test (500 docs < 100ms)

**Estimated test rewrite effort:** 4-6 hours (not included in plan's schedule)

---

## 5. Skill Design Completeness

### Rating: GREEN

The plan's `/memory:search` skill design is sufficient:
- Progressive disclosure (compact list -> Read tool) is clean
- CLI interface (`--query`, `--root`, `--mode`) is standard
- Shared engine extraction is straightforward

**Minor concern:** The skill frontmatter triggers list should include more coding-oriented terms like "find memory", "search memory", "look up", "recall" to improve trigger reliability beyond the claimed 67%.

---

## 6. Migration Risk

### Rating: GREEN

**Rollback path:** Config key `match_strategy: "title_tags"` (legacy) vs `"fts5_bm25"` (new). This is clean.

**Mid-session behavior:** Retrieval hook runs per-prompt via subprocess. Changing the script mid-session takes effect on the next prompt. No state leakage.

**Data migration:** None needed. FTS5 reads existing JSON files directly. No schema changes.

**One concern:** If a user has the plugin auto-update and the FTS5 import fails (missing extension), they lose ALL retrieval until they manually set `match_strategy: "title_tags"`. The plan should include an automatic fallback: try FTS5, if ImportError/OperationalError, fall back to keyword silently with a stderr warning.

---

## 7. Performance Validation

### Rating: GREEN (better than claimed)

**Empirical benchmarks on this WSL2 system (Linux filesystem):**

| Docs | File Read | FTS5 Build | Query (avg 5) | TOTAL |
|------|-----------|-----------|---------------|-------|
| 50 | 1.4ms | 1.9ms | 0.2ms | **4.7ms** |
| 100 | 3.3ms | 2.6ms | 0.2ms | **8.0ms** |
| 200 | 7.7ms | 3.3ms | 0.5ms | **13.2ms** |
| 500 | 18.4ms | 7.7ms | 0.9ms | **31.1ms** |
| 1000 | 14.0ms* | - | - | **~15ms** |

*FTS5-only benchmark (no disk I/O) for 1000 docs.

**Plan claimed:** 500 docs -> ~35ms. **Actual:** 31.1ms including full disk I/O. **VALIDATED.**

**Gemini's concern about disk I/O:**
> "Reading 500 files from disk takes significantly longer (often 20-50ms)."

Our benchmark shows 18.4ms for 500 files on Linux filesystem, within acceptable range. WSL2 `/mnt/c/` would be 10-50x slower but the plan already documents this.

**Key finding:** Full pipeline (read + build + query) for the expected corpus size (<500 docs) is **well under 100ms** on Linux filesystem. No lazy-loading needed for this use case (retrieval hook fires on every prompt anyway).

---

## Blocking Issues (Must Fix Before Implementation)

### BLOCKER 1: Drop tokenchars (RED)
**What:** Change FTS5 tokenizer from `unicode61 tokenchars '_.-'` to plain `unicode61`.
**Why:** tokenchars breaks substring/suffix matching for coding terms. Default unicode61 with phrase queries handles compounds correctly.
**Impact:** Affects Phase 2 FTS5 CREATE statement and query construction. Phase 1 Python tokenizer is unaffected.
**Fix:** One-line change in FTS5 CREATE. Query escaping already handles quoting.

### BLOCKER 2: Automatic FTS5 Fallback (RED -> YELLOW with fix)
**What:** Add try/except around FTS5 initialization. Fall back to existing keyword system if FTS5 unavailable.
**Why:** Without fallback, users on minimal Python builds lose ALL retrieval.
**Fix:** ~15 LOC try/except wrapper. Keep current keyword scoring as fallback.

### BLOCKER 3: Test Rewrite Budget (YELLOW)
**What:** Plan underestimates test migration effort.
**Why:** 42% of existing tests break. 7 new test categories needed.
**Fix:** Add 4-6 hours to Day 3 or extend to Day 4 morning.

---

## Non-Blocking Recommendations

1. **Filter retired entries before FTS5 insert** -- saves unnecessary indexing
2. **Add `ORDER BY score ASC` explicitly** -- defensive coding for BM25 negative scores
3. **Strip leading/trailing delimiters from cleaned tokens** -- prevents edge case FTS5 phrase issues
4. **Phase 1 is NOT throwaway** (disagreeing with Gemini's suggestion to skip it):
   - Phase 1 tokenizer fix benefits the PYTHON-side query construction which feeds FTS5
   - Phase 1 body extraction code is reused in Phase 2 for FTS5 body column population
   - Phase 1 provides a validated safety net if Phase 2 slips
5. **Add FTS5 availability check at import time** -- `sqlite3.connect(':memory:').execute("CREATE VIRTUAL TABLE _test USING fts5(c)"); conn.close()`

---

## Gemini 3.1 Pro Full Opinion Summary

**On 3-day schedule:** "Highly realistic" but underestimates BM25 tuning and disk I/O.

**On tokenchars:** "It is a massive rabbit hole. Drop custom tokenchars. Use default unicode61 and quote queries as phrase matches."

**On Phase 1 skip:** Gemini suggested skipping Phase 1 (body content on legacy system) and going straight to FTS5. I DISAGREE -- Phase 1 code is reused in Phase 2, and provides a safe fallback.

**On in-memory rebuild:** "RAM usage negligible at <500 docs. Primary gotcha is CPU/IO on cold CLI commands." Our benchmarks confirm this is not an issue (31ms total at 500 docs).

---

## Final Assessment

The consolidated plan is **sound and implementable** with 3 targeted fixes:
1. Drop tokenchars (1-line change to spec)
2. Add FTS5 fallback (~15 LOC)
3. Budget 4-6 hours for test rewrite

After these fixes, confidence in the 3-day (plus buffer) implementation timeline is **HIGH**.
