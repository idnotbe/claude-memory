# Phase 3b Output: test_memory_judge.py

**Author:** judge-test-writer
**Date:** 2026-02-22
**Status:** COMPLETE

## Summary

Wrote `tests/test_memory_judge.py` with **51 tests** across 8 test classes (exceeding the 15-test minimum). All tests pass. Full test suite (734 tests) passes with no regressions.

## Test File Stats

- **File:** `tests/test_memory_judge.py`
- **Lines:** ~380 LOC
- **Test count:** 51 (15 required + 36 additional edge cases)
- **Runtime:** 0.15s

## Test Classes & Coverage

| Class | Tests | Covers |
|-------|-------|--------|
| `TestCallApi` | 8 | Success, no key, timeout, HTTP error, URL error, empty content, malformed JSON, header verification |
| `TestExtractRecentContext` | 10 | Nested content, flat fallback, missing file, max_turns, path validation, list content, truncation, non-message types, corrupt JSONL, human type |
| `TestFormatJudgeInput` | 10 | Deterministic shuffle, cross-run stability, different prompts, with/without context, html.escape, memory_data tags, prompt truncation, display indices, sorted tags |
| `TestParseResponse` | 9 | Valid JSON, preamble/markdown, string coercion, nested braces, invalid, empty keep, out-of-range, missing key, non-list keep |
| `TestExtractIndices` | 5 | Boolean rejection, mixed types, non-list input, negative indices, non-digit strings |
| `TestJudgeCandidates` | 7 | End-to-end integration, API failure, empty list, parse failure, no context, dedup, keeps all |
| `TestJudgeSystemPrompt` | 2 | Data warning presence, output format |

## Key Design Decisions

1. **Helper functions** (`_make_api_response`, `_mock_urlopen`, `_make_candidate`, `_write_transcript`) keep tests concise and DRY
2. **Integration tests** (`TestJudgeCandidates`) pre-compute order maps via `format_judge_input` to construct valid mock API responses that test the full pipeline
3. **Dedup test** verifies `sorted(set(...))` behavior in `judge_candidates`
4. **Cross-run stability test** independently computes the sha256 seed and shuffle to verify determinism
5. **Path validation test** uses `/etc/passwd` (always outside `/tmp/` and `$HOME/`)
6. **All mocking** uses `unittest.mock.patch` with `os.environ` patching for API key

## Security-Relevant Tests

- Boolean rejection (`bool` is subclass of `int`)
- Path traversal validation (only `/tmp/` and `$HOME/` accepted)
- HTML escaping of titles, categories, and tags
- `<memory_data>` tag wrapping for prompt injection defense
- System prompt data-not-instructions warning
