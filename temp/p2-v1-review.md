# Plan #2 Logging Infrastructure -- V1 Correctness + Security Review

**Reviewer:** V1 Correctness + Security Reviewer (Claude Opus 4.6)
**Date:** 2026-02-25
**Scope:** Full Phase 1-5 implementation review
**External validation:** Codex 5.3 + Gemini 3.1 Pro (see `temp/p2-v1-clink.md`)

---

## Test & Compile Results

- **`python3 -m py_compile`**: All 5 modified/new scripts pass (memory_logger.py, memory_retrieve.py, memory_judge.py, memory_search_engine.py, memory_triage.py)
- **`pytest tests/ -v`**: **838 passed** in 50.12s, zero failures
- All 38 logger-specific tests pass (test_memory_logger.py)

---

## Findings

### F-01: Schema deviation -- `search.query` data fields [MEDIUM]

**Description:** The schema contract (`temp/p2-logger-schema.md` Section 6) specifies `search.query` data fields as: `query_tokens`, `engine`, `candidates_found`, `results[]`. The actual implementation in `memory_search_engine.py:500-507` emits: `fts_query`, `token_count`, `result_count`, `top_score`.

**Impact:** Downstream PoC analysis scripts (Plan #3) that consume logs according to the schema contract will fail to find expected fields. This breaks the contract-first design principle.

**Evidence:**
```python
# Schema says:
# "query_tokens", "engine", "candidates_found", "results"

# Actual (memory_search_engine.py:500-507):
emit_event("search.query", {
    "fts_query": _fts_query_str,       # not in schema
    "token_count": _token_count,        # not in schema
    "result_count": len(results),       # schema says "candidates_found"
    "top_score": round(_top_score, 4),  # not in schema
}, ...)
```

**Fix:** Either update the schema contract to match the implementation, or update the implementation to match the schema. Given this is v1 and the schema is meant to be the API boundary, the schema should be updated to reflect what is actually emitted. Alternatively, emit both sets of fields for compatibility.

**Status:** OPEN

---

### F-02: Schema deviation -- `judge.evaluate` data fields [MEDIUM]

**Description:** The schema contract (Section 4) specifies `judge.evaluate` data fields as: `model`, `candidates_in`, `accepted` (int count), `rejected` (int count), `batch_count`, `results[]` (with path + verdict). The actual implementation in `memory_judge.py:368-377` and `426-435` emits: `candidate_count` (not `candidates_in`), `model`, `batch_count`, `mode`, `accepted_indices` (list, not count), `rejected_indices` (list, not count). No `results[]` array with path+verdict.

**Impact:** Same as F-01: breaks contract-first design. PoC scripts expecting `candidates_in` will get KeyError.

**Evidence:**
```python
# Schema says: candidates_in, accepted (int), rejected (int), results[{path, verdict}]
# Actual (memory_judge.py:426-435):
emit_event("judge.evaluate", {
    "candidate_count": len(candidates),   # schema says "candidates_in"
    "model": model,
    "batch_count": 1,
    "mode": "sequential",                  # not in schema
    "accepted_indices": _kept_sorted,      # schema says "accepted" (int)
    "rejected_indices": _rejected,         # schema says "rejected" (int)
}, ...)
# Missing: results[] with path + verdict
```

**Fix:** Align schema and implementation. The implementation's approach (indices lists) arguably provides more information than counts alone. Update the schema to match.

**Status:** OPEN

---

### F-03: Schema deviation -- `retrieval.search` missing fields [LOW]

**Description:** The schema specifies `retrieval.search` should include `candidates_post_judge` and `injected_count`. The actual `retrieval.search` event (memory_retrieve.py:471-485) omits both. `candidates_post_judge` is emitted in a separate debug-level event (line 519-524), and `injected_count` is in the `retrieval.inject` event.

**Impact:** Minor. The data is captured across events, just not in a single event as the schema suggests. Correlation by session_id + timestamp recovers this.

**Fix:** Either add the missing fields to the `retrieval.search` event, or update the schema to clarify the field distribution across events.

**Status:** OPEN

---

### F-04: Schema deviation -- `retrieval.inject` missing `output_mode` [LOW]

**Description:** The schema (Section 2) specifies `retrieval.inject` should include `output_mode` (`"full"`, `"compact"`, or `"silent"`). Neither the FTS5 path (line 533-542) nor the legacy path (line 678-688) includes this field.

**Impact:** PoC #6 (Nudge compliance rate) explicitly depends on `output_mode` per the plan. Without this field, that PoC cannot measure compact injection occurrence.

**Fix:** Add `"output_mode": "full"` (or the actual mode) to both `retrieval.inject` emit sites.

**Status:** OPEN

---

### F-05: `retrieval.search` -- `candidates_found` equals `candidates_post_threshold` [LOW]

**Description:** At memory_retrieve.py:469-475, both `candidates_found` and `candidates_post_threshold` are set to `len(results)`, which is the count *after* `score_with_body()` applies thresholding (line 270: `apply_threshold()`). This means the "found" count is already filtered, making the two fields redundant.

**Impact:** The schema intends `candidates_found` to be the raw pre-threshold count. Having both identical defeats the purpose of tracking candidate attrition through the pipeline.

**Evidence:**
```python
_candidates_post_threshold = len(results)  # line 469
# ...
"candidates_found": _candidates_post_threshold,         # line 474 -- same var!
"candidates_post_threshold": _candidates_post_threshold, # line 475 -- same var!
```

**Fix:** Capture the raw candidate count before `apply_threshold()` is called inside `score_with_body()`, and pass it out (either by modifying the return or by querying FTS separately).

**Status:** OPEN

---

### F-06: Directory permissions -- `os.makedirs()` without explicit mode [MEDIUM]

**Description:** `memory_logger.py:151` and `267` call `os.makedirs(str(log_dir), exist_ok=True)` without specifying `mode`. The default is `0o777` (modified by umask). While file-level permissions are correctly `0o600`, directory permissions depend on the system umask.

**Impact:** On systems with permissive umask (e.g., `000`), log directories could be world-readable/writable. This enables the TOCTOU symlink attack in cleanup (F-07). Both Codex 5.3 and Gemini 3.1 Pro flagged this independently.

**Fix:** Add `mode=0o700` to both `os.makedirs()` calls:
```python
os.makedirs(str(log_dir), mode=0o700, exist_ok=True)
```

**Status:** OPEN

---

### F-07: TOCTOU symlink race in `cleanup_old_logs()` [MEDIUM]

**Description:** `cleanup_old_logs()` checks `category_dir.is_symlink()` (line 129) before iterating with `category_dir.iterdir()` (line 133). Between the check and the use, an attacker could replace the directory with a symlink. Both Codex 5.3 and Gemini 3.1 Pro identified this independently.

**Impact:** An attacker with write access to the log root could cause cleanup to delete `.jsonl` files in an arbitrary directory. Severity is mitigated by: (a) the attacker needs local write access to `logs/`, (b) only `.jsonl` files older than retention_days are deleted, (c) fail-open semantics mean the worst case is benign.

**Fix:** The primary mitigation is F-06 (restrict directory permissions to 0o700). For defense-in-depth, `os.scandir()` with `DirEntry.is_symlink()` could reduce the race window, or `openat`/`unlinkat` could eliminate it entirely.

**Status:** OPEN (mitigated by F-06 fix)

---

### F-08: `O_NOFOLLOW` fallback to 0 on non-Linux platforms [LOW]

**Description:** `memory_logger.py:35` sets `_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)`. On platforms without `O_NOFOLLOW` (e.g., some older Windows builds), this silently degrades to no symlink protection. Codex 5.3 flagged this.

**Impact:** Low. The plugin targets Linux (as evidenced by the WSL2 environment and Claude Code's platform). Windows does not have the same symlink attack surface. The fallback is a reasonable design choice for portability.

**Fix:** Consider logging a warning (at debug level) when `O_NOFOLLOW` is unavailable, or document the limitation.

**Status:** ACCEPTABLE (documented limitation)

---

### F-09: `time.monotonic()` vs `time.perf_counter()` inconsistency [INFO]

**Description:** `memory_judge.py` uses `time.monotonic()` for duration measurement (lines 356, 363, 396), while `memory_retrieve.py` and `memory_search_engine.py` use `time.perf_counter()`. The plan specifies `time.perf_counter()`.

**Impact:** Negligible. Both clocks are suitable for duration measurement. `perf_counter()` has higher resolution. `monotonic()` was pre-existing in `memory_judge.py` before the logging integration.

**Fix:** No action required. The judge's use of `monotonic()` is pre-existing and correct for its purpose (deadline management in parallel batching). The elapsed time is converted to ms before passing to `emit_event()`.

**Status:** ACCEPTABLE

---

### F-10: Query tokens logged at info level [LOW]

**Description:** `retrieval.search` events include `query_tokens` at info level (memory_retrieve.py:472). `search.query` events include `fts_query` at info level (memory_search_engine.py:501). These contain user query terms, which may reveal user intent or project details.

**Impact:** The plan acknowledges this explicitly (Section 3, schema design, bullet "query_tokens은 info 레벨에서 기록됨 -- `.gitignore` 가이드 필수") and treats it as an accepted risk with mitigation via `.gitignore` guidance. Codex 5.3 flagged it at LOW.

**Fix:** Already mitigated by design decision + `.gitignore` guidance in the plan.

**Status:** ACCEPTABLE (by design)

---

### F-11: Legacy triage log dual-write uses `os.fdopen()` not `os.write()` [INFO]

**Description:** The legacy `.triage-scores.log` dual-write in `memory_triage.py:1037` uses `os.fdopen(fd, "a")` + `.write()`, while the plan specifies `os.write(fd, line_bytes)` for atomic append. The new `emit_event()` path correctly uses `os.write()`.

**Impact:** None for the new logging system. The legacy path is explicitly marked as "LEGACY: remove after migration validation" (line 1012). The dual-write is temporary.

**Fix:** No fix needed -- this is the legacy code being preserved during migration, not the new logging path.

**Status:** ACCEPTABLE (legacy, scheduled for removal)

---

### F-12: Lazy import pattern consistent across all 4 modified files [INFO -- PASS]

**Description:** Verified the `e.name` scoping pattern in all 4 files:

| File | Lines | Pattern correct |
|------|-------|-----------------|
| memory_retrieve.py | 41-48 | Yes -- `getattr(e, 'name', None) != 'memory_logger'` with `raise` for transitive deps |
| memory_judge.py | 31-38 | Yes -- identical pattern |
| memory_search_engine.py | 24-31 | Yes -- identical pattern |
| memory_triage.py | 31-38 | Yes -- identical pattern |

All 4 files define fallback stubs for `emit_event`, `get_session_id`, and `parse_logging_config`.

**Status:** PASS

---

### F-13: Backward compatibility of `judge_candidates()` signature [INFO -- PASS]

**Description:** Three new keyword-only parameters were added: `memory_root=""`, `config=None`, `session_id=""`. All have defaults. Existing callers in tests (e.g., `judge_candidates("query", candidates)`) continue to work without modification. All 838 tests pass.

**Status:** PASS

---

### F-14: Existing hook behaviors unchanged [INFO -- PASS]

**Description:** Verified that logging is purely additive:
- All `emit_event()` calls are standalone statements (not conditional on results)
- No existing control flow is modified
- `emit_event()` is wrapped in fail-open try/except at the module level (line 288 of memory_logger.py)
- Config loading in `memory_triage.py` stores `_raw` config (line 583) without affecting existing config behavior
- stderr output is preserved alongside new logging (dual-write pattern for triage, existing stderr prints for judge/retrieve)

**Status:** PASS

---

### F-15: Secret residue -- no titles/content at info level [INFO -- PASS]

**Description:** Audited every `emit_event()` call across all 4 modified scripts. At info level:
- `retrieval.search`: results contain `path`, `score`, `raw_bm25`, `body_bonus`, `confidence` -- NO titles
- `retrieval.inject`: results contain `path`, `confidence` -- NO titles
- `retrieval.skip`: `reason`, `prompt_length` -- NO titles
- `judge.evaluate`: `candidate_count`, `model`, `accepted_indices`, `rejected_indices` -- NO titles, NO paths
- `judge.error`: error type/message, model -- NO titles
- `search.query`: `fts_query`, `token_count`, `result_count`, `top_score` -- NO titles
- `triage.score`: `text_len`, `exchanges`, `tool_uses`, triggered categories with scores -- NO titles, NO snippets

Both Codex 5.3 and Gemini 3.1 Pro independently confirmed this.

**Status:** PASS

---

### F-16: File permissions consistently 0o600 [INFO -- PASS]

**Description:** All `os.open()` calls in `memory_logger.py` specify `0o600`:
- Line 154 (`.last_cleanup` file): `0o600`
- Line 275 (log file): `0o600`

Test `test_emit_creates_file_and_writes_valid_jsonl` implicitly validates file creation.

**Status:** PASS

---

### F-17: Path traversal prevention effective [INFO -- PASS]

**Description:** `_sanitize_category()` provides two layers of defense:
1. `_SAFE_CATEGORY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")` -- strict allowlist
2. Fallback `re.sub(r"[^a-zA-Z0-9_-]", "", candidate)` -- strips all unsafe chars
3. Empty result maps to `"unknown"`

Test coverage includes: `../../etc` -> `unknown`, `a/b` -> `ab`, empty -> `unknown`, normal -> `normal`.

Both external models confirmed path traversal is effectively prevented.

**Status:** PASS

---

### F-18: Config injection prevention [INFO -- PASS]

**Description:** `parse_logging_config()` applies:
- `isinstance(config, dict)` check with safe default return
- `bool()` cast for `enabled`
- `str().lower()` + allowlist check for `level`
- `int()` cast with `ValueError/TypeError/OverflowError` catch for `retention_days`
- Negative retention_days clamped to 14
- Outer `except Exception` returns safe defaults

No `eval()`, `exec()`, `importlib`, or dynamic path construction from config values.

**Status:** PASS

---

## Plan Compliance Checklist

### Phase 1: Logging Contract Definition
| Item | Status | Notes |
|------|--------|-------|
| JSONL schema finalized | DONE | `temp/p2-logger-schema.md` exists with all 7 event types |
| event_type taxonomy confirmed | DONE | All 7 types documented and implemented |
| Config keys in default config | DONE | `assets/memory-config.default.json` has `logging` section |
| Sample JSONL verification | DONE | Schema doc includes jq/python verification examples |

### Phase 2: Shared Logger Module
| Item | Status | Notes |
|------|--------|-------|
| `memory_logger.py` created | DONE | 290 LOC, stdlib only |
| `emit_event()` with O_APPEND+os.write | DONE | Lines 272-280 |
| `get_session_id()` | DONE | Lines 74-89 |
| `cleanup_old_logs()` | DONE | Lines 96-165 |
| `parse_logging_config()` | DONE | Lines 42-67 |
| Level filtering | DONE | Lines 225-232 |
| Fail-open guarantee | DONE | Outer try/except at line 288 |

### Phase 3: Search Pipeline Instrumentation
| Item | Status | Notes |
|------|--------|-------|
| FTS5 path timing | DONE | perf_counter at lines 459, 466 |
| Full candidate pipeline logging | PARTIAL | candidates_found = candidates_post_threshold (F-05) |
| Final injection logging | DONE | retrieval.inject at lines 533, 678 |
| 0-result / skip event | DONE | retrieval.skip at multiple sites |
| Judge instrumentation | DONE | judge.evaluate and judge.error |
| CLI search logging | DONE | search.query at line 500 |

### Phase 4: Legacy Log Migration
| Item | Status | Notes |
|------|--------|-------|
| Triage scores -> new logger | DONE | emit_event("triage.score") at line 1000 |
| Legacy dual-write preserved | DONE | Lines 1012-1046 (marked LEGACY) |
| stderr output preserved | DONE | Existing stderr prints not removed |

### Phase 5: Testing
| Item | Status | Notes |
|------|--------|-------|
| Normal append test | DONE | TestNormalAppend class |
| Directory auto-creation | DONE | test_auto_creates_log_directory |
| Permission error fail-open | DONE | test_directory_permission_error_fail_open |
| Invalid config safety | DONE | TestDisabledAndInvalidConfig (5 tests) |
| Level filtering | DONE | TestLevelFiltering (3 tests) |
| Cleanup behavior | DONE | TestCleanup (4 tests) |
| Cleanup time gate | DONE | test_cleanup_time_gate_skip |
| Session ID extraction | DONE | TestGetSessionId (3 tests) |
| Concurrent append safety | DONE | test_concurrent_emit_no_corruption (50 threads) |
| p95 < 5ms benchmark | DONE | test_emit_event_p95_under_5ms (100 iterations) |
| Existing test regression | DONE | 838 tests pass |

### Phase 6: Documentation
| Item | Status | Notes |
|------|--------|-------|
| CLAUDE.md Key Files table | NOT CHECKED | Not in scope for this review (code-focused) |
| Config key documentation | DONE | Default config updated |

---

## Summary of Findings by Severity

| Severity | Count | Finding IDs |
|----------|-------|-------------|
| CRITICAL | 0 | -- |
| HIGH | 0 | -- |
| MEDIUM | 4 | F-01, F-02, F-06, F-07 |
| LOW | 4 | F-03, F-04, F-05, F-08 |
| INFO | 8 | F-09 through F-18 (6 PASS, 2 ACCEPTABLE) |

---

## Recommended Actions Before Merge

**Must fix (MEDIUM):**
1. **F-06**: Add `mode=0o700` to both `os.makedirs()` calls in `memory_logger.py` (2-line change)
2. **F-01 + F-02**: Reconcile schema contract (`temp/p2-logger-schema.md`) with actual emit payloads. Either update the schema doc to match implementation, or update the code. Given schema_version=1, updating the schema doc is the lower-risk option.

**Should fix (LOW):**
3. **F-04**: Add `output_mode` field to `retrieval.inject` events (needed for PoC #6)
4. **F-05**: Differentiate `candidates_found` from `candidates_post_threshold` (needed for pipeline attrition analysis)

**Can defer:**
5. **F-03**: `candidates_post_judge`/`injected_count` in `retrieval.search` -- data available across events
6. **F-07**: TOCTOU in cleanup -- mitigated by F-06 fix
7. **F-08**: O_NOFOLLOW fallback -- acceptable for target platform

---

## Final Verdict

### **CONDITIONAL PASS**

The logging infrastructure is well-designed and correctly implemented. The core security posture is strong: path traversal prevention is effective, POSIX atomic writes are correct, fail-open semantics work, no secret residue at info level, config injection is prevented, and all 838 tests pass.

The CONDITIONAL status is due to:
1. **Schema-implementation mismatches** (F-01, F-02) that would break the contract-first design principle and cause issues for Plan #3 PoC consumers. These are straightforward to resolve by updating the schema document.
2. **Directory permission hardening** (F-06) which both external models flagged independently and is a 2-line fix.

Once these items are addressed, this is a clean PASS.
