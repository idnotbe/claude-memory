# Phase B -- V2 Independent Adversarial Verification Report

**Date:** 2026-02-25
**Verifier:** V2 (independent adversarial, different angle from V1)
**Scope:** A-04 (E2E integration), A-05 (lazy import fallback), A-06+A-07 (performance/concurrency)
**Test Suite Status:** 72/72 tests passing (confirmed via pytest run)

---

## Verification Approach (Distinct from V1)

V2 focuses on five cross-cutting angles:
1. **Cross-cutting contract verification** -- Do tests validate the schema contract from `p2-logger-schema.md`?
2. **Regression safety** -- Would tests catch signature/behavior changes to `emit_event()`?
3. **Behavioral completeness** -- Map ALL `emit_event` call sites vs test coverage
4. **Test determinism** -- Flakiness risk analysis
5. **Security in test fixtures** -- Do tests mask or accurately model security properties?

---

## 1. Cross-Cutting Contract Verification

### 1.1 Schema Contract vs E2E Test Validation

The schema contract (`temp/p2-logger-schema.md`) defines specific `data` field structures per event type. The E2E tests validate via `_E2E_EVENT_DATA_KEYS` (test-side constant, lines 1549-1555).

**Gap analysis:**

| Event Type | Schema `data` Fields | E2E Validated Fields | MISSING from Validation |
|-----------|---------------------|---------------------|------------------------|
| `retrieval.search` | query_tokens, engine, candidates_found, candidates_post_threshold, results[] (path, score, raw_bm25, body_bonus, confidence) | query_tokens, engine, candidates_found | `candidates_post_threshold`, `results[].raw_bm25`, `results[].body_bonus` |
| `retrieval.inject` | injected_count, results[] (path, confidence) | injected_count, results | Results inner structure only validated in separate test |
| `retrieval.skip` | reason, prompt_length (conditional), query_tokens (conditional) | reason | `prompt_length` validated only in short_prompt-specific test, not in main validator |
| `judge.evaluate` | candidate_count, model, batch_count, mode, accepted_indices, rejected_indices | NOT TESTED E2E | Complete blind spot |
| `judge.error` | error_type, message, fallback, candidate_count, model | NOT TESTED E2E | Complete blind spot |
| `triage.score` | text_len, exchanges, tool_uses, triggered[] | NOT TESTED E2E | Complete blind spot |
| `search.query` | fts_query, token_count, result_count, top_score | NOT TESTED E2E | Complete blind spot |
| `retrieval.fallback` | engine, reason | In _E2E_EVENT_DATA_KEYS but NEVER TRIGGERED | Dead validation code |
| `retrieval.judge_result` | candidates_post_judge, judge_active | In _E2E_EVENT_DATA_KEYS but NEVER TRIGGERED | Dead validation code |

**Severity: HIGH** -- The `_E2E_EVENT_DATA_KEYS` constant is a test-side shadow of the schema contract. It is not derived from or validated against the actual schema document. If the schema evolves (e.g., a field is renamed in `memory_retrieve.py`), the test constant silently drifts. Furthermore, the validation only checks for key *presence* (subset check), not key *completeness* (exact match). Extra keys are silently ignored, meaning accidental data leakage (e.g., logging titles at info level) would not be caught.

### 1.2 Envelope Schema Validation

The unit test `test_schema_required_fields` (lines 98-141) properly validates all 10 envelope fields (schema_version, timestamp, event_type, level, hook, script, session_id, duration_ms, data, error). The E2E test `test_full_pipeline_produces_valid_jsonl` also validates these per-entry. This is solid.

**Timestamp format compliance:** The schema specifies "millisecond precision" (`YYYY-MM-DDThh:mm:ss.mmmZ`). The unit test uses `datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")` which accepts microsecond precision (`%f` parses 1-6 digits). The code produces 3-digit (millisecond) precision via `[:-3]` truncation (logger line 269). The test accepts but does not *enforce* exactly 3 digits after the decimal. Minor but technically a schema conformance gap.

---

## 2. Regression Safety Analysis

### 2.1 Signature Coupling

If `emit_event()` signature changes (e.g., a parameter is renamed or removed), the following test categories would catch it:

| Scenario | Would Tests Catch It? | Reason |
|----------|----------------------|--------|
| `emit_event` parameter renamed (e.g., `memory_root` -> `root`) | YES | 50+ direct calls in tests use keyword args |
| `emit_event` new required parameter added | YES | Existing calls would fail with TypeError |
| `emit_event` return type changed (currently None -> returns dict) | NO | No test asserts return value |
| `emit_event` silently drops `data` dict keys | PARTIAL | Unit tests validate synthetic data; E2E validates actual pipeline data but with incomplete key checks |
| `emit_event` changes JSONL serialization (e.g., `separators` change) | NO | Tests use `json.loads()` which tolerates whitespace changes |
| `parse_logging_config` return dict key renamed | YES | Direct assertion on `cfg["enabled"]`, `cfg["level"]`, etc. |

**Severity: LOW** -- The test suite provides good coupling to the emit_event signature via keyword argument usage across 50+ call sites. The main gap is that no test validates the compactness of the JSONL output (no spaces in separators).

### 2.2 Consumer-Side Data Dict Construction

The critical regression risk is in how consumer scripts CONSTRUCT the data dict before calling `emit_event`. For example, `memory_retrieve.py` line 486-500 builds the `retrieval.search` data dict with fields `query_tokens`, `engine`, `candidates_found`, `candidates_post_threshold`, and `results[]`. If someone removes `candidates_post_threshold` from this construction, only the E2E test would catch it -- and it does NOT currently validate this field (see gap table above).

**Severity: MEDIUM** -- The E2E tests provide a subprocess execution safety net, but the field-level validation is too loose to catch data dict regression.

---

## 3. Behavioral Completeness -- emit_event Call Site Coverage Map

### 3.1 Complete Call Site Inventory

| Script | Line(s) | Event Type | Level | Tested by E2E? | Tested by Unit? |
|--------|---------|-----------|-------|----------------|----------------|
| memory_retrieve.py | 352 | retrieval.skip (short_prompt) | info | YES (tests 4,5) | YES (synthetic) |
| memory_retrieve.py | 376 | retrieval.skip (empty_index) | info | NO | YES (synthetic) |
| memory_retrieve.py | 391 | retrieval.skip (retrieval_disabled) | info | NO | YES (synthetic) |
| memory_retrieve.py | 431 | retrieval.skip (max_inject_zero) | info | NO | YES (synthetic) |
| memory_retrieve.py | 449 | retrieval.skip (empty_index, 2nd) | info | NO | YES (synthetic) |
| memory_retrieve.py | 486 | retrieval.search | info | YES (tests 1,2) | YES (synthetic) |
| memory_retrieve.py | 535 | retrieval.judge_result | debug | NO (judge disabled in E2E) | NO |
| memory_retrieve.py | 549 | retrieval.inject (FTS5 path) | info | YES (tests 1,3) | YES (synthetic) |
| memory_retrieve.py | 563 | retrieval.skip (no_fts5_results) | info | YES (test 6) | YES (synthetic) |
| memory_retrieve.py | 577 | retrieval.fallback | warning | NO (FTS5 always available) | NO |
| memory_retrieve.py | 697 | retrieval.inject (legacy path) | info | NO (FTS5 always available) | NO |
| memory_judge.py | 368 | judge.evaluate (parallel) | info | NO | NO |
| memory_judge.py | 384 | judge.error (parallel_failure) | warning | NO | NO |
| memory_judge.py | 402 | judge.error (api_failure) | warning | NO | NO |
| memory_judge.py | 415 | judge.error (parse_failure) | warning | NO | NO |
| memory_judge.py | 428 | judge.evaluate (sequential) | info | NO | NO |
| memory_search_engine.py | 500 | search.query | info | NO | NO |
| memory_triage.py | 1000 | triage.score | info | NO | NO |

### 3.2 Coverage Summary

| Category | Total Call Sites | E2E Covered | Unit Covered | ZERO Coverage |
|----------|-----------------|-------------|--------------|---------------|
| retrieval.* | 11 | 5 (45%) | 8 (73%) | 3 (fallback, legacy inject, judge_result) |
| judge.* | 5 | 0 (0%) | 0 (0%) | **5 (100%)** |
| search.* | 1 | 0 (0%) | 0 (0%) | **1 (100%)** |
| triage.* | 1 | 0 (0%) | 0 (0%) | **1 (100%)** |
| **TOTAL** | **18** | **5 (28%)** | **8 (44%)** | **10 (56%)** |

**Severity: HIGH** -- 10 out of 18 emit_event call sites have ZERO test coverage for the actual data dict they construct. The existing unit tests validate `emit_event` itself (the logging mechanism), but do not validate the *data contract compliance* of the dicts constructed by consumer scripts.

---

## 4. Test Determinism Analysis

### 4.1 Timing-Dependent Tests

| Test | Mechanism | Flakiness Risk |
|------|----------|----------------|
| `test_emit_event_p95_under_5ms` | 100 calls, p95 < 5ms | **MEDIUM** -- On slow CI/CD machines or under I/O pressure, file writes can exceed 5ms. Mitigating factor: 5ms is generous for a single append. |
| `test_emit_with_cleanup_under_50ms` | Single emit + 98-file cleanup scan < 50ms | **MEDIUM** -- Involves 28 file deletions and directory traversal. Slow network filesystems (NFS, EFS) could exceed this. |
| `test_inject_duration_covers_full_pipeline` | inject_dur >= search_dur | **LOW** -- This is a monotonic relationship (pipeline timer wraps search timer). Would only fail on clock anomaly. |

### 4.2 File System Race Conditions

| Test | Concern | Assessment |
|------|---------|-----------|
| `test_concurrent_emit_no_corruption` | 8 threads x 50 writes | **LOW** risk -- O_APPEND guarantees atomicity for writes < PIPE_BUF. Payload is small (~200 bytes). |
| `test_large_payload_no_corruption` | 8 threads x 20 writes of ~3.5KB | **LOW** risk -- Payload verified to be < 4096 bytes (PIPE_BUF). POSIX guarantees atomicity. |
| `test_payload_size_near_pipe_buf` | Asserts 2048 <= size <= 4096 | **LOW** risk -- Deterministic single-threaded write. |

### 4.3 Ordering Assumptions

| Test | Concern | Assessment |
|------|---------|-----------|
| `test_log_entries_ordered_by_pipeline_stage` | search before inject in JSONL | **LOW** risk -- Both events are written sequentially in a single-threaded pipeline. O_APPEND ensures order within a single process. |
| `_read_log_lines` helper | Iterates `cat_dir.iterdir()` | **LOW** risk -- For tests with a single category, only one dir/file. For the cleanup test, the test reads specific files, not relying on iteration order. |

### 4.4 Subprocess Tests (E2E + Lazy Import)

| Test | Concern | Assessment |
|------|---------|-----------|
| All E2E tests | 15-second timeout for subprocess | **LOW** -- Python startup + script execution is well under 15s. |
| Lazy import tests | Path manipulation in subprocess | **LOW** -- Uses fresh Python process with clean sys.path. No caching effects. |

**Overall Determinism Verdict: ACCEPTABLE** -- The main flakiness risks are the two performance benchmark tests. These should be marked with `@pytest.mark.slow` or similar to allow exclusion in constrained CI environments. However, for local development, the margins are generous enough.

---

## 5. Security in Test Fixtures

### 5.1 Symlink Containment Test (`TestSymlinkContainment`)

**Mechanism verified:** When `emit_event("evil.test", ...)` is called, `os.makedirs` at line 295 creates the directory at the symlink target (because `makedirs` follows symlinks with `exist_ok=True`). The containment check at lines 298-301 (`log_dir.resolve().relative_to(logs_root.resolve())`) then detects that the resolved path escapes `logs_root` and returns early. The test correctly verifies no file is written to the symlink target.

**Verified independently:** I ran `os.makedirs` on a symlink path and confirmed it does NOT replace the symlink; it follows it. The subsequent `resolve().relative_to()` check catches the escape. The test IS valid.

**However:** The TOCTOU gap identified by the external reviewer (Gemini) is real but applies to `cleanup_old_logs`, not `emit_event`. In cleanup, `is_symlink()` is checked before `iterdir()`, creating a window for symlink replacement. This is a production code issue, not a test fixture issue. The test `test_cleanup_skips_symlinked_dirs` validates the static case correctly but cannot test the TOCTOU race. This is an inherent limitation of unit testing for race conditions.

**Severity: LOW (for tests)** -- Tests accurately model the static security properties. The TOCTOU gap is a production code concern that should be tracked separately.

### 5.2 Lazy Import Fallback Security

The fallback stubs define `emit_event(*args, **kwargs): pass` -- a silent no-op. This is correct for fail-open semantics. However, if an attacker could control `sys.path` to inject a malicious `memory_logger.py`, the real import would succeed and the attacker's code would execute. The `e.name` check only guards against transitive import failures, not path hijacking. This is inherent to Python's import mechanism, not a test deficiency.

### 5.3 E2E Test Environment

The E2E tests correctly strip `ANTHROPIC_API_KEY` from the subprocess environment (line 1503: `env.pop("ANTHROPIC_API_KEY", None)`), ensuring the LLM judge is never called. This prevents:
- Accidental API charges during testing
- Nondeterministic test outcomes from LLM responses
- API key leakage into test logs

**But this also means:** The judge path is NEVER exercised in E2E tests. All 5 `judge.*` call sites have zero E2E coverage.

---

## 6. External Review Findings Integration

The Gemini external review (via clink) identified 5 issues. My assessment:

| # | Gemini Finding | Severity | V2 Assessment |
|---|---------------|----------|---------------|
| 1 | TOCTOU in cleanup_old_logs | Critical (Gemini) | **MEDIUM** -- Real production gap, but not a test deficiency. The attacker must have write access to the logs directory to exploit this. Filed as separate concern. |
| 2 | E2E coverage blind spots | High (Gemini) | **AGREED HIGH** -- 3/4 consumer scripts untested E2E. `retrieval.fallback` and `retrieval.judge_result` are dead entries in `_E2E_KNOWN_EVENT_TYPES`. |
| 3 | Hardcoded latency assertions | High (Gemini) | **MEDIUM** -- 5ms and 50ms budgets are generous for local dev. Mark as `@pytest.mark.benchmark` for CI exclusion. |
| 4 | Untested lazy import for 2/4 consumers | Medium (Gemini) | **AGREED MEDIUM** -- memory_retrieve.py and memory_judge.py not tested. Stub dependencies should be created for isolation. |
| 5 | Subset-only schema validation | Medium (Gemini) | **AGREED MEDIUM** -- `expected_keys - set(data.keys())` misses extra keys. Should use equality check or jsonschema. |

Gemini's correction on `os.makedirs` behavior was accurate: makedirs does NOT overwrite symlinks; it follows them. The containment check subsequently catches the escape.

---

## 7. Per-Action Assessment

### A-04: E2E Integration Tests (10 tests)

| Criterion | Verdict | Notes |
|-----------|---------|-------|
| Tests execute? | PASS | 10/10 green |
| Schema contract validated? | PARTIAL | Envelope schema: solid. Data dict keys: subset-only validation, missing several contract fields |
| Call site coverage? | PARTIAL | Covers retrieval.search + retrieval.inject + retrieval.skip (3 of 5 retrieval event types). Zero coverage for judge/triage/search scripts |
| Regression detection? | GOOD | Would catch most retrieval pipeline regressions. Cannot catch judge/fallback/legacy path regressions |
| Determinism? | GOOD | Subprocess isolation is clean. No ordering or timing concerns |

**A-04 Verdict: CONDITIONAL PASS**

### A-05: Lazy Import Fallback Tests (6 tests)

| Criterion | Verdict | Notes |
|-----------|---------|-------|
| Tests execute? | PASS | 6/6 green |
| Scenario coverage? | GOOD | Missing, SyntaxError, transitive dep -- all three scenarios covered |
| Consumer coverage? | PARTIAL | 2/4 consumers tested (memory_search_engine, memory_triage). memory_retrieve and memory_judge excluded. |
| Isolation quality? | EXCELLENT | Fresh subprocess, controlled sys.path, no mocking |

**A-05 Verdict: CONDITIONAL PASS**

### A-06+A-07: Performance & Concurrency Tests (4 tests)

| Criterion | Verdict | Notes |
|-----------|---------|-------|
| Tests execute? | PASS | 4/4 green |
| Cleanup latency validated? | GOOD | Realistic 98-file layout, cleanup + emit under 50ms |
| Concurrent correctness? | EXCELLENT | PIPE_BUF-boundary payloads, 160 concurrent writes, zero corruption |
| Determinism? | ACCEPTABLE | Timing assertions could fail on slow machines but margins are generous |

**A-06+A-07 Verdict: PASS**

---

## 8. Issues Summary

| ID | Severity | Category | Description |
|----|----------|----------|-------------|
| V2-01 | HIGH | Coverage Gap | 10 of 18 emit_event call sites (56%) have ZERO test coverage for data dict construction. All judge.*, search.*, and triage.* events are completely untested. |
| V2-02 | HIGH | Contract Drift | `_E2E_EVENT_DATA_KEYS` is a test-side shadow of the schema contract, not derived from or linked to the authoritative schema document. Uses subset-only validation (missing keys detected, extra keys silently accepted). |
| V2-03 | MEDIUM | Coverage Gap | `retrieval.fallback` and `retrieval.judge_result` are listed in `_E2E_KNOWN_EVENT_TYPES` but never triggered by any test. These are dead validation entries that provide false confidence. |
| V2-04 | MEDIUM | Coverage Gap | Lazy import fallback tests cover only 2 of 4 consumer scripts. memory_retrieve.py (the most critical consumer) is excluded. |
| V2-05 | MEDIUM | Contract Drift | Schema contract specifies `retrieval.search.results[]` must contain `raw_bm25` and `body_bonus` fields. No test (unit or E2E) validates these fields are present in actual pipeline output. |
| V2-06 | LOW | Determinism | Performance benchmark tests (`p95 < 5ms`, `cleanup < 50ms`) could fail on resource-constrained CI environments. Should be marked for conditional execution. |
| V2-07 | LOW | Completeness | Timestamp format compliance is tested loosely (`%f` accepts 1-6 digits) but the schema mandates exactly 3 digits (millisecond precision). |

---

## 9. Overall Verdict

### CONDITIONAL PASS

The Phase B behavioral tests are well-designed, deterministic, and validate the core logging mechanism thoroughly. The E2E integration tests (A-04) are a significant quality improvement -- they exercise the real pipeline via subprocess and catch real schema violations. The lazy import tests (A-05) and performance/concurrency tests (A-06+A-07) are solid.

However, the tests have significant coverage gaps that limit their value as regression guards:

### Conditions for Full PASS

1. **[V2-01 / V2-03] Add E2E or integration tests for untested event types.** At minimum:
   - `search.query` via `memory_search_engine.py --query` subprocess
   - `triage.score` via `memory_triage.py` subprocess with a transcript fixture
   - Remove `retrieval.fallback` and `retrieval.judge_result` from `_E2E_KNOWN_EVENT_TYPES` if they cannot be triggered, OR add tests that actually trigger them

2. **[V2-02 / V2-05] Tighten data dict validation.** Either:
   - Switch `_E2E_EVENT_DATA_KEYS` to use set equality (exact match) rather than subset check, OR
   - Import expected keys from a shared constant in the production code, OR
   - Add specific assertions for `raw_bm25` and `body_bonus` in the search results test

3. **[V2-04] Extend lazy import tests to cover memory_retrieve.py.** The isolation framework already supports this -- just add `memory_search_engine.py` as a stub dependency in the isolated directory.

Items V2-06 and V2-07 are LOW severity and do not block full PASS.

---

## Appendix: Test Execution Evidence

```
tests/test_memory_logger.py - 72 passed in 1.02s
Platform: Linux 6.6.87.2-microsoft-standard-WSL2
Python: 3.11.14
pytest: 9.0.2
```
