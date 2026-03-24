---
status: done
progress: "전체 완료. Phase 0-4 all done. Commits: 05bdc31, cd5559b, b5a957e, 582f993"
---

# Action Plan: PRD/Architecture 현행화 (v5.1.0 → v6.0.0)

**Goal**: `docs/requirements/prd.md`, `docs/architecture/architecture.md`, 및 `CLAUDE.md`를 현재 구현(v6.0.0)에 맞게 업데이트
**Scope**: 문서 현행화. 코드 변경(RUNBOOK threshold, SKILL.md max_inject)은 별도 action plan으로 추적.
**Rollback**: Phase 1 각 step과 각 phase 경계에서 git commit. Validation gate 실패 시 `git revert`로 마지막 passing commit 복원.
**Evidence**: `temp/arch-analysis.md`, `temp/req-analysis.md`, `temp/done-analysis.md`
**Verification**: `temp/verify-r1-completeness.md`, `temp/verify-r1-ops-risk.md`, `temp/verify-r2-final.md`

---

## Phase 0: Scope Lock & Source-of-Truth Matrix
> 목표: 변경 범위 확정, 불일치 분류, 부분 업데이트 현황 파악

- [v] Step 0.1: Source-of-truth matrix 작성
  - 각 PRD/Arch 섹션 → 대응하는 코드/스크립트 파일 매핑
  - Sentinel "JSON state machine" claim → `memory_triage.py` 코드에서 state 필드 확인
  - 파일: `temp/source-of-truth-matrix.md`

- [v] Step 0.2: Scope 결정
  - **In-scope**: PRD, Architecture doc, CLAUDE.md (staging path, component descriptions)
  - **Out-of-scope (별도 추적)**: SKILL.md max_inject default 수정, RUNBOOK threshold code/config 불일치, plugin.json/hooks.json version bump, SKILL.md staging path (코드 변경)
  - Out-of-scope 항목 → 별도 action plan: `action-plans/code-config-drift-fixes.md`

- [v] Step 0.3: 부분 업데이트 현황 파악
  - PRD §3.1.2는 이미 "Three-Phase Save Orchestration (SKILL.md v6)" 제목으로 부분 업데이트됨
  - 각 섹션을 "full rewrite" / "verify-and-patch" / "no change"로 재분류
  - 파일: `temp/section-change-map.md`

**Validation Gate**: 모든 planned doc change에 code-backed source가 있으며, 미해결 불일치가 별도 추적됨

---

## Phase 1: P0 전면 재작성 (핵심 아키텍처 변경)
> 목표: 가장 큰 구조적 차이를 해소.
> 규칙: 각 step 완료 후 git commit. 동일 개념은 PRD→Arch 순서로 연달아 작업.

- [v] Step 1.1: Orchestration Flow — PRD §3.1.2 재작성 (또는 verify-and-patch)
  - §3.1.2가 이미 v6 내용이면: staging path, Phase 1.5 optional 여부, `memory_orchestrate.py --action run` 상세만 패치
  - §3.1.2가 v5 내용이면: 3-phase (SETUP, Phase 1 DRAFT, Phase 2 COMMIT) 기준 전면 재작성
  - Phase 3 haiku saver 제거, `run_in_background: true` drafter, M1 fallback 기술
  - 참조: `SKILL.md`, `memory_orchestrate.py`, `CLAUDE.md`
  - **git commit checkpoint**

- [v] Step 1.2: Orchestration Flow — Arch §2.1 Auto-Capture Flow 재작성
  - Flow 다이어그램을 v6 3-phase 기준으로 재작성
  - `memory_orchestrate.py`의 7-step (3 `--action` modes + no-flag default) 명시
  - `PinnedStagingDir` fd-pinning 사용 기술
  - 참조: `temp/arch-analysis.md §1.3`
  - **git commit checkpoint**

- [v] Step 1.3: Orchestration Model — Arch §4 재작성
  - Execution Model Summary 테이블: 3-phase 반영
  - Subagent 테이블: Phase 3 행 제거, Phase 1.5 VERIFY optional, `run_in_background: true` 명시
  - Direct Bash Commands 테이블: 모두 `memory_orchestrate.py (subprocess)` 경유
  - Inconsistencies 섹션: Point 2,3,4 "RESOLVED" 표시
  - 참조: `temp/arch-analysis.md §1.4`
  - **git commit checkpoint**

- [v] Step 1.4: Storage Layout — PRD §5.1 재작성
  - `.claude/memory/.staging/` → `<staging_base>/.claude-memory-staging-<hash>/` (외부 경로)
  - Staging base 4-tier resolution: XDG_RUNTIME_DIR > /run/user/$UID > macOS confstr > ~/.cache
  - `.claude/memory/` 내부 구조 유지 (sessions/, decisions/ 등)
  - Legacy fallback은 명시적으로 "Legacy" 라벨
  - 참조: `memory_staging_utils.py:_resolve_staging_base()`
  - **git commit checkpoint**

- [v] Step 1.5: Staging Lifecycle — Arch §5.1, §5.2 재작성
  - Location: `memory_staging_utils.get_staging_dir()` 기반
  - Lifecycle 다이어그램: Stop hook → SETUP → Phase 1 DRAFT → Phase 2 COMMIT
  - Flag Files 테이블(§5.2) 업데이트:
    - 경로를 `<staging_dir>/` 표기로 변경
    - `.triage-fire-count`, `.stop_hook_lock` 추가
    - `.triage-pending.json` 생성자: `memory_orchestrate.py`
    - `last-save-result.json` 생성자: `memory_orchestrate.py`
  - **Dependency**: Step 1.3 완료 후 실행 (Phase 3 제거 반영 필요)
  - 참조: `temp/arch-analysis.md §1.5`
  - **git commit checkpoint**

- [v] Step 1.6: CLAUDE.md 업데이트
  - `/tmp/.claude-memory-staging-<hash>/` 참조 → `<staging_dir>/` 또는 XDG 기반 설명으로 변경
  - `memory_staging_utils.py` description: PinnedStagingDir, XDG resolution, parent chain validation 반영
  - `memory_log_analyzer.py` description: `--metrics`, `--watch` 모드 추가
  - `memory_orchestrate.py` description: `execute_saves()`, `--action prepare/commit/run` modes 반영
  - Sentinel state machine 관련 기술 업데이트 (해당 부분이 있다면)
  - 참조: `temp/done-analysis.md §Cross-Reference with Current CLAUDE.md`
  - **git commit checkpoint**

**Validation Gate**: triage부터 commit까지 save path를 legacy 5-phase 모델이나 `.staging/` 가정 없이 추적 가능; CLAUDE.md에 legacy `/tmp/` 참조 없음

---

## Phase 2: P1 주요 업데이트 (컴포넌트, 관측성, 해결된 문제)
> 목표: 신규 컴포넌트 문서화, 해결된 pain point 반영, dependency 갱신
> git commit at phase boundary

- [v] Step 2.1: Arch §3 신규 컴포넌트 상세 섹션
  - §3.15 `memory_staging_utils.py`: PinnedStagingDir, staging base resolution, parent chain validation, is_staging_path()
  - `memory_orchestrate.py` 기존 섹션 확장: `execute_saves()`, 3 `--action` modes + no-flag default
  - `memory_write.py` 섹션(§3.7): `--skip-auto-enforce`, `--result-file`, C1(overwrite guard), C2(index dedup)

- [v] Step 2.2: Component Map 업데이트 (PRD §8, Arch §1)
  - PRD §8 Dependency Map: `memory_staging_utils.py` 추가 (대부분의 hook scripts에서 import)
  - PRD §8: `memory_orchestrate.py` 전체 dependency 기술
  - PRD §8: staging path를 `<staging_dir>/` 표기
  - Arch §1 Component Map: `memory_staging_utils.py` 추가, staging 경로 외부화 반영

- [v] Step 2.3: PRD §3.3 Staging Utilities 업데이트
  - §3.3.7: `cleanup-intents` action 추가
  - `--result-file` flag 기술 (`write-save-result-direct` 제거 및 보안 개선)

- [v] Step 2.4: Retrieval Flow 업데이트 (PRD §3.2, Arch §2.2)
  - Staging path 변경: `get_staging_dir()` 사용, legacy fallback
  - `score_description()` feature 추가 (최대 2점 bonus, 이미 매칭된 항목에만)
  - Save confirmation / orphan detection 경로 업데이트
  - `retrieval.judge.dual_verification` config 키 언급

- [v] Step 2.5: Observability 섹션 확장 (PRD §3.10, Arch §3.14)
  - 누락 event types: `triage.idempotency_skip` (5종), `save.start`/`save.complete`, `retrieval.inject`/`judge_result`/`fallback`
  - Metrics dashboard (`--metrics`), watch mode (`--watch`)
  - `phase_timing` dict (triage_ms, orchestrate_ms, write_ms, total_ms)

- [v] Step 2.6: Sentinel/Concurrency 메커니즘 업데이트
  - PRD §3.1.1: sentinel → JSON state machine (pending/saving/saved/failed)
  - `update-sentinel-state` action 문서화 (memory_write.py)
  - Triage lock mechanism (O_CREAT|O_EXCL)
  - Fire count tracking, save result guard
  - Arch §6: resolved race conditions 표시 (§6.4 #3 double enforcement: RESOLVED)

- [v] Step 2.7: Resolved Pain Points & Weaknesses
  - PRD §6: §6.2 Screen Noise "RESOLVED", §6.3 Guardian "LARGELY RESOLVED", §6.4 Complexity "RESOLVED"
  - Arch §8: §8.2 "RESOLVED", §8.3 "RESOLVED", §8.4 "PARTIALLY RESOLVED", §8.7 "RESOLVED by --skip-auto-enforce"

**Validation Gate**: 신규 컴포넌트마다 backing file reference + behavioral statement가 현재 구현과 일치
**git commit checkpoint**

---

## Phase 3: P2 세부 수정
> 목표: 나머지 차이 해소
> git commit at phase boundary

- [v] Step 3.1: Test Coverage 업데이트 (PRD §7)
  - 신규 test files 추가 (as of 2026-03-24, 정확한 수는 실행 시 확인)
  - "as of" 표기 사용

- [v] Step 3.2: Guard Rails 섹션 업데이트 (PRD §3.4, Arch §2.3)
  - Write guard: dual-path staging (legacy + XDG)
  - Staging guard: `memory_staging_utils` constants 기반 dynamic regex
  - Validate hook: `is_staging_path()` 사용

- [v] Step 3.3: Config 키 추가 (PRD §3.9, Arch §5.4)
  - Agent-interpreted: `architecture.simplified_flow`
  - Script-read: Arch에 `logging.*` 추가 (PRD에는 이미 있음)
  - Script-read: `retrieval.judge.dual_verification`

- [v] Step 3.4: Security 섹션 업데이트 (PRD §4.3, Arch §7.3)
  - Guarantee/invariant 중심 (syscall 상세보다 보안 보장)
  - PinnedStagingDir → TOCTOU 방어, parent chain validation → symlink/traversal 방어
  - `write-save-result-direct` 제거 → shell injection 방어
  - Legacy compatibility path 명시적 "Legacy" 라벨

- [v] Step 3.5: Version/Metadata 일괄 업데이트 (모든 내용 변경 완료 후)
  - PRD header: v5.1.0 → v6.0.0
  - Arch header: v5.1.0 → v6.0.0
  - PRD §9 Plugin Manifest version 기술 업데이트 (실제 plugin.json 변경은 별도 action plan)

**Validation Gate**: guard/config/test 섹션이 현재 구현과 일치; version headers v6.0.0
**git commit checkpoint**

---

## Phase 4: Cross-Verification & AI Usability
> 목표: 정확성, 일관성, AI agent 사용성 검증

- [v] Step 4.1: Code-to-doc 정확성 검증
  - Orchestration flow ↔ `memory_orchestrate.py`
  - Staging path ↔ `memory_staging_utils.py`
  - Observability events ↔ 실제 `emit_event()` 호출
  - Sentinel states ↔ `memory_triage.py`

- [v] Step 4.2: PRD ↔ Architecture 상호 일관성 검증
  - 동일 개념에 동일 용어 (phase 이름, state 이름, default 값)
  - 다이어그램 일관성
  - 공유 개념은 한쪽을 canonical, 다른 쪽은 cross-reference로 권장

- [v] Step 4.3: Cross-doc 일관성 검증
  - CLAUDE.md와의 정합성 (Phase 1.6 업데이트 부분)
  - SKILL.md, plugin.json, hooks.json 비교 → 불일치 시 별도 이슈 기록
  - Markdown anchor 및 내부 cross-reference 검증

- [v] Step 4.4: AI Agent Usability 검증 (task-based walkthrough)
  - Scenario 1: "Updated docs만으로 auto-capture save flow를 triage부터 last-save-result.json까지 추적"
  - Scenario 2: "Updated docs만으로 staging 경로 결정 로직과 보안 모델 설명"
  - Scenario 3: "Updated docs만으로 save 후 metrics/evidence 위치 및 partial failure 감지 설명"

**Validation Gate**: 3개 시나리오 docs만으로 통과; 모든 cross-doc 불일치 기록됨

---

## Appendix A: 변경 영향 매트릭스

| PRD Section | Change Type | Step | Arch Section | Change Type | Step |
|-------------|------------|------|--------------|-------------|------|
| §1 Product Vision | No change | - | §1 Component Map | Update | 2.2 |
| §2 User Stories | No change | - | §1 Execution Model | Rewrite | 1.3 |
| §3.1.1 Triage | Update | 2.6 | §2.1 Auto-Capture | **Rewrite** | 1.2 |
| §3.1.2 Orchestration | **Rewrite/Patch** | 1.1 | §2.2 Retrieval Flow | Update | 2.4 |
| §3.2 Retrieval | Update | 2.4 | §2.3 Guard Flow | Update | 3.2 |
| §3.3 CRUD/Staging | Update | 2.3 | §3.1-3.9 Components | Update | 2.1 |
| §3.4 Guard Rails | Update | 3.2 | §3.10 Logger | No change | - |
| §3.9 Config | Update | 3.3 | §3.14 Log Analyzer | Update | 2.5 |
| §3.10 Logging | Update | 2.5 | §3.15 Staging Utils | **New** | 2.1 |
| §4.3 Security | Update | 3.4 | §4 Orchestration | **Rewrite** | 1.3 |
| §5.1 Storage Layout | **Rewrite** | 1.4 | §5.1 Staging Life. | **Rewrite** | 1.5 |
| §6 Pain Points | Update | 2.7 | §5.2 Flag Files | Update | 1.5 |
| §7 Test Coverage | Update | 3.1 | §6 Concurrency | Update | 2.6 |
| §8 Dependency Map | Update | 2.2 | §8 Weaknesses | Update | 2.7 |
| §9 Manifest | Update | 3.5 | - | - | - |

## Appendix B: Out-of-Scope Items (별도 Action Plan: `code-config-drift-fixes.md`)

| Item | Description | Recommended Action |
|------|-------------|-------------------|
| RUNBOOK threshold | Code DEFAULT_THRESHOLDS 0.5 vs memory-config.default.json 0.4 | config를 0.5로 통일 또는 code를 0.4로 변경 |
| SKILL.md max_inject | SKILL.md says "default: 5", actual default is 3 | SKILL.md 수정 |
| plugin.json version | Still "5.1.0" | "6.0.0"으로 변경 |
| hooks.json description | References "v5.0.0" | "v6.0.0"으로 변경 |
| SKILL.md staging path | References `/tmp/.claude-memory-staging-<hash>/` | XDG 기반으로 변경 |

## Appendix C: Verification Feedback Trace

| Finding | Source | Severity | Resolution |
|---------|--------|----------|------------|
| CLAUDE.md excluded from scope | R1-ops E1 | CRITICAL | Step 1.6 추가; CLAUDE.md in-scope |
| No rollback strategy | R1-ops E4 | HIGH | Git commit checkpoints + rollback rule |
| Known Drift anti-pattern | R1-ops M1 | HIGH | Appendix B로 대체 (별도 action plan) |
| Retrieval flow no owning step | R1-comp M1 | HIGH | Step 2.4 추가 |
| update-sentinel-state misplaced | R1-comp A1 | HIGH | Step 2.6으로 이동 |
| Partial execution cross-doc | R1-ops E2 | HIGH | Phase 1 topic 기준 재정렬 + git checkpoints |
| PRD partially updated | R1-ops E3 | MEDIUM | Step 0.3 verify-and-patch 분류 |
| Duplicate drift docs | R1-ops C2 | MEDIUM | Known Drift 섹션 제거, Appendix B 사용 |
| Step 2.2 too broad | R1-comp S2 | MEDIUM | Steps 2.1/2.2/2.3으로 분할 |
| Version bump timing | R1-comp S3 | MEDIUM | Phase 3 Step 3.5 (마지막)로 이동 |
| Step dependency 1.5→1.3 | R1-ops C1 | MEDIUM | Step 1.5에 dependency 명시 |
| Test count instability | R1-comp A3 | MEDIUM | "as of" 표기, 실행 시 확인 |
| dual_verification config | R1-comp M3 | MEDIUM | Step 3.3에 추가 |
| score_description() missing | R1-comp M2 | MEDIUM | Step 2.4에 포함 |
| --result-file / write-save-result-direct | R1-comp M5 | LOW | Step 2.3, 3.4에 포함 |
| --skip-auto-enforce docs | R1-comp M7 | LOW | Step 2.7에 포함 |
| C1/C2 fix docs | R1-comp M4 | LOW | Step 2.1에 포함 |
| run_in_background docs | R1-comp M6 | LOW | Step 1.3에 포함 |
| "three modes" wording | R1-comp A2 | LOW | Step 1.2에 반영 |
| Sentinel code-backing | R1-ops C3 | MEDIUM | Step 0.1에서 확인 |
| CLAUDE.md Step 1.6 narrow | R2 Codex | HIGH→MEDIUM | Step 1.6 범위 확대 (orchestrate, sentinel) |
| Rollback formalization | R2 Codex | HIGH→LOW | Plan header에 rollback rule 추가 |
