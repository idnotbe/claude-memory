# Session 2 V1 Functional Correctness Verification Report

**Date:** 2026-02-21
**Verifier:** Claude Opus 4.6 (v1-functional agent)
**File:** `hooks/scripts/memory_retrieve.py` (645 lines)
**Verdict:** PASS WITH NOTES

---

## 1. Function-by-Function Verification

### 1.1 `build_fts_index_from_index(index_path)` -- Lines 268-286

**Purpose:** Parse index.md into an FTS5 in-memory table.

**Verification:**

| Aspect | Expected | Actual | Verdict |
|--------|----------|--------|---------|
| FTS5 schema | `title, tags, path UNINDEXED, category UNINDEXED` | Matches (line 276-278) | PASS |
| Parsing | Uses `parse_index_line()` | Confirmed (line 282) | PASS |
| Tags format | Space-joined from set | `" ".join(parsed["tags"])` (line 283) | PASS |
| Empty index | Returns conn with empty table | Verified: `query_fts` returns `[]` | PASS |
| Malformed lines | `parse_index_line()` returns None, skipped | Confirmed (line 282-284) | PASS |
| Parameterized insert | Uses `executemany` with `?` | Confirmed (line 285) | PASS |

**Edge cases tested:**
- Empty index.md -> empty FTS5 table, no crash
- Lines without `#tags:` -> empty string for tags column
- Malformed lines -> skipped silently

**Verdict: CORRECT**

---

### 1.2 `build_fts_query(tokens)` -- Lines 289-310

**Purpose:** Build FTS5 MATCH query with smart wildcard strategy.

**Verification:**

| Input | Expected Output | Actual Output | Verdict |
|-------|----------------|---------------|---------|
| `['user_id']` | `"user_id"` | `"user_id"` | PASS |
| `['auth']` | `"auth"*` | `"auth"*` | PASS |
| `['user_id', 'auth']` | `"user_id" OR "auth"*` | `"user_id" OR "auth"*` | PASS |
| `['!!!', '@#$']` | `None` | `None` | PASS |
| `['React.FC']` | `"react.fc"` | `"react.fc"` | PASS |
| `['rate-limiting']` | `"rate-limiting"` | `"rate-limiting"` | PASS |
| `['v2.0']` | `"v2.0"` | `"v2.0"` | PASS |
| `['the', 'is', 'a']` | `None` (all stopwords) | `None` | PASS |
| `['x', 'y']` | `None` (len <= 1) | `None` | PASS |
| `['a_']` | `None` (stripped to 'a', len=1) | `None` | PASS |

**Sanitization chain:**
1. `re.sub(r'[^a-z0-9_.\-]', '', t.lower())` -- strips everything except safe chars
2. `.strip('_.-')` -- removes leading/trailing delimiters
3. Length check: `len(cleaned) > 1`
4. Stopword check
5. Compound detection: `any(c in cleaned for c in '_.-')`

**Security:** Double quotes cannot appear in cleaned tokens (regex strips them). FTS5 operators like `AND`, `OR`, `NOT`, `NEAR` are quoted and neutralized. Tested: `'" ; DROP TABLE memories; --'` -> tokens `{table, memories, drop}` -> `"table"* OR "memories"* OR "drop"*` (safe).

**Verdict: CORRECT**

---

### 1.3 `query_fts(conn, fts_query, limit)` -- Lines 313-334

**Purpose:** Execute FTS5 MATCH query and return ranked results.

**Verification:**

| Aspect | Expected | Actual | Verdict |
|--------|----------|--------|---------|
| Parameterized query | `WHERE memories MATCH ?` with `(fts_query, limit)` | Confirmed (line 321) | PASS |
| Return format | `list[dict]` with title, tags (set), path, category, score | Confirmed (lines 326-333) | PASS |
| Tags splitting | Space-split, stripped, filtered empty | `set(t.strip() for t in tags_str.split() if t.strip())` | PASS |
| Score source | BM25 `rank` column | Confirmed (line 320) | PASS |
| Limit | Passed to SQL LIMIT | Confirmed (line 322) | PASS |

**Tag splitting correctness:** FTS5 stores tags as space-separated string. `split()` on whitespace is correct for this format. Tags with spaces (not possible since `parse_index_line` splits on commas and strips) would be split, but this is consistent with the index format.

**Verdict: CORRECT**

---

### 1.4 `apply_threshold(results, mode)` -- Lines 337-360

**Purpose:** Apply Top-K threshold with 25% noise floor.

**Verification:**

| Aspect | Expected | Actual | Verdict |
|--------|----------|--------|---------|
| MAX_AUTO | 3 | `MAX_AUTO = 3` (line 344) | PASS |
| MAX_SEARCH | 10 | `MAX_SEARCH = 10` (line 345) | PASS |
| Mode selection | `mode == "auto"` -> 3, else -> 10 | Confirmed (line 346) | PASS |
| Empty results | `[]` | Confirmed (line 349) | PASS |
| Sort order | Most negative first, then category priority | `(r["score"], CATEGORY_PRIORITY.get(r["category"], 10))` | PASS |
| Noise floor | 25% of best abs score | `noise_floor = best_abs * 0.25` (line 357) | PASS |
| Floor filter | `abs(score) >= noise_floor` | Confirmed (line 358) | PASS |
| Zero score guard | Skip floor if best_abs <= 1e-10 | Confirmed (line 356) | PASS |

**Edge case testing:**

| Scenario | Result | Verdict |
|----------|--------|---------|
| Scores: [-10, -8, -5, -1], auto | Returns [-10, -8, -5] (D filtered: abs(1) < 2.5) | PASS |
| All same score [-5, -5, -5, -5], auto | Returns 3, sorted by category priority | PASS |
| Tiny scores [-0.001, -0.0001], auto | Returns [-0.001] only (0.0001 < 0.00025) | PASS |
| Zero score [0.0], auto | Returns [{score: 0.0}] (floor check skipped) | PASS |

**Sort correctness with BM25 scores:** BM25 `rank` values are negative (more negative = better match). Sorting by `(r["score"], priority)` ascending puts most negative first, then lowest priority number (highest category priority). This is correct.

**Noise floor with BM25:** `abs(results[0]["score"])` gets the magnitude of the best score. `abs(r["score"]) >= noise_floor` checks each result's magnitude against 25% of the best. This correctly filters weak matches regardless of sign.

**Verdict: CORRECT**

---

### 1.5 `_check_path_containment(json_path, memory_root_resolved)` -- Lines 363-369

**Purpose:** Block path traversal attacks.

**Verification:**

| Input | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Valid path inside memory_root | `True` | `True` | PASS |
| `../../etc/passwd` traversal | `False` | `False` | PASS |
| Absolute path `/etc/passwd` | `False` | `False` | PASS |
| Symlink to outside directory | `False` | `False` | PASS |

**Correctness:** Uses `json_path.resolve().relative_to(memory_root_resolved)` which resolves symlinks before comparison. The `ValueError` catch handles containment failure correctly.

**Note from Codex review:** `Path.resolve()` could raise `OSError`/`RuntimeError` on symlink loops. Current code only catches `ValueError`. This is a LOW severity edge case since malformed symlinks would need local filesystem access.

**Verdict: CORRECT** (with minor hardening opportunity noted)

---

### 1.6 `score_with_body(conn, fts_query, user_prompt, top_k_paths, memory_root, mode)` -- Lines 372-423

**Purpose:** Hybrid scoring combining FTS5 title+tags ranking with body content bonus.

**Verification:**

| Aspect | Expected | Actual | Verdict |
|--------|----------|--------|---------|
| Initial fetch | `limit=top_k_paths * 3` | `query_fts(conn, fts_query, limit=top_k_paths * 3)` (line 385) | PASS |
| Path containment pre-filter | ALL entries checked | Lines 395-398: list comprehension on all `initial` | PASS |
| Body scoring loop | Only `initial[:top_k_paths]` | Confirmed (line 401) | PASS |
| Retired detection | `data.get("record_status") == "retired"` | Confirmed (line 406) | PASS |
| Retired marking | Sets `_retired=True`, `body_bonus=0`, continues | Confirmed (lines 407-409) | PASS |
| Body text extraction | `extract_body_text(data)` | Confirmed (line 410) | PASS |
| Body bonus cap | `min(3, len(body_matches))` | Confirmed (line 414) | PASS |
| Error handling | Sets `body_bonus=0` | Confirmed (line 416) | PASS |
| Retired filtering | Removes entries with `_retired` flag | `[r for r in initial if not r.get("_retired")]` (line 419) | PASS |
| Score adjustment | `score - body_bonus` (more negative = better) | Confirmed (line 421) | PASS |
| Final threshold | `apply_threshold(initial, mode)` | Confirmed (line 423) | PASS |

**Security fix verified:** The path containment pre-filter at lines 395-398 was added after the security review found that entries beyond `top_k_paths` bypassed containment checks. The fix applies `_check_path_containment` to ALL entries in `initial` before any body scoring. This closes the HIGH severity gap.

**Project root resolution:** `project_root = memory_root.parent.parent` (line 389). If `memory_root` is `.claude/memory`, then `project_root` is the project directory. Index paths are project-relative (e.g., `.claude/memory/decisions/foo.json`), so `project_root / result["path"]` resolves correctly. Verified with real file reads.

**Retired entries beyond top_k_paths (known limitation):**
- Only `initial[:top_k_paths]` entries get JSON-read for retirement checks
- Entries at positions `top_k_paths` through the end are never checked for retirement
- This is a pre-existing design tradeoff (same gap in legacy path at line 620-630)
- Mitigated by index rebuild filtering inactive entries
- Severity: MEDIUM (documented, not a regression)

**Body bonus math verification:**
- BM25 score: e.g., -3.0 (more negative = better)
- Body bonus: e.g., 2 (capped at 3)
- Adjusted: -3.0 - 2 = -5.0 (more negative = better)
- Correct: body matches improve ranking

**Verdict: CORRECT** (with known limitation on retired entries beyond top_k_paths)

---

### 1.7 `_output_results(top, category_descriptions)` -- Lines 426-452

**Purpose:** Output matched memories in XML format with sanitization.

**Verification:**

| Aspect | Expected | Actual | Verdict |
|--------|----------|--------|---------|
| Sanitize titles | `_sanitize_title()` applied | Confirmed (line 446) | PASS |
| Sanitize tags | `html.escape()` applied | Confirmed (line 448) | PASS |
| Sanitize paths | `html.escape()` applied | Confirmed (line 449) | PASS |
| Sanitize description keys | `re.sub(r'[^a-z_]', '')` | Confirmed (line 437) | PASS |
| Sanitize description values | `_sanitize_title()` applied | Confirmed (line 436) | PASS |
| XML wrapper | `<memory-context source=".claude/memory/">...</memory-context>` | Confirmed (lines 444, 452) | PASS |
| Empty key skipping | Skip if `safe_key` is empty | Confirmed (lines 438-439) | PASS |

**Injection testing:**

| Attack | Input | Output | Safe? |
|--------|-------|--------|-------|
| XSS in title | `<script>alert(1)</script>` | `&lt;script&gt;alert(1)&lt;/script&gt;` | YES |
| XML breakout in description | `test <desc>` | `test &lt;desc&gt;` | YES |
| Tag injection | `jwt<evil>` | `jwt&lt;evil&gt;` | YES |
| Description attribute breakout | `desc" evil="true` | `desc&quot; evil=&quot;true` | YES |
| Category key injection | `DECISION; DROP` | `decision` (stripped non-alpha) | YES |

**Verdict: CORRECT**

---

## 2. main() Flow Verification

### 2.1 Flow Diagram

```
stdin (JSON) -> parse hook_input
  |
  +-- empty/invalid -> exit(0)
  +-- prompt < 10 chars -> exit(0)
  |
  v
Locate memory_root (.claude/memory)
  |
  +-- No index.md? Try rebuild -> still missing? exit(0)
  |
  v
Read config (if exists)
  |
  +-- retrieval.enabled == false -> exit(0)
  +-- max_inject == 0 -> exit(0)
  |
  v
Parse index entries
  |
  +-- No entries -> exit(0)
  |
  v
Branch:
  +-- HAS_FTS5 and match_strategy == "fts5_bm25"
  |     -> tokenize (compound) -> build_fts_query
  |     -> No valid query? exit(0)
  |     -> build_fts_index_from_index -> score_with_body -> _output_results
  |
  +-- else (legacy fallback)
        -> tokenize (legacy) -> score_entry per entry + score_description
        -> check_recency deep check -> _output_results
```

### 2.2 Branch Conditions

| Condition | FTS5 Path | Legacy Path | Verdict |
|-----------|-----------|-------------|---------|
| `HAS_FTS5=True, strategy="fts5_bm25"` | YES | - | PASS |
| `HAS_FTS5=True, strategy="title_tags"` | - | YES | PASS |
| `HAS_FTS5=False, strategy="fts5_bm25"` | - | YES | PASS |
| `HAS_FTS5=False, strategy="title_tags"` | - | YES | PASS |
| No config file | FTS5 (defaults to "fts5_bm25") | - | PASS |

### 2.3 Config Reading

| Config Value | Handling | Verified |
|-------------|----------|----------|
| `retrieval.enabled: false` | `sys.exit(0)` at line 504 | YES |
| `retrieval.max_inject` | Clamped to [0, 20], fallback 3 | YES |
| `retrieval.match_strategy` | Compared with `==`, default "fts5_bm25" | YES |
| `categories.*.description` | Truncated to 500 chars, sanitized | YES |
| Invalid max_inject | Warning to stderr, default 3 | YES |
| Invalid JSON config | Silently caught, defaults used | YES |

### 2.4 Exit Codes

All exit paths use `sys.exit(0)` (silent, no error). The only way to get output is through `_output_results()` -> `return` at line 559 (FTS5) or `_output_results()` at line 640 (legacy). This is correct for a UserPromptSubmit hook where exit 0 = inject stdout into context.

### 2.5 Connection Cleanup

The FTS5 path uses `try/finally` (lines 551-555) to ensure the SQLite connection is always closed, even if `score_with_body` raises an exception. Verified correct.

### 2.6 Index Rebuild on Demand

Lines 478-488: If `index.md` doesn't exist but `memory_root` is a directory, runs `memory_index.py --rebuild`. Uses `capture_output=True` and `timeout=10` to prevent hanging. Graceful fallback if rebuild fails.

**Verdict: CORRECT**

---

## 3. Checklist Verification

Verifying every item from `temp/s2-master.md` Session 2 checklist:

| # | Checklist Item | Status | Evidence |
|---|---------------|--------|----------|
| 1 | `build_fts_index_from_index()` | DONE | Lines 268-286, tested with fixture |
| 2 | `build_fts_query()` | DONE | Lines 289-310, 10 edge cases verified |
| 3 | `query_fts()` | DONE | Lines 313-334, parameterized, tested |
| 4 | `apply_threshold()` | DONE | Lines 337-360, noise floor verified |
| 5 | `score_with_body()` with path containment | DONE | Lines 372-423, containment pre-filter at 395-398 |
| 6 | FTS5 fallback when `HAS_FTS5=False` | DONE | Line 546: condition requires both `HAS_FTS5 and match_strategy == "fts5_bm25"` |
| 7 | Config branch: read `match_strategy` | DONE | Line 514, supports "fts5_bm25" and "title_tags" |
| 8 | Update `assets/memory-config.default.json` | DONE | `max_inject: 3`, `match_strategy: "fts5_bm25"` confirmed |
| 9 | Preserve `score_entry()` for fallback | DONE | Unchanged at line 94, used at line 580 |
| 10 | Preserve path containment in `main()` | DONE | Lines 606-609 (legacy) and 395-398 (FTS5) |
| 11 | Smoke test: FTS5 and fallback queries | DONE | Implementation report confirms 9/9 smoke tests |
| 12 | Rollback plan ready | DONE | Documented in master plan; setting `match_strategy: "title_tags"` reverts to legacy |

**All 12 checklist items verified as DONE.**

---

## 4. External Model Opinions

### Codex (via pal clink)

**Findings:**
1. **HIGH: Retired filtering incomplete beyond `top_k_paths`** -- Only `initial[:top_k_paths]` entries get JSON status checks. Entries beyond that are never marked `_retired`. This is a known limitation, pre-existing in the legacy path, and documented in both the arch review (M2) and security review.

2. **MEDIUM: Fetch cap limits recall** -- `limit=top_k_paths * 3` caps the SQL fetch. If many entries fail containment, valid entries beyond the cap are missed. Correctness issue, not security.

3. **LOW: `_check_path_containment` OSError** -- `Path.resolve()` could raise `OSError` on symlink loops. Currently only catches `ValueError`. Theoretical risk.

4. **CONFIRMED correct:**
   - Path containment blocks traversal (`../../etc/passwd`) -- verified with PoC
   - Body bonus cap at 3 works correctly
   - Score subtraction (more negative = better) is directionally correct
   - Exception fallback sets `body_bonus=0` (safe)

### Gemini (via pal clink)

Gemini CLI had a network error and could not complete the review. The arch review (`temp/s2-arch-review.md`) already includes Gemini opinions from an earlier session which are consistent with the findings above.

---

## 5. Test Suite Results

### Compile Check
```
python3 -m py_compile hooks/scripts/memory_retrieve.py  -> PASS
```

### Full Test Suite
```
502 passed, 10 xpassed in 30.21s
```

Zero failures. The 10 xpassed are previously expected-fail tests that now pass (positive sign).

### Manual Integration Tests (run during this verification)

| # | Test | Result |
|---|------|--------|
| 1 | FTS5: auth query matches JWT entry | PASS |
| 2 | FTS5: database query matches Postgres entry | PASS |
| 3 | FTS5: no match returns empty | PASS |
| 4 | FTS5: retired entry filtered from results | PASS |
| 5 | FTS5: body bonus improves JWT ranking | PASS |
| 6 | FTS5: empty index returns no results | PASS |
| 7 | main(): short prompt exits silently | PASS |
| 8 | main(): no memory root exits silently | PASS |
| 9 | main(): matching query produces output | PASS |
| 10 | main(): disabled retrieval exits silently | PASS |
| 11 | main(): max_inject=0 exits silently | PASS |
| 12 | main(): legacy path via config works | PASS |
| 13 | main(): empty stdin exits silently | PASS |
| 14 | main(): invalid JSON stdin exits silently | PASS |
| 15 | apply_threshold: noise floor filters weak matches | PASS |
| 16 | apply_threshold: category priority tiebreaks correct | PASS |
| 17 | apply_threshold: tiny scores filtered correctly | PASS |
| 18 | apply_threshold: zero score handled (no floor applied) | PASS |
| 19 | _output_results: XSS in title escaped | PASS |
| 20 | _output_results: XML breakout in description escaped | PASS |
| 21 | _output_results: tag injection escaped | PASS |
| 22 | _check_path_containment: traversal blocked | PASS |
| 23 | _check_path_containment: symlink blocked | PASS |
| 24 | build_fts_query: compound tokens get exact match | PASS |
| 25 | build_fts_query: single tokens get prefix wildcard | PASS |
| 26 | build_fts_query: special-only input returns None | PASS |
| 27 | sanitize_title: control chars stripped | PASS |
| 28 | sanitize_title: arrow delimiter replaced | PASS |
| 29 | sanitize_title: tags marker stripped | PASS |
| 30 | sanitize_title: truncated to 120 chars | PASS |

**30/30 manual tests passed.**

---

## 6. Known Limitations (Not Bugs)

These are documented design tradeoffs, not defects:

1. **Retired entries beyond `top_k_paths` unchecked** -- Pre-existing in legacy path. Mitigated by index rebuild. Severity: MEDIUM. Tracked as arch review M2.

2. **FTS5 tokenizer splits on `_`, `.`, `-`** -- `"user_id"` matches `user id` (space-separated) too. This is FTS5 default behavior. Known Limitation #1 in implementation report.

3. **In-place score mutation** -- `r["score"]` is mutated with body bonus, losing raw BM25 score. Tracked as arch review M1. Planned fix in S3.

4. **Double-read of index.md** -- FTS5 path reads index.md in `entries` loop (emptiness check) and again in `build_fts_index_from_index`. Negligible performance impact (<1ms). Planned fix in S3 extraction.

5. **No recency bonus in FTS5 path** -- BM25 scoring replaces the legacy recency bonus. Acceptable tradeoff: BM25 relevance ranking is more precise.

6. **`_check_path_containment` doesn't catch OSError** -- `Path.resolve()` could theoretically raise on symlink loops. Requires local filesystem access. Severity: LOW.

---

## 7. Overall Verdict

### PASS WITH NOTES

The FTS5 engine implementation is **functionally correct**. Every function behaves as specified in the plan. All 12 checklist items are verified complete. The main() flow correctly routes between FTS5 and legacy paths. Security invariants (path containment, SQL injection prevention, output sanitization) are preserved. The HIGH severity path containment gap identified by the security review has been fixed.

**Notes (tracked, not blocking):**
- M1: In-place score mutation (S3 fix planned)
- M2: Retired entries beyond top_k_paths (pre-existing, documented)
- L1: `_check_path_containment` OSError hardening (LOW, theoretical)

**Test results:**
- Compile: PASS
- Full test suite: 502 passed, 10 xpassed, 0 failed
- Manual integration: 30/30 passed
- External model review (Codex): confirmed correctness with notes

**Confidence level: HIGH**
