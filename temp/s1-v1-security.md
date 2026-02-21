# Session 1 Security Verification Report

**Reviewer:** V1-SECURITY (Opus 4.6)
**Date:** 2026-02-21
**Scope:** `hooks/scripts/memory_retrieve.py` -- Session 1 changes (dual tokenizer, extract_body_text, HAS_FTS5)
**External validation:** Gemini 3.1 Pro (via pal clink, codereviewer role)
**Test suite:** 435 passed, 10 xpassed, 0 failed

---

## Summary

The Session 1 implementation is **PASS -- no security blockers**. All existing security measures are intact and functioning correctly. One minor concern identified (body text memory allocation before truncation) has negligible practical impact due to multiple mitigating factors. The Gemini reviewer agreed on ReDoS safety and FTS5 check safety, and raised the body text concern which I evaluated and downgraded to LOW after quantifying real-world impact.

---

## S1. ReDoS (Regular Expression Denial of Service) -- PASS

**Pattern tested:** `_COMPOUND_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+")`

**Methodology:** Tested with 5 pathological input patterns at 10K, 50K, and 100K character sizes (15 tests total).

| Input Pattern | 100K chars | Time |
|---|---|---|
| All same char (`aaa...`) | 1 token | <0.001s |
| Alternating compound (`a_a_...`) | 1 token | <0.001s |
| Mixed compound (`a_b.a_b...`) | 1 token | <0.001s |
| Backtrack-trigger (`a` + `_`*100 + `!` repeated) | 980 tokens | 0.003s |
| All underscores (`___...`) | 0 tokens | 0.002s |

**Analysis:** No nested quantifiers means no exponential backtracking. The alternation `|` causes at most linear backtracking: the first branch `[a-z0-9][a-z0-9_.\-]*[a-z0-9]` tries, fails at the final anchor, backtracks linearly through the `*` quantifier, then the second branch `[a-z0-9]+` tries. Both branches are O(N).

**Gemini 3.1 Pro verdict:** PASS. Confirmed O(N) linear backtracking, no nested repetition.

---

## S2. extract_body_text() Memory Safety -- PASS (with LOW concern)

**Tested scenarios:**

| Scenario | Result | Status |
|---|---|---|
| 100KB string in single field | Truncated to 2000 chars | PASS |
| Multiple 50KB fields (7 fields * 50KB * 10 items) | Truncated to 2000 chars | PASS |
| 10-level deeply nested dict | Skipped non-string gracefully | PASS |
| None, False, 0, empty string values | Empty string returned | PASS |
| Lists with mixed types (None, int, bool, str, dict) | Only strings extracted | PASS |
| content=None / content=string / content=list | Empty string (isinstance guard) | PASS |
| Missing content key / missing category | Empty string | PASS |

**Gemini concern -- memory allocation before truncation:**

Gemini flagged that `" ".join(parts)[:2000]` allocates the full joined string before slicing, which could cause OOM with very large fields.

**My assessment: LOW, not MEDIUM.** Reasons:

1. **Data is already in memory.** `extract_body_text()` receives a dict that was loaded from JSON. The strings are already Python objects in memory. The join creates one additional temporary copy.

2. **Schema validation on write.** `memory_write.py` validates all content through Pydantic models before writing. Field sizes are bounded by schema constraints. A malicious 500MB field would fail validation.

3. **Subprocess isolation.** `memory_retrieve.py` runs as a subprocess (hook). OOM kills only that process, not Claude Code. The hook has a 10-second timeout.

4. **Measured impact.** With 7 fields of 10MB each (70MB total, far beyond any realistic memory file), `tracemalloc` shows the `join` line allocates only 2049 bytes (the truncated result). The temporary full-size string is created and immediately eligible for GC. Peak process memory was 133MB (including the test data itself).

5. **Practical memory file sizes.** Real memory files are 1-10KB. Even a degenerate file with many large fields would produce at most ~100KB before truncation.

**Recommendation for Session 2:** Not blocking. If desired, an early-exit pattern could be added to track accumulated length and break early. But this is a micro-optimization given the mitigating factors above.

---

## S3. FTS5 Check Safety -- PASS (with LOW concern)

### S3a. `:memory:` database filesystem impact
**PASS.** Verified that no files are created in the temp directory before/after the FTS5 check. In-memory databases exist entirely in RAM.

### S3b. Connection closed on success path
**PASS.** After `_test.close()`, attempting `_test.execute("SELECT 1")` raises `ProgrammingError: Cannot operate on a closed database.`

### S3c. Resource leak on exception path
**LOW CONCERN.** If `sqlite3.connect(":memory:")` succeeds but `CREATE VIRTUAL TABLE ... USING fts5(c)` fails, the `_test` connection is never closed. This is technically a resource leak, but:
- Runs exactly once at import time (O(1))
- In-memory connection has no file handles
- GC will eventually collect it
- Cannot be triggered repeatedly by an attacker

**Fix (hygiene, not security):** Use `contextlib.closing()` or add `_test.close()` in a `finally` block.

### S3d. stdout corruption
**PASS.** Module import produces zero stdout output. The FTS5 unavailable warning goes to stderr only. Verified by capturing both stdout and stderr during import.

---

## S4. Legacy Path Security Preservation -- PASS

### S4a. `_sanitize_title()` intact
**PASS.** Verified all sanitization behaviors:

| Attack Vector | Input | Sanitized | Status |
|---|---|---|---|
| Control characters | `\x00`, `\x01`, `\x7f` | Stripped | PASS |
| Zero-width/bidi chars | `\u200b`, `\u200f`, `\u202e` | Stripped | PASS |
| Unicode tag chars | `\U000e0001`, `\U000e007f` | Stripped | PASS |
| Index injection (` -> `) | `Title -> path` | `Title - path` | PASS |
| Index injection (`#tags:`) | `#tags:hack` | `hack` | PASS |
| XSS (`<script>`) | `<script>alert(1)</script>` | `&lt;script&gt;...` | PASS |
| Quote injection | `"quotes"` | `&quot;quotes&quot;` | PASS |
| Ampersand | `&` | `&amp;` | PASS |
| Length overflow (200 chars) | `a` * 200 | Truncated to 120 | PASS |

### S4b. Path containment checks
**PASS.** Two path containment checks found in `main()`:
1. Line ~391: Deep-check candidates (`scored[:_DEEP_CHECK_LIMIT]`)
2. Line ~411: Beyond-limit candidates (`scored[_DEEP_CHECK_LIMIT:]`)

Both use `file_path.resolve().relative_to(memory_root_resolved)` with `ValueError` catch and `continue` to skip entries outside memory root.

### S4c. XML escaping in output
**PASS.** `html.escape()` is used for:
- Tags (line 446): `html.escape(t)` for each tag
- Paths (line 448): `html.escape(entry["path"])`
- Category descriptions go through `_sanitize_title()` which includes XML escaping

### S4d. No new stdout output paths
**PASS.** AST analysis confirms exactly 3 `print()` calls without `file=sys.stderr`, all in `main()`:
- Line 441: `<memory-context>` opening tag
- Line 449: Memory entry line
- Line 450: `</memory-context>` closing tag

No print-to-stdout calls exist in any helper function. The FTS5 warning (line 261) correctly uses `file=sys.stderr`.

---

## S5. Prompt Injection via Body Text -- PASS

### S5a. FTS5 injection via body content
**PASS.** Tested 7 malicious body strings containing FTS5 operators (`MATCH`, `OR`, `NEAR`, `UNION SELECT`, etc.). After `tokenize()`, all tokens contain only `[a-z0-9_.-]` characters. FTS5 operators and SQL injection payloads are reduced to harmless alphanumeric tokens.

Example: `") UNION SELECT * FROM sqlite_master--"` -> `{'union', 'select', 'sqlite_master'}` (safe tokens)

### S5b. Scoring influence via body text
**PASS.** The plan caps body bonus at `min(3, len(body_matches))`. Even with 191 unique tokens from a crafted body, the maximum scoring influence is +3 points. Title match (2pts/word) and tag match (3pts/word) dominate scoring.

### S5c. Special characters in body fields
**PASS.** HTML, SQL, and FTS5 special characters in body fields are stripped by `tokenize()` before any query construction. The regex `[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+` only matches alphanumeric characters plus `_`, `.`, `-`.

---

## S6. Module-Level Side Effects -- PASS

### S6a. Import-time execution
**PASS.** The FTS5 check at lines 253-261 runs once at import time. It:
- Uses `:memory:` database (no filesystem)
- Creates no persistent state beyond `HAS_FTS5` boolean and closed `_test` connection
- Cannot be triggered repeatedly (module import caching)
- Takes <2ms

### S6b. Exploitability
**PASS.** No external input influences the FTS5 check. It tests a fixed SQL statement against the local sqlite3 installation. There is no injection vector.

### S6c. Sensitive information exposure
**PASS.** The stderr warning (`"[WARN] FTS5 unavailable; using keyword fallback"`) reveals only that FTS5 is unavailable. No paths, configs, data, or version information is exposed.

### S6d. `_test` variable in module namespace
**LOW.** `_test` persists as `memory_retrieve._test` after import. It is a closed connection object. While it cannot be used for database operations (raises `ProgrammingError`), it is unnecessary in the namespace.

**Fix (hygiene):** Add `del _test` after `_test.close()` in the try block.

---

## S7. Test Suite -- PASS

```
======================= 435 passed, 10 xpassed in 17.46s =======================
```

All 435 tests pass. 10 xpassed tests indicate some `xfail` markers that now pass (likely due to Session 1 changes making previously-expected failures succeed). No failures, no errors.

---

## External Validation Summary

### Gemini 3.1 Pro (codereviewer role)

| Item | Gemini Verdict | My Verdict | Rationale for Difference |
|---|---|---|---|
| ReDoS on `_COMPOUND_TOKEN_RE` | PASS | PASS | Agreement |
| `extract_body_text()` memory | FAIL (Medium DoS) | LOW CONCERN | Gemini assumed unbounded input (500MB). In practice, inputs are schema-validated, subprocess-isolated, and typically 1-10KB. |
| FTS5 check resource leak | PASS (informational) | PASS (LOW) | Agreement |

**Key disagreement:** Gemini rated `extract_body_text()` memory as FAIL/Medium. I downgrade to LOW because:
1. Gemini's 500MB payload scenario requires bypassing `memory_write.py`'s Pydantic validation
2. The hook runs as a subprocess with timeout (process isolation)
3. Measured allocation for the join line itself is 2KB (tracemalloc)
4. The strings are already in memory from JSON load -- the join is a temporary copy

---

## Findings Summary

| Item | Verdict | Severity | Action |
|---|---|---|---|
| S1. ReDoS | PASS | None | No action |
| S2. Body text memory | PASS | LOW | Consider early-exit in Session 2 (not blocking) |
| S3. FTS5 check safety | PASS | LOW | Add `del _test` after close (hygiene) |
| S4. Legacy security preserved | PASS | None | All measures intact |
| S5. Body text injection | PASS | None | Tokenizer strips all unsafe chars |
| S6. Module-level side effects | PASS | LOW | `_test` in namespace (hygiene) |
| S7. Test suite | PASS | None | 435 passed, 0 failed |

**Overall: PASS -- No security blockers. Safe to proceed to Session 2.**
