# Closed Feedback Loop: Test Suite Analysis

Test-to-requirements traceability analysis for claude-memory plugin.

## 1. Test Suite Inventory

**Total: 1,095 tests across 20 files** (collected by pytest in 0.73s)

### File-by-File Catalog

| # | Test File | Tests | Script Under Test | What It Verifies |
|---|-----------|-------|--------------------|-----------------|
| 1 | `conftest.py` | -- | (shared fixtures) | Memory factories, index builders, filesystem fixtures, bulk data generator |
| 2 | `test_memory_triage.py` | ~95 | `memory_triage.py` | Config loading, category descriptions, transcript parsing (Bug 1-4), text extraction, activity metrics, keyword scoring, co-occurrence boosting, session summary scoring, threshold evaluation, stop flag lifecycle (sentinel TTL/creation/staleness), context file generation (staging dir routing, 50KB cap, permissions), triage_data JSON structure, file-based triage_data output with fallback, exit protocol (stdout JSON + exit 0), CONSTRAINT threshold calibration, end-to-end integration |
| 3 | `test_memory_retrieve.py` | ~105 | `memory_retrieve.py` | Tokenization (stop words, char length), index line parsing (enriched/legacy formats), scoring (exact title/tag/prefix match, combined scoring, no double-counting), recency check, category priority, config behavior (max_inject, retrieval disabled), description token scoring, confidence labeling, XML-safe structured output, tiered output modes (result/compact/silenced), search hints, abs_floor/cluster_count thresholds, save-result display and cleanup, orphan triage detection, pending notification |
| 4 | `test_memory_write.py` | ~65 | `memory_write.py` | auto_fix (timestamps, tag normalization, slugification, confidence clamping), Pydantic validation (all 6 categories, enum errors, missing fields, extra fields), build_index_line, word_difference_ratio, merge protections (immutable fields, grow-only tags, tags eviction at cap, append-only changes), CRUD integration (create/update/retire with subprocess), OCC hash check, archive/unarchive lifecycle, path traversal blocking, tag sanitization (newlines, commas, control chars, arrow/tags-prefix stripping), create forcing active status, title null-byte/newline stripping, update without hash warning |
| 5 | `test_memory_index.py` | ~18 | `memory_index.py` | scan_memories (active only, include_inactive, corrupt JSON skip), rebuild (enriched format, skip retired/archived, multiple categories, empty store), validate (in-sync, missing from index, stale entries), GC (grace period, custom grace, missing retired_at), health report (good/needs-attention/retired/desync/empty), query (match/no-match) |
| 6 | `test_memory_candidate.py` | ~25 | `memory_candidate.py` | Tokenize (basic, short words, empty, stop-word-only), parse_index_line (enriched with tags, legacy, non-matching, all category displays), score_entry (exact title, tag 3pts, prefix 4+ chars, no match, combined), build_excerpt (all categories, corrupt/missing JSON, change summary, list field joining), CLI integration (candidate found, no candidate below threshold, lifecycle NOOP, DELETE disallowed per category, structural vetoes, empty index, tag scoring, backward-compat legacy index, excerpt key_fields), DELETE_DISALLOWED constant verification |
| 7 | `test_memory_draft.py` | ~40 | `memory_draft.py` | assemble_create (all 6 categories, auto-populate fields, slugification, change entries, optional fields, timestamps), assemble_update (immutable preservation, times_updated increment, change append, tag union, related_files union, content shallow merge, record_status preservation), path validation (staging, tmp, arbitrary, dotdot), CLI integration (create/update, invalid input, missing fields, invalid JSON), edge cases (empty tags, long titles, unicode), new-info-file for candidate, full Phase 1 pipeline integration (candidate -> draft -> write) |
| 8 | `test_memory_judge.py` | ~55 | `memory_judge.py` | call_api (success, no key, timeout, HTTP error, URL error, empty content, malformed JSON, headers, payload body, unicode decode, non-text blocks), extract_recent_context (normal, empty, flat fallback, max turns, path validation, traversal, list content, truncation, non-message types, corrupt JSONL, non-dict, human type), format_judge_input (shuffling, deterministic seeds, cross-run stability, context inclusion, HTML escaping, memory_data tags, prompt truncation, display indices, tags sorting, lone surrogate, shuffle seed override, breakout injection), parse_response (valid JSON, preamble, string indices, nested braces, invalid, empty keep, out-of-range, missing keep, boolean/mixed/negative/string rejection), judge_candidates integration (success, API failure, empty list, parse failure, no context, dedup indices, keeps all, missing transcript), parallel execution (_judge_batch global indices, offset, API/parse failure, independent shuffle, empty keep, _judge_parallel splits/merges, partial keep, one batch fail, timeout, odd count, exception, threshold triggering, sequential fallback) |
| 9 | `test_memory_write_guard.py` | ~25 | `memory_write_guard.py` | Block memory directory writes, allow non-memory writes, allow temp staging files, handle missing/empty/invalid inputs, block memory path endings, config file exemptions (allow at root, block in subdirectories, block similar filenames), staging auto-approve (intent JSON, triage-data, last-save-result, context txt, new files, unknown filename blocked, wrong extension blocked, hardlink detection, traversal denied, all known filenames) |
| 10 | `test_memory_staging_guard.py` | ~25 | `memory_staging_guard.py` | True positives: block heredoc/echo/tee/cp/mv/dd/install/bare-redirect/printf/append to .staging/. True negatives: allow Write tool, cat read, ls, other directories, memory_write.py execution, grep, rm, non-Bash tools, unlink. Hardlink blocking (ln, ln -f, link, case-insensitive, symlink to other dir allowed). Edge cases: empty command, invalid JSON, empty stdin, missing tool_input, deny message contains Write tool guidance |
| 11 | `test_memory_validate_hook.py` | ~30 | `memory_validate_hook.py` | is_memory_file (JSON path, non-memory, non-JSON matched, index.md matched, empty), get_category_from_path (all folders mapped), integration (non-memory passthrough, valid memory passes, invalid quarantined, empty/missing input), config file exemptions (skip validation, not quarantined, subdirectory still validated, regular files still validated), staging exemption (JSON/txt/nested/triage-data allowed, no bypass warning, non-staging shows warning), staging near-miss (.staging as file, .stagingfoo, wrong nesting level), staging hard link (warning-only diagnostic, normal file exempted), staging security (traversal blocked, non-staging validated), cross-hook parity (Pre+PostToolUse agree on staging and config) |
| 12 | `test_memory_logger.py` | ~100+ | `memory_logger.py` | Normal JSONL append with schema verification, auto-create directories, permission error fail-open, disabled config, empty/none/string/list config safe defaults, level filtering (debug/info/warning/error), cleanup (old files, time gate, missing marker, disabled, symlink dirs/files), path traversal sanitization, results truncation, concurrent safety (ThreadPoolExecutor), non-serializable data (datetime, set, frozenset), p95 benchmark (< 5ms), parse_logging_config (full plugin config, sub-dict, negative retention, unknown level, boolean string enabled/disabled), NaN/Inf duration handling, symlink category escape prevention, long category truncation, timestamp-filename date match, missing logger import resilience (search_engine, triage, judge), syntax error logger resilience, transitive dependency failure propagation, emit+cleanup benchmark (< 50ms), large payload corruption, pipe buffer boundary, full pipeline JSONL integration, search/inject/skip event structures, logging config enable/disable/level-change workflows, results truncation metadata |
| 13 | `test_rolling_window.py` | ~30 | `memory_enforce.py` + `memory_write.py` | enforce_rolling_window (triggers 1 retirement, no trigger at limit, multiple retirements, ordering by created_at + filename tiebreaker, CLI/config max_retained override, corrupted JSON skipped, retire_record failure breaks loop, file disappears between scan/retire, dry-run no modification, empty directory, memory root discovery, lock not acquired raises, max_retained 0/-1 rejected, dynamic cap for large excess, dynamic cap floor, max_retire override, config 0/-1 fallback, max_retire CLI 0 rejected, dry-run respects dynamic cap). FlockIndex (require_acquired raises/passes, timeout backward compat, permission denied compat). retire_record (matches do_retire behavior, relative path, already retired, archived raises, FlockIndex rename no remaining references) |
| 14 | `test_adversarial_descriptions.py` | ~80 | `memory_triage.py` + `memory_retrieve.py` | Malicious descriptions (14 vectors: XML breakout, XSS, control chars, zero-width, very long, index injection, newlines, shell injection, backticks, HTML script, bidi, null embedded, tag chars) tested against _sanitize_snippet, context files, block messages, triage_data JSON, _sanitize_title. Config edge cases (100 categories, null/false/zero/empty-list/empty-dict descriptions, unicode category names, non-dict categories). Scoring exploitation (score_description cap at 2, prefix rounding, empty inputs). Cross-function interaction (extra description keys, empty results, none descriptions, mixed categories). Retrieval description injection (quote breakout, angle brackets, normal text preservation, arrow/tags markers). Truncation interaction (500-char config vs 120-char sanitize). Context file overwrite (no stale data). Sanitization consistency (triage vs retrieval agree). JSON roundtrip (quotes, newlines, unicode, null bytes, JSON-in-JSON, backslash-n) |
| 15 | `test_fts5_benchmark.py` | ~6 | `memory_search_engine.py` | 500-doc index build < 100ms, 500-doc query < 100ms, 500-doc full cycle < 100ms, result correctness (runbook keywords), 500-doc with body < 100ms |
| 16 | `test_fts5_search_engine.py` | ~20 | `memory_search_engine.py` | Basic build+query, build with body, no-match empty, smart wildcard (compound exact, single prefix, mixed, prefix matches in FTS5), body extraction (all 6 categories, all BODY_FIELDS covered), hybrid scoring (body bonus improves ranking, capped at 3), FTS5 fallback (cli_search empty when no FTS5, retrieve falls back to legacy) |
| 17 | `test_v2_adversarial_fts5.py` | ~80 | `memory_search_engine.py` + `memory_retrieve.py` | FTS5 query injection (NEAR/NOT/AND/OR operators, SQL injection, column filter, prefix/phrase/star operator injection, actual FTS5 execution, unicode lookalikes). Path traversal (dotdot, absolute outside, within valid prefix, inside .claude but outside memory, valid accepted, unicode components, very long, symlink, dotdot with existing dir, Python path.join absolute override). Index corruption (closing XML tag, embedded newlines, SQL in title, extremely long line, binary data, arrow delimiter in title, tags in title, crafted tags in FTS5 insert). Stress testing (1000 entries performance, 100 identical matches noise floor, sorting stability, large index build). Tokenizer edge cases (underscores, version strings, hyphens, single char, all stop words, empty, very long, special chars only, mixed valid/invalid, numeric, uppercase, compound preservation, duplicates, embedded null). Score manipulation (max body bonus, tags spam, title keyword stuffing, match_strategy code injection). Config manipulation (max_inject extreme/NaN/Infinity/string, retrieval null, categories not dict). Containment (traversal filtered before body scoring, many traversal entries beyond top_k). Output sanitization (XSS payloads, zero-width, bidi, tag characters, output_results captures all paths, description injection). Body text edge cases (truncation, non-dict content, missing content, unknown category, nested dicts, injection payloads). Compound vs legacy tokenizer. apply_threshold edge cases (empty, single, noise floor, all-zero, very close scores, auto/search caps, negative score sorting). parse_index_line robustness (arrow in title, tags marker, empty/lowercase category, long tags, whitespace-only tags, newline). FTS5 error handling (empty query, malformed query, closed connection) |
| 18 | `test_regression_popups.py` | ~25 | Guard scripts + SKILL.md | No "ask" verdict in guard scripts (AST analysis + raw text scan for all 3 guards), only allow/deny values permitted. SKILL.md bash commands vs Guardian block/ask patterns (4 block + 4 ask pattern tests). SKILL.md Rule 0 compliance (no heredoc+.claude, no find-delete+.claude, no rm+.claude, no inline-JSON+.claude, python3-c known instances tracking). Guard script existence checks. Guardian pattern sync (optional, when guardian repo available) |
| 19 | `test_log_analyzer.py` | ~40 | `memory_log_analyzer.py` | Minimum sample size validity guards for all rate-based anomaly detectors: _detect_zero_length_prompt (boundary testing at _MIN_SKIP_EVENTS_ZERO_PROMPT=10), _detect_skip_rate_high (boundary at _MIN_RETRIEVAL_EVENTS_SKIP_RATE=20), _detect_category_never_triggers (boundary at _MIN_TRIAGE_EVENTS_CATEGORY=30), _detect_booster_never_hits (boundary at _MIN_TRIAGE_EVENTS_BOOSTER=50, old format, session_summary excluded, mixed categories, zero primary), _detect_error_spike (boundary at _MIN_ERROR_SPIKE_EVENTS=10, multiple categories, finding structure). Constant value sanity checks |
| 20 | `test_arch_fixes.py` | ~40 | Multiple scripts | Issue 1: index.md rebuild-on-demand (trigger when missing, no rebuild when present, missing script handling, timeout, missing root). Issue 2: _resolve_memory_root fail-closed (marker path, without marker, relative/absolute resolution, multiple segments, external path rejected, error message). Issue 3: max_inject clamping [0,20] (negative, zero, 5 default, 20 clamp, 100 clamp, string/null/float invalid, missing key, missing config, string number coerced, disabled). Issue 4: mkdir-based lock (acquire/release, context manager, stale detection, timeout, permission denied, cleanup normal/exception, write operation uses lock). Issue 5: Prompt injection defense (title sanitization, arrow/tags markers, truncation, whitespace, output format, pre-sanitization, tags formatting, write-side sanitization, combined sanitization, embedded close tag, no raw line, rebuild with sanitized titles, max_inject limits surface, lock not needed for rebuild, validated root with lock) |


## 2. Current Requirements Tracing Status

### Existing Tracing: None

The test suite has **zero formal requirements tracing**. Specifically:
- No `@pytest.mark.requirement()` or similar custom markers
- No `# REQ-xxx` comments linking tests to specifications
- No traceability matrix document
- No pytest plugin for requirements mapping

### What Exists Instead

The project uses an informal test plan at `/home/idnotbe/projects/claude-memory/action-plans/_ref/TEST-PLAN.md` that organizes tests by priority:
- **P0 -- Security-Critical**: Prompt injection, max_inject clamping, config integrity
- **P1 -- Core Functional**: Keyword matching, index operations, candidate selection, write operations, triage hook
- **P2 -- Guard and Validation**: Write guard, validate hook
- **P3 -- Nice to Have**: Schema validation, integration, CI/CD

The TEST-PLAN.md describes *what to write* but does not assign requirement IDs or link to specific test functions.

### Existing Pytest Configuration

`conftest.py` provides:
- 6 memory data factories (`make_decision_memory`, etc.)
- 2 filesystem fixtures (`memory_root`, `memory_project`)
- Helpers: `write_memory_file`, `write_index`, `build_enriched_index`
- `bulk_memories` fixture (500 diverse entries for benchmarks)

No `pytest.ini`, `pyproject.toml`, or `setup.cfg` with pytest configuration. The only markers in use are:
- `@pytest.mark.parametrize` (test parameterization, ~15 usages)
- `@pytest.mark.skipif` (FTS5 availability check, 2 files)
- Historical `@pytest.mark.xfail` (removed after fixes applied, referenced in `test_arch_fixes.py` docstring)


## 3. Proposed Requirements Taxonomy

Based on the TEST-PLAN.md priorities and the actual codebase, requirements should map to these domains:

### Security Requirements (SEC-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| SEC-001 | Title sanitization: strip control chars, zero-width, angle brackets, backticks | P0 |
| SEC-002 | Title sanitization: strip index delimiters (` -> `, `#tags:`) | P0 |
| SEC-003 | Title sanitization: truncate to max length | P0 |
| SEC-004 | max_inject clamped to [0, 20] | P0 |
| SEC-005 | Malformed config: graceful fallback to defaults | P0 |
| SEC-006 | FTS5 query injection prevention (operators quoted/filtered) | P0 |
| SEC-007 | Path traversal prevention (memory_write target resolution) | P0 |
| SEC-008 | Path containment (candidate paths under memory root) | P0 |
| SEC-009 | Write guard blocks direct writes to memory directory | P0 |
| SEC-010 | Staging guard blocks Bash writes to .staging/ | P0 |
| SEC-011 | Validate hook quarantines invalid memory files | P0 |
| SEC-012 | No "ask" verdict from guard scripts (only allow/deny) | P0 |
| SEC-013 | LLM judge integrity: deterministic shuffling, XML-wrapped data | P0 |
| SEC-014 | Hardlink defense in staging file validation | P0 |
| SEC-015 | Staging traversal prevention (realpath + marker check) | P0 |
| SEC-016 | Thread safety in parallel judge executions | P0 |
| SEC-017 | Snippet sanitization (control chars, zero-width, XML escaping) | P0 |
| SEC-018 | Logger path traversal prevention (category sanitization) | P1 |
| SEC-019 | Logger symlink protection | P1 |
| SEC-020 | Transcript path validation (restrict to /tmp/ and $HOME/) | P1 |

### Functional Requirements -- Retrieval (RET-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| RET-001 | Short prompts (<10 chars) exit silently | P1 |
| RET-002 | Stop words excluded from tokenization | P1 |
| RET-003 | Exact word match scores 2 points on title | P1 |
| RET-004 | Exact tag match scores 3 points | P1 |
| RET-005 | Prefix match (4+ chars) scores 1 point on title | P1 |
| RET-006 | Category priority ordering in results | P1 |
| RET-007 | Recency bonus for recently modified files | P1 |
| RET-008 | FTS5 BM25 search with fallback to legacy keyword | P1 |
| RET-009 | Body text extraction and hybrid scoring | P1 |
| RET-010 | Description token scoring (capped at 2) | P1 |
| RET-011 | Confidence labeling in output (high/medium/low) | P1 |
| RET-012 | Tiered output mode (result/compact/silenced) | P2 |
| RET-013 | Search hints for no-match/all-low scenarios | P2 |
| RET-014 | Save-result display and cleanup | P2 |
| RET-015 | Orphan triage detection | P2 |
| RET-016 | Pending notification display | P2 |
| RET-017 | abs_floor / cluster_count threshold filtering | P2 |

### Functional Requirements -- Triage (TRI-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| TRI-001 | Keyword scoring: primary patterns per category | P1 |
| TRI-002 | Co-occurrence boosting within 4-line window | P1 |
| TRI-003 | Session summary scoring: activity-based (tool uses, exchanges) | P1 |
| TRI-004 | Threshold comparison: above triggers, below does not | P1 |
| TRI-005 | Stop flag lifecycle: create on exit 2, TTL-based refire prevention | P1 |
| TRI-006 | Context file generation with staging dir routing | P1 |
| TRI-007 | Context file truncation at 50KB | P1 |
| TRI-008 | Category description loading from config | P1 |
| TRI-009 | Triage data JSON output (file-based with inline fallback) | P1 |
| TRI-010 | Exit protocol: stdout JSON + exit 0 | P1 |
| TRI-011 | Transcript parsing: JSONL with corrupt line skipping | P1 |
| TRI-012 | Text preprocessing: fenced code block stripping | P1 |
| TRI-013 | CONSTRAINT threshold calibration (0.45 with keyword expansion) | P1 |

### Functional Requirements -- Write Operations (WRT-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| WRT-001 | CREATE produces valid JSON + updates index | P1 |
| WRT-002 | UPDATE modifies file, preserves history, bumps timestamps | P1 |
| WRT-003 | RETIRE (soft) sets record_status, removes from index | P1 |
| WRT-004 | OCC hash check: reject update with wrong hash | P1 |
| WRT-005 | Title/tag sanitization at write time | P1 |
| WRT-006 | Pydantic validation: reject invalid data with clear errors | P1 |
| WRT-007 | auto_fix: populate missing fields (timestamps, schema_version) | P1 |
| WRT-008 | Slugification of IDs | P1 |
| WRT-009 | Merge protections: immutable fields, grow-only tags, append-only changes | P1 |
| WRT-010 | Archive/unarchive lifecycle transitions | P1 |
| WRT-011 | Anti-resurrection: block create when retired file exists | P1 |
| WRT-012 | Tags cap enforcement (TAG_CAP with eviction) | P1 |
| WRT-013 | Changes FIFO overflow handling (CHANGES_CAP) | P1 |
| WRT-014 | Restore: retired -> active (clear retirement fields, re-add to index) | P2 |

### Functional Requirements -- Index (IDX-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| IDX-001 | Rebuild generates enriched format with tags | P1 |
| IDX-002 | Rebuild skips retired and archived entries | P1 |
| IDX-003 | Validate detects missing-from-index and stale entries | P1 |
| IDX-004 | GC respects grace period, custom config, missing retired_at | P1 |
| IDX-005 | Health report: category counts, heavily-updated detection | P2 |
| IDX-006 | Query: keyword match/no-match | P2 |
| IDX-007 | Rebuild-on-demand when index.md missing | P1 |

### Functional Requirements -- Candidate Selection (CAN-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| CAN-001 | Score >= 3 threshold for candidate selection | P1 |
| CAN-002 | DELETE disallowed for decision/preference/session_summary | P1 |
| CAN-003 | Lifecycle event + no candidate = NOOP | P1 |
| CAN-004 | Enriched index with tags boosts scoring | P1 |
| CAN-005 | Backward compatibility with legacy index format | P1 |

### Functional Requirements -- Draft Assembly (DRA-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| DRA-001 | assemble_create produces schema-valid JSON for all 6 categories | P1 |
| DRA-002 | assemble_update preserves immutable fields, increments counters | P1 |
| DRA-003 | Input path validation (staging + /tmp only) | P1 |
| DRA-004 | Full Phase 1 pipeline integration (candidate -> draft -> write) | P1 |

### Functional Requirements -- Rolling Window Enforcement (ENF-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| ENF-001 | Retire oldest when active count exceeds max_retained | P1 |
| ENF-002 | Ordering by created_at with filename tiebreaker | P1 |
| ENF-003 | Corrupted JSON skipped, not crashed | P1 |
| ENF-004 | Dry-run mode: report without modification | P2 |
| ENF-005 | Dynamic cap for large excess (not hardcoded 10) | P1 |
| ENF-006 | FlockIndex lock management (acquire, release, stale detection) | P1 |

### Functional Requirements -- Guard Hooks (GRD-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| GRD-001 | Config file (memory-config.json) exempted from write guard | P1 |
| GRD-002 | Staging files auto-approved by write guard | P1 |
| GRD-003 | Cross-hook parity: Pre/PostToolUse agree on exemptions | P1 |
| GRD-004 | SKILL.md commands do not trigger Guardian patterns | P1 |
| GRD-005 | SKILL.md follows Rule 0 for Guardian compatibility | P1 |

### Non-Functional Requirements (NFR-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| NFR-001 | 500-doc FTS5 index build < 100ms | P2 |
| NFR-002 | 500-doc FTS5 query < 100ms | P2 |
| NFR-003 | 500-doc full cycle (build + query + threshold) < 100ms | P2 |
| NFR-004 | Logger emit p95 < 5ms | P2 |
| NFR-005 | Logger emit+cleanup < 50ms | P2 |
| NFR-006 | Fail-open on errors: hooks exit 0 on unexpected input | P1 |

### Observability Requirements (OBS-xxx)

| Req ID | Requirement | Priority |
|--------|------------|----------|
| OBS-001 | JSONL structured logging with schema version | P2 |
| OBS-002 | Level filtering (debug/info/warning/error) | P2 |
| OBS-003 | Log retention cleanup with time gating | P2 |
| OBS-004 | Log analyzer minimum sample size guards | P2 |
| OBS-005 | Log analyzer anomaly detectors (zero-prompt, skip-rate, category-never, booster-never, error-spike) | P2 |


## 4. Mapping Strategy: Test Function -> Requirement ID

### Approach: pytest Custom Markers

```python
# conftest.py addition
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "requirement(id): Link test to requirement ID(s)")
    config.addinivalue_line("markers", "priority(level): P0/P1/P2/P3 priority level")
    config.addinivalue_line("markers", "security: Security-critical test")
    config.addinivalue_line("markers", "integration: Integration test (subprocess)")
    config.addinivalue_line("markers", "performance: Performance benchmark test")
```

### Application Pattern

```python
# Example in test_memory_retrieve.py
class TestScoreEntry:
    @pytest.mark.requirement("RET-003")
    def test_exact_title_match_2_points(self):
        entry = {"title": "JWT authentication", "tags": set()}
        tokens = {"jwt"}
        score = score_entry(tokens, entry)
        assert score == 2

    @pytest.mark.requirement("RET-004")
    def test_exact_tag_match_3_points(self):
        ...

# Example in test_memory_write_guard.py
class TestWriteGuard:
    @pytest.mark.requirement("SEC-009")
    @pytest.mark.security
    def test_blocks_memory_directory_write(self):
        ...

# Multiple requirements per test
class TestCrossHookParity:
    @pytest.mark.requirement("GRD-003", "SEC-015")
    @pytest.mark.integration
    def test_parity_staging_both_hooks_allow(self, tmp_path):
        ...
```

### Many-to-Many Relationship

One test can verify multiple requirements, and one requirement can be verified by multiple tests. The marker accepts variadic arguments:

```python
@pytest.mark.requirement("SEC-001", "SEC-002", "SEC-003")
def test_sanitize_title_strips_all_danger(self):
    ...
```


## 5. Auto-Generated Requirements Pass/Fail Report

### pytest Plugin: `conftest_requirements.py`

```python
"""pytest plugin for requirements traceability.

Add to conftest.py or as a separate plugin. Generates a JSON report
mapping requirement IDs to test results after each test run.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytest


# -----------------------------------------------------------------------
# Storage
# -----------------------------------------------------------------------

_REQ_RESULTS = defaultdict(lambda: {
    "tests": [],
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "errors": 0,
    "status": "unknown",
})


# -----------------------------------------------------------------------
# Hooks
# -----------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requirement(*ids): Link test to one or more requirement IDs"
    )
    config.addinivalue_line(
        "markers",
        "priority(level): P0/P1/P2/P3 priority level"
    )
    config.addinivalue_line("markers", "security: Security-critical test")
    config.addinivalue_line("markers", "integration: Integration test")
    config.addinivalue_line("markers", "performance: Performance benchmark")


def pytest_runtest_makereport(item, call):
    """After each test phase (setup/call/teardown), record results."""
    if call.when != "call":
        return

    # Extract requirement markers
    req_markers = list(item.iter_markers(name="requirement"))
    if not req_markers:
        return

    # Determine outcome
    if call.excinfo is None:
        outcome = "passed"
    elif call.excinfo.typename == "Skipped":
        outcome = "skipped"
    else:
        outcome = "failed"

    # Record against each requirement
    test_id = item.nodeid
    for marker in req_markers:
        for req_id in marker.args:
            entry = _REQ_RESULTS[req_id]
            entry["tests"].append({
                "nodeid": test_id,
                "outcome": outcome,
                "duration": call.duration,
            })
            entry[outcome] = entry.get(outcome, 0) + 1


def pytest_sessionfinish(session, exitstatus):
    """After all tests complete, compute statuses and write report."""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_requirements": len(_REQ_RESULTS),
        "requirements": {},
    }

    passed_count = 0
    failed_count = 0
    partial_count = 0
    untested_count = 0

    for req_id, data in sorted(_REQ_RESULTS.items()):
        total = len(data["tests"])
        if total == 0:
            data["status"] = "untested"
            untested_count += 1
        elif data["failed"] > 0 or data.get("errors", 0) > 0:
            data["status"] = "FAIL"
            failed_count += 1
        elif data["skipped"] == total:
            data["status"] = "skipped"
        elif data["passed"] == total:
            data["status"] = "PASS"
            passed_count += 1
        else:
            data["status"] = "partial"
            partial_count += 1

        report["requirements"][req_id] = data

    report["summary"] = {
        "passed": passed_count,
        "failed": failed_count,
        "partial": partial_count,
        "untested": untested_count,
    }

    # Write JSON report
    report_path = Path("temp/requirements-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Write human-readable summary to terminal
    if _REQ_RESULTS:
        session.config._tw.sep("=", "Requirements Traceability Report")
        session.config._tw.line(
            f"  PASS: {passed_count}  FAIL: {failed_count}  "
            f"PARTIAL: {partial_count}  UNTESTED: {untested_count}"
        )
        for req_id, data in sorted(_REQ_RESULTS.items()):
            icon = {
                "PASS": "OK",
                "FAIL": "XX",
                "partial": "..",
                "skipped": "--",
                "untested": "??",
            }.get(data["status"], "??")
            session.config._tw.line(
                f"  [{icon}] {req_id}: "
                f"{data['passed']}P {data['failed']}F {data['skipped']}S "
                f"({len(data['tests'])} tests)"
            )
        session.config._tw.line(
            f"\n  Report: {report_path.resolve()}"
        )
```

### Usage

```bash
# Run all tests and generate requirements report
pytest tests/ -v

# Run only security-critical tests
pytest tests/ -m security

# Run tests for a specific requirement
pytest tests/ -m "requirement" -k "SEC-001"

# Generate report in CI
pytest tests/ --tb=short 2>&1 | tee test-output.log
cat temp/requirements-report.json
```

### Report Output Example

```
=================== Requirements Traceability Report ===================
  PASS: 47  FAIL: 0  PARTIAL: 0  UNTESTED: 3
  [OK] CAN-001: 2P 0F 0S (2 tests)
  [OK] CAN-002: 3P 0F 0S (3 tests)
  [OK] SEC-001: 14P 0F 0S (14 tests)
  [OK] SEC-004: 8P 0F 0S (8 tests)
  [??] WRT-014: 0P 0F 0S (0 tests)

  Report: /home/idnotbe/projects/claude-memory/temp/requirements-report.json
```

### Dashboard Integration

The `temp/requirements-report.json` can be consumed by:
1. **CI pipeline**: Parse JSON, fail build if any requirement is FAIL
2. **Coverage dashboard**: Render as HTML table with color-coded status
3. **Slack/Teams webhook**: Post summary on each merge to main
4. **CLAUDE.md auto-update**: Script that reads report and updates a requirements status section

Script to generate a markdown dashboard from the JSON report:

```python
#!/usr/bin/env python3
"""Generate markdown requirements dashboard from pytest report."""

import json
import sys
from pathlib import Path

report = json.loads(Path("temp/requirements-report.json").read_text())
reqs = report["requirements"]
summary = report["summary"]

print("# Requirements Status Dashboard")
print(f"\nGenerated: {report['generated_at']}")
print(f"\n| Status | Count |")
print("|--------|-------|")
for k, v in summary.items():
    print(f"| {k.upper()} | {v} |")

print(f"\n## Details\n")
print("| Req ID | Status | Tests | Passed | Failed |")
print("|--------|--------|-------|--------|--------|")
for req_id, data in sorted(reqs.items()):
    status = data["status"]
    print(f"| {req_id} | {status} | {len(data['tests'])} | {data['passed']} | {data['failed']} |")
```


## 6. Coverage Gap Analysis

### Requirements With No Test Coverage

| Req ID | Description | Gap Severity |
|--------|------------|-------------|
| WRT-014 | Restore: retired -> active | Medium -- `memory_write.py` supports `restore` action but no dedicated test exists (only indirectly tested via archive lifecycle) |
| SEC-020 | Transcript path validation | Low -- `memory_triage.py` validates paths but test coverage is only in judge tests (`test_extract_recent_context_path_validation`), not in triage-specific tests |

### Areas With Thin Coverage

| Area | Current Tests | Gap Description |
|------|--------------|-----------------|
| Concurrent write safety | 0 | `memory_write.py` uses FlockIndex but no concurrent write test exists (only rolling window tests the lock) |
| memory_draft.py CLI error paths | ~3 | Only happy-path + invalid input; no test for corrupted candidate file, disk-full during draft write |
| memory_search_engine.py CLI mode | 1 | Only `cli_search` with mocked FTS5; no test for actual `--query` / `--mode search` CLI invocation |
| memory_judge.py end-to-end | 1 | Single integration test with mock API; no test with real transcript file + real candidate list |
| Config file schema drift | 0 | No test verifying `assets/schemas/*.schema.json` match Pydantic models |
| Hooks.json configuration | 0 | No test verifying `hooks/hooks.json` is valid JSON with correct script paths |
| Plugin manifest | 0 | No test verifying `.claude-plugin/plugin.json` is valid |

### Test Quality Observations

**Strengths:**
- Security testing is exceptionally thorough (adversarial descriptions, FTS5 injection, path traversal, sanitization consistency)
- Regression tests for specific bugs (popups, Guardian conflicts) prevent recurrence
- Performance benchmarks guard against degradation
- Logger has the most comprehensive test file (~100+ tests including fail-open resilience)

**Weaknesses:**
- No formal requirements tracing makes it impossible to answer "is requirement X tested?"
- TEST-PLAN.md is partially stale (some test IDs described there were renamed during implementation)
- No mutation testing to verify test assertion quality


## 7. Implementation Plan

### Phase 1: Add Markers (Low effort, high value)

1. Add `pytest_configure` to `conftest.py` with the marker definitions
2. Add `@pytest.mark.requirement()` to existing tests based on the mapping table above
3. Add the plugin code to `conftest.py` for JSON report generation

Estimated work: 2-3 hours (mechanical -- most tests map 1:1 to requirements)

### Phase 2: CI Integration

1. Add `pytest --tb=short` step to CI that generates `temp/requirements-report.json`
2. Add post-step that parses report and fails if any P0 requirement is FAIL
3. Optional: commit report as artifact for historical tracking

### Phase 3: Gap Closure

1. Add `test_restore_action` in `test_memory_write.py` (WRT-014)
2. Add concurrent write safety test using ThreadPoolExecutor
3. Add `hooks.json` / `plugin.json` validity tests
4. Add schema drift test (compare Pydantic model fields vs JSON Schema)

### Phase 4: Dashboard

1. Generate markdown dashboard from JSON report on each CI run
2. Optionally publish as GitHub Pages or PR comment
