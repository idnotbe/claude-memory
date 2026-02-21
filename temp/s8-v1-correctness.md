# V1 Correctness Review -- test_memory_judge.py & SKILL.md

**Reviewer:** v1-correctness
**Date:** 2026-02-22
**Files reviewed:** `tests/test_memory_judge.py` (649 LOC, 51 tests), `skills/memory-search/SKILL.md`, `hooks/scripts/memory_judge.py` (254 LOC)
**Spec reference:** `research/rd-08-final-plan.md` lines 946-969

---

## Summary

The test file is well-structured with 51 tests across 7 classes. All 51 pass. Coverage of `memory_judge.py` is strong -- every public function and the private `_extract_indices` have dedicated test classes. The SKILL.md judge section is correctly placed and well-documented. Findings below are organized by severity.

---

## HIGH Severity

### H1: `test_call_api_no_key` relies on env mutation outside patch context

**File:** `tests/test_memory_judge.py:79-84`
**Issue:** The test uses `patch.dict(os.environ, {}, clear=True)` then calls `os.environ.pop("ANTHROPIC_API_KEY", None)` inside the `with` block. The `clear=True` already removes all env vars including `ANTHROPIC_API_KEY`, so the `pop` is redundant but harmless. However, the real concern is that `clear=True` wipes ALL environment variables (HOME, PATH, etc.) during the test. If `call_api` or any called code reads any other env var, behavior could differ from production. This test works today only because `call_api` checks `ANTHROPIC_API_KEY` first and short-circuits.

**Impact:** Low functional risk (test passes correctly), but fragile pattern that could mask bugs if `call_api` ever adds another env check.

**Recommendation:** Use `patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""})` or just remove the key: `with patch.dict(os.environ, {}, clear=False):` then `os.environ.pop(...)`. Or more simply: ensure ANTHROPIC_API_KEY is absent without clearing everything.

---

### H2: `test_extract_recent_context_max_turns` assertion may be brittle

**File:** `tests/test_memory_judge.py:187-201`
**Issue:** The test creates 20 messages (10 user + 10 assistant alternating), passes `max_turns=3`, and asserts `len(lines) == 3`. This works because of the interaction between `deque(maxlen=max_turns * 2)` (keeps last 6 messages) and the `parts[-max_turns:]` slice (takes last 3 parts). However, the test doesn't verify WHICH 3 messages appear. If the implementation changes the slicing logic (e.g., bug introduced that takes the first 3 instead of last 3), the test would still pass.

**Impact:** The test verifies count but not ordering/identity of the retained messages.

**Recommendation:** Assert that the 3 retained lines contain the LAST 3 messages (e.g., "Message 17", "Message 18", "Message 19") to catch ordering regressions.

---

## MEDIUM Severity

### M1: No test for `call_api` request body/payload correctness

**File:** `tests/test_memory_judge.py:139-148`
**Issue:** `test_call_api_passes_correct_headers` verifies headers but not the JSON payload body. There is no test that verifies the payload contains the correct model, max_tokens=128, system prompt, and user message. A bug that omits the system prompt or sends the wrong max_tokens would not be caught.

**Recommendation:** Add an assertion that parses the request body (from `req.data`) and checks model, max_tokens, system, and messages fields.

---

### M2: No test for `call_api` with non-text content block type

**File:** `hooks/scripts/memory_judge.py:85`
**Issue:** Line 85 checks `blocks[0].get("type") == "text"`. If the first content block has type `"tool_use"` or similar, `call_api` returns `None`. There's a test for empty content blocks (`test_call_api_empty_content_blocks`) but none for the case where the first block is a non-text type (e.g., `{"type": "tool_use", "id": "..."}`).

**Recommendation:** Add a test where the response has `content: [{"type": "tool_use", ...}]` and verify `call_api` returns `None`.

---

### M3: No test for `call_api` OSError path

**File:** `hooks/scripts/memory_judge.py:87-89`
**Issue:** The except clause catches `OSError` in addition to `URLError`, `HTTPError`, `TimeoutError`, etc. Tests cover `TimeoutError`, `HTTPError`, and `URLError` explicitly but not a standalone `OSError` (e.g., connection reset). While `URLError` is a subclass of `OSError` so it's partially covered, a direct `OSError` test would confirm the catch clause works as expected.

**Impact:** Low -- the existing tests cover the parent class via subclasses. But completeness would be better.

**Recommendation:** Consider adding a test with `side_effect=OSError("Connection reset")`.

---

### M4: No test for `extract_recent_context` symlink traversal

**File:** `hooks/scripts/memory_judge.py:102-105`
**Issue:** The path validation uses `os.path.realpath()` to resolve symlinks, then checks if the resolved path starts with `/tmp/` or `$HOME/`. But there's no test verifying that a symlink pointing outside these directories is rejected. The `test_extract_recent_context_path_validation` test only checks `/etc/passwd` (a literal disallowed path), not a symlink-based escape.

**Recommendation:** Add a test that creates a symlink in `/tmp/` pointing to `/etc/passwd` and verifies the resolved path check still allows/blocks it appropriately. (Note: this specific symlink case would actually PASS the check since `/etc/passwd` doesn't start with `/tmp/` or `$HOME` after resolution -- confirming the defense works.)

---

### M5: `test_judge_candidates_integration` couples to `format_judge_input` internals

**File:** `tests/test_memory_judge.py:511-545`
**Issue:** The integration test pre-computes the order map by calling `format_judge_input` directly, then constructs the mock API response with the correct display index. This is clever but means the test partially tests `format_judge_input` again rather than treating `judge_candidates` as a black box. If the shuffle algorithm changes in `format_judge_input`, this test would need updating even if `judge_candidates` behavior is unchanged.

**Impact:** Coupling concern, not a correctness bug. The alternative (mocking `format_judge_input` inside `judge_candidates`) would be worse because it would not test the real integration.

**Recommendation:** Acceptable trade-off. Document in a comment that this is intentional coupling for end-to-end verification. No code change needed.

---

### M6: Missing test for `judge_candidates` when `transcript_path` is provided but file doesn't exist

**File:** `hooks/scripts/memory_judge.py:236-237`
**Issue:** When `include_context=True` and `transcript_path` points to a nonexistent file, `extract_recent_context` returns `""`, so `context` is empty. This path is tested indirectly (via `test_judge_candidates_no_context` with `include_context=False`) but never explicitly with `include_context=True` + missing file.

**Recommendation:** Add a test with `transcript_path="/tmp/nonexistent.jsonl"` and `include_context=True` to verify graceful degradation (should still work, just no context injected).

---

### M7: SKILL.md says "2 or more results" but doesn't clarify what "results" means post-BM25

**File:** `skills/memory-search/SKILL.md:113`
**Issue:** The judge gating condition says "The search returned 2 or more results." This is slightly ambiguous -- does it mean the raw BM25 result count, or the count after max_results capping? The intent is clear (raw count from the search engine) but the language could be tighter.

**Impact:** Low ambiguity -- agent-interpreted instructions, and the intent is clear from context.

**Recommendation:** No change needed. The existing wording is adequate.

---

## LOW Severity

### L1: Spec calls for ~200 LOC but actual is 649 LOC (51 tests vs 15 planned)

**File:** `research/rd-08-final-plan.md:946` vs `tests/test_memory_judge.py`
**Issue:** The spec planned 15 tests in ~200 LOC. The actual file has 51 tests in 649 LOC. This is a POSITIVE deviation -- significantly more coverage than planned.

**Impact:** None negative. The additional 36 tests cover edge cases the spec didn't anticipate (boolean rejection, negative indices, non-digit strings, html escaping, tags sorting, dedup, human type, etc.).

**Recommendation:** No change needed. Update spec to note actual coverage exceeded plan.

---

### L2: `test_system_prompt_output_format` checks substring not full format

**File:** `tests/test_memory_judge.py:647-648`
**Issue:** The test checks `'{"keep":' in JUDGE_SYSTEM` -- this verifies the substring exists but doesn't verify the full example format `{"keep": [0, 2, 5]}`. A minor point since the prompt is a constant string that won't change at runtime.

**Recommendation:** Acceptable as-is. System prompt tests are sanity checks, not behavioral tests.

---

### L3: `_make_candidate` helper uses set for tags, but source code does `sorted(c.get("tags", set()))`

**File:** `tests/test_memory_judge.py:49-55` vs `hooks/scripts/memory_judge.py:166`
**Issue:** The test helper defaults to `tags={"test"}` (a set), which matches the expected input format in `format_judge_input`. This is correct. However, in production, candidates come from `memory_retrieve.py` which may pass tags as a list. The `sorted()` call handles both, so this is fine.

**Recommendation:** No change needed.

---

### L4: No explicit test that `format_judge_input` with 0 candidates works

**File:** `hooks/scripts/memory_judge.py:144-177`
**Issue:** `format_judge_input` with an empty candidate list would produce a `<memory_data>` block with no entries. While `judge_candidates` guards against empty candidates (returning `[]` early on line 232), there's no explicit test of `format_judge_input([])`.

**Impact:** Near-zero -- `judge_candidates` early-returns before calling `format_judge_input` with empty input.

**Recommendation:** Optional: add a test. Not necessary given the early-return guard.

---

## SKILL.md Review

### Checklist Results

- [x] **Judge section correctly placed** -- Between "Parsing Results" and "Presenting Results" (lines 105-177). This is the right position: search results are parsed, then optionally filtered by judge, then presented.

- [x] **Lenient mode criteria matches spec** -- SKILL.md says "RELATED to the user's query? Be inclusive" (line 147), matching spec line 969: "Which of these memories are RELATED to the user's query? Be inclusive."

- [x] **Graceful degradation documented** -- Lines 163-165: "Show all unfiltered BM25 results. Do not discard results on judge failure." This correctly implements the None-returns-None fallback pattern from `memory_judge.py`.

- [x] **Config gating documented** -- Line 115: `retrieval.judge.enabled` must be true. Line 116 clarifies on-demand search does NOT need ANTHROPIC_API_KEY (uses Task subagent).

- [x] **Comparison table is accurate** -- Lines 170-177 correctly distinguish strict (auto-inject) from lenient (on-demand). The criteria descriptions match `JUDGE_SYSTEM` (strict: "DIRECTLY RELEVANT and would ACTIVELY HELP") and SKILL.md subagent prompt (lenient: "RELATED to the query").

### SKILL.md Notes

- The `<search_results>` XML tag in the subagent prompt (line 133) correctly mirrors the `<memory_data>` tag used in `memory_judge.py`'s JUDGE_SYSTEM prompt. Both include the anti-injection warning about treating content as DATA.

- The subagent prompt specifies `model=haiku` which aligns with the default config model `claude-haiku-4-5-20251001`.

- The "When to Apply" section correctly specifies 2 conditions (2+ results AND judge.enabled). The "Note" clarifying no API key requirement is a useful distinction.

---

## Coverage Matrix

| Function | Tests | Branches covered | Missing branches |
|----------|-------|-----------------|-----------------|
| `call_api` | 8 | success, no key, timeout, HTTP error, URL error, empty blocks, malformed JSON, headers | Non-text block type (M2), OSError (M3), payload body (M1) |
| `extract_recent_context` | 10 | happy path, missing file, flat fallback, max_turns, path validation, list content, truncation, non-msg types, corrupt JSONL, human type | Symlink traversal (M4), empty file (handled implicitly by corrupt test) |
| `format_judge_input` | 9 | shuffle determinism, different seeds, cross-run stability, with/without context, html escape, memory_data tags, truncation, display indices, tag sorting | Empty candidates (L4) |
| `parse_response` | 9 | valid JSON, preamble, string indices, nested braces, invalid, empty keep, out-of-range, missing key, non-list keep | All significant branches covered |
| `_extract_indices` | 5 | boolean rejection, mixed types, non-list, negative, non-digit strings | All branches covered |
| `judge_candidates` | 7 | integration, API failure, empty, parse failure, no context, dedup, keep all | Missing file with include_context=True (M6) |
| `JUDGE_SYSTEM` | 2 | data warning, output format | Sanity checks only -- adequate |

**Overall coverage assessment:** Strong. Every function has tests. The most critical paths (API failure -> None, parse failure -> None, shuffle determinism, index mapping) are well-tested. The gaps identified above are edge cases, not core logic.

---

## Findings Summary

| ID | Severity | Category | Description |
|----|----------|----------|-------------|
| H1 | HIGH | Test Fragility | `clear=True` in env patch wipes all env vars unnecessarily |
| H2 | HIGH | Assertion Quality | `max_turns` test checks count but not identity of retained messages |
| M1 | MEDIUM | Coverage Gap | No test for `call_api` request payload body correctness |
| M2 | MEDIUM | Coverage Gap | No test for non-text content block type in API response |
| M3 | MEDIUM | Coverage Gap | No explicit `OSError` test for `call_api` |
| M4 | MEDIUM | Security | No symlink traversal test for path validation |
| M5 | MEDIUM | Test Design | Integration test couples to `format_judge_input` internals (acceptable) |
| M6 | MEDIUM | Coverage Gap | No test for missing transcript with `include_context=True` |
| M7 | MEDIUM | Documentation | SKILL.md "2 or more results" slightly ambiguous |
| L1 | LOW | Positive | 51 tests exceeds 15 planned (good) |
| L2 | LOW | Assertion | System prompt test checks substring, not full format |
| L3 | LOW | Test Design | Tags as set vs list -- both work, correct as-is |
| L4 | LOW | Coverage Gap | No test for `format_judge_input` with empty candidates |

**Actionable fixes needed:** H1, H2, M1, M2, M6 (5 items)
**Optional improvements:** M3, M4 (2 items)
**Acceptable as-is:** M5, M7, L1-L4 (6 items)
