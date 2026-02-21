# V2 Functional Testing - Output Report

## Overall Verdict: CONDITIONAL PASS (3 test failures are pre-existing test staleness, not code defects)

---

## 1. Compile Checks

```
python3 -m py_compile hooks/scripts/memory_retrieve.py  -> OK
python3 -m py_compile hooks/scripts/memory_index.py     -> OK
```
Both files compile cleanly.

---

## 2. pytest Results

```
445 collected, 432 passed, 3 failed, 10 xpassed
```

### Test Failures (all 3 are stale-test conflicts, NOT code bugs)

---

#### FAILURE 1: `test_excludes_short_words` (test_memory_retrieve.py:52)

**What the test expects:**
```python
tokens = tokenize("go to db mx")
assert "db" not in tokens  # expects 2-char token to be excluded
```

**Why it fails:**
Fix C1 changed `len(word) > 2` to `len(word) > 1` to allow 2-char tokens like `ci`, `db`, `ui`. This is an intentional behavior change. The test was written against the OLD behavior.

**Status: STALE TEST** -- test was written before the C1 fix and reflects old behavior. The fix is correct and intentional.

---

#### FAILURE 2: `test_score_description_single_prefix_floors_to_zero` (test_adversarial_descriptions.py:359)

**What the test expects:**
```python
# 0.5 prefix -> int(0.5) = 0, then min(2, 0) = 0
score == 0
```

**What the code now returns:** `1` (because `int(0.5 + 0.5) = int(1.0) = 1`)

**Why it fails:**
Fix B2 changed `int(score)` to `int(score + 0.5)` (round-half-up). With this change, `0.5` no longer floors to `0` -- it rounds up to `1`. The test was written expecting the old floor behavior.

**Status: STALE TEST** -- the test was written before the B2 rounding fix. The B2 fix intentionally changes the behavior.

**Confirmed via mission brief:** Mission asked "Verify score_description(1.5) returns 2 not 1" -- and it does return 2 as intended.

---

#### FAILURE 3: `test_score_description_one_exact_one_prefix` (test_adversarial_descriptions.py:397)

**What the test expects:**
```python
# 1 exact (1.0) + 1 prefix (0.5) = int(1.5) = 1
score == 1
```

**What the code now returns:** `2` (because `int(1.5 + 0.5) = int(2.0) = 2`)

**Why it fails:**
Same B2 fix. `1.5` now rounds to `2` instead of truncating to `1`. The test predates the fix.

**Status: STALE TEST** -- Mission brief explicitly verified that `score_description(1.5)` should return `2` (not `1`). The code is correct; the test is outdated.

---

### Root Cause Summary

All 3 failures are from tests written **before** the C1 and B2 fixes, and they encode the old (buggy) behavior. These are stale/outdated tests, not regressions. The tests `test_adversarial_descriptions.py` and `test_memory_retrieve.py` were both last committed at the same time as the source code (`733f86b`) -- meaning the tests predate the current round of fixes.

The git diff shows that `tests/test_adversarial_descriptions.py` and `tests/test_memory_retrieve.py` were **NOT modified** by the current fix authors (they are not in the working tree changes).

---

## 3. Per-Fix Manual Verification

### A1: Tag XML Injection (PASS)
```python
html.escape('</memory-context>') -> '&lt;/memory-context&gt;'
```
End-to-end test: index line with tag `</memory-context><injected>` produces:
```
#tags:&lt;/memory-context&gt;&lt;injected&gt;,auth
```
**PASS: XML injection in tags is neutralized.**

---

### A2: Path Traversal Containment (PASS)
Tested malicious paths:
- `../../../etc/passwd` -> BLOCKED (ValueError on relative_to)
- `/etc/passwd` (absolute path) -> BLOCKED
- `.claude/memory/../../../etc/secret` -> BLOCKED

Both the top-20 deep-check loop and the fallback loop (`scored[_DEEP_CHECK_LIMIT:]`) have the containment check.
**PASS: Path traversal blocked in both code paths.**

---

### A3: cat_key XML Attribute Injection (PASS)
```python
re.sub(r'[^a-z_]', '', 'cat=key'.lower()) -> 'catkey'
re.sub(r'[^a-z_]', '', 'key"name'.lower()) -> 'keyname'
re.sub(r'[^a-z_]', '', '').lower() -> '' (skipped)
```
**PASS: Attribute injection prevented via key sanitization.**

---

### A4: Path Field XML Escape (PASS)
```python
html.escape('.claude/memory/<script>.json') -> '.claude/memory/&lt;script&gt;.json'
html.escape('.claude/memory/a&b.json') -> '.claude/memory/a&amp;b.json'
```
**PASS: Path XML escaping works correctly.**

---

### B1: Truncation Order Fix (PASS)
Crafted title: `'A' * 119 + '&x'` (121 chars, `&` at position 119):
- **OLD behavior**: escape first (`&amp;` at 119-123), then truncate at 120 -> `'AAAA...A&'` (broken entity!)
- **NEW behavior**: truncate first (`'A'*119 + '&'`), then escape -> `'AAAA...A&amp;'` (clean)

**PASS: Truncation before XML escaping prevents mid-entity cuts.**

---

### B2: score_description Rounding (PASS for intended behavior)
```python
score_description({'architectural', 'rati'}, {'architectural', 'rationale'}) -> 2
```
`1 exact (1.0) + 1 prefix (0.5) = 1.5 -> int(1.5 + 0.5) = int(2.0) = 2`

This matches the mission brief check: "Verify score_description(1.5) returns 2 not 1."
**PASS: Rounding works as intended (2 not 1).**
**Note: 2 stale tests encode the old behavior and fail. Tests need updating.**

---

### B3: grace_period_days Type Coercion (PASS)
```
'90' (string) -> 90
90 (int) -> 90
'invalid' -> 30 (fallback)
None -> 30 (fallback)
-5 -> 0 (clamped to 0)
0 -> 0
```
**PASS: All type coercion cases handled correctly.**

---

### B4: Index Rebuild Title Sanitization (PASS with known limitation)

End-to-end test with injected title `'Auth setup -> fake_path #tags:injection attack'`:
- Generated index.md line: `- [DECISION] Auth setup - fake_path injection attack -> ...`
- Arrow injection neutralized: ` -> ` -> ` - `
- `#tags:` marker removed (content "injection attack" remains as title text)

**PASS: Format injection markers stripped.**

**KNOWN LIMITATION (v1-security LOW, not fixed):** Null bytes are NOT stripped by `_sanitize_index_title()`. `'\x00'.join(title.split())` won't remove null bytes since `str.split()` only splits on whitespace. This was flagged in v1-security as a LOW finding and was not fixed in this round.

```python
_sanitize_index_title('Normal\x00Title') -> 'Normal\x00Title'  # null bytes remain
```

---

### C1: 2-char Tokens Reachable (PASS)
```python
tokenize("ci pipeline failing") -> {'pipeline', 'ci', 'failing'}
tokenize("db connection error") -> {'error', 'db', 'connection'}
tokenize("save as new file") -> {'save', 'file', 'new'}  # 'as' is stop word
tokenize("jwt vs oauth") -> {'jwt', 'oauth'}  # 'vs' is stop word
```
**PASS: 2-char tokens like ci, db, ui are matchable. New stop words prevent flooding.**
**Note: 1 stale test encodes old behavior (db should be excluded) and fails.**

---

### C2: Description Flooding Fix (PASS)
- Unrelated entry (text_score=0): description bonus NOT applied -> final score = 0
- Related entry (text_score=7): description bonus applied -> final score = 9
- Old behavior would have given unrelated entry score=2 (description bonus without guard)

**PASS: Description bonus only applied when text_score > 0.**

---

### C3: Reverse Prefix Matching (PASS)
```python
score_entry({'authentication'}, {'title': 'Auth token setup', 'tags': {'auth'}}) -> 1
```
- `authentication`.startswith(`auth`) = True, `len('auth')` = 4 >= 4 -> match
- `score_entry({'authentication'}, {'title': 'au token', 'tags': set()})` -> 0 (len('au')=2 < 4, blocked)

**PASS: Reverse prefix works for 4+ char targets, blocked for shorter.**

---

### C4: Documentation Comment (PASS)
Code at `memory_retrieve.py:347-350` has the comment:
```python
# Also include entries beyond deep-check limit (no recency bonus, no retired check).
# Safety assumption: index.md only contains active entries (rebuild_index filters inactive).
```
**PASS: Comment-only fix confirmed present.**

---

## 4. Edge Cases

| Test | Result |
|------|--------|
| `tokenize('')` | `set()` -- safe |
| `tokenize('   ')` | `set()` -- safe |
| `_sanitize_title('')` | `''` -- safe |
| `_sanitize_title('x'*500)` | truncated to len 120 |
| `_sanitize_title('Normal\u200bHidden\ufeffText')` | zero-width chars stripped |
| `score_entry({'auth'}, {'title': '', 'tags': set()})` | `0` -- safe |
| `score_description(set(), {'tokens'})` | `0` -- safe |
| `score_description({'tokens'}, set())` | `0` -- safe |
| Very long prompt (many words) | score capped at 2 via min(2, ...) |

---

## 5. Stale Tests That Need Updating

These 3 tests encode pre-fix behavior and must be updated by the code authors:

1. `tests/test_memory_retrieve.py::TestTokenize::test_excludes_short_words` -- expects `db` excluded (old `len > 2`), must change to expect `db` included
2. `tests/test_adversarial_descriptions.py::TestScoringExploitation::test_score_description_single_prefix_floors_to_zero` -- expects 0, new behavior is 1
3. `tests/test_adversarial_descriptions.py::TestScoringExploitation::test_score_description_one_exact_one_prefix` -- expects 1, new behavior is 2

These are **test updates needed**, not code bugs. The fixes are correct.

---

## Summary

| Fix | Functional Status | Notes |
|-----|------------------|-------|
| A1: Tag XML injection | PASS | html.escape works end-to-end |
| A2: Path traversal | PASS | Both loops have containment check |
| A3: cat_key injection | PASS | Regex strips invalid attr chars |
| A4: Path XML escape | PASS | html.escape on paths |
| B1: Truncation order | PASS | Truncate-then-escape prevents mid-entity cuts |
| B2: Rounding | PASS (code), 2 stale tests | 1.5 -> 2 as intended |
| B3: Type coercion | PASS | String, None, negative all handled |
| B4: Index sanitization | PASS | Arrow/tags injection prevented; null bytes unhandled (known LOW) |
| C1: 2-char tokens | PASS (code), 1 stale test | ci/db/ui matchable, stop words prevent flooding |
| C2: Description flooding | PASS | text_score > 0 guard works |
| C3: Reverse prefix | PASS | authentication matches auth (4-char guard works) |
| C4: Documentation | PASS | Comment present |

**3 pytest failures are all stale tests encoding pre-fix behavior, not code regressions.**
