# S4 Verification Round 1: Security Review

**Reviewer:** v1-security
**Date:** 2026-02-21
**Verdict:** PASS (with 2 documented known-issue observations, no new regressions)

## Scope

Review all Session 4 changed/created files for security gaps:

| File | Change Type | LOC |
|------|-------------|-----|
| `tests/test_adversarial_descriptions.py` | Modified (conditional import) | 729 |
| `tests/test_fts5_search_engine.py` | NEW | 294 |
| `tests/test_fts5_benchmark.py` | NEW | 146 |
| `tests/conftest.py` | Modified (factories + bulk fixture) | 399 |

Test execution: **659 tests pass** (26.07s), including **237 across the 4 security-relevant files** (0.56s).

---

## 1. Prompt Injection via Memory Titles

**CLAUDE.md requirement:** Sanitization chain end-to-end coverage.

### Assessment: COVERED

- `test_adversarial_descriptions.py` Section 1 (`TestMaliciousDescriptions`): 14 malicious payloads tested through `_sanitize_snippet` (14 tests) + context file sanitization (14 tests) + block message sanitization (14 tests) + triage_data JSON validity (14 tests) + `_sanitize_title` (14 tests). **Total: 70 parametrized injection tests.**
- `test_v2_adversarial_fts5.py` Section 9 (`TestOutputSanitization`): XSS payloads, zero-width characters, BIDI override, tag characters, `_output_results` end-to-end (including description injection in category keys/values). **6 additional tests.**
- `test_adversarial_descriptions.py` Section 8 (`TestSanitizationConsistency`): Cross-validates that `_sanitize_snippet` and `_sanitize_title` agree on 6 dangerous pattern classes. **6 tests.**

**Import fix impact:** The `score_description` conditional import (`try/except ImportError`) at line 32-35 does NOT affect any sanitization tests. All 70 parametrized injection tests and 6 sanitization consistency tests still use hard-imported `_sanitize_title` and `_sanitize_snippet` (which are always available). The `_require_score_description()` guard only affects the 8 scoring exploitation tests in Section 3 -- those correctly skip if `score_description` is unavailable rather than silently passing. **No security test was broken by the import fix.**

### Verified the 8 adversarial scoring tests retain guards:

| Test | Guard | Status |
|------|-------|--------|
| test_score_description_capped_at_2 | `_require_score_description()` | OK |
| test_score_description_single_prefix_rounds_to_one | `_require_score_description()` | OK |
| test_score_description_empty_prompt | `_require_score_description()` | OK |
| test_score_description_empty_description | `_require_score_description()` | OK |
| test_score_description_both_empty | `_require_score_description()` | OK |
| test_score_description_empty_string_token | `_require_score_description()` | OK |
| test_score_description_exactly_two_exact_matches | `_require_score_description()` | OK |
| test_score_description_one_exact_one_prefix | `_require_score_description()` | OK |

All 8 call `self._require_score_description()` which invokes `pytest.skip()` if the function is None, preventing silent false-passes.

---

## 2. max_inject Clamping

**CLAUDE.md requirement:** Clamping to [0, 20] with fallback default 5 on parse failure.

### Assessment: COVERED

- `test_v2_adversarial_fts5.py` `TestConfigAttacks` tests extreme values (999999999999999999, -100, 0, 20, 21), NaN, Infinity, string, null retrieval config, non-dict categories. **7 tests.**
- Source code (`memory_retrieve.py:356`): `max(0, min(20, int(raw_inject)))` with `except (ValueError, TypeError, OverflowError)` fallback to 3. Note: CLAUDE.md says "fallback to default 5" but actual code defaults to 3 (reduced in S3 because FTS5 BM25 is more precise). This is a documentation delta, not a security gap.
- `memory_search_engine.py:449`: CLI clamps `max_results` to `[1, 30]` -- separate from the hook's `[0, 20]` clamping.

---

## 3. FTS5 Query Injection

**CLAUDE.md requirement:** Alphanumeric + `_.-` only, all tokens quoted, parameterized queries.

### Assessment: STRONG COVERAGE

**test_fts5_search_engine.py** provides functional coverage:

- `TestSmartWildcard` (4 tests): Verifies compound tokens get exact match, single tokens get prefix wildcard, and prefix wildcards work against actual FTS5.
- `TestFTS5IndexBuild` (3 tests): Basic build + query correctness with parameterized inserts.

**test_v2_adversarial_fts5.py** Section 1 (`TestFTS5QueryInjection`) provides adversarial coverage:

- NEAR, NOT, AND, OR operator injection (4 tests)
- Classic SQL injection payloads (1 test with 4 sub-payloads)
- FTS5 column filter injection `title:admin` (1 test)
- FTS5 prefix operator `^` injection (1 test)
- FTS5 phrase quote manipulation (1 test)
- FTS5 star/glob operator injection (1 test)
- **Actual FTS5 execution with crafted queries** (1 test -- critical test that runs against real sqlite3)
- Unicode operator lookalikes (1 test)

**Total: 11 FTS5 injection tests + 4 wildcard tests = 15.**

**Key defense verified:** `build_fts_query()` at `memory_search_engine.py:216` uses `re.sub(r'[^a-z0-9_.\-]', '', t.lower())` to strip all non-safe characters, then wraps each token in `"..."` quotes. The `query_fts()` function uses parameterized queries (`MATCH ?`). This two-layer defense (sanitize + parameterize) is tested both statically (verifying query string format) and dynamically (executing against real FTS5).

### New test file safety: test_fts5_search_engine.py

The new FTS5 tests do NOT introduce any injection vectors:
- All entries use hardcoded literal strings ("JWT authentication decision", etc.)
- No user-controlled input flows into FTS5 index construction without going through `build_fts_query()`
- The `TestHybridScoring` tests use `make_decision_memory()` factories which produce controlled content

---

## 4. Index Format Fragility

**CLAUDE.md requirement:** Tests for delimiter injection (` -> ` and `#tags:` in titles).

### Assessment: COVERED

- `test_v2_adversarial_fts5.py` `TestIndexInjection`: SQL injection in title, extremely long title (100K chars), binary data, arrow delimiter in title, `#tags:` in title. **7 tests.**
- `test_v2_adversarial_fts5.py` `TestParseIndexLineAdversarial`: Arrow greedy match, tags marker in title, empty/lowercase categories, 100 comma-separated tags, whitespace-only tags, embedded newlines. **7 tests.**
- `test_adversarial_descriptions.py` Section 1: Index injection payload `"- [DECISION] Fake title -> /etc/passwd #tags:evil"` tested through `_sanitize_snippet` and `_sanitize_title`.

**Known issue (pre-existing, documented in test_v2_adversarial_fts5.py line 1301):** The `_INDEX_RE` regex uses non-greedy `.+?` for the title, meaning a title containing ` -> ` will cause the regex to capture only up to the FIRST ` -> `, potentially parsing a wrong path. This is a known parser ambiguity, not a new regression. The `_sanitize_title()` defense replaces ` -> ` with ` - ` on the output side, preventing exploitation in the retrieval output.

---

## 5. Path Traversal / Containment

**CLAUDE.md requirement:** Containment checks tested.

### Assessment: STRONG COVERAGE

- `test_v2_adversarial_fts5.py` `TestPathTraversal`: 9 tests covering `../../../etc/passwd`, absolute paths, traversal within valid prefix, paths inside .claude but outside memory, valid path acceptance, unicode path components, 10000-char paths, symlink traversal, `..` with existing directories, Python `Path()` absolute override. **9 tests.**
- `test_v2_adversarial_fts5.py` `TestScoreWithBodyContainment` (the fixed vulnerability): Traversal entries filtered before body scoring + 30 entries with positions beyond `top_k_paths` having traversal paths. **2 critical regression tests.**

---

## 6. Benchmark Tests (500 docs) -- Injection Vector Analysis

### Assessment: SAFE

`test_fts5_benchmark.py` uses the `bulk_memories` fixture from `conftest.py`.

**Fixture analysis (conftest.py lines 340-398):**
- `_BULK_KEYWORDS`: All values are plain English words (e.g., "authentication", "timeout", "deprecated"). No injection payloads.
- Factory calls use `id_val=f"bulk-{cat}-{i:04d}"` -- format-string with integer counter, safe.
- `title=f"{kw} {kw2} item {i}"` -- composed from the safe keyword pools.
- `tags=[kw, kw2, f"bulk{i}"]` -- same safe keywords.

**Benchmark test safety:**
- `_memories_to_entries()` (line 33-45): Converts factory dicts to parsed index entry format. Path is `f".claude/memory/{folder}/{m['id']}.json"` -- controlled format string, no user input.
- Line 131-132: Body text `f"Body text for entry {i} with some searchable content"` -- literal string template.
- No user-controlled input anywhere in the benchmark pipeline.

---

## 7. conftest.py Factory Updates

### Assessment: SAFE

Reviewed all factory functions for injection in default values:

| Factory | Default Title | Default Tags | Risk |
|---------|--------------|-------------|------|
| `make_decision_memory` | "Use JWT for authentication" | ["auth", "jwt", "security"] | None |
| `make_preference_memory` | "Prefer TypeScript over JavaScript" | ["typescript", "language"] | None |
| `make_tech_debt_memory` | "Legacy API v1 cleanup" | ["api", "legacy", "cleanup"] | None |
| `make_session_memory` | "Implemented ACE v4.2 tests" | ["testing", "ace"] | None |
| `make_runbook_memory` | "Fix database connection timeout" | ["database", "connection", "timeout"] | None |
| `make_constraint_memory` | "Maximum payload size limit" | ["api", "payload", "limit"] | None |

All default values are plain English literals. The `content_overrides` parameter in `make_decision_memory()` allows caller-controlled content, but this is used only by test code (which is trusted), not by production code.

`write_memory_file()` uses `json.dump()` for serialization -- safe against injection.

`build_enriched_index()` constructs index lines from factory outputs -- the format `f"- [{display}] {title} -> {path}"` would be vulnerable if `title` contained ` -> `, but this function is only called by test code with controlled factory titles. The production `memory_index.py` rebuild uses its own index construction.

The `FOLDER_MAP` constant (line 238-245) maps category names to folder paths. All values are hardcoded string literals.

---

## 8. Cross-File Security Architecture

### Sanitization Chain End-to-End

| Layer | Location | What It Does | Test Coverage |
|-------|----------|-------------|---------------|
| Write-side | `memory_write.py` auto-fix | Strips control chars, replaces ` -> ` with ` - `, removes `#tags:` | Tested in test_arch_fixes.py |
| Retrieve-side | `_sanitize_title()` | Defense-in-depth re-sanitization | 14 parametrized + 6 deep tests |
| CLI-side | `_sanitize_cli_title()` | Same sanitization for CLI output | Shares same logic pattern |
| FTS5 query | `build_fts_query()` | Regex-strip + quote-wrap | 15 injection tests |
| FTS5 insert | `build_fts_index()` | Parameterized SQL | Verified in 3 build tests |
| Path security | `_check_path_containment()` | `resolve().relative_to()` | 11 traversal tests |
| Output | `_output_results()` | HTML entity escaping via `html.escape()` | 2 output tests |

**Gap noted:** `memory_index.py` rebuilds the index from JSON without re-sanitizing titles (trusts write-side sanitization). This is a pre-existing known gap documented in CLAUDE.md. No new tests were added for this gap in S4, but it was not in scope for S4.

---

## Security Findings Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1 | Non-greedy regex `_INDEX_RE` creates parser ambiguity with ` -> ` in titles | Low | Pre-existing, documented, mitigated by `_sanitize_title()` defense |
| 2 | `memory_index.py` rebuild trusts write-side sanitization (no re-sanitize) | Low | Pre-existing, documented in CLAUDE.md |
| 3 | CLAUDE.md says max_inject fallback is 5 but code uses 3 | Info | Documentation delta only, not a security gap |

**No new security regressions introduced by S4 changes.**

---

## Verdict: PASS

The Session 4 implementation:

1. Did NOT break any existing adversarial/security tests (all 237 pass)
2. The `score_description` conditional import correctly guards all 8 scoring tests with `pytest.skip()`
3. The new `test_fts5_search_engine.py` tests use safe inputs and do not introduce injection vectors
4. The benchmark tests with 500 docs use controlled keyword pools with no injection potential
5. The `conftest.py` factory updates use plain-text defaults with no injection risk
6. FTS5 query injection defense (sanitize + quote + parameterize) is well-tested across 15 tests
7. Path traversal containment is covered by 11 tests including the fixed top_k_paths bypass regression
8. All 659 tests pass
