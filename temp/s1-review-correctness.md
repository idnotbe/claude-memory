# Session 1 Correctness Review

**Reviewer:** reviewer-correctness
**Date:** 2026-02-21
**Scope:** `hooks/scripts/memory_retrieve.py` -- Session 1 changes (dual tokenizer, extract_body_text, HAS_FTS5)
**Test suite:** 435 passed, 10 xpassed, 0 failed

---

## Summary

The Session 1 implementation is **correct and safe for merge**. No blockers found. All existing call sites use `legacy=True`, preserving exact backward compatibility for the keyword scoring path. The new compound tokenizer, body extraction, and FTS5 check are well-implemented with proper defensive coding. A few minor improvements are worth noting for Session 2.

---

## Findings

### F1. Redundant second regex alternative in _COMPOUND_TOKEN_RE -- LOW

**Location:** `hooks/scripts/memory_retrieve.py:57`

```python
_COMPOUND_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+")
```

**Issue:** The second alternative `[a-z0-9]+` can only uniquely match single-character tokens (e.g., `"a"`, `"1"`). For multi-character purely alphanumeric tokens like `"hello"`, the first alternative already matches them (`h` + `ell` + `o`). Since `tokenize()` line 70 filters out `len(w) > 1`, every token uniquely matched by the second alternative is immediately discarded.

**Verified by:** Gemini 3.1 Pro code review (confirming NFA left-to-right alternative evaluation) and manual testing.

**Impact:** No functional impact. The regex is functionally correct. The redundant branch adds negligible overhead (~25% extra regex evaluation time per Gemini's estimate, but absolute time is sub-microsecond on normal inputs).

**Recommendation for Session 2:** Consider simplifying to `re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]")`. Not worth changing now since it works correctly and is already committed.

---

### F2. `_test` variable leaks into module namespace -- LOW

**Location:** `hooks/scripts/memory_retrieve.py:255`

```python
_test = sqlite3.connect(":memory:")
_test.execute("CREATE VIRTUAL TABLE _t USING fts5(c)")
_test.close()
```

**Issue:** The `_test` variable remains accessible as `memory_retrieve._test` after the try block. While the connection is properly closed, the closed connection object persists in module scope.

**Verified by:** `hasattr(mr, '_test')` returns `True` after import.

**Impact:** Negligible. The variable is closed and name-prefixed with underscore (private convention). No functional impact.

**Recommendation for Session 2:** Use `del _test` after `_test.close()` inside the try block to clean up. Not blocking.

---

### F3. BODY_FIELDS omits some schema fields -- MEDIUM

**Location:** `hooks/scripts/memory_retrieve.py:213-223`

**Issue:** Several searchable fields from the JSON schemas are not included in BODY_FIELDS:

| Category | Missing Fields | Type | Impact |
|---|---|---|---|
| decision | `alternatives` | array of {option, rejected_reason} | Medium -- rejected alternatives contain useful search terms |
| decision | `status` | enum string | Low -- enum values (proposed/accepted/deprecated/superseded) rarely useful for search |
| constraint | `kind`, `severity`, `expires` | enum/string | Low -- enums add little search value; expires is a date |
| tech_debt | `status`, `priority` | enum strings | Low -- enum values rarely useful for search |
| preference | `strength` | enum string | Low -- enum values rarely useful |
| preference | `examples` | {prefer: [], avoid: []} | Medium -- examples contain concrete code patterns users might search for |

**Verified by:** Cross-referencing BODY_FIELDS against all 6 `assets/schemas/*.schema.json` files.

**Impact:** Body text extraction will miss some searchable content. The most notable gaps are `decision.alternatives` (rejected options with reasons) and `preference.examples` (concrete code patterns). For Session 1, this has zero impact since `extract_body_text()` is not yet called from any scoring path -- it is scaffolding for Session 2's FTS5 indexing.

**Recommendation for Session 2:** Add `alternatives` to decision fields and `examples` handling (would need special-case for the nested {prefer, avoid} structure). Enum fields can remain excluded.

---

### F4. Compound tokenizer backward compatibility is fully preserved -- CONFIRMED (no finding)

**Verification performed:**
1. All 3 call sites in scoring path use `legacy=True`: line 102 (score_entry), line 351 (main prompt), line 359 (main descriptions)
2. Pure-word inputs produce identical results in legacy and compound modes
3. For inputs with underscores/dots/hyphens (e.g., `"memory_write.py"`), legacy splits into components while compound preserves the full token -- but this difference is irrelevant since only `legacy=True` is used
4. The `tokenize()` function default is `legacy=False`, which is correct for the Session 2 FTS5 use case

**Risk assessment:** Zero regression risk. The only way backward compatibility could break is if a call site accidentally uses `legacy=False` (the default). Code search confirms all 3 existing call sites explicitly pass `legacy=True`.

---

### F5. extract_body_text() handles all edge cases correctly -- CONFIRMED (no finding)

**Verification performed:**
| Input | Expected | Actual | Status |
|---|---|---|---|
| Missing `content` key | `""` | `""` | PASS |
| `content=None` | `""` | `""` | PASS |
| `content="string"` | `""` | `""` | PASS |
| `content=["list"]` | `""` | `""` | PASS |
| Missing `category` | `""` | `""` | PASS |
| Unknown category | `""` | `""` | PASS |
| List with int/bool items | Skip non-strings | Skips correctly | PASS |
| Dict with non-string values | Skip non-strings | Skips correctly | PASS |
| Truncation at 2000 chars | Exactly 2000 | Exactly 2000 | PASS |
| Empty content dict | `""` | `""` | PASS |

The `isinstance(content, dict)` guard on line 230 correctly prevents crashes on non-dict content.

---

### F6. _COMPOUND_TOKEN_RE is safe from ReDoS -- CONFIRMED (no finding)

**Verification performed:**
1. Pattern `[a-z0-9][a-z0-9_.\-]*[a-z0-9]` has no nested or overlapping quantifiers
2. Pathological inputs tested (10,000-char strings of various patterns): all completed in <0.001s
3. Linear O(N) backtracking confirmed by Gemini 3.1 Pro review
4. Hyphen escaping `\-` is correct and unambiguous inside character class

---

### F7. FTS5 availability check is correct -- CONFIRMED (no finding)

**Verification performed:**
1. `except Exception` catches both `ImportError` (sqlite3 not available) and `sqlite3.OperationalError` (FTS5 extension missing)
2. `KeyboardInterrupt` and `SystemExit` are NOT caught (they subclass `BaseException`, not `Exception`) -- correct behavior
3. Warning message goes to stderr (correct -- stdout is consumed by Claude as hook output)
4. Connection is properly closed on success path
5. `:memory:` database has no filesystem side effects

---

### F8. `key_changes` schema mismatch -- LOW

**Location:** `hooks/scripts/memory_retrieve.py:215` / `assets/schemas/session-summary.schema.json:72`

**Issue:** The `session_summary` schema defines `key_changes` as `"type": "array", "items": { "type": "string" }` (array of strings). However, the implementer's test used `key_changes: [{"file": "main.py", "change": "added error handling"}]` (array of dicts). The schema says strings, but real-world data might contain dicts.

`extract_body_text()` handles this correctly via the `isinstance(item, dict)` branch at line 243, which extracts string values from dict items. So even if data deviates from schema, the function gracefully degrades.

**Impact:** None -- the function handles both array-of-strings and array-of-dicts correctly. But the test data doesn't match the schema spec, which could be confusing.

---

## Regex Edge Cases Summary

| Input | Compound Result | Correct? |
|---|---|---|
| `"v2.0"` | `['v2.0']` | Yes |
| `"___"` | `[]` | Yes -- no alphanumeric |
| `"a-"` | `['a']` | Yes -- second alt catches `a`, discarded by len>1 |
| `"-a"` | `['a']` | Yes -- same |
| `"a_b_c_d_e_f"` | `['a_b_c_d_e_f']` | Yes -- no backtracking risk |
| `"hello"` | `['hello']` | Yes -- matched by first alt (h+ell+o) |
| `"a..b"` | `['a..b']` | Yes -- consecutive dots in middle ok |
| `"a__b"` | `['a__b']` | Yes -- consecutive underscores ok |
| `"1.2.3"` | `['1.2.3']` | Yes -- version strings preserved |
| `""` | `[]` | Yes |

---

## Verdict

**PASS -- No blockers. Implementation is correct, backward-compatible, and safe.**

| Severity | Count | Details |
|---|---|---|
| BLOCKER | 0 | -- |
| HIGH | 0 | -- |
| MEDIUM | 1 | F3: BODY_FIELDS omits decision.alternatives and preference.examples |
| LOW | 3 | F1: Redundant regex branch; F2: _test namespace leak; F8: key_changes test data/schema mismatch |

All MEDIUM and LOW findings are non-blocking for Session 1 and can be addressed in Session 2.
