# Fix Algorithm/Scoring Issues - Output Report

## Status: COMPLETE

All 5 algorithm issues fixed in `hooks/scripts/memory_retrieve.py`. No changes needed in `memory_index.py`.

## Fixes Applied

### B2: int(score) Truncation -> round-half-up (line 153)
**File**: `hooks/scripts/memory_retrieve.py:153`
- Changed `int(score)` to `int(score + 0.5)`
- Uses standard round-half-up instead of Python's banker's rounding (`round()`)
- `round(0.5)` returns 0 (banker's rounding), but `int(0.5 + 0.5)` returns 1 - consistent behavior
- Score 1.5 now correctly becomes 2 (was 1)

### C1: 2-char tokens now reachable (line 67 + lines 33-34)
**File**: `hooks/scripts/memory_retrieve.py:67`
- Changed `len(word) > 2` to `len(word) > 1` - enables 2-char tokens like `ci`, `db`, `ui`, `k8`
- Added `"as", "am", "us", "vs"` to STOP_WORDS to prevent flooding from common 2-char words
- Gemini review identified this risk: without these additions, "save as..." would trigger unrelated matches
- `"go"` was already in STOP_WORDS (good)

### C2: Description category flooding fixed (lines 309-314)
**File**: `hooks/scripts/memory_retrieve.py:309-314`
- Added `and text_score > 0` guard before applying description bonus
- Previously: all entries in a category received description bonus even with 0 title/tag score
- Now: description bonus only boosts entries that already matched on title or tags
- Prevents SESSION_SUMMARY flooding on prompts matching "next steps session" description

### C3: Reverse prefix matching added (lines 120-123)
**File**: `hooks/scripts/memory_retrieve.py:120-123`
- Added `elif any(pw.startswith(target) and len(target) >= 4 for target in combined_targets): score += 1`
- Forward prefix still checked first (no change to existing behavior)
- New reverse prefix: "authentication" in prompt now matches "auth" tag
- Guard: `len(target) >= 4` prevents "cat" (3 chars) from matching "category" - raised from the brief's suggested 3 to 4 based on Gemini review

### C4: Documentation comment added (lines 347-350)
**File**: `hooks/scripts/memory_retrieve.py:347-350`
- Added comment explaining the assumption that entries beyond `_DEEP_CHECK_LIMIT` (rank 21+) are not checked for retired status
- Documents the safety assumption: `index.md` only contains active entries because `rebuild_index()` filters inactive
- No code change needed - comment-only fix as recommended

## External Reviews

### Gemini (via pal clink)
- Confirmed all 5 fixes are sound
- Key modification to B2: recommended `int(score + 0.5)` over `round()` to avoid banker's rounding edge case
- Key modification to C3: recommended raising target guard from 3 to 4 chars to reduce false positives
- Key addition to C1: recommended adding `"as", "am", "us", "vs"` to STOP_WORDS

### Codex
- Unavailable (usage limit exceeded)

## Testing

- `python3 -m py_compile hooks/scripts/memory_retrieve.py` - PASS
- `python3 -m py_compile hooks/scripts/memory_index.py` - PASS
- `pytest tests/test_memory_triage.py tests/test_memory_write.py -v` - 150/150 PASS

## Files Changed

- `hooks/scripts/memory_retrieve.py` - 5 changes (STOP_WORDS addition, tokenize threshold, score_entry reverse prefix, score_description rounding, description flood guard + C4 comment)
- `hooks/scripts/memory_index.py` - No changes (C4 was comment-only in retrieve.py)
