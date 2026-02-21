# Session 9 Implementer Notes -- ThreadPoolExecutor

**Date:** 2026-02-22
**Task:** Task #1 -- Add ThreadPoolExecutor(max_workers=2) to memory_judge.py
**Status:** COMPLETE

## Files Changed

| File | Changes | LOC Delta |
|------|---------|-----------|
| `hooks/scripts/memory_judge.py` | Added parallel batch splitting | +106 (256 -> 362) |
| `tests/test_memory_judge.py` | Added 26 new tests (5 classes) | +26 tests (60 -> 86) |

## Design Decisions

### 1. Module constants over config keys
- `_PARALLEL_THRESHOLD = 6` and `_EXECUTOR_TIMEOUT_PAD = 2.0` as module constants
- Rationale: These are implementation details, not user-tunable config. Adding config parsing would consume LOC budget without user benefit.
- Source: Vibe-check recommendation

### 2. shuffle_seed parameter on format_judge_input()
- **Self-critique catch:** Initial implementation modified `user_prompt` for batch-specific shuffling (`f"{user_prompt}_batch{offset}"`), which polluted the "User prompt:" line in the API payload the judge LLM sees.
- **Fix:** Added optional `shuffle_seed` parameter to `format_judge_input()`. When provided, it overrides the SHA256 seed derivation while keeping `user_prompt` in the formatted output.
- Backward-compatible: `shuffle_seed=None` default preserves existing behavior.

### 3. Total deadline enforcement
- Codex 5.3 flagged risk of timeout stacking (per-future waits + sequential fallback).
- Solution: `deadline = time.monotonic() + timeout + _EXECUTOR_TIMEOUT_PAD`, passed to `as_completed(timeout=max(0.1, deadline - time.monotonic()))`.
- Each future's internal `call_api()` already has `timeout` on `urllib.request.urlopen`, so threads terminate naturally.

### 4. Fail-fast on any batch failure
- If any batch returns `None` (API failure or parse failure), the entire parallel attempt returns `None`.
- `judge_candidates()` then falls through to the sequential single-batch path.
- If sequential also fails, returns `None` to the caller for conservative fallback.

### 5. Semantic acceptability of batch splitting
- **Codex 5.3** (cautious): Splitting changes judge's comparison context; borderline candidates may be treated differently.
- **Gemini 3 Pro** (supportive): JUDGE_SYSTEM demands absolute binary classification ("A memory QUALIFIES if..."), not relative ranking. Evaluating subsets independently is mathematically equivalent. Smaller batches may actually improve precision by reducing "lost in the middle" effect.
- **Resolution:** Proceeded with splitting. The judge prompt is absolute classification, and the performance benefit of parallelism outweighs the minor semantic change.

## Architecture

```
judge_candidates()
  |
  +-- len > 6? ---> _judge_parallel()
  |                   |
  |                   +-- ThreadPoolExecutor(max_workers=2)
  |                   |     +-- _judge_batch(batch1, offset=0)
  |                   |     +-- _judge_batch(batch2, offset=mid)
  |                   |
  |                   +-- Merge global indices
  |                   |
  |                   +-- Failure? -> return None
  |
  +-- (fallback or len <= 6) ---> Sequential single-batch (original path)
```

### 3-Tier Timeout Defense
1. **Per-call timeout** (default 3s): `urllib.request.urlopen(timeout=...)` in `call_api()`
2. **Executor deadline** (per-call + 2s): `as_completed(timeout=deadline - now)` in `_judge_parallel()`
3. **Hook timeout** (15s): External Claude Code hook timeout in `hooks.json`

## New Functions

### `_judge_batch(user_prompt, batch, global_offset, context, model, timeout) -> list[int] | None`
- Judges a single batch of candidates
- Uses `shuffle_seed` for independent anti-position-bias per batch
- Returns global indices (batch-local + offset) or None on failure
- Pure function, thread-safe (no shared mutable state)

### `_judge_parallel(user_prompt, candidates, context, model, timeout) -> list[int] | None`
- Splits candidates at midpoint (`len // 2`)
- Submits 2 batches to ThreadPoolExecutor
- Enforces total deadline via `as_completed(timeout=...)`
- Any failure returns None for fallback

### Modified: `format_judge_input(..., shuffle_seed=None)`
- New optional parameter: `shuffle_seed` overrides SHA256 seed derivation
- User prompt text in output is unchanged (always shows original prompt)
- Backward-compatible: None default preserves existing behavior

### Modified: `judge_candidates()`
- Signature unchanged (backward-compatible)
- New parallel path for len > _PARALLEL_THRESHOLD
- Falls back to sequential on parallel failure

## Thread Safety Analysis

| Component | Thread-safe? | Reason |
|-----------|-------------|--------|
| `urllib.request.urlopen` | Yes | Per-call request objects, no shared state |
| `hashlib.sha256` | Yes | Per-call instance in format_judge_input |
| `random.Random(seed)` | Yes | Per-call instance, not module-level rng |
| `html.escape` | Yes | Pure function |
| `json.loads/dumps` | Yes | Pure functions |
| `format_judge_input()` | Yes | All locals, no shared mutable state |
| `parse_response()` | Yes | All locals, no shared mutable state |
| `_judge_batch()` | Yes | Composes thread-safe functions only |

## Test Descriptions (26 new tests)

### TestConstants (2 tests)
- `test_parallel_threshold_value`: Verifies _PARALLEL_THRESHOLD == 6
- `test_executor_timeout_pad_value`: Verifies _EXECUTOR_TIMEOUT_PAD == 2.0

### TestJudgeBatch (6 tests)
- `test_judge_batch_returns_global_indices`: Offset correctly added to local indices
- `test_judge_batch_offset_zero`: First batch (offset=0) returns unmodified indices
- `test_judge_batch_api_failure_returns_none`: API timeout returns None
- `test_judge_batch_parse_failure_returns_none`: Unparseable response returns None
- `test_judge_batch_independent_shuffle`: Different offsets produce different shuffles
- `test_judge_batch_empty_keep`: Empty keep returns empty list (not None)

### TestJudgeParallel (7 tests) -- mocks _judge_batch for isolation
- `test_parallel_splits_and_merges`: 8 candidates, both batches keep all
- `test_parallel_partial_keep`: Subset keep from each batch merges correctly
- `test_parallel_one_batch_fails_returns_none`: One None -> entire result None
- `test_parallel_timeout_returns_none`: Slow batch triggers deadline
- `test_parallel_empty_keep_both_batches`: Both empty -> empty (not None)
- `test_parallel_odd_candidate_count`: 7 candidates split 3+4
- `test_parallel_exception_in_batch_returns_none`: RuntimeError triggers fallback

### TestJudgeCandidatesParallel (10 tests)
- `test_parallel_triggered_above_threshold`: 8 candidates -> 2 API calls (parallel)
- `test_sequential_for_at_threshold`: 6 candidates -> 1 API call (sequential)
- `test_parallel_fallback_to_sequential`: Parallel fails -> 3 total API calls
- `test_parallel_both_fail_sequential_also_fails`: All fail -> None
- `test_parallel_preserves_candidate_order`: Results in original order
- `test_zero_candidates`: Empty list -> empty list
- `test_one_candidate`: Single candidate -> sequential
- `test_two_candidates`: Two candidates -> sequential
- `test_exact_threshold_plus_one`: 7 candidates -> parallel
- `test_large_candidate_list`: 30 candidates split 15+15

### TestFormatJudgeInput (1 new test)
- `test_format_judge_input_shuffle_seed_override`: Seed changes order, prompt unchanged in output

## External Reviews

### Codex 5.3 (codereviewer role)
- No critical issues
- HIGH: Semantic regression from splitting (decided acceptable per Gemini's analysis)
- HIGH: Timeout stacking (addressed with deadline enforcement)
- MEDIUM: Index mapping (addressed with offset-based mapping)
- Thread safety confirmed sound

### Gemini 3 Pro (codereviewer role)
- Design is "structurally sound, thread-safe, and an excellent enhancement"
- HIGH: Must catch `concurrent.futures.TimeoutError` from `future.result()` (addressed)
- MEDIUM: Anthropic rate limits may increase 429s (gracefully handled by fallback)
- LOW: Same shuffle seed for equal-size batches (addressed with `shuffle_seed` param)
- Confirmed: batch splitting is semantically acceptable for absolute classification

## Test Results
- **86 tests in test_memory_judge.py**: All pass
- **769 tests total across test suite**: All pass
- No regressions in existing functionality
