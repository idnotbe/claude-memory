# Technical Review: rd-08-final-plan.md (Post-R3 Update)

**Reviewer:** Technical Reviewer Agent
**Date:** 2026-02-21
**Document:** `research/rd-08-final-plan.md` (~1297 lines)
**Source files cross-referenced:** memory_retrieve.py, memory_index.py, memory_candidate.py, test_memory_retrieve.py, test_adversarial_descriptions.py, conftest.py, assets/memory-config.default.json, hooks/hooks.json, .claude-plugin/plugin.json, commands/memory-search.md

---

## Summary Verdict: PASS WITH ISSUES

The plan is technically sound in its overall architecture and decision rationale. The FTS5 BM25 approach is correct (independently verified by Gemini 3 Pro via clink). Session ordering, dependency graph, and risk matrix are internally consistent. However, there are **2 HIGH** and **3 MEDIUM** code-sample bugs that would block or confuse an implementer if copy-pasted directly. These are fixable without architectural changes.

**Confidence: HIGH** (cross-referenced all source files, verified FTS5 claims with external model, calibrated severity via vibe-check)

---

## Findings

### HIGH Severity

#### H1. `build_fts_index_from_index()` references fields not in index.md (Lines 242-258)

**What's wrong:** The FTS5 table schema includes `id UNINDEXED` and `updated_at UNINDEXED`. The code at line 255-256 accesses `parsed["id"]` and `parsed["updated_at"]`. However, the current index.md format is:
```
- [CATEGORY] title -> path #tags:t1,t2
```
The existing `parse_index_line()` in `memory_retrieve.py` (line 72-90) returns keys: `category`, `title`, `path`, `tags`, `raw`. There are NO `id` or `updated_at` fields extractable from index.md lines without JSON parsing.

**Impact:** This code will raise `KeyError` at runtime. The plan's claim of "1 file read, no JSON parsing" is incompatible with the FTS5 schema requiring `id` and `updated_at`.

**Fix:** Either:
1. Remove `id UNINDEXED, updated_at UNINDEXED` from the FTS5 schema (simplest -- these fields aren't used in MATCH queries, only as passthrough metadata)
2. Derive `id` from path (e.g., `Path(parsed["path"]).stem`) and omit `updated_at`
3. Explicitly state that `parse_index_line()` must be enhanced to extract these fields (but they don't exist in the current index format)

Option 1 or 2 is recommended. `id` can be derived from path cheaply; `updated_at` is unused in the FTS5 query path and can be looked up later from JSON when needed.

---

#### H2. `score_with_body()` references undefined variable `fts_query_source_text` (Line 283)

**What's wrong:** The function signature is `score_with_body(conn, fts_query, top_k_paths, memory_root, mode="auto")`. Line 283 reads:
```python
query_tokens = set(tokenize(fts_query_source_text))
```
`fts_query_source_text` is not a parameter, local variable, or global. This will raise `NameError` at runtime.

**Impact:** The hybrid scoring function is central to Phase 2a. An implementer copy-pasting this code will get a crash.

**Fix:** Either:
1. Add `fts_query_source_text` as a parameter (the original user prompt text, before FTS5 query construction)
2. Replace with `fts_query` if the FTS query string itself is suitable for tokenization (it's not -- it contains FTS5 syntax like `"token"*`)
3. Rename the parameter `fts_query` to `fts_query` and add a separate `user_prompt` parameter

The intended semantics is clearly "the original user prompt text" so adding a `user_prompt: str` parameter is the cleanest fix.

---

### MEDIUM Severity

#### M1. CATEGORY_PRIORITY uses lowercase keys in plan code vs. uppercase in codebase (Lines 98-101)

**What's wrong:** The plan's `apply_threshold()` code uses:
```python
CATEGORY_PRIORITY = {
    "decision": 1, "constraint": 2, "preference": 3,
    "runbook": 4, "tech_debt": 5, "session_summary": 6,
}
```
But the existing `CATEGORY_PRIORITY` in `memory_retrieve.py` (line 38-45) uses uppercase keys: `"DECISION"`, `"CONSTRAINT"`, etc. The `entry["category"]` values from `parse_index_line()` are also uppercase (matched by the regex `[A-Z_]+`).

**Impact:** If the implementer uses the plan's lowercase keys with the existing parse output, all lookups will miss and fall through to the default priority 10, destroying category-based tie-breaking.

**Fix:** Either use uppercase keys in the plan code (matching existing convention) or explicitly note that the FTS5 path will normalize categories to lowercase (requiring a `.lower()` call on parsed categories).

---

#### M2. `query_tokens = set(tokenize(...))` is redundant (Line 283)

**What's wrong:** `tokenize()` already returns a `set[str]` (per the plan's own definition at line 170-174 and the current code at line 63-69). Wrapping it in `set()` is a no-op.

**Impact:** Not a bug, but signals that the code sample wasn't tested. Combined with H2, this reduces confidence in the code samples' copy-paste readiness.

**Fix:** Remove the `set()` wrapper: `query_tokens = tokenize(fts_query_source_text)`.

---

#### M3. CamelCase identifiers are a blind spot not acknowledged in the plan (Missing from Risk Matrix)

**What's wrong:** The plan extensively discusses `user_id` (snake_case), `React.FC` (dot-separated), and `rate-limiting` (hyphenated) but never mentions camelCase identifiers like `userId`, `rateLimit`, or `getUserById`. The `unicode61` tokenizer does NOT split on case boundaries, so `userId` tokenizes as a single token `[userid]`. A query for `user_id` (which becomes phrase `[user][id]`) will NOT match `userId`.

This was independently confirmed by Gemini 3 Pro via clink: "unicode61 does not split words on case boundaries. The identifier userId tokenizes as a single, unbroken token [userid]."

**Impact:** In mixed-convention codebases (TypeScript uses camelCase, Python uses snake_case), FTS5 retrieval will have a systematic blind spot for camelCase terms. This affects both titles and body content.

**Fix:** Add to the Risk Matrix as MEDIUM/Likely. Acknowledge the limitation and document that camelCase identifiers in memory titles should be avoided or also include the snake_case variant in tags.

---

### LOW Severity

#### L1. BODY_FIELDS includes fields not in current test fixtures (Lines 182-212)

**What's wrong:** Several BODY_FIELDS entries reference fields that don't appear in the test fixtures in `conftest.py`:
- `session_summary`: `in_progress`, `blockers`, `key_changes` not in `make_session_memory()`
- `runbook`: `environment` not in `make_runbook_memory()`
- `tech_debt`: `acceptance_criteria` not in `make_tech_debt_memory()`

**Impact:** Not a bug -- `extract_body_text()` gracefully skips missing fields. But tests built from `conftest.py` factories won't exercise these extraction paths. The implementer should either update the test factories or add separate test fixtures with these fields.

**Fix:** Note in Session 4 checklist that test factories may need updating to cover all BODY_FIELDS.

---

#### L2. Minor line reference: Plan says `score_description` import is at "line 29" (Line 336)

**What's wrong:** The import statement `score_description,` is actually at line 28 of `test_adversarial_descriptions.py`, within the multi-line import block spanning lines 25-30.

**Impact:** Negligible. An implementer would search for the function name, not navigate to a specific line number. The substantive claim (non-conditional import that would cause ImportError) is completely correct.

**Fix:** Change "line 29" to "line 28" or just say "module-level import block".

---

### INFORMATIONAL

#### I1. FTS5 unicode61 phrase matching claim is VERIFIED CORRECT (Lines 78-83)

The plan's R3-verified clarification that `"user_id"` becomes a phrase query `[user][id]` and matches `user id` (space-separated) is confirmed correct by both SQLite documentation and empirical testing via Gemini 3 Pro clink.

#### I2. Session dependency graph is internally consistent (Lines 978-1005)

Verified all 8 dependency edges in the graph. Each rationale is sound:
- S1->S2: S2 uses `extract_body_text()` and `tokenize()` from S1. Correct.
- S2->S3: S3 extracts functions from S2 into shared engine. Correct.
- S3->S5: Both modify `memory_retrieve.py`. Correct.
- S5->S4: S5 changes output format; S4 tests must target final format. Correct.
- S4->S6: Measurement requires passing tests. Correct.
- S6->S7: S7 conditional on S6 precision result. Correct.
- S7->S8: S8 tests S7 code. Correct.
- S8->S9: S9 extends S7 features. Correct.

No parallelism opportunities were missed. The linearized order is correct.

#### I3. Files Changed table is complete (Lines 1151-1167)

Cross-referenced against all session checklists. The table covers all files that will be modified or created. The R3 additions (memory-config.default.json Phase 2a, plugin.json, test_adversarial_descriptions.py, conftest.py, CLAUDE.md) are all present. No missing files detected.

#### I4. hooks.json timeout claim is accurate (Line 914)

Current `UserPromptSubmit` hook timeout is 10s (hooks.json line 52). The plan proposes increasing to 15s when the LLM judge is added (Phase 3). This is correct and necessary -- the judge adds ~1-3s of API latency.

#### I5. Existing `commands/memory-search.md` acknowledged (Line 1039)

The plan correctly notes the need to reconcile with the existing `commands/memory-search.md` command. The current plugin.json already registers this command. The plan leaves the decision (coexist or replace) to the implementer. This is appropriate.

#### I6. plugin.json skills array claim is accurate (Lines 323, 1038)

The current `plugin.json` has `"skills": ["./skills/memory-management"]`. The plan correctly states that `"./skills/memory-search"` needs to be added. The file path `.claude-plugin/plugin.json` matches the actual location.

---

## Estimates Consistency Check

| Session | Plan LOC | Plan Time | Assessment |
|---------|----------|-----------|------------|
| S1 | ~80 | 4-6 hrs | Reasonable |
| S2 | ~200-240 | 6-8 hrs | Reasonable, includes main() rewrite + security |
| S3 | ~100 net new | 4-6 hrs | Reasonable |
| S5 | ~20 | 1-2 hrs | Reasonable |
| S4 | ~70 new tests | 8-10 hrs | Slightly generous but defensible (import fix + test rewrite) |
| S6 | ~0 (manual) | 3-4 hrs | Reasonable for 40-50 query evaluation |
| S7 | ~170 | 4-6 hrs | Reasonable |
| S8 | ~280 | 4-6 hrs | Tight -- 280 LOC of tests in 4-6 hrs is ambitious |
| S9 | ~70 | 2-4 hrs | Reasonable |

**Mandatory total (S1-S6):** ~470-510 LOC, 3-4 days -- internally consistent.
**Full total (S1-S9):** ~990-1030 LOC, 5-6 days -- internally consistent.

S8 (280 LOC in 4-6 hrs) is the tightest estimate. 15 test functions at ~18 LOC each is realistic for unit tests but the integration test and search skill judge update could push this over.

---

## External Validation Summary

- **FTS5 unicode61 behavior:** Verified correct via Gemini 3 Pro (clink). Confirmed tokenization of compound identifiers, phrase matching semantics, and query syntax requirements.
- **CamelCase blind spot:** Identified by Gemini 3 Pro as a HIGH risk not covered in the plan. Elevated to M3 above.
- **Vibe check calibration:** Confirmed that initial findings were skewing toward document-formatting nitpicks. Refocused on code sample correctness (H1, H2) which are higher-impact.

---

## Consolidated Fix List

| # | Severity | Fix | Effort |
|---|----------|-----|--------|
| H1 | HIGH | Fix `build_fts_index_from_index()` FTS5 schema -- remove or derive `id`/`updated_at` | 5 min |
| H2 | HIGH | Add `user_prompt` parameter to `score_with_body()`, fix `fts_query_source_text` reference | 2 min |
| M1 | MEDIUM | Align CATEGORY_PRIORITY keys with codebase convention (uppercase) | 2 min |
| M2 | MEDIUM | Remove redundant `set()` wrapper on `tokenize()` call | 1 min |
| M3 | MEDIUM | Add camelCase blind spot to Risk Matrix | 5 min |
| L1 | LOW | Note test factory updates needed for BODY_FIELDS coverage | 2 min |
| L2 | LOW | Fix "line 29" to "line 28" for score_description import reference | 1 min |

**Total fix effort: ~20 minutes of document editing.** None of these require architectural changes.
