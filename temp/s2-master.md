# Session 2: FTS5 Engine Core -- Master Orchestration

**Date:** 2026-02-21
**Status:** COMPLETE
**Scope:** Phase 2a from rd-08-final-plan.md (~200-240 LOC, 6-8 hours)

---

## Session 2 Checklist (from plan)

- [ ] `build_fts_index_from_index()` -- parse index.md into FTS5 in-memory table
- [ ] `build_fts_query()` -- smart wildcard (compound=phrase, single=prefix)
- [ ] `query_fts()` -- FTS5 MATCH query executor
- [ ] `apply_threshold()` -- pure Top-K with 25% noise floor
- [ ] `score_with_body()` -- hybrid scoring with **path containment security check** (MUST preserve)
- [ ] FTS5 fallback: when `HAS_FTS5=False`, route to preserved keyword path using `_LEGACY_TOKEN_RE`
- [ ] Config branch: read `match_strategy`, support `"fts5_bm25"` (default) and `"title_tags"` (legacy)
- [ ] Update `assets/memory-config.default.json`: `match_strategy: "fts5_bm25"`, `max_inject: 3`
- [ ] Preserve `score_entry()` for fallback path (do NOT remove)
- [ ] Preserve path containment checks from current `main()` (security)
- [ ] Smoke test: 5 FTS5 queries return expected results; 5 fallback queries also work
- [ ] Rollback plan ready

## Key Design Decisions (from plan)

### FTS5 Table Schema (title + tags only for auto-inject)
```python
conn = sqlite3.connect(":memory:")
conn.execute("""
    CREATE VIRTUAL TABLE memories USING fts5(
        title, tags,
        path UNINDEXED, category UNINDEXED
    );
""")
```

### Smart Wildcard
- Compound tokens (containing `_`, `.`, `-`): exact phrase match `"user_id"`
- Single tokens: prefix wildcard `"auth"*`

### Pure Top-K Threshold
- MAX_AUTO = 3, MAX_SEARCH = 10
- 25% noise floor as safety net
- Sort by score (most negative = best), then category priority

### Hybrid Scoring
- Phase A: Parse index.md (1 file read)
- Phase B: Query FTS5, get top-K candidates
- Phase C: Read JSON for top-K only, extract body content
- Phase D: Final ranking with body bonus

### Security (MUST preserve)
- Path containment: `resolve().relative_to(memory_root.resolve())`
- XML escaping in output
- Title sanitization

### Config
- `match_strategy: "fts5_bm25"` (new default) or `"title_tags"` (legacy)
- `max_inject: 3` (reduced from 5)
- Code defaults to `fts5_bm25` when key absent (silent upgrade for existing users)

## Team Structure

### Phase 1: Implementation
1. **implementer** - Writes FTS5 engine functions + main() restructuring + config update
2. **arch-reviewer** - Reviews architecture/design before and after implementation
3. **security-reviewer** - Reviews security aspects (path traversal, injection, etc.)

### Phase 2: Verification Round 1
4. **v1-functional** - Functional correctness verification
5. **v1-security** - Security-focused verification
6. **v1-integration** - Integration and compatibility verification

### Phase 3: Verification Round 2
7. **v2-adversarial** - Adversarial testing (attack scenarios, edge cases)
8. **v2-independent** - Fresh-eyes independent review

## File Outputs
- Implementation: `temp/s2-implementer-output.md`
- Arch review: `temp/s2-arch-review.md`
- Security review: `temp/s2-security-review.md`
- V1 reports: `temp/s2-v1-*.md`
- V2 reports: `temp/s2-v2-*.md`

## Post-Review Fixes Applied

1. **Security fix (HIGH):** Added `_check_path_containment()` helper and pre-filter in `score_with_body()` to check ALL entries for path containment, not just top_k_paths. This was a security regression found by security-reviewer.
2. **Bug fix:** Restored `json_path = project_root / result["path"]` in body scoring loop (lost during edit).
3. **M1 fix:** Added `r["raw_bm25"] = r["score"]` before body bonus mutation to preserve original BM25 score for debugging.
4. **M3 fix:** Added `max_inject` parameter to `apply_threshold()` and `score_with_body()` so config's max_inject is respected instead of being silently capped at hardcoded MAX_AUTO=3.
5. **top_k_paths scaling fix:** Changed hardcoded `10` to `max(10, max_inject)` in main()'s `score_with_body()` call so that when max_inject > 10, enough candidates get body scoring and retired checks. Found by Codex and Gemini clink reviews.
6. All tests passing: 596 passed, 10 xpassed, 0 failed.

## Review Verdicts

- **Architecture:** APPROVE WITH CHANGES (2 medium: M1 in-place score mutation, M2 retired beyond top_k -- M2 addressed by security fix)
- **Security:** SECURE WITH CAVEATS (1 HIGH: path containment gap -- FIXED; rest SECURE)

## Verification Results

### V1 Round (3 verifiers, parallel)
| Verifier | Verdict | Key Findings |
|----------|---------|-------------|
| v1-functional | PASS WITH NOTES | All 8 functions correct, 502 tests pass, 30 manual tests pass |
| v1-security | SECURE | Path containment fix verified, SQL injection not exploitable, full parity |
| v1-integration | PASS | Legacy preserved, hook contract unchanged, config migration seamless |

### V2 Round (2 verifiers, parallel)
| Verifier | Verdict | Key Findings |
|----------|---------|-------------|
| v2-adversarial | PASS | 94 adversarial tests, no exploitable issues, path fix verified |
| v2-independent | APPROVE WITH CHANGES | 8/10 quality, net-new: max_inject partially ignored in FTS5 path |

### Tracked Issues for S3
| ID | Severity | Status | Issue |
|----|----------|--------|-------|
| M1 | Medium | FIXED | In-place score mutation loses raw BM25 score |
| M2 | Medium | Deferred | Retired entries beyond top_k_paths not checked (pre-existing) |
| M3 | Medium | FIXED | max_inject config partially ignored by apply_threshold hardcoded MAX_AUTO=3 |
| -- | High | FIXED | top_k_paths didn't scale with max_inject (exposed by M3 fix, found by Codex+Gemini) |
| L1 | Low | Deferred | Double-read of index.md (defer to S3 extraction) |
| L2 | Low | Deferred | build_fts_index_from_index coupled to file format |

## Final State of memory_retrieve.py
- Lines 1-262: Existing code (S1 -- dual tokenizer, body extraction, FTS5 check)
- Lines 264-370: FTS5 engine functions (build_fts_index, build_fts_query, query_fts, apply_threshold)
- Lines 371-423: _check_path_containment + score_with_body (with security pre-filter)
- Lines 425-442: _output_results (shared output formatter)
- Lines 444-644: main() (FTS5 branch + legacy fallback)
- Total: ~644 lines (~162 LOC added)
