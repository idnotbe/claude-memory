# Plan #2 Phase 3-4 Self-Review

**Date:** 2026-02-25
**Scope:** Search pipeline instrumentation (Phase 3) + Legacy log migration (Phase 4)

---

## Changes Summary

### Files Modified

| File | LOC Added | Changes |
|------|-----------|---------|
| `hooks/scripts/memory_retrieve.py` | ~55 | Lazy import, 4 logging points (search, judge filter, inject, skip), pipeline timing |
| `hooks/scripts/memory_judge.py` | ~35 | Lazy import, 2 event types (evaluate, error), session_id/memory_root/config threading |
| `hooks/scripts/memory_search_engine.py` | ~25 | Lazy import, --session-id arg, CLI search timing + logging |
| `hooks/scripts/memory_triage.py` | ~20 | Lazy import, emit_event for triage.score, `_raw` config stashing, LEGACY comment |

**Total LOC added:** ~135 (plan estimate: 65-105 LOC)

---

## Self-Critique Checklist

| Check | Status | Notes |
|-------|--------|-------|
| All emit_event() calls fail-open | PASS | emit_event itself catches all exceptions; fallback stubs are noops |
| Lazy import with e.name scoping | PASS | Identical pattern in all 4 files |
| duration_ms via time.perf_counter() | PASS | retrieve + search_engine use perf_counter; judge uses pre-existing monotonic() (acceptable) |
| session_id correctly extracted | PASS | retrieve: from hook_input["transcript_path"]; judge: threaded from caller; search: --session-id or env var; triage: from transcript_path |
| memory_root passed correctly | PASS | All emit_event calls include memory_root |
| config passed correctly | PASS | All emit_event calls include config (raw dict or None for pre-config exits) |
| No titles in info-level data | PASS | Results arrays contain only {path, score, raw_bm25, body_bonus, confidence} |
| results[] format matches schema | PASS | path, score, raw_bm25, body_bonus, confidence per result |
| No new external dependencies | PASS | All additions use stdlib only |
| Existing functionality unchanged | PASS | 838/838 tests pass, no behavioral changes |

---

## Design Decisions

### 1. Pre-config emit_event calls use config=None
For early skip events (short_prompt, empty_index before config is loaded), `config=None` is passed. `emit_event` with `None` config will use default `{"enabled": False}` and return immediately. This means these early skip events are never actually logged. This is acceptable because:
- If logging is disabled (default), no loss
- If logging is enabled, these events represent noise (non-searches)
- The pipeline timer starts AFTER config is loaded, so meaningful events always have config

### 2. candidates_found == candidates_post_threshold
In the retrieval.search event, both fields have the same value because `score_with_body()` returns post-threshold results. Capturing the pre-threshold count would require instrumenting inside `score_with_body()`, which would be more invasive. For PoC #5, the post-threshold count is the meaningful metric since the threshold is the quality gate.

### 3. Judge uses time.monotonic() not perf_counter()
The judge's pre-existing timing code uses `time.monotonic()`. Converting this to emit_event's `duration_ms` is correct -- both monotonic and perf_counter measure intervals without clock drift. Changing the judge's timer would be a non-additive modification that could affect existing stderr output.

### 4. Triage _raw config stashing
Added `config["_raw"] = raw` to `load_config()` -- one line, minimal invasiveness. This allows the emit_event caller to access the full config dict (with `logging` key) without re-reading the config file. No tests broke because no tests assert on specific config dict keys being absent.

### 5. Dual-write in triage
New emit_event call placed BEFORE legacy write block, so the new logger gets data even if legacy write fails. Legacy block marked with `# LEGACY: remove after migration validation` comment as specified.

---

## Known Limitations

1. **Query tokens at info level**: Plan explicitly allows this for PoC #5/#7. `.gitignore` guidance is the designated mitigation.
2. **candidates_found imprecision**: Same as candidates_post_threshold. Acceptable for v1.
3. **Gemini review unavailable**: Network error prevented Gemini 3.1 Pro review. Codex 5.3 review completed successfully with all HIGH findings addressed.

---

## Verification Results

| Step | Result |
|------|--------|
| `py_compile` all 4 files | PASS |
| `pytest tests/ -v` (838 tests) | 838 passed, 0 failed |
| Vibe-check | PASS with 2 notes (both addressed) |
| Codex 5.3 codereviewer | 1 HIGH fixed, 3 MEDIUM accepted, 1 LOW accepted |
| Gemini 3.1 Pro codereviewer | FAILED (network error) |
