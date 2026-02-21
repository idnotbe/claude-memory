# Risk Assessment: Retrieval Improvement Plan (Track D -- Adversarial Analysis)

**Date:** 2026-02-21
**Analyst role:** Risk assessment and adversarial analysis agent
**Scope:** Performance, correctness, integration, and process risks in rd-08-final-plan.md
**Method:** Code analysis + empirical benchmarking on this system (SQLite 3.50.4, WSL2 Linux 6.6.87.2)

---

## Summary of Findings

| Rating | Count | IDs |
|--------|-------|-----|
| CRITICAL | 1 | R4 (tokenizer fallback regression) |
| HIGH | 3 | R6a (phrase query false matches), R11 (measurement gate statistics), R12 (tests-after-implementation) |
| MEDIUM | 5 | R5 (index.md parsing), R6b (short token wildcards), R7 (BM25 score handling), R10 (backward compat), R13 (rollback plan) |
| LOW | 4 | R1 (FTS5 latency), R2 (memory pressure), R3 (concurrent invocations), R8 (hook timeout), R9 (import path) |

---

## A. Performance Risks

### R1. FTS5 In-Memory Rebuild Latency -- LOW

**Concern:** Every UserPromptSubmit invocation rebuilds an in-memory SQLite FTS5 index from index.md. With 500+ entries, could this approach the 10-second hook timeout?

**Empirical measurement on this system:**

```
N=  100: build + query =   0.78ms
N=  500: build + query =   2.26ms
N= 1000: build + query =   5.69ms
N= 2000: build + query =   9.23ms
```

With hybrid scoring (FTS5 build + query + K JSON file reads for body content):

```
N=500, K= 5: total =  3.06ms
N=500, K=10: total =  2.60ms
N=500, K=20: total =  2.60ms
```

**Verdict:** The plan's claim of "< 100ms for 500 docs" is correct with enormous margin. Even at 2000 entries (well beyond the `max_memories_per_category: 100` default across 6 categories = 600 max), total latency is under 10ms. The 10-second timeout is not at risk from FTS5 operations.

**Rating: LOW.** Performance is not a concern for any realistic corpus size. The plan's in-memory rebuild strategy is sound.

**Caveat:** These benchmarks were run on a tmpfs filesystem in WSL2. Users on `/mnt/c/` (Windows filesystem via WSL2) may see 3-5x slower file I/O. Even at 5x, the 10ms becomes 50ms -- still well within budget.

---

### R2. Memory Pressure -- LOW

**Empirical measurement:**

```
In-memory DB size for 1000 entries: ~200 KB (50 pages * 4096 bytes)
```

**Verdict:** 200 KB for 1000 entries is negligible. Even with Python interpreter overhead (~30 MB baseline), total process memory is well under any reasonable limit. The in-memory database is a subprocess that exits after each invocation, so there is no accumulation.

**Rating: LOW.** No memory pressure concern.

---

### R3. Concurrent Invocations -- LOW

**Concern:** Can two UserPromptSubmit hooks run simultaneously, and do their in-memory databases interfere?

**Empirical test:** Created two independent `:memory:` SQLite connections with the same table name. Each sees only its own data. Isolation is correct.

```
conn1 has: [('only in conn1',)]
conn2 has: [('only in conn2',)]
Isolation: CORRECT
```

**Verdict:** In-memory SQLite databases are process-private. Even if two hook invocations run concurrently (separate Python processes), they have completely independent in-memory databases. No file locking or shared state concerns.

**Rating: LOW.** No concurrency risk.

---

## B. Correctness Risks

### R4. Tokenizer Change Blast Radius on Fallback Path -- CRITICAL

**The core problem:** The plan changes `_TOKEN_RE` from `[a-z0-9]+` to `[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+`. This preserves compound identifiers (`user_id`, `React.FC`, `rate-limiting`) as single tokens. But the **fallback path** (when FTS5 is unavailable) uses the same `tokenize()` function with the old `score_entry()` logic. These are **incompatible**.

**Demonstrated regression:**

```
Prompt: "fix the user_id field"
  OLD tokens: ['field', 'fix', 'id', 'the', 'user']
  NEW tokens: ['field', 'fix', 'the', 'user_id']

Title: "User ID validation"
  Tokens (both): ['id', 'user', 'validation']

OLD scoring: 'user' exact title (2) + 'id' exact title (2) = 4 points
NEW scoring: 'user_id' exact match against {user, id, validation} = 0 points
             prefix check: 'user_id'.startswith('user') [len 4 >= 4] = 1 point
             NET: 1 point (75% score reduction!)
```

The new tokenizer produces compound tokens from the prompt that cannot match against individual-word tokens in titles. The fallback `score_entry()` does exact word matching and prefix matching, neither of which handles the token-granularity mismatch.

**Additional regressions found:**

| Text with NEW tokenizer | Tokens LOST | Impact on fallback |
|---|---|---|
| `user_id authentication field` | `user`, `id` | Cannot match titles with "user" or "id" separately |
| `React.FC component definition` | `react`, `fc` | Cannot match "React" or "FC" separately |
| `rate-limiting configuration` | `rate`, `limiting` | Cannot match "rate" or "limiting" separately |
| `pydantic v2.0 migration` | `v2` | Loses v2 token entirely (becomes `v2.0`) |
| `use-jwt decision for auth` | `jwt`, `use` | Cannot match "jwt" or "use" separately |
| `test_memory_retrieve.py failures` | `test`, `memory`, `retrieve`, `py` | FOUR tokens lost; single compound token replaces all |

**Why this is CRITICAL:**
1. The fallback is the ONLY retrieval path when FTS5 is unavailable (documented as mandatory in the plan).
2. The regression affects exactly the kind of queries the tokenizer change is supposed to improve.
3. The fallback is also used by `memory_candidate.py`, which has an identical `_TOKEN_RE` and `tokenize()`. Changing one without the other creates an inconsistency.
4. Users on systems without FTS5 would silently get degraded retrieval with no indication.

**Mitigation required:** The fallback path needs its own tokenizer that splits compounds back into component tokens, OR the tokenizer change must only apply to the FTS5 path while preserving the old tokenizer for fallback. The plan does not address this.

---

### R5. index.md Parsing Assumptions -- MEDIUM

**Tested:** The `parse_index_line()` regex handles the following correctly:
- Header lines (`# Memory Index`, empty lines, HTML comments): correctly rejected
- Titles with quotes, colons, `C++`: correctly parsed
- Tags with hyphens (`rate-limiting`) and dots (`v2.0`): preserved as-is
- Path traversal attempts (`../../etc/passwd`): matched by regex but caught by containment check elsewhere

**FTS5 data insertion:** Special characters in titles (quotes, `++`, `OR`, `NOT`, `*`, `{braces}`) do NOT cause FTS5 insertion errors. FTS5 treats inserted data as content, not query syntax. All inserts succeed.

**One concern:** The `_INDEX_RE` uses `(.+?)` for title capture with `\s+->\s+` as the next delimiter. If a title contains the literal string ` -> `, the regex's non-greedy match would stop at the first occurrence, truncating the title and misidentifying the path. The `_sanitize_index_title()` function in `memory_index.py` replaces ` -> ` with ` - ` during index rebuild, but if someone hand-edits index.md or if a title somehow gets through with ` -> `, parsing breaks silently.

**Rating: MEDIUM.** The regex is robust for normal cases, and the write-side sanitization handles the delimiter injection. But the defense depends on the write side never failing to sanitize, and there is no read-side validation of the parsed path.

---

### R6a. Smart Wildcard Phrase Query False Matches -- HIGH

**The plan claims:** `"user_id"` matches `user_id` exactly (no false positives from `user identity`).

**Empirically verified:** This claim is **partially correct but overstated**. FTS5's `unicode61` tokenizer treats `_` as a separator, so `"user_id"` becomes a phrase query for the token sequence `[user][id]`. This matches:
- `user_id field in database` (correct -- intended match)
- `user id validation in form inputs` (FALSE MATCH -- "user" followed by "id" with a space separator)

It does NOT match:
- `user identification system` ("identification" is not "id")
- `user identity management` ("identity" is not "id")
- `userid login form` ("userid" is one token, not "user" + "id")

**The false positive class is real but narrow:** It only fires when the component tokens appear adjacent in the same order but with a different delimiter (space vs underscore vs dot vs hyphen). In practice, "user id" (space-separated) appearing in a title where the user is searching for "user_id" (underscore) is likely to be relevant anyway. But it violates the "exact match" contract stated in the plan.

**Rating: HIGH.** The plan's Decision #3 documentation claims exact matching for compound tokens, which is factually incorrect. While the practical impact is moderate (the false positive class is somewhat relevant), the mismatch between documented behavior and actual behavior will cause confusion during debugging and test writing. The plan should be corrected to say "phrase match" rather than "exact match."

---

### R6b. Short Token Wildcard Edge Cases -- MEDIUM

**Tokens like `v2` and `v3`:** These are 2 characters, pass the `len(cleaned) > 1` filter, and contain no compound delimiters, so they get wildcard treatment: `"v2"*`. Empirically tested:
- `"v2"*` matches `v2 api endpoint migration` -- correct
- `"v2"` (exact) also matches -- so the wildcard adds no value but no harm

**Tokens like `db`:** Same pattern, 2 chars, no compound delimiters, gets `"db"*`. This would match `dbase`, `dbo`, `dbms` -- potentially unexpected prefix expansion for very short tokens.

**The 2-character minimum:** The plan filters tokens with `len(cleaned) > 1`, so single-character tokens are excluded. But 2-character tokens with wildcard expansion (`"db"*`, `"js"*`, `"py"*`, `"go"*`) can produce broad matches. Consider: `"go"*` matches `good`, `google`, `golang`, `government`...

**However:** The current STOP_WORDS list includes `"go"` and `"as"`, but NOT `"db"`, `"js"`, `"py"`, `"ci"`, `"cd"`. These are meaningful coding terms that SHOULD match, so broad wildcard expansion on them is arguably correct behavior for a coding memory system.

**Rating: MEDIUM.** The 2-character wildcard expansion is a design tradeoff, not a bug. But it should be documented that short tokens like `"db"*` will match broadly, and the test suite should cover these cases explicitly.

---

### R6c. `React.FC` Phrase Query Semantics -- Verified Correct

**Tested:** `"react.fc"` becomes a phrase query for `[react][fc]`. Results:
- Matches `React.FC component definition` (correct)
- Does NOT match `react native fc navigation` (non-adjacent react...fc)
- Does NOT match `fc barcelona react to loss` (reversed order)

**Rating: Not a risk.** The phrase query correctly requires adjacency and order.

---

### R7. BM25 Score Interpretation -- MEDIUM

**Verified:** FTS5 `rank` column returns NEGATIVE values (more negative = better match):

```
rank=-3.881530: authentication system security layer   (best)
rank=-3.596639: authentication jwt token refresh endpoint
rank=-3.350708: random content with authentication mentioned once  (worst)
```

**The plan's noise floor uses `abs()`:**
```python
best_abs = abs(results[0]["score"])  # 3.88
noise_floor = best_abs * 0.25       # 0.97
# Keep if abs(score) >= noise_floor
```

**Tested:** With the above scores, all three results pass the noise floor (all `abs(score) >= 0.97`). This is correct behavior.

**However, there is a subtle issue in the plan's `apply_threshold()` code:**
```python
results.sort(key=lambda r: (r["score"], ...))
```
Since scores are negative, sorting by `r["score"]` ascending puts the most negative (best) first. This is correct. But the variable naming `best_abs = abs(results[0]["score"])` assumes `results[0]` is the best match after sorting, which is true.

**Potential issue in `score_with_body():`**
```python
r["final_score"] = r["score"] - r.get("body_bonus", 0)  # More negative = better
```
Subtracting a positive body_bonus from a negative score makes it more negative (better). This arithmetic is correct but counterintuitive. A comment-only clarification is sufficient.

**Rating: MEDIUM.** The math is correct but the negative-score convention is error-prone. Every developer touching this code must understand that "more negative = better." A single sign error anywhere in the scoring pipeline would silently corrupt ranking. Recommend adding a helper function `is_better_score(a, b)` or normalizing to positive scores internally.

---

## C. Integration Risks

### R8. Hook Timeout -- LOW

**Current timeout:** 10 seconds (from `hooks/hooks.json`).
**Plan increases to 15s:** Only in Phase 3 (judge layer, which adds ~1-2s API call).
**FTS5 path latency:** < 10ms total (empirically verified at 500 entries + 10 JSON reads).
**JSON file reads for recency check:** The current code reads up to `_DEEP_CHECK_LIMIT = 20` JSON files. This adds < 5ms on fast filesystem.

**Total estimated latency for FTS5 path:** < 50ms. The 10-second timeout has > 199x safety margin.

**Judge path (Phase 3):** Adds ~900ms P50 for API call + ~50ms for context extraction. Total ~1s. The 15-second timeout has > 13x safety margin.

**Rating: LOW.** No timeout risk for any planned code path. The timeout increase to 15s for Phase 3 is a reasonable precaution but not strictly necessary for the FTS5-only phases.

---

### R9. Search Engine Extraction Import Path -- LOW

**Concern:** `memory_search_engine.py` is a new file that needs to be importable from `memory_retrieve.py`. The plan uses:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_search_engine import build_fts_index, query_fts
```

**Analysis:** This is the standard pattern for sibling imports in Python scripts. Since `__file__` resolves to the actual script location (whether in the development repo at `/home/idnotbe/projects/claude-memory/hooks/scripts/` or the plugin install at `~/.claude/plugins/claude-memory/hooks/scripts/`), the import will work in both contexts.

**One edge case:** If the hook is invoked with a relative path and the working directory changes between invocation and import, `__file__` might not resolve correctly. However, Claude Code's hook execution uses `$CLAUDE_PLUGIN_ROOT` (absolute path), so this is not a practical concern.

**Rating: LOW.** The import mechanism is correct and robust for the deployment model.

---

### R10. Backward Compatibility -- MEDIUM

**Config default change:** The plan changes `match_strategy` from `"title_tags"` to `"fts5_bm25"` in `assets/memory-config.default.json`.

**Current state:** `match_strategy` is currently an **agent-interpreted key** that the retrieval script completely ignores. The script always uses the keyword scoring path regardless of the config value. This means:

1. **Existing users with no `match_strategy` key in their config:** The script falls back to its built-in default. If the plan makes the script READ this key (to switch between FTS5 and keyword paths), then missing key = needs a default. The plan specifies `"fts5_bm25"` as the new default. This means existing users get silently upgraded to FTS5.

2. **Existing users with `match_strategy: "title_tags"`:** They explicitly set this (or inherited it from the old default config). The plan should preserve their choice by routing to the keyword fallback path.

3. **New users:** Get `"fts5_bm25"` from the default config. No issue.

**The gap:** The plan does not specify what happens when:
- `match_strategy` is missing from config entirely (likely for users who created config before this key existed)
- `match_strategy` is an unrecognized value (e.g., a typo or future value)

The plan should specify: missing key = `"fts5_bm25"` (new default), unrecognized value = `"fts5_bm25"` with stderr warning.

**Additionally:** The plan changes `max_inject` from 5 to 3. This is a behavioral change for existing users who have no explicit `max_inject` in their config and rely on the default. The reduced injection count may surprise users who expected 5 results.

**Rating: MEDIUM.** The config migration path is mostly clean but has undocumented edge cases around missing keys and the `max_inject` default reduction. The silent upgrade to FTS5 is appropriate (it is strictly better than keyword matching), but the `max_inject` reduction should be documented as a breaking change.

---

## D. Process Risks

### R11. Measurement Gate Statistical Validity -- HIGH

**The plan proposes:** 20 queries with max_inject=3, yielding 60 binary injection decisions. Decision rule: precision >= 80% means skip Phase 3 (judge).

**Statistical analysis (Wilson score 95% confidence interval):**

```
n_queries= 20 (n= 60), observed=70%: 95% CI = [57.5%, 80.1%]
n_queries= 20 (n= 60), observed=75%: 95% CI = [62.8%, 84.2%]
n_queries= 20 (n= 60), observed=80%: 95% CI = [68.2%, 88.2%]
n_queries= 20 (n= 60), observed=85%: 95% CI = [73.9%, 91.9%]
```

**The problem:** With 60 decisions:
- If observed precision is 80%, the true precision could be anywhere from 68% to 88% (20% CI width).
- If observed precision is 75%, the true precision could be anywhere from 63% to 84%.
- The gate cannot reliably distinguish 75% precision (should proceed to judge) from 85% precision (should skip judge).

**Practical implications:**
- A sample that barely passes 80% could have a true precision of 68% (should have failed).
- A sample that barely fails at 78% could have a true precision of 88% (should have passed).
- The measurement gate creates a false sense of rigor while providing insufficient statistical power.

**At 50 queries (150 decisions):**
- 80% observed: CI = [72.9%, 85.6%] -- 13% width, more actionable but still not tight.

**Rating: HIGH.** The 20-query gate is not large enough to make a statistically meaningful go/no-go decision at the 80% threshold. Recommend either: (a) increase to 40-50 queries, (b) use a more lenient threshold (70% skip, 90% definitely skip), or (c) acknowledge the gate is a rough sanity check, not a statistical test, and adjust the process description accordingly.

---

### R12. Tests Written After Implementation -- HIGH

**The plan's session sequence:**
- Session 2: FTS5 engine core (Phase 2a)
- Session 3: Search skill extraction + integration (Phase 2b)
- Session 4: Tests (Phase 2c)

**The risk:** Bugs introduced in Sessions 2-3 are not caught until Session 4. This creates several problems:

1. **Accumulated tech debt:** By the time tests are written, the developer has moved on mentally from the implementation details. Bugs found during testing require context-switching back to code written 1-2 days earlier.

2. **Test contamination:** Tests written after the implementation tend to test "what the code does" rather than "what the code should do." The developer unconsciously writes tests that pass, not tests that verify the specification.

3. **Integration bugs compound:** The FTS5 engine (Session 2) and search skill (Session 3) are integrated. A bug in the engine might be masked by the skill's error handling, only surfacing as a subtle ranking issue that is hard to diagnose.

4. **Specific risk -- tokenizer fallback:** If the tokenizer change (Session 1) introduces the R4 regression, it won't be caught until Session 4 unless the developer manually tests the fallback path. The plan's Session 1 validation ("verify tokenizer on 10+ coding identifiers") tests the new tokenizer but not its interaction with the old scoring logic.

**Rating: HIGH.** The plan should include at minimum a smoke test after each session:
- Session 1: Verify `tokenize()` + `score_entry()` still produce non-zero scores for compound identifiers (tests the fallback path).
- Session 2: Verify FTS5 build + query returns expected results for 5 representative queries.
- Session 3: End-to-end test with subprocess invocation.

---

### R13. Rollback Plan -- MEDIUM

**The plan mentions:** `match_strategy: "title_tags"` as a config-based rollback switch. The FTS5 code path is gated on this config value plus the `HAS_FTS5` runtime check.

**What is NOT addressed:**

1. **Rollback of the tokenizer change (Session 1):** The `_TOKEN_RE` change affects both the FTS5 path and the fallback path. Setting `match_strategy: "title_tags"` rolls back the scoring engine but NOT the tokenizer. If the new tokenizer introduces the R4 regression in the fallback path, the config switch makes it worse (forces the fallback path which is now broken by the new tokenizer).

2. **Rollback of index.md format changes:** If the FTS5 engine adds new fields to index.md (e.g., body text excerpts, updated_at), rolling back to the keyword system means the old parser sees unexpected content. The plan does not change the index.md format, but this should be explicitly confirmed.

3. **Git-based rollback:** The plan does not mention a git branch strategy. If all changes are committed to the main branch incrementally, rolling back Session 2 while keeping Session 1 requires `git revert` of specific commits. A feature branch with squash-merge would make rollback cleaner.

4. **No automated rollback trigger:** If retrieval starts timing out or producing zero results, the user must manually set `match_strategy: "title_tags"`. There is no self-healing mechanism.

**Rating: MEDIUM.** The config-based switch is a good start, but the tokenizer change creates a coupling that the rollback plan does not account for. Recommend: keep the old `_TOKEN_RE` as `_LEGACY_TOKEN_RE` and use it in the fallback path, ensuring the fallback is truly independent of the FTS5-related changes.

---

## Additional Findings (Not in Original Question Scope)

### R14. `memory_candidate.py` Tokenizer Consistency -- MEDIUM (Bonus Finding)

`memory_candidate.py` has its own `_TOKEN_RE = re.compile(r"[a-z0-9]+")` and `tokenize()` function (line 71, 83-89). The plan only mentions changing the tokenizer in `memory_retrieve.py`. If the retrieval tokenizer changes but the candidate tokenizer does not, the two scripts will produce different tokens from the same text.

This matters because `memory_candidate.py` is used for ACE consolidation (update/delete candidate selection). A memory that matches well in the new retrieval tokenizer might not be found by the candidate selector, or vice versa. The plan should either: (a) change both tokenizers, (b) extract tokenization into a shared module, or (c) explicitly document that the candidate tokenizer is intentionally different.

### R15. FTS5 Phrase Query Position Sensitivity -- LOW (Informational)

FTS5 phrase queries are position-sensitive: `"user id"` requires `user` immediately followed by `id`. This means:
- `"user_id"` matches `user_id field` and `user id validation` (both have adjacent user+id)
- `"user_id"` does NOT match `id user` (reversed order)
- `"user_id"` does NOT match `user login id` (non-adjacent)

This is generally correct behavior for compound identifiers, but it means the FTS5 path has different matching semantics than the keyword path (which matches unordered and non-adjacent). The plan should document this difference.

---

## Risk Matrix Summary

| ID | Risk | Rating | Justification | Recommended Action |
|----|------|--------|---------------|-------------------|
| R1 | FTS5 rebuild latency | LOW | Empirically < 10ms at 500 entries | None needed |
| R2 | Memory pressure | LOW | ~200KB for 1000 entries | None needed |
| R3 | Concurrent invocations | LOW | In-memory DBs are process-private | None needed |
| R4 | **Tokenizer fallback regression** | **CRITICAL** | New tokenizer breaks old scoring: 75% score reduction on compound identifiers | Keep legacy tokenizer for fallback path |
| R5 | index.md parsing edge cases | MEDIUM | Regex is robust; write-side sanitization covers delimiter injection | Add read-side path validation |
| R6a | **Phrase query false matches** | **HIGH** | `"user_id"` matches `user id` (space-separated); plan claims "exact match" | Correct documentation; consider if this matters in practice |
| R6b | Short token wildcards | MEDIUM | 2-char tokens like `"db"*` match broadly | Document behavior; add test cases |
| R7 | BM25 score sign convention | MEDIUM | Negative scores are correct but error-prone | Add helper function or normalize |
| R8 | Hook timeout | LOW | < 50ms total FTS5 latency vs 10s timeout | None needed |
| R9 | Import path for search engine | LOW | `sys.path.insert(0, dirname(__file__))` is correct | None needed |
| R10 | Backward compatibility | MEDIUM | Silent upgrade to FTS5 + max_inject reduction | Document breaking changes |
| R11 | **Measurement gate statistics** | **HIGH** | 20 queries gives 20% CI width; cannot distinguish 75% from 85% | Increase to 40-50 queries or reframe as sanity check |
| R12 | **Tests after implementation** | **HIGH** | Bugs in Sessions 2-3 uncaught until Session 4 | Add smoke tests to each session |
| R13 | Rollback plan gaps | MEDIUM | Config switch does not roll back tokenizer | Keep legacy tokenizer separate |
| R14 | Candidate tokenizer inconsistency | MEDIUM | memory_candidate.py has separate tokenizer | Synchronize or document difference |
| R15 | FTS5 position sensitivity | LOW | Different matching semantics vs keyword path | Document difference |

---

## Top 3 Action Items (Blocking)

1. **Fix R4 (CRITICAL):** Preserve the old `_TOKEN_RE` as `_LEGACY_TOKEN_RE` and use it exclusively in the keyword fallback path (`score_entry`, `score_description`). The new compound-preserving tokenizer should only be used for FTS5 query construction. This prevents the fallback path from regressing.

2. **Fix R6a (HIGH):** Correct the plan's documentation for Decision #3 to state "phrase match" rather than "exact match." Acknowledge that `"user_id"` matches any adjacent `[user][id]` sequence regardless of original delimiter. Evaluate whether this matters for the target use case (likely acceptable but should be conscious decision, not an undocumented behavior).

3. **Fix R12 (HIGH):** Add minimal smoke tests to Sessions 1-3 instead of deferring all testing to Session 4. At minimum:
   - Session 1: Test `tokenize()` + `score_entry()` on compound identifiers with the new tokenizer (catches R4 immediately).
   - Session 2: Test `build_fts_index_from_index()` + `query_fts()` returns expected results for 5 queries.
   - Session 3: One subprocess integration test verifying end-to-end output.
