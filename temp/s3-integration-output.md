# Session 3 -- implementer-integration Output Report

**Date:** 2026-02-21
**Status:** COMPLETE
**Task:** Add 0-result hint + update CLAUDE.md + sync tokenizer documentation

---

## Summary

Added 0-result hint injection to `memory_retrieve.py` at 3 scoring exit points, updated `CLAUDE.md` with 5 changes reflecting the new FTS5 search engine architecture, and documented the intentional tokenizer difference in `memory_candidate.py`.

## Files Changed

### Modified: `hooks/scripts/memory_retrieve.py` (3 hint insertions)

Added HTML comment hint at 3 exit points where a valid query returns 0 results:

1. **FTS5 path** (line 382): After `score_with_body()` returns empty results, inside the `if fts_query:` block. This naturally gates the hint to cases where a valid query existed (not all stop-words).

2. **Legacy path -- no scored** (line 418-420): After the scoring loop finds 0 entries with score > 0. The legacy path already exits at line 394 if `prompt_words` is empty, so this is always a valid-query case.

3. **Legacy path -- no final** (line 456-459): After deep-check filters out all candidates (retired, path traversal, etc). All entries scored but none survived containment/retired checks.

**Hint wording** (softened per Gemini clink review):
```
<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->
```

**Where hints are NOT added** (intentional):
- Empty index (`if not entries:` line 359) -- no memory data exists, not a search miss
- Empty/short prompt (line 288-289) -- greeting/ack, no search attempted
- All stop-words / no valid query tokens (FTS5 path, `fts_query` is None) -- nothing meaningful to search for
- Config disabled / max_inject=0 (lines 323, 346) -- retrieval intentionally off

### Modified: `CLAUDE.md` (5 changes)

1. **Architecture table** (line 18): Updated UserPromptSubmit description from "Python keyword matcher" to "FTS5 BM25 keyword matcher injects relevant memories (fallback: legacy keyword)"

2. **Key Files table** (lines 40-41):
   - Updated `memory_retrieve.py` role to "FTS5 BM25 retrieval hook" with deps "stdlib + memory_search_engine"
   - Added `memory_search_engine.py` with role "Shared FTS5 engine, CLI search interface" and deps "stdlib + sqlite3"

3. **Tokenizer note** (line 49): Added note between Key Files table and Config line documenting the intentional tokenizer difference: `memory_candidate.py` uses 3+ char tokens, `memory_search_engine.py`/`memory_retrieve.py` use 2+ chars.

4. **Security Considerations** (line 120): Added item #5: "FTS5 query injection -- Prevented: alphanumeric + `_.-` only, all tokens quoted. In-memory database (`:memory:`) -- no persistence attack surface. Parameterized queries (`MATCH ?`) prevent SQL injection."

5. **Quick Smoke Check** (lines 131, 137): Added `memory_search_engine.py` to compile check list and added FTS5 search command example.

### Modified: `hooks/scripts/memory_candidate.py` (comment added)

Added 4-line comment above `_TOKEN_RE` (lines 71-75) explaining the intentional tokenizer difference:
```python
# NOTE: Uses len(w) > 2 filter (3+ char tokens). This intentionally differs from
# memory_search_engine.py / memory_retrieve.py which use len(w) > 1 (2+ char tokens).
# Shorter tokens improve retrieval recall but would add noise to candidate selection
# scoring, where precision matters more. Do NOT "sync" these without testing impact.
```

Decision: Do NOT change `memory_candidate.py`'s threshold. Changing it could affect ACE candidate selection behavior. Document only.

## Cross-File Consistency Check

- `memory_search_engine.py` exports: tokenize, parse_index_line, build_fts_index, build_fts_query, query_fts, apply_threshold, extract_body_text, STOP_WORDS, CATEGORY_PRIORITY, HAS_FTS5, BODY_FIELDS
- `memory_retrieve.py` imports exactly these symbols (lines 24-36)
- Both use `sqlite3.connect(":memory:")` for FTS5
- Both use `_COMPOUND_TOKEN_RE` for FTS5 path and `_LEGACY_TOKEN_RE` for legacy fallback
- Compile check passed for all three modified files

## External Reviews

### Gemini clink (post-implementation)
**Key findings:**
- Critical: None
- High: None
- Medium: Imperative hint wording ("Use /memory:search...") may cause Claude to needlessly execute search on general programming questions. **Fix applied:** Softened to conditional "No matching memories found. If project context is needed, use /memory:search <topic>"
- Low: AI not told a search was attempted. **Addressed** by "No matching memories found" prefix.
- Positive: Logic correctly avoids hints for empty database, stop-word-only prompts, and deep-check filtering.

### Vibe checks (pre + post implementation)
**Pre:** Approach confirmed valid, especially the concern about distinguishing "no valid tokens" from "valid query, no results". Gemini agreed only the latter should get the hint.
**Post:** All deliverables verified complete. No scope creep. Pre-existing CLAUDE.md issue noted but correctly deferred.

## Pre-existing Issue Noted (NOT fixed -- out of scope)

CLAUDE.md line 114 says "fallback to default 5 on parse failure" but `memory_retrieve.py` now uses default 3 (changed in Session 2 when FTS5 was introduced -- BM25 is more precise, fewer results needed). This is a pre-existing documentation drift, not part of Task #3.

## Known Gap for Review

- `skills/memory-search/SKILL.md` documents `--include-retired` flag but `memory_search_engine.py` CLI does not implement it. The `_cli_load_entries()` function always filters retired entries. Reviewers should flag this.

## Test Results

```
606 passed in 25.18s
```

All existing tests pass. No new tests added (hint injection is output-only; testing requires integration tests with full hook stdin/stdout simulation).

## Verification Checklist

- [x] `python3 -m py_compile hooks/scripts/memory_retrieve.py` -- pass
- [x] `python3 -m py_compile hooks/scripts/memory_candidate.py` -- pass
- [x] `python3 -m py_compile hooks/scripts/memory_search_engine.py` -- pass
- [x] `pytest tests/ -v` -- 606 passed
- [x] 0-result hint: FTS5 path (valid query, no results) -- added
- [x] 0-result hint: Legacy path (no scored entries) -- added
- [x] 0-result hint: Legacy path (no final after deep check) -- added
- [x] 0-result hint: NOT at empty-index exit -- verified
- [x] 0-result hint: NOT at empty/short prompt exit -- verified
- [x] 0-result hint: NOT at all-stop-words exit (FTS5) -- verified
- [x] CLAUDE.md: Architecture table updated -- done
- [x] CLAUDE.md: Key Files table updated (+engine, updated retrieve) -- done
- [x] CLAUDE.md: Security section FTS5 note added -- done
- [x] CLAUDE.md: Quick Smoke Check FTS5 commands added -- done
- [x] CLAUDE.md: Tokenizer note added -- done
- [x] memory_candidate.py: Tokenizer difference comment added -- done
- [x] Gemini clink review: 1 medium finding addressed (hint wording softened)
- [x] Vibe check pre-implementation: approach validated
- [x] Vibe check post-implementation: all deliverables confirmed
