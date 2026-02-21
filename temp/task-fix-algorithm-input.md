# Fix Algorithm/Scoring Issues - Input Brief

## Your Task
Fix 5 algorithm issues in `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py` and `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py`.

## Issues

### B2: int(score) Truncation in score_description (LOW)
**Location**: memory_retrieve.py line 144
**Problem**: `int(score)` truncates instead of rounding. `1.5` becomes `1` instead of `2`.
**Current code**:
```python
return min(2, int(score))
```
**Fix**: Use `round()`:
```python
return min(2, round(score))
```

### C1: 2-Char Tokens Permanently Unreachable (MEDIUM)
**Location**: memory_retrieve.py lines 63-66
**Problem**: `tokenize()` discards tokens with `len(word) <= 2`. Technical abbreviations like `ci`, `db`, `ui` can never match.
**Current code**:
```python
if word not in STOP_WORDS and len(word) > 2:
    tokens.add(word)
```
**Fix**: Lower the minimum to 2 chars BUT only for exact tag matching context. One approach: change `len(word) > 2` to `len(word) > 1` (allow 2-char tokens). This is safe because STOP_WORDS already filters common short words (is, an, to, etc.). Two-char meaningful words (ci, db, ui, k8, go) are NOT in STOP_WORDS.

**CAREFUL**: This affects ALL tokenization including title matching. Verify stop words cover common 2-letter words. Check STOP_WORDS set carefully - "go" IS in STOP_WORDS (good), but verify no false positive 2-char matches would flood results.

### C2: Description Category Flooding (LOW)
**Location**: memory_retrieve.py lines 298-302
**Problem**: All entries in a category get the same description bonus. SESSION_SUMMARY has description with common words ("next", "steps", "session"), giving all session entries +2 on many prompts.
**Fix**: Scale description score by inverse frequency. If a category has many entries, the per-entry description bonus should be lower. Simple approach: only apply description bonus to entries that ALREADY have text_score > 0 from title/tag matching.
```python
if text_score > 0:  # Only boost entries that already matched on title/tags
    text_score += score_description(prompt_words, cat_desc_tokens)
```

### C3: Prefix Direction Asymmetry (LOW)
**Location**: memory_retrieve.py lines 112-116
**Problem**: Only checks `target.startswith(prompt_word)`. "authentication" in prompt can't match "auth" tag.
**Current code**:
```python
if any(target.startswith(pw) for target in combined_targets):
    score += 1
```
**Fix**: Add reverse prefix check with lower weight:
```python
# Forward prefix: prompt word is prefix of target (existing)
if any(target.startswith(pw) for target in combined_targets):
    score += 1
# Reverse prefix: target is prefix of prompt word (new, lower weight)
elif len(pw) >= 4 and any(pw.startswith(target) and len(target) >= 3 for target in combined_targets):
    score += 1
```

### C4: Retired Entries at Rank 21+ Skip Retired Check (LOW)
**Location**: memory_retrieve.py lines 329-330 AND memory_index.py
**Problem**: Entries beyond `_DEEP_CHECK_LIMIT` (20) are included without checking retired status from JSON.
**Fix**: Two-part fix:
1. In `memory_index.py` `rebuild_index()`: Already only indexes active entries (line 94), so this is already handled at rebuild time. The gap is when index is stale.
2. In `memory_retrieve.py`: No code change needed if index is kept current. But add a comment documenting this assumption.

**Alternative**: Add `#status:active` or `#status:retired` to index lines so retrieval can filter cheaply. This requires changes to BOTH memory_index.py (output format) and memory_retrieve.py (parsing).

For simplicity, just add a comment in memory_retrieve.py explaining the assumption that index.md only contains active entries.

## Important Notes
- Read files FIRST before making any changes
- Make minimal, focused changes
- After fixing, write output to `/home/idnotbe/projects/claude-memory/temp/task-fix-algorithm-output.md`
- Use vibe-check skill before finalizing
- Use pal mcp clink to get codex/gemini opinions
- Spawn subagents for review
