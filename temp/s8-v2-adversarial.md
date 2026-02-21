# V2 Fresh Adversarial Review

**Reviewer:** v2-adversarial
**Date:** 2026-02-22
**Scope:** test_memory_judge.py (58 tests), skills/memory-search/SKILL.md, hooks/scripts/memory_judge.py (254 LOC)
**V1 reviews read:** s8-v1-correctness.md, s8-v1-security.md, s8-v1-adversarial.md

---

## Executive Summary

V1 did solid work on coverage gaps, plan drift, and injection vectors. V2 found **3 HIGH findings** that V1 completely missed, all verified by executing the code. The most critical is a real production bug: `extract_recent_context` crashes with `AttributeError` on valid-JSON-but-non-dict JSONL lines (e.g., `42`, `[1,2,3]`, `null`, `true`). The existing `test_corrupt_jsonl` gives false confidence because it only tests *invalid* JSON, not valid JSON of wrong type. Additionally, `call_api` does not catch `UnicodeDecodeError` from malformed server bytes, and `format_judge_input` crashes on lone surrogates. V2 also found 3 MEDIUM issues in test design (mock self-fulfilling prophecy, mock patching inconsistency, no title-length guard) and 3 LOW issues.

**Severity Distribution:** 3 HIGH, 3 MEDIUM, 3 LOW (all NEW, not V1 repeats)

---

## NEW Findings (with explanation of why V1 missed them)

### H1: `extract_recent_context` crashes on valid-JSON non-dict JSONL lines (BUG)

**Location:** `hooks/scripts/memory_judge.py:115-119`
**Impact:** Unhandled `AttributeError` crash in production; propagates up through `judge_candidates`
**Verified:** YES -- executed and confirmed crash

**The bug:** Line 115 parses each JSONL line with `json.loads(line)`. Line 119 calls `msg.get("type")`. If the parsed JSON is a valid value but not a dict (e.g., `42`, `[1,2,3]`, `"string"`, `null`, `true`), `.get()` raises `AttributeError`. The inner `try/except` only catches `json.JSONDecodeError`. The outer `try/except` only catches `(FileNotFoundError, OSError)`. `AttributeError` is not a subclass of either.

**Proof of crash:**
```python
# JSONL with line: 42
extract_recent_context("/tmp/test.jsonl")  # -> AttributeError: 'int' object has no attribute 'get'

# JSONL with line: [1,2,3]
extract_recent_context("/tmp/test.jsonl")  # -> AttributeError: 'list' object has no attribute 'get'

# JSONL with line: null
extract_recent_context("/tmp/test.jsonl")  # -> AttributeError: 'NoneType' object has no attribute 'get'
```

**Why V1 missed it:** V1-correctness mentioned `test_corrupt_jsonl` as "handled implicitly by corrupt test" (Coverage Matrix, line 182). V1-adversarial focused on message identity and deque interaction. V1-security noted path validation gaps. None of them executed the code with non-dict JSONL input. The assignment specifically asked "What if `extract_recent_context` encounters a JSONL line that is valid JSON but not a dict?" -- this is it.

**Fix:** Add `if not isinstance(msg, dict): continue` after `json.loads(line)` on line 115, or broaden the inner except to catch `(json.JSONDecodeError, AttributeError)`.

**Test needed:**
```python
def test_extract_recent_context_non_dict_jsonl(self, tmp_path):
    """Valid JSON lines that are not dicts are skipped without crash."""
    transcript = tmp_path / "transcript.jsonl"
    with open(transcript, "w") as f:
        f.write("42\n")
        f.write("[1, 2, 3]\n")
        f.write('"just a string"\n')
        f.write("null\n")
        f.write("true\n")
        f.write(json.dumps({"type": "user", "content": "valid line"}) + "\n")
    result = extract_recent_context(str(transcript), max_turns=5)
    assert "valid line" in result
```

---

### H2: `call_api` does not catch `UnicodeDecodeError` (BUG)

**Location:** `hooks/scripts/memory_judge.py:83, 87-89`
**Impact:** Unhandled exception if API returns non-UTF-8 bytes
**Verified:** YES -- confirmed via exception hierarchy analysis

**The bug:** Line 83: `json.loads(resp.read().decode("utf-8"))`. If the server returns malformed bytes (truncated gzip, encoding mismatch), `.decode("utf-8")` raises `UnicodeDecodeError`. The except clause on lines 87-89 catches `(URLError, HTTPError, json.JSONDecodeError, TimeoutError, OSError, KeyError, IndexError)` but NOT `UnicodeDecodeError` or its parent `ValueError`.

Exception hierarchy: `UnicodeDecodeError -> UnicodeError -> ValueError -> Exception`. None of `ValueError`, `UnicodeError`, or `UnicodeDecodeError` appear in the except clause.

**Why V1 missed it:** V1-correctness focused on missing exception *types* (OSError, non-text block) that ARE in the clause or have subclass coverage. V1-security focused on injection vectors. V1-adversarial focused on payload and dead code. None analyzed the `.decode("utf-8")` call path independently from the `json.loads()` call path.

**Fix:** Add `ValueError` (covers `UnicodeDecodeError` and `json.JSONDecodeError`) to the except clause, or add `UnicodeDecodeError` specifically.

**Test needed:**
```python
def test_call_api_unicode_decode_error(self):
    """Returns None when response contains invalid UTF-8 bytes."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"\xff\xfe{invalid utf8"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        result = call_api("system", "msg")
    assert result is None
```

---

### H3: `format_judge_input` crashes on lone surrogates in user_prompt (BUG)

**Location:** `hooks/scripts/memory_judge.py:159`
**Impact:** Unhandled `UnicodeEncodeError` crash
**Verified:** YES -- executed `format_judge_input('\ud800', ...)` and confirmed crash

**The bug:** Line 159: `hashlib.sha256(user_prompt.encode()).hexdigest()`. The `.encode()` call uses UTF-8 by default, which rejects lone surrogate code points (`\ud800`-`\udfff`). This raises `UnicodeEncodeError` which propagates uncaught through `judge_candidates`.

**Why V1 missed it:** V1 focused on prompt truncation, shuffle behavior, and HTML escaping. No reviewer tested non-standard Unicode input to `format_judge_input`. The assignment specifically mentioned ">10KB titles" but the surrogate issue is on the prompt side.

**Practical risk:** LOW in production (user prompts rarely contain lone surrogates), but this is a defensive coding gap. The function's docstring promises deterministic output; it should not crash on any string input Python can represent.

**Fix:** Use `user_prompt.encode("utf-8", errors="replace")` or `errors="surrogatepass"`.

---

### M1: `test_judge_candidates_no_context` is a self-fulfilling mock prophecy

**Location:** `tests/test_memory_judge.py:629-648`
**Impact:** Test cannot fail because it pre-computes the correct answer and feeds it back

**The test:**
1. Calls `format_judge_input(prompt, candidates)` to get `order_map`
2. Computes `display_idx = order_map.index(0)` -- the "correct" answer
3. Mocks the API to return `{"keep": [display_idx]}`
4. Calls `judge_candidates(prompt, candidates, include_context=False)`
5. Asserts `len(result) == 1`

This tests a tautological round-trip: "if the API returns the correct answer, the function returns the correct output." The test CANNOT fail unless the function is completely broken (wrong shuffle seed, wrong parse, etc.) -- but those are already tested by other tests. This specific test adds no discriminating power for the `include_context=False` path.

**Why V1 missed it:** V1-adversarial analyzed mock quality (line 199-215 "Tests Testing the Mock vs Real Code") and concluded "No tests are testing the mock instead of real code." They examined the pattern but did not identify this specific self-fulfilling prophecy because they focused on whether mocks were *appropriate* rather than whether the test could *fail*.

**What would be a better test:** Mock the API to return `{"keep": []}` (empty) and verify the function returns `[]` with `include_context=False`. This tests the same code path without the tautological setup.

---

### M2: Mock patching location is inconsistent between TestCallApi and TestJudgeCandidates

**Location:** `tests/test_memory_judge.py` -- TestCallApi vs TestJudgeCandidates
**Impact:** TestCallApi patches the global `urllib.request.urlopen`; TestJudgeCandidates patches `memory_judge.urllib.request.urlopen`

**Details:**
- `TestCallApi` (lines 70-174): `patch("urllib.request.urlopen", ...)`
- `TestJudgeCandidates` (lines 566+): `patch("memory_judge.urllib.request.urlopen", ...)`

The global patch in TestCallApi could leak to other urllib callers in the test process during the `with` block. This doesn't cause failures today (tests are fast, no concurrent urllib use), but it's a latent cross-test contamination vector. The TestJudgeCandidates approach (patching the module reference) is correct.

**Why V1 missed it:** V1-adversarial reviewed mock strategy but focused on whether mocks test real code (lines 199-215). The inconsistency in WHERE the mock is applied was not analyzed.

**Fix:** Change TestCallApi to use `patch("memory_judge.urllib.request.urlopen", ...)` for consistency.

---

### M3: No title/tags length guard in `format_judge_input` -- unbounded output

**Location:** `hooks/scripts/memory_judge.py:164-170`
**Impact:** A candidate with a >10KB title produces a >10KB line in the judge prompt, potentially exceeding API input limits

**Details:** Line 172 truncates `user_prompt` to 500 chars. But lines 167-170 apply no truncation to `title`, `category`, or `tags`. A malicious or buggy memory with a 100KB title would produce a 100KB+ formatted string sent to the API with `max_tokens=128`. The API call would likely succeed (Anthropic accepts large inputs) but waste tokens and money.

Verified: `format_judge_input("query", [{"title": "A" * 15000, ...}])` produces a 15KB+ result.

**Why V1 missed it:** The assignment specifically asked about ">10KB titles" but V1 focused on prompt truncation and HTML escaping. V1-correctness L4 mentioned empty candidates but not oversized ones. V1-adversarial mentioned 500-char prompt truncation (L4) but didn't check title truncation.

**Fix:** Add `title = html.escape(c.get("title", "untitled")[:200])` (truncate before escaping to limit output size).

---

### L1: `test_extract_recent_context_corrupt_jsonl` gives false confidence

**Location:** `tests/test_memory_judge.py:291-300`
**Impact:** Test name and docstring imply graceful handling of all corrupt input, but only tests invalid JSON syntax

**The test writes:**
- `"not valid json\n"` -- caught by `json.JSONDecodeError`
- `"{bad\n"` -- caught by `json.JSONDecodeError`

**What it does NOT test:**
- `"42\n"` -- valid JSON, wrong type -> CRASHES (see H1)
- `"[1,2]\n"` -- valid JSON, wrong type -> CRASHES
- `"null\n"` -- valid JSON, wrong type -> CRASHES

The docstring says "Skips corrupt lines gracefully" but the function does NOT skip non-dict JSON lines gracefully. The test passes because it never exercises the failing path.

**Why V1 missed it:** V1-correctness noted "empty file (handled implicitly by corrupt test)" in the coverage matrix, implying the test was adequate. The distinction between "invalid JSON" and "valid JSON of wrong type" was not analyzed.

---

### L2: `format_judge_input` silently mangles string-typed `tags`

**Location:** `hooks/scripts/memory_judge.py:166`
**Impact:** If `tags` is a string instead of set/list, `sorted()` iterates characters

**Verified:** `format_judge_input("q", [{"title": "T", "category": "c", "tags": "single-tag"}])` produces tags output: `-, a, e, g, g, i, l, n, s, t` (sorted individual characters).

This is not a crash, but it's a silent data corruption that produces confusing output. No test covers this case. In production, `tags` should always be a set/list (validated by `memory_write.py`), but `format_judge_input` accepts raw dicts and does no type checking.

**Why V1 missed it:** V1-correctness L3 noted "tags as set vs list -- both work." V1 did not test tags as a *string*. V1-adversarial did not test malformed candidate dicts beyond the `_extract_indices` level.

---

### L3: SKILL.md "Processing Judge Output" has no bounds validation instruction

**Location:** `skills/memory-search/SKILL.md:155-158`
**Impact:** If haiku subagent returns out-of-range indices (e.g., `{"keep": [0, 99]}`), the agent would try to access a non-existent result

**Details:** The SKILL.md says:
1. "Parse the subagent's response as JSON. Extract the `keep` array."
2. "Filter the search results to only include indices listed in `keep`."

There is no instruction to:
- Validate indices are within `[0, total_results-1]`
- Handle markdown-wrapped JSON responses (unlike `memory_judge.py` which has the `find`/`rfind` fallback)
- Deduplicate indices

The API-based judge (`memory_judge.py`) has `_extract_indices` with bounds checking, boolean rejection, string coercion, and dedup. The SKILL.md on-demand judge has none of these safeguards documented.

**Why V1 missed it:** V1-correctness M7 noted "2 or more results" ambiguity but not the missing validation. V1-adversarial M5 focused on the query injection vector. V1-security focused on snippet sanitization. None analyzed the *output processing* instructions for completeness.

---

## Tests-That-Can't-Fail Analysis

| Test | Can it fail? | Why | Verdict |
|------|-------------|-----|---------|
| `test_judge_candidates_no_context` | Only if pipeline is totally broken | Pre-computes correct answer, feeds it to mock | WEAK -- self-fulfilling prophecy (M1) |
| `test_judge_candidates_keeps_all` | Only if `_extract_indices` is totally broken | `keep=[0,1,2]` with 3 candidates always keeps all regardless of shuffle | WEAK -- no selectivity tested |
| `test_judge_candidates_empty_list` | Only if early-return removed | `judge_candidates("query", [])` -> `[]` is a trivial early-return | ACCEPTABLE -- tests the guard |
| `test_extract_recent_context_corrupt_jsonl` | Always passes | Only tests invalid JSON (caught), not valid-non-dict (crashes) | FALSE CONFIDENCE (L1/H1) |
| `test_format_judge_input_without_context` | Only if default behavior changes | Negative assertion on empty-context case | ACCEPTABLE -- sanity check |
| `test_system_prompt_output_format` | Only if constant changes | Substring check on string constant | ACCEPTABLE -- regression guard |

**Tests where mock guarantees the outcome (mock leakage):**
- `test_judge_candidates_no_context`: Mock response is computed from `format_judge_input` output, creating a closed loop. The test validates wiring, not logic.
- `test_judge_candidates_dedup_indices`: Mock sends duplicate of the "correct" index. Test validates `sorted(set(...))` but the specific index is pre-computed from the real function.
- `test_judge_candidates_keeps_all`: Mock sends all indices `[0,1,2]`. With 3 candidates, any valid implementation returns all 3.

---

## Summary Table

| ID | Severity | Category | Finding | V1 Coverage | New? |
|----|----------|----------|---------|-------------|------|
| H1 | HIGH | Bug | `extract_recent_context` crashes on valid-JSON non-dict JSONL | V1 said "handled implicitly" | YES |
| H2 | HIGH | Bug | `call_api` does not catch `UnicodeDecodeError` from `.decode()` | V1 tested other exception types | YES |
| H3 | HIGH | Bug | `format_judge_input` crashes on lone surrogate in prompt | V1 did not test exotic Unicode | YES |
| M1 | MEDIUM | Test Design | `test_judge_candidates_no_context` is self-fulfilling mock | V1 said "no tests test the mock" | YES |
| M2 | MEDIUM | Test Design | Inconsistent mock patching location (global vs module) | V1 missed | YES |
| M3 | MEDIUM | Missing Guard | No title/tags length truncation in `format_judge_input` | V1 missed (>10KB titles) | YES |
| L1 | LOW | False Confidence | `test_corrupt_jsonl` only tests invalid JSON, not wrong-type JSON | V1 said "adequate" | YES |
| L2 | LOW | Silent Bug | String-typed `tags` silently mangled to sorted characters | V1 said "both work" for set/list | YES |
| L3 | LOW | SKILL.md Gap | No bounds validation in judge output processing instructions | V1 focused on input injection | YES |

**Actionable fixes needed:** H1, H2 (real bugs that can crash in production)
**Should fix:** H3, M3 (defensive coding improvements)
**Test improvements:** M1, M2, L1 (strengthen test confidence)
**Documentation:** L2, L3 (document known limitations)
