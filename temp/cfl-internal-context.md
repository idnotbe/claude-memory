# Closed Feedback Loop (CFL) -- Internal Context Synthesis

**Date**: 2026-03-22
**Source documents**: PRD v5.1.0, Architecture v5.1.0, Observability Action Plan, tests/ directory (20 files)

---

## 1. PRD Key Requirements Summary

### 1.1 User Stories (US-1 ~ US-11)

| ID | Description | Verifiable? | Current Test Coverage |
|----|-------------|-------------|----------------------|
| US-1 | Auto-capture on session end (Stop hook evaluates, blocks, saves) | Yes | `test_memory_triage.py` (scoring, blocking, context files, e2e) |
| US-2 | Auto-inject on prompt (UserPromptSubmit searches + injects) | Yes | `test_memory_retrieve.py` (scoring, FTS5, output, integration) |
| US-3 | Save confirmation on next session | Yes | `test_memory_retrieve.py::TestSaveConfirmation` (6 tests) |
| US-4 | Orphan crash detection | Yes | `test_memory_retrieve.py::TestOrphanCrashDetection` (6 tests) |
| US-5 | Session rolling window (auto-cap at N) | Yes | `test_rolling_window.py` (19 tests) |
| US-6 | Manual save via `/memory:save` | Partially | SKILL.md orchestration -- no automated e2e test |
| US-7 | Status check via `/memory` | No | Slash command -- no automated test |
| US-8 | Lifecycle management (`--retire/archive/restore/gc`) | Yes | `test_memory_write.py` (retire/archive/unarchive flows), `test_memory_index.py::TestGC` |
| US-9 | Configuration via `/memory:config` | No | Slash command -- no automated test |
| US-10 | Explicit search via `/memory:search` | Partially | `test_fts5_search_engine.py` (engine tested), slash command flow untested |
| US-11 | Recall via conversational prompts | No | Depends on LLM behavior -- not unit-testable |

### 1.2 Functional Requirements (FR)

#### FR-3.1: Auto-Capture (Triage + 5-Phase Save)

| Requirement | PRD Section | Pass/Fail Criteria | Test Coverage |
|-------------|-------------|---------------------|---------------|
| Triage reads last N messages (default 50) | 3.1.1 | Configurable, clamped 10-200 | `test_memory_triage.py::TestParseTranscriptFiltering` |
| Code block stripping before scoring | 3.1.1 | False positives reduced | `test_memory_triage.py::TestExtractTextContent` |
| Activity metrics extraction (tool_uses, distinct_tools, exchanges) | 3.1.1 | Correct counts | `test_memory_triage.py::TestExtractActivityMetrics` |
| 6-category scoring (5 text + 1 activity) | 3.1.1 | Per-category patterns | `test_memory_triage.py::TestConstraintThresholdFix`, `TestScoreLogging` |
| Co-occurrence boosting (4-line window) | 3.1.1 | Primary vs boosted weights | `test_memory_triage.py::TestConstraintThresholdFix` (tests boosters) |
| Configurable thresholds (0.4-0.6 defaults) | 3.1.1 | Clamped 0.0-1.0 | `test_memory_triage.py::TestEdgeCases::test_run_triage_respects_thresholds` |
| Re-fire prevention (flag + sentinel) | 3.1.1 | 5min TTL, idempotent | `test_memory_triage.py::TestSentinelIdempotency` (7 tests) |
| Context file generation per category | 3.1.1 | `.staging/context-<cat>.txt` | `test_memory_triage.py::TestContextFileIncludesDescription`, `TestStagingPaths` |
| Triage-data.json atomic write | 3.1.1 | tmp+rename pattern | `test_memory_triage.py::TestRunTriageWritesTriageDataFile` (3 tests) |
| CUD Resolution table (7 rules) | 3.1.3 | Mechanical resolution | **NO dedicated test** -- relies on SKILL.md interpretation |
| Phase 1 parallel intent drafting | 3.1.2 | Agent subagents with Read+Write only | **NO automated test** -- subagent spawning is runtime |
| Phase 2 content verification | 3.1.2 | Hallucination=BLOCK, minor=ADVISORY | **NO automated test** -- subagent spawning is runtime |
| Phase 3 single save subagent | 3.1.2 | Combined Bash call | **NO automated test** -- subagent spawning is runtime |

#### FR-3.2: Memory Retrieval

| Requirement | PRD Section | Pass/Fail Criteria | Test Coverage |
|-------------|-------------|---------------------|---------------|
| FTS5 BM25 search | 3.2.1 | In-memory SQLite, ranked results | `test_fts5_search_engine.py` (full coverage) |
| Hybrid body scoring (+3 bonus max) | 3.2.1 | Body text bonus capped | `test_fts5_search_engine.py::TestHybridScoring`, `test_v2_adversarial_fts5.py::TestScoreManipulation` |
| 25% noise floor | 3.2.1 | Weak matches filtered | `test_v2_adversarial_fts5.py::TestApplyThresholdEdgeCases` |
| max_inject clamped [0,20] | 3.2.1 | Config validation | `test_arch_fixes.py::TestIssue3MaxInjectClamp` (11 tests) |
| LLM Judge (optional) | 3.2.1 | Anti-position-bias, batch splitting | `test_memory_judge.py` (45+ tests) |
| Confidence labeling (high/medium/low) | 3.2.1 | Ratio to best score | `test_memory_retrieve.py::TestConfidenceLabel` (14 tests) |
| Tiered output mode | 3.2.1 | HIGH/MEDIUM/LOW rendering | `test_memory_retrieve.py::TestTieredOutput` (10 tests) |
| Legacy keyword fallback | 3.2.2 | When FTS5 unavailable | `test_fts5_search_engine.py::TestFTS5Fallback` |
| Short prompt skip (<10 chars) | 3.2.1 | Greetings skipped | `test_memory_retrieve.py::TestRetrieveIntegration::test_short_prompt_skipped` |
| Save confirmation Block 1 | 3.2.1 | <24h result displayed + deleted | `test_memory_retrieve.py::TestSaveConfirmation` (6 tests) |
| Orphan detection Block 2 | 3.2.1 | Stale triage-data warning | `test_memory_retrieve.py::TestOrphanCrashDetection` (6 tests) |
| Pending notification Block 3 | 3.2.1 | .triage-pending check | `test_memory_retrieve.py::TestPendingSaveNotification` (7 tests) |

#### FR-3.3: Memory CRUD

| Requirement | PRD Section | Pass/Fail Criteria | Test Coverage |
|-------------|-------------|---------------------|---------------|
| CREATE with auto-fix + validation | 3.3.1 | Schema-valid output | `test_memory_write.py::TestCreateFlow`, `TestAutoFix` |
| CREATE anti-resurrection (24h) | 3.3.1 | Block re-creation | `test_memory_write.py::TestCreateFlow::test_create_anti_resurrection` |
| CREATE forces record_status=active | 3.3.1 | Injection prevention | `test_memory_write.py::TestCreateRecordStatusInjection` (2 tests) |
| UPDATE merge protections | 3.3.2 | Grow-only tags, append-only changes | `test_memory_write.py::TestMergeProtections` (7 tests) |
| UPDATE OCC hash check | 3.3.2 | MD5 mismatch = conflict | `test_memory_write.py::TestUpdateFlow::test_update_occ_hash_mismatch` |
| UPDATE slug rename (>50% title change) | 3.3.2 | File renamed | `test_memory_write.py::TestUpdateFlow::test_update_slug_rename` |
| RETIRE soft delete | 3.3.3 | Status=retired, removed from index | `test_memory_write.py::TestRetireFlow` (3 tests) |
| ARCHIVE long-term preservation | 3.3.4 | Status=archived, not GC-eligible | `test_memory_write.py::TestArchiveFlow` (5 tests) |
| UNARCHIVE restore | 3.3.5 | Archived -> active | `test_memory_write.py::TestUnarchiveFlow` (5 tests) |
| RESTORE from retired | 3.3.6 | Retired -> active | Indirectly via `test_rolling_window.py` restore-related tests |
| Atomic writes (tmp+rename) | 3.3.1 | No partial files | Structural (uses `atomic_write_json`) |

#### FR-3.4: Guard Rails

| Requirement | PRD Section | Pass/Fail Criteria | Test Coverage |
|-------------|-------------|---------------------|---------------|
| Write guard blocks memory dir | 3.4.1 | DENY for non-staging | `test_memory_write_guard.py` (16 tests) |
| Write guard staging auto-approve (4 gates) | 3.4.1 | Extension, filename, nlink, new file | `test_memory_write_guard.py::TestStagingAutoApprove` (10 tests) |
| Staging guard blocks Bash writes | 3.4.2 | Heredoc, cat, tee, cp, mv | `test_memory_staging_guard.py` (20+ tests) |
| Validate hook quarantines invalid | 3.4.3 | Detection-only, rename | `test_memory_validate_hook.py` (20+ tests) |
| Staging exemption (validate hook) | 3.4.3 | .staging/ skipped | `test_memory_validate_hook.py::TestStagingExemption` (6 tests) |
| Cross-hook parity | 3.4.1-3 | Consistent allow/deny | `test_memory_validate_hook.py::TestCrossHookParity` (2 tests) |

#### FR-3.5-3.8: Supporting Scripts

| Requirement | Script | Test Coverage |
|-------------|--------|---------------|
| Rolling window enforcement | memory_enforce.py | `test_rolling_window.py` (19 tests) |
| Index rebuild/validate/gc/health | memory_index.py | `test_memory_index.py` (15+ tests) |
| Draft assembly (create/update) | memory_draft.py | `test_memory_draft.py` (30+ tests) |
| Candidate selection (ACE) | memory_candidate.py | `test_memory_candidate.py` (20+ tests) |

### 1.3 Non-Functional Requirements (NFR)

| NFR | PRD Section | Pass/Fail Criteria | Test Coverage |
|-----|-------------|---------------------|---------------|
| Minimal screen noise | 4.1 | No approval popups | `test_regression_popups.py` (8 tests + pattern scanning) |
| Guardian compatibility | 4.1 | No false positives | `test_regression_popups.py::TestSkillMdGuardianConflicts`, `TestSkillMdRule0Compliance` |
| Hook timeouts | 4.2 | 5s/15s/30s per type | Configured in hooks.json -- no runtime test |
| FTS5 sub-ms query | 4.2 | Performance requirement | `test_fts5_benchmark.py` (5 benchmarks) |
| Fail-open design | 4.4.1 | Errors never block user | Structural -- tested across all integration tests |
| OCC (MD5 hash) | 4.4.2 | Concurrent update safety | `test_memory_write.py::test_update_occ_hash_mismatch` |
| Atomic writes | 4.4.3 | tmp+rename pattern | Structural -- used throughout |
| FlockIndex (mkdir lock) | 4.4.4 | 15s timeout, 60s stale | `test_arch_fixes.py::TestIssue4MkdirLock` (8 tests) |
| Venv bootstrap | 4.4.5 | Pydantic v2 auto-resolution | Structural -- os.execv() pattern |

### 1.4 Security Requirements

| Threat | PRD Section | Defense | Test Coverage |
|--------|-------------|---------|---------------|
| Prompt injection | 4.3.1 | Title/tag sanitization | `test_adversarial_descriptions.py`, `test_arch_fixes.py::TestIssue5TitleSanitization`, `test_v2_adversarial_fts5.py::TestOutputSanitization` |
| Config manipulation | 4.3.2 | Clamping, validation | `test_arch_fixes.py::TestIssue3MaxInjectClamp`, `test_v2_adversarial_fts5.py::TestConfigAttacks` |
| Index fragility | 4.3.3 | Delimiter stripping | `test_v2_adversarial_fts5.py::TestIndexInjection` |
| FTS5 injection | 4.3.4 | Safe chars, parameterized queries | `test_v2_adversarial_fts5.py::TestFTS5QueryInjection` (10 tests) |
| LLM judge integrity | 4.3.5 | Anti-position-bias, XML wrapping | `test_memory_judge.py` (shuffle tests, memory_data tag tests) |
| Path traversal | 4.3.5 | resolve+relative_to, containment | `test_v2_adversarial_fts5.py::TestPathTraversal` (10 tests), `test_memory_write.py::TestPathTraversal` |
| Hard link defense | 4.3.5 | nlink check | `test_memory_write_guard.py::test_staging_hardlink_no_allow`, `test_memory_validate_hook.py::TestStagingHardLink` |
| Thread safety | 4.3.6 | No shared mutable state | `test_memory_judge.py::TestJudgeParallel` (7 tests) |
| Anti-resurrection | 4.3.7 | 24h cooldown check inside flock | `test_memory_write.py::test_create_anti_resurrection` |

---

## 2. Architecture Decisions Relevant to CFL

### 2.1 핵심 아키텍처 결정 (Key Design Decisions)

Architecture Document Section 8에서 10가지 known weakness를 식별함:

| ID | Weakness | CFL 관련성 |
|----|----------|-----------|
| 8.1 | Stop hook re-fire loop (flag consumed before sentinel) | **High** -- 관찰 불가. fire_count 로깅 없음 |
| 8.2 | Multi-phase orchestration complexity (5 phases, 3 subagent types) | **High** -- Phase 1/2/3 subagent 행동 검증 불가 |
| 8.3 | Screen noise from intermediate steps | **Medium** -- popup 측정 불가 (platform limitation) |
| 8.4 | Mixed execution models (hooks/skills/subagents/bash) | **Medium** -- 실행 경로 추적 어려움 |
| 8.5 | PostToolUse limitation (detection-only) | **Low** -- 구조적 한계, 테스트로 커버 |
| 8.6 | Staging directory as shared mutable state | **Medium** -- 중간 상태 corruption 감지 불가 |
| 8.7 | Dual enforcement for session summaries | **Low** -- 중복이지만 안전 |
| 8.8 | Config split (script-read vs agent-interpreted) | **High** -- agent-interpreted config 효과 검증 불가 |
| 8.9 | Index as single point of failure | **Medium** -- corrupt index 자동 감지 없음 |
| 8.10 | Tokenizer inconsistency (intentional) | **Low** -- 문서화됨 |

### 2.2 Execution Model Summary (CFL 관점)

```
                    Deterministic (testable)          LLM-dependent (not unit-testable)
                    -------------------------         ---------------------------------
Hook scripts:       triage, retrieve, guards,         (none)
                    validate, logger

Scripts:            candidate, draft, write,           (none)
                    enforce, index, search_engine

Orchestration:      (none)                            SKILL.md Phases 0-3
                                                       Phase 1 drafter agents
                                                       Phase 2 verification agents
                                                       Phase 3 save agent
```

**CFL 핵심 인사이트**: 모든 deterministic 컴포넌트는 pytest로 검증 가능하지만, 5-Phase orchestration (SKILL.md) 전체는 **LLM 행동에 의존**하므로 unit test 불가. 이 gap을 메우려면 integration/e2e 테스트 또는 로그 기반 사후 검증이 필요함.

### 2.3 Data Flow (검증 가능한 체크포인트)

Auto-capture flow에서 검증 가능한 체크포인트:
1. **Triage output** -- `triage-data.json` 구조 검증 가능 (test 존재)
2. **Intent files** -- `intent-<cat>.json` 스키마 검증 가능 (test 부재)
3. **Candidate output** -- `memory_candidate.py` JSON 출력 검증 (test 존재)
4. **Draft files** -- `draft-<cat>.json` Pydantic 검증 (test 존재)
5. **Final memory files** -- `memory_write.py` 스키마 검증 (test 존재)
6. **Save result** -- `last-save-result.json` 구조 검증 (test 존재)

**Gap**: 체크포인트 2 (intent files)와 Phase 간 전환 로직의 자동 검증이 없음.

---

## 3. Observability & Logging 현황

### 3.1 현재 로깅 기능 (memory_logger.py)

**기능:**
- JSONL structured logging (fail-open, atomic append)
- Event categories: triage, retrieval, search, guard, validate
- Level filtering: debug < info < warning < error
- Session ID correlation (from transcript path)
- Auto-cleanup (retention_days, default 14)
- Results truncation (max 20 entries per log line)
- Symlink protection during cleanup

**Test coverage**: `test_memory_logger.py` -- 60+ tests covering:
- Normal append, directory handling, config parsing
- Level filtering, cleanup, session ID extraction
- Concurrent append, performance benchmarks
- Path traversal prevention, symlink protection
- NaN/Infinity handling, set serialization
- End-to-end logging pipeline, operational workflow smoke tests

### 3.2 현재 로깅 이벤트

| Event Type | Logged By | Data |
|------------|-----------|------|
| `triage.score` | memory_triage.py | Category scores, triggered categories, text length, metrics |
| `triage.error` | memory_triage.py | Triage failures |
| `retrieval.skip` | memory_retrieve.py | Short prompt, disabled |
| `retrieval.search` / `retrieval.inject` | memory_retrieve.py | Query, results, count |
| `retrieval.error` | memory_retrieve.py | Retrieval failures |
| `search.query` | memory_search_engine.py | CLI search queries |
| `guard.write_deny` / `guard.write_allow_staging` | memory_write_guard.py | Guard decisions |
| `guard.staging_deny` | memory_staging_guard.py | Staging guard denials |
| `validate.*` | memory_validate_hook.py | Validation results, quarantines |

### 3.3 Observability Gaps (action-plans/observability-and-logging.md)

**Status: not-started**

| Gap | Impact | Phase |
|-----|--------|-------|
| Stop hook re-fire count per session | 효과 검증 불가 | Phase 1 |
| Session ID in all triage events | 세션 간 상관관계 불완전 | Phase 1 |
| Idempotency skip logging | 어떤 guard가 발동했는지 불명 | Phase 1 |
| Save flow end-to-end timing | 병목 식별 불가 | Phase 2 |
| User popup confirmations | Popup 빈도 측정 불가 (platform limitation) | N/A |
| Guardian popup triggers | Memory ops와 상관관계 불가 | N/A |
| Subagent model compliance | Instruction violation 감지 불가 | Phase 2 |
| Write tool vs script path usage | Migration completeness 검증 불가 | Phase 2 |
| Triage-to-save latency | User wait time 측정 불가 | Phase 2 |

**Gemini V-R1/R2 권고**: Phase 1 (triage observability)만 즉시 진행. Phase 2-3는 architecture-simplification.md 이후.

### 3.4 Log Analyzer (memory_log_analyzer.py)

**현재 기능:**
- Skip rate spike detection (90%+ = critical)
- Zero-length prompt detection (50%+ of skips)
- Category never triggers detection
- Booster never hits detection
- Error spike detection (10%+)
- Minimum sample size guards (false alarm 방지)

**Test coverage**: `test_log_analyzer.py` -- 30+ tests covering all anomaly detectors with minimum sample size validation.

---

## 4. Test Structure Analysis

### 4.1 Test Files Overview (20 files)

| Test File | # Classes | # Tests (approx) | Coverage Area |
|-----------|-----------|-------------------|---------------|
| `conftest.py` | 0 | N/A | Shared fixtures (6 memory factories, index builder, filesystem setup) |
| `test_memory_triage.py` | 14 | ~60 | Triage scoring, config, transcript parsing, context files, e2e |
| `test_memory_retrieve.py` | 16 | ~70 | Retrieval, scoring, confidence, output, save confirm, orphan, pending |
| `test_memory_write.py` | 14 | ~45 | CRUD, merge protections, OCC, anti-resurrection, validation |
| `test_memory_candidate.py` | 7 | ~25 | Candidate selection, scoring, CUD, vetoes, excerpts |
| `test_memory_draft.py` | 9 | ~35 | Draft assembly, input validation, path security, CLI |
| `test_memory_index.py` | 6 | ~15 | Index rebuild, validate, GC, health, query |
| `test_memory_write_guard.py` | 2 | ~20 | Write guard decisions, staging auto-approve |
| `test_memory_staging_guard.py` | 4 | ~25 | Staging guard patterns, edge cases, hardlink blocking |
| `test_memory_validate_hook.py` | 8 | ~25 | PostToolUse validation, quarantine, staging exemption |
| `test_memory_judge.py` | 11 | ~50 | LLM judge API, batching, shuffling, parsing |
| `test_memory_logger.py` | 20 | ~80 | Logging, config, cleanup, concurrency, performance, e2e |
| `test_fts5_search_engine.py` | 5 | ~20 | FTS5 index, query, body extraction, hybrid scoring |
| `test_fts5_benchmark.py` | 1 | 5 | Performance (500-doc benchmarks) |
| `test_rolling_window.py` | 2 | ~25 | Rolling window enforcement, FlockIndex, retire_record |
| `test_arch_fixes.py` | 6 | ~30 | 5 architectural fix verifications |
| `test_regression_popups.py` | 4 | ~12 | Approval popup regression, Guardian pattern compliance |
| `test_adversarial_descriptions.py` | 8 | ~35 | Category description injection attacks |
| `test_v2_adversarial_fts5.py` | 12 | ~55 | FTS5 injection, path traversal, score manipulation, config attacks |
| `test_log_analyzer.py` | 7 | ~30 | Log anomaly detection with min sample guards |

**Total**: approximately **~560 tests** across 20 files.

### 4.2 Test Architecture

**Patterns used:**
- `conftest.py` provides 6 category-specific memory factories + `bulk_memories` (500-entry) fixture
- `memory_root` and `memory_project` fixtures create temp directory structures
- Both unit tests (direct function import) and integration tests (subprocess execution) exist
- Security tests are separated into dedicated adversarial test files

**Test infrastructure strengths:**
- Comprehensive shared fixtures with realistic data
- Both unit and CLI integration tests for major scripts
- Dedicated adversarial/security test suites
- Performance benchmarks with time bounds
- Regression tests for specific bug classes (popups)

### 4.3 PRD-to-Test Coverage Gap Analysis

#### Well-covered areas (Pass/Fail deterministic):
- Triage scoring algorithms (all 6 categories)
- Retrieval pipeline (FTS5, legacy, confidence, output)
- CRUD operations (all 6 actions)
- Guard rails (write guard, staging guard, validate hook)
- Security (injection, traversal, sanitization, thread safety)
- Index management (rebuild, validate, GC, health)
- Logging (emit, config, cleanup, concurrency)
- Rolling window enforcement

#### Gaps (requirements without automated verification):

| Gap ID | Requirement | Reason | CFL Priority |
|--------|-------------|--------|--------------|
| G-1 | Phase 1-2-3 orchestration (SKILL.md) | LLM-dependent, subagent spawning | **Critical** |
| G-2 | CUD Resolution table correctness | Implemented as SKILL.md prose, not code | **High** |
| G-3 | Intent file schema validation | No schema enforcement for intent-<cat>.json | **High** |
| G-4 | Cross-phase data integrity | Staging directory state transitions untested | **High** |
| G-5 | Slash command flows (US-6,7,8,9) | Require full Claude Code runtime | **Medium** |
| G-6 | Screen noise measurement (NFR-4.1) | Platform limitation -- no API to count popups | **Medium** |
| G-7 | Stop hook re-fire count | No fire_count logging yet | **Medium** |
| G-8 | Save flow end-to-end timing | No timing instrumentation | **Medium** |
| G-9 | Agent-interpreted config effectiveness | `categories.*.enabled` depends on LLM | **Medium** |
| G-10 | Concurrent session stops | Race condition between two sessions | **Low** |
| G-11 | Subagent model compliance | Instruction following verification | **Low** |

### 4.4 Test Extension Opportunities for CFL

#### 4.4.1 Immediate (no new infrastructure needed):

1. **CUD Resolution unit tests** -- Extract the CUD table as a Python function (it's currently in SKILL.md prose) and add parameterized tests for all 7 resolution rules.
2. **Intent file schema tests** -- Add Pydantic models for SAVE/NOOP intent formats and validate in `test_memory_draft.py`.
3. **Cross-phase staging state tests** -- Test that each phase's output files have the expected structure for the next phase.
4. **Triage fire_count tests** -- Once Phase 1 of observability plan lands, add `test_memory_triage.py::TestFireCount`.

#### 4.4.2 Medium-term (requires log analysis infrastructure):

5. **Post-hoc orchestration verification** -- Use `memory_log_analyzer.py` to verify save flow completed correctly by checking log event sequences.
6. **Save timing regression tests** -- After Phase 2 of observability plan, add timing bounds to integration tests.
7. **Save-result structure validation** -- Verify `last-save-result.json` contains correct categories/titles after save flows.

#### 4.4.3 Long-term (requires e2e test harness):

8. **Full save flow e2e** -- Simulate triage -> SKILL.md -> save with mock subagents.
9. **Screen noise measurement** -- Count tool calls in mock sessions.
10. **Config propagation e2e** -- Verify agent-interpreted config changes affect behavior.

---

## 5. CFL-Specific Observations

### 5.1 이미 존재하는 피드백 루프 요소

1. **Log anomaly detection** (`memory_log_analyzer.py`) -- 비정상 패턴 자동 감지
2. **Index validation** (`memory_index.py --validate`) -- 인덱스 무결성 확인
3. **Health report** (`memory_index.py --health`) -- 시스템 상태 요약
4. **Save confirmation** (retrieval Block 1) -- 이전 세션 저장 결과 확인
5. **Orphan detection** (retrieval Block 2) -- 비정상 종료 감지
6. **Pending notification** (retrieval Block 3) -- 실패한 저장 감지

### 5.2 누락된 피드백 루프 요소

1. **Requirement traceability** -- PRD 요구사항 ID -> 테스트 매핑이 없음 (이 문서가 첫 시도)
2. **Runtime correctness verification** -- 저장된 메모리가 원본 대화와 일치하는지 검증 없음
3. **Drift detection** -- SKILL.md 지시사항 대비 실제 LLM 행동 편차 감지 없음
4. **Coverage tracking** -- 어떤 PRD 요구사항이 테스트로 커버되는지 자동 추적 없음
5. **Regression prevention** -- 새로운 버그 클래스 발생 시 자동으로 회귀 테스트 추가하는 프로세스 없음

### 5.3 CFL 구현을 위한 핵심 데이터 소스

| Data Source | Location | Available Now? | CFL Use |
|-------------|----------|----------------|---------|
| JSONL logs | `.claude/memory/logs/` | Yes | Event sequence analysis, anomaly detection |
| Test results | `pytest tests/ -v` | Yes | Pass/fail per requirement |
| Save results | `.staging/last-save-result.json` | Yes | Save quality metrics |
| Index health | `memory_index.py --health` | Yes | Data integrity |
| Log analyzer | `memory_log_analyzer.py` | Yes | Anomaly alerts |
| Triage-data.json | `.staging/triage-data.json` | Transient | Triage decision audit |
| Intent files | `.staging/intent-<cat>.json` | Transient | Phase 1 output audit |
| Draft files | `.staging/draft-<cat>.json` | Transient | Phase 1.5 output audit |

**주의**: Staging 파일은 성공 시 cleanup되므로, CFL이 이를 활용하려면 cleanup 전에 캡처하거나 로그에 기록해야 함.
