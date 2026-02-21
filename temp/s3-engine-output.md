# Session 3 -- implementer-engine Output Report

**Date:** 2026-02-21
**Status:** COMPLETE
**Task:** Extract shared FTS5 functions to memory_search_engine.py + CLI + full-body search

---

## Summary

Extracted shared FTS5 search functions from `memory_retrieve.py` into a new `memory_search_engine.py` module. Added CLI interface with `--query`, `--root`, `--mode`, `--format`, and `--max-results` flags. Implemented full-body search mode. Fixed all 3 S2 deferred issues (M2, L1, L2).

## Files Changed

### New: `hooks/scripts/memory_search_engine.py` (447 lines)

Shared FTS5 search engine module. Contains:
- **Shared constants:** STOP_WORDS, CATEGORY_PRIORITY, _INDEX_RE, _LEGACY_TOKEN_RE, _COMPOUND_TOKEN_RE, BODY_FIELDS
- **HAS_FTS5:** Module-level FTS5 availability check (warning deferred to callers)
- **tokenize():** Dual tokenizer (legacy + compound)
- **parse_index_line():** Index line parser
- **extract_body_text():** Body content extractor
- **build_fts_index():** New signature `(entries: list[dict], include_body=False)` (L1/L2 fix)
- **build_fts_query():** Smart wildcard FTS5 query builder
- **query_fts():** FTS5 MATCH executor
- **apply_threshold():** Top-K with noise floor
- **CLI functions:** `_check_path_containment()`, `_cli_load_entries()`, `cli_search()`, `main()`

### Modified: `hooks/scripts/memory_retrieve.py` (464 lines, was 653)

Refactored to import shared functions from engine. Kept hook-specific logic:
- **score_entry(), score_description():** Legacy keyword scoring (unchanged)
- **check_recency():** Recency/retired check (unchanged)
- **_sanitize_title():** Output sanitization (unchanged)
- **_check_path_containment():** Path security (kept separate from engine's copy)
- **score_with_body():** Hybrid scoring with M2 fix (reads ALL ~30 results for retired check)
- **_output_results():** XML output formatting (unchanged)
- **main():** Hook entry point, now uses `build_fts_index(entries)` instead of `build_fts_index_from_index(index_path)`

### Modified: `tests/test_v2_adversarial_fts5.py`

Updated imports to use `memory_search_engine` for engine functions and `memory_retrieve` for hook functions. Added `build_fts_index_from_index()` compatibility wrapper (reads index.md then calls `build_fts_index(entries)`).

## S2 Deferred Issues Fixed

### M2: Retired entries beyond top_k_paths
**Problem:** Entries ranked beyond `top_k_paths` in FTS5 results skipped JSON read, so retired status was unchecked.
**Fix:** `score_with_body()` now reads JSON for ALL path-contained FTS5 results (~30 files) to check retired status, not just `top_k_paths` (10). Body extraction still only runs for `top_k_paths` entries. Performance cost: ~20 additional small JSON reads (~3ms on SSD), well within 10s hook timeout.

### L1: Double-read of index.md
**Problem:** FTS5 path read index.md once in main() for emptiness check, then again in `build_fts_index_from_index()`.
**Fix:** main() now parses index entries once into `entries: list[dict]`, then passes to `build_fts_index(entries)`. Single read, single parse.

### L2: build_fts_index_from_index coupled to file format
**Problem:** `build_fts_index_from_index(index_path)` was coupled to reading and parsing index.md directly.
**Fix:** Replaced with `build_fts_index(entries: list[dict], include_body=False)`. Accepts pre-parsed entries, reusable by both hook and CLI. The `include_body` parameter enables full-body FTS5 indexing for search mode.

## CLI Interface

```bash
# Title+tags search (default: top 3, JSON output)
python3 hooks/scripts/memory_search_engine.py --query "authentication" --root /path/to/.claude/memory

# Full-body search (top 10, reads all JSON files)
python3 hooks/scripts/memory_search_engine.py --query "JWT token rotation" --root /path/to/.claude/memory --mode search

# Human-readable output
python3 hooks/scripts/memory_search_engine.py --query "auth" --root /path/to/.claude/memory --format text

# Override max results
python3 hooks/scripts/memory_search_engine.py --query "auth" --root /path/to/.claude/memory --max-results 5
```

JSON output format:
```json
{
  "query": "authentication",
  "mode": "auto",
  "result_count": 2,
  "results": [
    {
      "title": "JWT authentication strategy",
      "category": "DECISION",
      "path": ".claude/memory/decisions/jwt-auth.json",
      "tags": ["auth", "jwt"],
      "score": -3.456
    }
  ]
}
```

## Architecture Decisions

### 1. score_with_body() stays in memory_retrieve.py
**Rationale:** It's tightly coupled to the hook's path resolution logic (`project_root = memory_root.parent.parent`). The CLI uses a different approach (full-body FTS5 table via `include_body=True`), so it doesn't need `score_with_body()` at all. Gemini clink review confirmed this decision.

### 2. Engine core is IO-free, CLI wrapper handles file loading
**Rationale:** Core functions (`build_fts_index`, `build_fts_query`, `query_fts`, `apply_threshold`) have no file I/O. This makes them testable and reusable. The CLI wrapper (`_cli_load_entries`) handles path resolution, containment checks, retired filtering, and body extraction.

### 3. _check_path_containment duplicated in both files
**Rationale:** The function is 4 lines of trivial code. Having it in both files avoids import coupling and keeps each file self-contained for its security model. The engine's copy is scoped under the CLI section. Don't over-DRY security-critical code.

### 4. Full-body search uses separate FTS5 schema (not hybrid scoring)
**Rationale:** For `--mode search`, the CLI builds an FTS5 table with `title, tags, body, path UNINDEXED, category UNINDEXED`. BM25 naturally weights across all three indexed columns. This is cleaner than the hook's hybrid approach (FTS5 title+tags + separate body bonus), which exists because the hook can't afford to read all JSON files at startup.

### 5. sys.path.insert(0, ...) for import safety
**Rationale:** `memory_retrieve.py` runs as a subprocess from arbitrary cwd. Using `sys.path.insert(0, str(Path(__file__).resolve().parent))` ensures `memory_search_engine` is findable and shadows any accidental global packages.

## External Reviews

### Gemini clink (pre-implementation)
**Key findings:**
- Critical: score_with_body() must not be moved without refactoring its IO (accepted, kept in retrieve)
- High: Two divergent body search paths add complexity (accepted, justified by different use cases)
- Medium: sys.path safety net needed (implemented as insert(0,...))
- Low: HAS_FTS5 warning deferred to callers (implemented)
- Positive: build_fts_index decoupling is excellent

### Vibe checks (pre + post implementation)
**Pre:** Plan approved with adjustments (score_with_body stays, M2 strategy confirmed)
**Post:** Implementation validated. Minor docstring fix applied. No structural issues.

## Test Results

```
606 passed in 25.95s
```

All existing tests pass after refactoring. Test file `test_v2_adversarial_fts5.py` updated with compatibility wrapper.

## Verification Checklist

- [x] `python3 -m py_compile hooks/scripts/memory_search_engine.py` -- pass
- [x] `python3 -m py_compile hooks/scripts/memory_retrieve.py` -- pass
- [x] `pytest tests/ -v` -- 606 passed
- [x] All security checks preserved (path containment, title sanitization, XML escaping)
- [x] Legacy fallback path unchanged (score_entry, score_description)
- [x] FTS5 query injection prevention unchanged (parameterized MATCH, alphanumeric-only tokens)
- [x] M2 fix: retired entries checked on ALL FTS5 results
- [x] L1 fix: single index.md read
- [x] L2 fix: build_fts_index takes list[dict]
- [x] CLI: --query, --root, --mode, --format, --max-results flags working
- [x] Full-body search: FTS5 table with body column
- [x] JSON output for skill consumption
