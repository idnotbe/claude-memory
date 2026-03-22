# Closed Feedback Loop for claude-memory Plugin (v2)

**Research Document** | Date: 2026-03-22 | Status: Complete (v2, R1+R2 검증 반영)
**Purpose**: action-plans/ 생성 전 사전 연구. claude-memory 플러그인의 자율적 자가개선 루프 설계.
**Supersedes**: v1 (cross-repo promotion 모델)

---

## 1. Problem Statement

claude-memory 플러그인은 repo A (claude-memory)에서 개발되지만, 실제 사용은 repo B (ops 등)에서 이뤄진다. repo B에서 발견되는 버그, UX 문제, 성능 저하가 repo A로 자동으로 피드백되지 않아, 개선 사이클이 느리고 수동적이다.

**v2에서 추가된 핵심 문제:**
- 로그에 충분히 남기라고 해도, 실제 화면에 보이는 정보가 로그에 없다 (팝업, Guardian 승인 대화상자, 상태 메시지)
- ops 환경을 정확히 재현하거나 가져오기가 어렵다 (수동 의존)
- 외부 데이터에 의존하면 자율적 closed loop가 돌지 않는다

**현재 상태:**
- 21개 테스트 파일, 1158개 테스트 케이스 (Tier 1: 단위/통합 테스트)
- JSONL 로그 인프라 존재 (triage, retrieval, guard, validate 이벤트)
- `memory_logger.py` 기반 구조화된 로깅
- `memory_log_analyzer.py` 로 오프라인 분석 가능

---

## 2. Design Philosophy: v1 → v2

### v1의 근본 문제

v1은 "ops에서 발생하는 문제를 claude-memory로 가져온다"는 cross-repo promotion 모델이었다. 사용자 피드백이 지적한 4가지 문제:

1. **ops 환경 재현 불가**: ops 폴더의 정확한 환경을 가져오기 어렵다
2. **수동 의존**: 상황이 발생할 때마다 수동으로 가져와야 한다
3. **로그 불충분**: 실제 화면에 보이는 정보가 로그에 없다
4. **closed loop 불가**: 외부 데이터에 의존하면 자율적 개선 루프가 안 돈다

### v2의 핵심 전환

| 영역 | v1 | v2 |
|------|-----|-----|
| 데이터 소스 | ops 레포에서 수집/수입 | claude-memory 레포 내부에서 직접 생성 |
| 환경 | 외부 | 재귀적 자기 설치 + Guardian 공존 (ops 시뮬레이션) |
| 증거 | JSONL 로그만 | 로그 + stderr + stdout + stream-json + 수동 TUI 캡처 |
| Phase 3 | Cross-repo promotion | 요구사항 추적 + 완전한 테스트 커버리지 |
| Phase 5 | Shadow Loop (자동 patch) | **수동 먼저** → ralph loop로 자동화 |
| 한계 인정 | 없음 | Residual Risk Register (솔직한 한계 기록) |

### Honest Limitations

1. **TUI 팝업 자동 검증 불가**: `claude -p`에서 Guardian approval dialog이 발생하지 않음. Track B 수동 검증으로 보완.
2. **Guardian 수정 범위**: 탐지만 가능. Guardian 자체 버그는 이 레포에서 수정 불가.
3. **사용자의 allow/deny 응답 캡처 불가**: Claude Code가 hook stdout을 내부 소비하고 로그에 남기지 않음.

---

## 3. External Reference Analysis

### 3.1 karpathy/autoresearch

**핵심 아키텍처**: 3개 파일 (`prepare.py`, `train.py`, `program.md`)만으로 자율 연구 루프 구현.

**차용할 패턴:**
- 고정 시간 예산: 각 이터레이션에 일정 시간 할당
- 단일 지표: `val_bpb` → 우리는 "통과 요구사항 수"
- 결과 로그 (results.tsv → progress.txt): append-only 학습 로그
- keep/discard 패턴: 개선되면 유지, 아니면 revert

### 3.2 snarktank/ralph

**핵심 아키텍처**: Bash 루프 (`ralph.sh`) + `prd.json` + `progress.txt`.

**차용할 패턴:**
- prd.json → requirements.json (불변 요구사항 + 파생 상태)
- Fresh context per iteration (컨텍스트 오염 방지)
- progress.txt (append-only 학습 누적)
- Branch isolation + acceptance criteria
- Quality gates (typecheck + tests)

---

## 4. Screen Capture Research

> 상세: `temp/cfl-v2-screen-capture.md`

### 4.1 핵심 발견: 로그 갭의 원인

Claude Code의 transcript JSONL에 `hook_progress` 이벤트가 기록되지만, **hook이 반환하는 JSON 결정 (allow/deny/ask)은 기록되지 않는다.** Claude Code가 내부적으로 소비하고 버린다.

| 화면 요소 | Transcript JSONL | Stream-JSON | Guardian Log | Hook Audit |
|-----------|-----------------|-------------|--------------|------------|
| Hook decision (allow/deny) | **NO** | **NO** | Yes (자체 훅만) | **YES** (구현 시) |
| Permission dialog text | **NO** | **NO** | Partial | **NO** |
| 사용자 allow/deny 응답 | **NO** | **NO** | **NO** | **NO** |
| Memory triage output | Yes (user message) | No | No | **YES** |
| Stop hook injected message | Yes (user message) | No | No | **YES** |

### 4.2 추천 접근법 (3-Tier)

**Tier 1: Hook-Internal Audit Logging (즉시 구현)**
- `memory_logger.py` 확장하여 모든 hook 결정을 JSONL로 기록
- 이미 90% 인프라 존재. 최고 신뢰성, 최저 리스크.
- 한계: 자체 hook만 캡처. 다른 플러그인 결정이나 사용자 응답은 불가.

**Tier 2: `--debug "hooks" --debug-file` (CI/자동화용)**
- Claude Code 자체의 hook 디버그 출력 캡처
- 자동화 세션에서 추가 가시성 제공

**Tier 3: Terminal Recording (디버깅용)**
- `script -e -q -c "claude ..." output.log` 으로 full PTY 출력
- ANSI escape 포함 — 디버깅에만 사용, 프로덕션 분석에 부적합

**하지 않는 것:**
- ANSI escape sequence 의미론적 파싱
- TUI 레이아웃 재구성
- NODE_OPTIONS monkey-patching (너무 취약)

### 4.3 Cross-Model 합의

3개 모델 (Opus 4.6, Codex 5.3, Gemini 3.1 Pro) 모두 동의:
- TUI scraping은 프로덕션에 부적합
- Hook-internal audit logging이 가장 신뢰할 수 있는 접근
- 사용자의 수동 allow/deny 응답은 어떤 방법으로도 안정적 캡처 불가

---

## 5. Recursive Self-Installation Architecture

> 상세: `temp/cfl-v2-recursive-arch.md`

### 5.1 Core Decision: True Dogfood in Canonical Repo

claude-memory 레포에 claude-memory 플러그인을 직접 설치 (worktree가 아닌 실제 레포). Guardian도 공존 설치하여 ops 환경을 시뮬레이션.

**결정 근거:**
- 사용자가 실제 개발 작업 중 동작 관찰을 원함
- Worktree 격리는 경로 해석 버그를 숨김
- 기술적 위험은 각각 대상 완화 가능

### 5.2 경로 해석 분석

| 변수 | 값 | 용도 |
|------|-----|------|
| `$CLAUDE_PLUGIN_ROOT` | `~/projects/claude-memory` | Hook script 해석 |
| `cwd` | `~/projects/claude-memory` | memory_root 파생 |
| `memory_root` | `~/projects/claude-memory/.claude/memory` | 모든 읽기/쓰기 |
| Staging dir | `/tmp/.claude-memory-staging-52f0f4a8baed` | CWD 해시 기반 결정적 |

**순환 의존 없음.** `CLAUDE_PLUGIN_ROOT`와 `cwd`는 동일 경로를 가리키지만 논리적으로 다른 역할 (코드 위치 vs 데이터 위치). 스크립트가 하나를 통해 다른 것을 참조하지 않음.

### 5.3 CRITICAL: Guardian 공존 위험

| # | 위험 | 심각도 | 완화 |
|---|------|--------|------|
| 1 | **Guardian가 /tmp staging 쓰기 차단** — memory-drafter의 Write tool 호출을 Guardian이 거부 | HIGH | `.claude/guardian/config.json`에 `allowedExternalWritePaths` 설정 |
| 2 | **Stop hook 경쟁** — triage와 auto-commit이 동시 실행 | HIGH | Guardian auto-commit 비활성화 |
| 3 | **Git dirty tree** — 메모리 파일이 working tree 오염 | MEDIUM | `.gitignore` 업데이트 |
| 4 | **병렬 PreToolUse 평가** — 두 플러그인이 동일 Write call에 동시 반응 | LOW | 실제 문제 없음 (독립적, 멱등) |

### 5.4 구현 요건 (4개 파일 변경)

1. **`.claude/plugin-dirs`**: claude-memory (self) + claude-code-guardian 경로 추가
2. **`.claude/guardian/config.json`**: staging allowlist + auto-commit 비활성화
3. **`.gitignore`**: `.claude/memory/*.json`, `.claude/guardian/`, `.claude/cfl-data/` 제외
4. **`.claude/memory/memory-config.json`** (선택): debug logging 활성화

### 5.5 Venv Bootstrap: 무관

시스템 Python에 pydantic 2.12.5 설치됨. `memory_write.py`의 `os.execv` 재실행이 트리거되지 않음. Venv 경로 문제는 현재 환경에서 무관.

---

## 6. 5-Phase Architecture (v2)

> 상세: `temp/cfl-v2-phase-redesign.md`

```
Phase 1: Evidence Contract (증거 계약) — Dual-Track 증거 수집 체계
    ↓
Phase 2: Recursive Self-Testing Loop (재귀적 자기 테스트) — 레포 내부 실행
    ↓
Phase 3: Requirement Traceability + Complete Test Coverage (추적 + 완전 커버리지)
    ↓
Phase 4: Automated Gap-to-Action Pipeline (갭 → 액션 플랜 자동화)
    ↓
Phase 5: Manual-First → Ralph Loop (수동 개선 → 자동화)
```

### 6.1 Phase 1: Evidence Contract

**목표**: CLI-visible 현상을 구조적으로 캡처하는 증거 수집 체계 + 수동 TUI 검증 보완 트랙.

**Dual-Track:**
- **Track A (자동)**: `claude -p` + `--output-format stream-json` + stderr 분리 + JSONL 플러그인 로그 + workspace 스냅샷
- **Track B (수동)**: 대화형 세션에서 스크린샷/asciinema로 TUI 캡처. `evidence/manual-checklist.md` 기반.

**산출물:**
- Scenario Registry (`evidence/scenarios/*.json`): id, prompt, setup, checks, requirement_ids
- Run Result Schema (`evidence/runs/run-*/metadata.json`): stdout, stderr, logs, verdict, exit codes
- ANSI-stripped plaintext 분석 (ANSI 파싱 아닌 제거 후 regex)
- Manual checklist (Track B)

**Screen Capture 전략** (cross-model 합의 + R1 반영):
1. **두 번 분리 실행** (R1 ISSUE: script + stream-json은 PTY 간섭으로 동시 사용 불가):
   - Run A: `claude -p --output-format stream-json > output.json 2>stderr.txt` (기계 판독용)
   - Run B: `script -e -q -c "claude -p ..." stdout-raw.txt` (원시 캡처, 디버깅용)
2. ANSI strip 후 plaintext forbidden regex 탐지
3. stream-json이 주 분석 소스, stdout plaintext는 보조

**검증 게이트**: 동일 시나리오 2회 실행 시 verdict 동일 (재현성).

### 6.2 Phase 2: Recursive Self-Testing Loop

**목표**: claude-memory 레포 내부에서 자기 자신 + Guardian을 composite plugin directory로 구성, ops 환경 시뮬레이션, 결과 수집.

**핵심 설계:**
- **Composite Plugin Directory**: `--plugin-dir`로 claude-memory (자기 자신) + Guardian pinned copy 동시 로드
- **Guardian 참조 관리**: `evidence/guardian-ref/`에 pinned copy (수동 업데이트, 안정성 우선)
- **격리 워크스페이스**: `/tmp/cfl-workspace-{run_id}/` + 격리된 `.claude/memory/`
- **`--permission-mode auto`**: 실제 사용과 유사한 동작
- **Meta-validation**: 의도적 실패 시나리오 (SCN-META-001)로 러너 자체의 신뢰성 검증

**초기 시나리오 (6개):**
1. SCN-RET-001: retrieval 기본 검색
2. SCN-CAP-001: Stop 훅 트리거 + 메모리 저장
3. SCN-UX-001: CLI 화면 노이즈 없음
4. SCN-GRD-001: Guardian 존재 시 충돌 없음
5. SCN-SAVE-001: 전체 저장 흐름
6. SCN-META-001: known-bad build must FAIL (meta-validation)

**Guardian 비교 테스트**: Guardian 있는 실행 vs Guardian 없는 기준선 → 차이가 곧 Guardian의 영향.

**`--plugin-dir` 결정 트리** (Week 1 spike):
- 반복 가능 → 직접 `--plugin-dir A --plugin-dir B`
- 반복 불가 → composite symlink directory 사용

**검증 게이트**: 알려진 나쁜 빌드가 FAIL, 좋은 빌드가 PASS.

### 6.3 Phase 3: Requirement Traceability + Complete Test Coverage

**목표**: PRD 모든 요구사항을 테스트에 매핑 + 누락 엣지케이스 추가 + 로그 분석 자동화.

**v1의 Phase 3 (cross-repo) + Phase 4 (traceability)를 통합** (순환 의존 해소).

**구성요소:**

1. **Pytest Requirement Markers**: `@pytest.mark.requirement("REQ-3.1.1")` + `@pytest.mark.edge_case("...")`
2. **Requirements Registry** (`evidence/requirements/requirements.json`): 모든 PRD 요구사항 + 검증 타입 + 테스트 매핑 + 엣지케이스 목록
3. **Residual Risk Register** (`evidence/requirements/residual-risks.json`): 100% 커버리지 불가능 영역을 솔직하게 기록
4. **Edge Case 전략**: 각 영역별 누락 엣지케이스 식별 (동시 트리거, 깨진 인덱스, 디스크 풀, 심볼릭 링크 공격 등)
5. **자동 로그 분석** (`evidence/log_analyzer.py`):
   - JSONL 이벤트 파싱 → 에러/느린 ops/누락 이벤트/중복 탐지
   - ANSI-stripped stderr에서 forbidden regex 탐지
   - **Log-stderr 교차 대조**: stderr에 에러가 있는데 로그에 없으면 discrepancy (로그 누락 의심)
6. **Coverage Dashboard**: Tier 1 (pytest, 즉시) + Tier 2 (live scenario, 캐시) 통합 리포트. Tier 2 없이도 Tier 1 리포트 독립 생성 가능.

**요구사항 분류 체계** (70+ 요구사항, 10개 도메인):

| 도메인 | ID 범위 | 테스트 파일 |
|--------|---------|------------|
| Security | SEC-001~020 | adversarial_*, v2_adversarial_* |
| Retrieval | RET-001~017 | test_memory_retrieve, test_fts5_* |
| Triage | TRI-001~013 | test_memory_triage |
| Write Ops | WRT-001~014 | test_memory_write |
| Index | IDX-001~007 | test_memory_index |
| Candidate | CAN-001~005 | test_memory_candidate |
| Draft | DRA-001~004 | test_memory_draft |
| Enforcement | ENF-001~006 | test_rolling_window |
| Guards | GRD-001~005 | test_*_guard, test_validate |
| Non-Functional | NFR-001~006 | test_regression_popups, test_fts5_benchmark |
| Observability | OBS-001~005 | test_memory_logger, test_log_analyzer |

**검증 게이트**: Deterministic 요구사항 100% 커버 + residual risks 등록.

### 6.4 Phase 4: Automated Gap-to-Action Pipeline

**목표**: Phase 3 커버리지 리포트에서 실패 요구사항 → action plan 자동 변환 + 중복 방지.

**파이프라인:**
```
Coverage report (FAIL 목록)
  → 각 FAIL에 대해:
    → action-plans/에서 requirement ID로 기존 plan 검색
    → 기존 active → 새 증거 추가
    → 기존 done → 회귀(regression) plan 생성
    → 없음 → 새 plan 생성 (템플릿 기반)
```

**중복 방지**: requirement ID 기반 exact match (v1의 미정의 → v2에서 해결).

**Action plan 템플릿**: status, requirement ID, 실패 증거 (테스트, 시나리오, 로그 분석 결과), suggested fix (수동 작성).

### 6.5 Phase 5: Manual-First → Ralph Loop

**목표**: 분석 → action plan → branch → 수정 → 테스트 → PR. **사람이 먼저 수동 실행**, 3회 성공 후 ralph loop 자동화.

**Stage 1: Manual Loop Protocol**
```
Step 1: coverage-report.json에서 FAIL 확인 + 실패 증거 분석
Step 2: Action plan 작성/확인 (Phase 4 자동 생성 또는 수동)
Step 3: git checkout -b fix/{issue}
Step 4: 소스 수정 + 테스트 추가
Step 5: pytest (Tier 1) + runner.py (Tier 2) + log_analyzer.py
Step 6: 통과 시 → git commit → gh pr create → action plan status: done
Step 7: 실패 시 → action plan에 원인 기록 → 재시도/접근 변경
```

**Stage 2: Ralph Loop Automation** (3회 manual 성공 후)
```bash
# evidence/ralph-loop.sh
for i in $(seq 1 $MAX_ITERATIONS); do
  # Git cleanliness check
  # 최우선 FAIL 요구사항 선택
  # Action plan 자동 생성
  # Branch 생성 (clean main에서)
  # Fresh context로 claude -p 수정 시도 (scope-bounded)
  # Quality gates: compile + pytest + scenario + log analysis + coverage check
  # PASS → commit + PR 생성
  # FAIL → discard + progress log 기록
done
```

**Safety Constraints (10개):**
1. Never auto-merge: PR만 생성, merge는 사람이
2. Never modify global plugin: `--plugin-dir .` 만 사용
3. Compile check: `python3 -m py_compile` 필수
4. Test regression: 기존 테스트 깨지면 즉시 discard
5. Cost cap: 1 iteration $5, 전체 $25
6. Single-concern: 한 번에 하나의 요구사항만
7. Scope bounding: 관련 파일로 수정 범위 제한
8. Git cleanliness: dirty working tree에서 실행 거부
9. Targeted verification: 대상 requirement PASS 전환 확인
10. Progress log: 모든 시도를 progress.txt에 기록

**자동화 전환 기준**: Manual 3회 성공 + cost ROI 양호 + 무한 반복 없음 확인.

---

## 7. Cross-Model Analysis (v1 + v2)

### 7.1 v1 합의 (유지)

| # | 합의 | 근거 |
|---|------|------|
| 1 | 방향은 맞지만 과도 설계 위험 | "simplest viable loop first" |
| 2 | `claude -p`가 모든 훅 트리거 | **R1에서 실증 확인** (v2.1.81) |
| 3 | prd.json은 mutable source of truth 아님 | 불변 요구사항 + 파생 상태 분리 |
| 4 | 결정적 오라클 우선 | pass/fail은 deterministic signal |
| 5 | 워크스페이스 격리 필수 | CWD 기반 memory_root 파생 |

### 7.2 v2 추가 합의

| # | 합의 | 출처 |
|---|------|------|
| 6 | TUI scraping은 프로덕션에 부적합 | 3모델 합의 (screen capture 연구) |
| 7 | Hook-internal audit logging이 최선 | 3모델 합의 |
| 8 | Self-contained 주장하려면 Guardian pinned copy 필수 | Codex + Gemini (v2 adversarial) |
| 9 | ANSI 파싱 포기, strip 후 plaintext regex | Gemini 지적, Codex 동의 |
| 10 | Phase 3/4 순환 의존 → 통합 | Codex 지적 |
| 11 | Manual-first는 "superb maturity model" | Gemini 평가 |
| 12 | script(1)은 child exit code 숨김 → -e 플래그 | Codex 지적 |

### 7.3 Key Disagreement + Resolution

| 주제 | Codex 5.3 | Gemini 3.1 Pro | 결론 |
|------|-----------|----------------|------|
| Guardian 관리 | Worktree 격리 | True dogfood + canonical | **True dogfood** (사용자 의도 우선) |
| Staging 위치 | 프로젝트 내부 | /tmp/ 유지 | **/tmp/ 유지** (popup 방지 기존 설계) |
| Coverage report | 통합만 | Tier 1/2 독립 | **독립 + 캐시 결합** |

---

## 8. Test Infrastructure Reuse

### 8.1 기존 자산 (1158 tests, 21 files)

| 테스트 파일 | PRD 섹션 | 커버리지 |
|------------|----------|---------|
| test_memory_triage.py | 3.1.1 | Triage scoring, thresholds, patterns |
| test_memory_retrieve.py | 3.2.1 | Retrieval flow, scoring, confidence |
| test_memory_write.py | 3.3 | CRUD, merge protections, OCC |
| test_memory_candidate.py | 3.8 | Candidate selection, CUD |
| test_memory_draft.py | 3.7 | Draft assembly, path security |
| test_memory_index.py | 3.6 | Index rebuild, validate, GC |
| test_memory_write_guard.py | 3.4.1 | Write guard |
| test_memory_staging_guard.py | 3.4.2 | Staging guard |
| test_memory_validate_hook.py | 3.4.3 | Validation, quarantine |
| test_memory_judge.py | 3.2 | LLM judge, batch, anti-bias |
| test_memory_logger.py | 3.10 | Structured logging |
| test_fts5_search_engine.py | 3.2.2 | FTS5, tokenization |
| test_fts5_benchmark.py | 4.2 | Search performance |
| test_rolling_window.py | 3.5 | Rolling window |
| test_regression_popups.py | 4.1 | Popup prevention |
| test_adversarial_*.py | 4.3 | Injection attacks |
| test_log_analyzer.py | 3.10 | Log analysis |

### 8.2 재사용 전략

1. **Markers 추가**: 기존 테스트에 `@pytest.mark.requirement()` 데코레이터. 코드 변경 없이 마커만 추가.
2. **conftest.py 확장**: requirement + edge_case 마커 등록, JSON report 플러그인.
3. **기존 fixtures 활용**: `memory_root`, `memory_project`, `write_memory_file`, `write_index`, `bulk_memories`.
4. **새 fixture**: live session workspace 셋업 (composite plugin dir + 격리된 CWD).

---

## 9. `claude --print` Hook Behavior (실증 확인)

**검증 결과 (R1 실증, Claude Code v2.1.81):**

| Hook Type | `--print` 모드 작동? | 검증 방법 |
|-----------|---------------------|-----------|
| UserPromptSubmit | YES | 매 프롬프트마다 로그 파일 생성 |
| Stop | YES | 세션 종료 시 로그 파일 생성 |
| PreToolUse | YES | Write tool call 전 실행 |
| PostToolUse | YES | Write tool call 후 실행 |

**결론**: pexpect/PTY 하네스 불필요. `claude -p` + `--plugin-dir` + `--permission-mode auto`로 충분.
**주의**: `--bare` 플래그는 훅 스킵. 절대 사용 금지.

---

## 10. Implementation Path

### Week 1: Phase 1 + Phase 2 Spike

1. Evidence schema 정의 + 3개 시나리오 작성
2. **SPIKE**: `--plugin-dir` 반복 가능 여부 확인
3. **SPIKE**: Guardian + Memory 동시 로드 확인
4. Guardian pinned copy 준비 (`evidence/guardian-ref/`)
5. `.claude/guardian/config.json` 생성 (staging allowlist + auto-commit off)
6. `.gitignore` 업데이트
7. Minimal runner (1개 시나리오)
8. Manual checklist 초안

### Week 2: Phase 2 완성 + Phase 3 시작

1. Runner 6개 시나리오 지원 (meta-validation 포함)
2. ANSI-stripped 캡처 구현 (`script -e`)
3. Log analyzer 기본 (plaintext regex, ANSI 파싱 없음)
4. Requirement markers 추가 시작
5. requirements.json 초안

### Week 3: Phase 3 완성 + Phase 4

1. 모든 기존 테스트에 requirement markers 추가
2. 엣지케이스 테스트 추가
3. Coverage report 생성 (Tier 1 즉시 + Tier 2 캐시)
4. Residual risk register 작성
5. Gap-to-action pipeline 구현

### Week 4: Phase 5 Manual Loop

1. Manual loop 1회차 실행
2. Progress log 시작
3. 프로세스 검증

### Week 5+: Phase 5 반복 + 자동화 판단

1. Manual loop 2-3회차
2. 패턴 추출 → ralph loop 구현
3. 자동화 전환 판단

**타임라인 주의** (R1 반영): 5주는 낙관적 추정. R1은 8-10주를 현실적으로 평가.
권장: Milestone 1 (Phase 1-3, Week 1-4) → Milestone 2 (Phase 4-5, Week 5-8).
Phase 4-5 착수 여부는 Phase 1-3 결과를 본 후 결정.

---

## 11. Risk Matrix (v2)

| # | 리스크 | 심각도 | 완화 |
|---|--------|--------|------|
| 1 | **TUI 팝업 자동 검증 불가** | CRITICAL | Track B 수동 검증 + popup regression tests. 한계 솔직히 인정. |
| 2 | **Guardian /tmp staging 차단** | HIGH | `allowedExternalWritePaths` 설정. 해시 `52f0f4a8baed` 결정적. |
| 3 | **Stop hook 경쟁 (triage vs auto-commit)** | HIGH | Guardian auto-commit 비활성화. |
| 4 | **Auto-fix가 global plugin 수정** | CRITICAL | `--plugin-dir .` 만 사용. PR만 생성, auto-merge 금지. |
| 5 | **자가 오염 (테스트 프롬프트 → triage 트리거)** | HIGH | Per-run 격리 + 비대상 훅 config 비활성화. |
| 6 | **Self-contained 주장 vs Guardian 전역 의존** | HIGH | Composite plugin dir + Guardian pinned copy. |
| 7 | **ANSI scraping 불안정** | HIGH | Strip 후 plaintext regex만. stream-json이 주 소스. |
| 8 | **Phase 3/4 순환 의존** | HIGH | 통합. Markers를 먼저 도입. |
| 9 | **script(1) child exit code 숨김** | MEDIUM | `script -e` 사용. |
| 10 | **Git dirty tree (메모리 파일)** | MEDIUM | `.gitignore` 업데이트. |
| 11 | **루프 공회전** | MEDIUM | MAX_ITERATIONS + scope bounding + manual 3회 후 자동화. |
| 12 | **커버리지 100% 허위 주장** | MEDIUM | Residual risk register 유지. |
| 13 | **E2E 비용** | LOW | 시나리오 수 제한, on-demand. |
| 14 | **Ralph loop sandbox escape** (R1 NEW) | CRITICAL | `--permission-mode auto`가 LLM에 제한 없는 Bash 접근. 컨테이너화 필수 (Phase 5 사전조건). |
| 15 | **Goodhart's law: test mutilation** (R1 NEW) | HIGH | Ralph loop가 테스트와 소스 모두 수정 가능 → 테스트 약화. Read-only test pinning 필수. |
| 16 | **"Closed loop" 이름의 거짓** (R2 NEW) | HIGH | 자동화 Track A는 CLI output만 커버. 실제 문제 (TUI 팝업)는 Track B 수동. "Closed loop"는 마케팅적 과장. |
| 17 | **자가참조 역설** (R2 NEW) | HIGH | ALL PASS 시 "버그 없음" vs "시나리오 부족" 구별 불가. 외부 오라클 없음. |
| 18 | **Guardian 시뮬레이션 충실도** (R2 NEW) | MEDIUM | Pinned copy ≠ real Guardian. 행위적 발산 감지 메커니즘 필요. |
| 19 | **비용 모델 과소추정** (R2 NEW) | MEDIUM | $16/loop → 현실적 $32-102/loop (재현성 2배, retry, Sonnet 가격). 월간 $704-2244. |
| 20 | **"Manual first = forever manual"** (R2 NEW) | MEDIUM | Owner/deadline/kill criteria/forcing function 부재. 자동화 전환 기준 구체화 필요. |

---

## 12. Cost Estimation

| 항목 | 단가 | 수량 | 소계 |
|------|------|------|------|
| Tier 1 pytest 전체 | $0 | 1097 tests | $0 |
| Tier 2 retrieval 시나리오 | ~$0.10 | 5개 | $0.50 |
| Tier 2 triage 시나리오 | ~$0.25 | 3개 | $0.75 |
| Tier 2 save flow 시나리오 | ~$1.50 | 3개 | $4.50 |
| Tier 2 guard 시나리오 | ~$0.10 | 3개 | $0.30 |
| **한 번 전체 실행** | | **~14 시나리오** | **~$6** |
| Manual loop 1회 (fix 시도) | ~$2.00 | 1 | $2.00 |
| Ralph loop 전체 (5 iterations) | | 5 | $10.00 |
| **전체 루프 1회** | | | **~$16** |

**ROI** (R2 비용 모델 수정 반영):
- 문서 원래 추정: $16/loop
- R1 수정: $16-87/loop (모델/retry에 따라)
- R2 현실적 추정: $32-102/loop (재현성 2배, retry 20%, Sonnet 가격 반영)
- 월간 (일일 실행): $704-2,244 → **on-demand 또는 주간 배치 필수**
- **핵심 질문**: 이 비용이 수동 dogfooding 시간 대비 가치 있는가? → Phase 1-2 결과를 본 후 판단

---

## 13. File Structure (v2)

```
evidence/                           # CFL 루트
  bootstrap.py                      # 환경 구성
  runner.py                         # Phase 2: 메인 러너
  log_analyzer.py                   # Phase 3: 자동 로그 분석
  coverage_report.py                # Phase 3: 커버리지 리포트
  pick_failing.py                   # Phase 5: 실패 요구사항 선택
  generate_action_plan.py           # Phase 4: action plan 자동 생성
  get_related_files.py              # Phase 5: requirement → 관련 파일
  ralph-loop.sh                     # Phase 5 Stage 2: 자동화 루프
  progress.txt                      # 학습 로그 (append-only)
  manual-checklist.md               # Track B: 수동 TUI 검증

  guardian-ref/                     # Guardian pinned copy
    VERSION
    .claude-plugin/plugin.json
    hooks/hooks.json
    hooks/scripts/...

  scenarios/                        # Phase 1: 시나리오 정의
    SCN-RET-001.json
    SCN-CAP-001.json
    SCN-UX-001.json
    SCN-GRD-001.json
    SCN-SAVE-001.json
    SCN-META-001.json

  fixtures/                         # 테스트용 메모리 파일

  requirements/                     # Phase 3: 요구사항 추적
    requirements.json
    coverage-report.json
    gap-analysis.json
    residual-risks.json

  runs/                             # Phase 2: 실행 결과
    run-{timestamp}-{scenario}/
      stdout.txt, stderr.txt        # ANSI-stripped
      stdout-raw.txt                # raw (script -e)
      output.json                   # stream-json
      logs/memory-events.jsonl
      workspace/.claude/memory/
      metadata.json

  manual/                           # Track B: 수동 캡처
    {date}/
      screenshots/
      asciinema/
      observations.md

  schemas/                          # JSON 스키마
    evidence.schema.json
    scenario.schema.json
```

---

## 14. Verification Findings (v1 유지 + v2 추가)

### 14.1 v1 Resolved Issues (유지)
- `claude -p` 훅 동작: 모든 4종 트리거됨 (R1 실증)
- Workspace 격리: CWD 기반 tmpdir 격리 가능
- venv 경로: 현재 환경에서 무관 (시스템 pydantic)

### 14.2 v2 Known Limitations
- TUI 팝업 자동 검증 불가 → Track B 수동 보완
- Hook stdout JSON 캡처 불가 (Claude Code 내부 소비) → audit logging으로 완화
- 사용자 allow/deny 응답 캡처 불가 → 근본적 한계
- Guardian 자체 버그 수정 불가 → 탐지 + 이 레포 측 완화만

### 14.3 Open Questions (action-plan에서 해결)
1. ~~`--plugin-dir` 반복 가능 여부~~ → **R1에서 해결: IS repeatable** (composite symlink 불필요)
2. Guardian + Memory composite 로드 시 실제 동작 (Week 1 spike — `--plugin-dir` 반복 가능하므로 난이도 하락)
3. `--debug "hooks" --debug-file`의 실제 캡처 범위 (검증 필요)
4. PermissionRequest/Notification hook event type의 plugin hooks.json 사용 가능 여부

---

## 15. Verification Summary (R1 + R2)

### 15.1 R1 Results

**R1-Feasibility** (`temp/cfl-v2-verify-r1-feasibility.md`): 0 BLOCKER, 3 ISSUE, 5 MINOR, 13 OK
- [ISSUE] script + stream-json PTY 간섭 → 분리 실행 (Section 6.1에 반영)
- [ISSUE] Guardian pinned copy provenance → UPSTREAM_SHA 추가 필요
- [ISSUE] 5주 타임라인 과도 낙관 → 현실적 8-10주 (Week 1-4: Phase 1-3, Week 5-8: Phase 4-5)
- [확인] `--plugin-dir` IS repeatable (spike 불필요)
- [확인] Staging hash 52f0f4a8baed 정확
- [확인] 테스트 수 1158개 (문서 수정 완료)

**R1-Risks** (`temp/cfl-v2-verify-r1-risks.md`): 2 SHOW-STOPPER, 5 추가 리스크
- [SHOW-STOPPER] Ralph loop sandbox escape — `--permission-mode auto` + Bash = 무제한 호스트 접근. 컨테이너화 필수.
- [SHOW-STOPPER] Goodhart's law — ralph loop가 테스트 약화 가능. Read-only test pinning 필수.
- [추가] os.execv crash cascade, 자가참조 오염 (ralph 특화), Guardian staleness deadlock, 비용 $16-87, transcript corruption

### 15.2 R2 Results

**R2-Holistic** (`temp/cfl-v2-verify-r2-holistic.md`): 2 ACTION NEEDED, 4 MINOR, 1 OK
- [ACTION NEEDED] Phase 5에 sandbox + test immutability 반영 필요 (Risk 14, 15에 추가 완료)
- [ACTION NEEDED] R1 show-stopper를 risk matrix에 반영 필요 (완료)
- [MINOR] 내부 일관성 OK, script/stream-json 간섭만 수정 필요 (완료)
- Phase 1-4는 action plan 생성 가능 상태. Phase 5만 아키텍처 업데이트 필요.

**R2-Adversarial** (`temp/cfl-v2-verify-r2-adversarial.md`): 2 CRITICAL, 4 HIGH, 3 MEDIUM
- [CRITICAL] **"Closed loop" 이름의 거짓**: 자동화 Track A는 CLI output만 커버. 동기 부여 문제 (TUI 팝업)는 수동 Track B. 루프가 닫힌 것은 이미 테스트 가능했던 부분뿐.
- [CRITICAL] **자가참조 역설**: ALL PASS 시 "버그 없음" vs "시나리오 부족" 구별 불가. 외부 오라클/incident corpus 없음.
- [HIGH] Guardian 시뮬레이션 = theater (frozen copy ≠ real behavior)
- [HIGH] 비용 $32-102/loop (문서의 $16 대비 2-6배)
- [HIGH] "Manual first" = "forever manual" (owner/deadline/kill criteria 부재)
- [HIGH] Evidence framework 복잡도 > plugin 복잡도 (12+ scripts vs 13 scripts)
- [MEDIUM] 6 시나리오로 70+ 요구사항 커버 불가능
- [MEDIUM] Honest Limitations = rhetorical indemnity (문제를 인정하되 해결하지 않음)
- [MEDIUM] CFL이 버그를 못 찾을 때의 pivot plan 없음

### 15.3 Cross-Model Consensus (Vibe Check)

**Gemini 3 Pro + Opus 4.6 합의**: 솔로 개발자에게 1158개 테스트가 있는 상황에서 5-Phase 자동화 프레임워크의 ROI는 부정적. **구조화된 수동 dogfooding**이 더 가치 있을 수 있다.

**권장 경로 (검증 반영):**
1. Phase 1-2는 가치 있음 — 실제로 돌려보고 데이터를 쌓는 것은 필수
2. Phase 3의 requirement markers는 가치 있음 — 기존 인프라 활용
3. Phase 4의 gap-to-action은 간소화 가능 — 수동으로도 충분
4. Phase 5의 ralph loop는 **Phase 1-3 결과를 본 후 결정** — 현 시점에서 구축은 premature
5. 전체 evidence/ 인프라는 **최소 기능만 먼저 구축** (runner.py + 3개 시나리오 + 수동 관찰), 복잡도는 필요에 따라 점진 추가

---

## 16. References

### External
- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — keep/discard 패턴
- [snarktank/ralph](https://github.com/snarktank/ralph) — prd.json + fresh context

### Internal
- PRD: `docs/requirements/prd.md`
- Architecture: `docs/architecture/architecture.md`
- Observability Plan: `action-plans/observability-and-logging.md`

### Working Files (temp/)
**v2 연구:**
- `temp/cfl-v2-screen-capture.md` — Screen capture 연구 (10 메커니즘, 3-tier 추천)
- `temp/cfl-v2-recursive-arch.md` — 재귀적 자기설치 아키텍처 (Guardian 공존 위험)
- `temp/cfl-v2-phase-redesign.md` — Phase 전체 재설계 (1202 lines, cross-model 반영)

**v2 검증:**
- `temp/cfl-v2-verify-r1-feasibility.md` — v2 R1: 실행 가능성 (0 BLOCKER, 3 ISSUE)
- `temp/cfl-v2-verify-r1-risks.md` — v2 R1: 리스크 (2 SHOW-STOPPER, 5 추가)
- `temp/cfl-v2-verify-r2-holistic.md` — v2 R2: 전체 품질 (2 ACTION NEEDED)
- `temp/cfl-v2-verify-r2-adversarial.md` — v2 R2: 반론 (2 CRITICAL, 4 HIGH)

**v1 검증 (역사적):**
- `temp/cfl-cross-model-synthesis.md` — v1 교차 분석 합성
- `temp/cfl-verify-r1-feasibility.md` — v1 R1: 실행 가능성
- `temp/cfl-verify-r1-risks.md` — v1 R1: 리스크
- `temp/cfl-verify-r2-holistic.md` — v1 R2: 전체 품질
- `temp/cfl-verify-r2-adversarial.md` — v1 R2: 반론
