---
status: done
progress: "Phase 0-4 완료. R1+R2 최종 검증 후 결정 수정: Finding #1 실제 (pytest 흡수), Finding #2 configuration observation (novel bug 아님). Track C 전체 휴면 — 인프라 보존, 정기 실행 취소."
---

# Track C: Automated Interactive Testing — Action Plan

플러그인의 **통합 행동**(integration behavior)을 검증하여 closed feedback loop을 강화한다. pytest로 불가능한 5가지 시나리오를 식별하고, 가장 효과적인 도구로 각각 검증한다.

## 핵심 원칙

**비용/시간은 제약이 아니다. 기능하는지, closed feedback을 효과적으로 만드는지만 중요하다.**

## 5개 시나리오 (기존 1232 pytest가 놓치는 것)

3-model 교차 검증 (Opus + Codex + Gemini)으로 식별한, 기존 테스트가 커버하지 못하는 통합 행동:

| ID | 시나리오 | 왜 pytest 불가? | 최적 도구 |
|----|----------|----------------|-----------|
| S1 | **Agentic Rejection Loop**: Write guard가 block한 후 LLM이 retry loop에 빠지는가? | pytest는 hook 반환값만 테스트, LLM의 행동 반응은 불가 | `claude -p --output-format stream-json` |
| S2 | **Cross-Plugin Popup**: memory + Guardian 동시 로딩 시 예기치 않은 dialog 발생? | pytest는 단일 플러그인 hook만 실행, 복수 플러그인 상호작용 불가 | Docker 샌드박스 + tmux (TUI 관찰 필요) |
| S3 | **Lifecycle Interruption**: triage 도중 SIGINT 시 triage-data.json 손상? | 기존 테스트는 항상 완료까지 실행 | pytest subprocess + `signal.SIGINT` |
| S4 | **Stderr/UI Corruption**: hook stderr가 TUI로 누출되는가? | subprocess 테스트는 stderr를 별도 캡처 | pytest subprocess stderr 감사 |
| S5 | **Hook Contract Drift**: Claude Code 업데이트로 hook payload 형식 변경? | pytest fixture는 수동 유지 스냅샷, 실제 payload drift 감지 불가 | `claude -p --output-format stream-json` |

**Codex 5.3 실증 확인**: `claude -p --output-format stream-json`에서 PreToolUse 거부 시 `tool_result(is_error: true)` + 재시도 쌍이 개별 `tool_use_id`로 출력됨. S1 retry 횟수 프로그래밍 카운팅 가능.

## Kill Criteria (효과성 기반)

| Trigger | Threshold | Action |
|---------|-----------|--------|
| 5개 시나리오 모두 novel signal 0 | 전체 구현 후 새 발견 0건 | Track C 퇴역, 레시피 보존 |
| 발견이 항상 pytest로 재현 가능 | 모든 발견을 subprocess 테스트로 전환 가능 | pytest 테스트 추가 후 Track C 퇴역 |
| Harness 불안정이 signal을 가림 | 실행 50% 이상이 harness 문제로 실패 | 기술 실패 — harness 신뢰성 부족 |
| Docker 환경에서 Claude 실행 불가 | Phase 2 gate 3회 실패 | Docker 포기, S2를 수동 테스트로 전환 |

**Continue 기준**: novel bug 발견 (기존 pytest 미탐지 + 사용자 영향), 또는 contract drift 조기 감지, 또는 cross-plugin 상호작용 버그 발견.

## Phase 0: Track A+ (pytest + stream-json — Docker 불필요, 즉시 시작)

**Goal**: S1, S3, S4, S5를 가장 저렴하고 결정적인 방법으로 검증. Docker 없이 즉시 실행 가능.

### S3: Lifecycle Interruption (pytest)
- [x] **0.1**: `tests/test_triage_interruption.py` 생성
- [x] **0.2**: `memory_triage.py`를 subprocess로 실행, `time.sleep(0.5)` 후 `proc.send_signal(signal.SIGINT)` 전송
- [x] **0.3**: Assert: `triage-data.json`이 부재이거나 유효한 JSON
- [x] **0.4**: Assert: staging directory에 corrupt 파일 없음 (`.tmp` + `context-*.txt` 포함)
- [x] **0.5**: 다양한 타이밍 (0.05s, 0.1s, 0.5s, 1.0s, 2.0s)으로 반복

### S4: Stderr Audit (pytest)
- [x] **0.6**: `tests/test_hook_stderr.py` 생성
- [x] **0.7**: 모든 hook 스크립트를 현실적 입력으로 subprocess 실행
- [x] **0.8**: Assert: stderr가 비어있거나 예상된 로그만 포함 (Python traceback, raw JSON, Warning, pydantic validation 등 없음)
- [x] **0.9**: 대상: `memory_triage.py`, `memory_retrieve.py`, `memory_write_guard.py`, `memory_staging_guard.py`, `memory_validate_hook.py` (valid + invalid 입력)

### S5: Hook Contract Drift (stream-json)
- [x] **0.10**: `tests/test_contract_drift.py` 생성
- [x] **0.11**: `claude -p "hello" --plugin-dir . --output-format stream-json` 실행
- [x] **0.12**: stream-json 출력 파싱: hook fire 이벤트 확인 (UserPromptSubmit, Stop 등)
- [x] **0.13**: Assert: hook이 기대하는 payload 필드 존재 확인
- [x] **0.14**: Claude Code 버전 기록 → 향후 버전 비교용 baseline

### S1: Agentic Rejection Loop (stream-json)
- [x] **0.15**: `tests/test_rejection_loop.py` 생성
- [x] **0.16**: `claude -p "write a file directly to .claude/memory/test.json" --plugin-dir . --output-format stream-json` 실행
- [x] **0.17**: stream-json 출력에서 `tool_use` + `tool_result(is_error: true)` 쌍 카운팅 (denial keyword 확장: blocked, denied, rejected)
- [x] **0.18**: Assert: retry 횟수 < 3 (LLM이 guard 거부를 수용) + 0-attempt 대안 경로
- [x] **0.19**: retry > 3이면 novel bug 발견 — 보고 + 대응

### OAuth 인증 지원 (추가)
- [x] **0.22**: `claude auth status --json` 기반 인증 감지 (`tests/conftest.py`에 `claude_authenticated()` 공유 헬퍼)
- [x] **0.23**: `test_contract_drift.py`, `test_rejection_loop.py` skip 조건 업데이트 (API key OR OAuth)
- [x] **0.24**: S5 contract drift **실제 감지**: v2.1.81에서 `--output-format stream-json`은 `--verbose` 필수 → 테스트에 `--verbose` 추가
- [x] **0.25**: 전체 재실행: 37/37 PASS, 0 SKIP (S1 3/3, S3 8/8, S4 20/20, S5 6/6)

### 전체 검증
- [x] **0.20**: `pytest tests/test_triage_interruption.py tests/test_hook_stderr.py tests/test_contract_drift.py tests/test_rejection_loop.py -v` → 37 PASS, 0 SKIP
- [x] **0.21**: 결과 기록: S1 3/3 PASS, S3 8/8 PASS, S4 20/20 PASS, S5 6/6 PASS

### Novel Findings
1. **S5 Contract Drift 감지** (Phase 0): Claude Code v2.1.81에서 `--output-format stream-json`을 `-p`와 함께 사용 시 `--verbose` 플래그 필수. 이전 버전에서는 불필요했음. S5가 설계 목적대로 contract drift를 감지한 첫 실제 사례.
2. **S2 Guardian Path Blocking Observation** (Phase 3): Guardian의 PreToolUse:Read/Write hook이 project 외부 경로를 차단하여 memory plugin의 정상 운영을 방해. **R2 검증 후 하향 조정**: 이것은 Guardian의 설계된 동작이며, CFL 연구(`research/closed-feedback-loop.md`)에 이미 known risk로 문서화됨. Docker 테스트 환경이 ops Guardian config(allowedExternalReadPaths)를 사용하지 않아 발생한 configuration artifact. Blocking event 자체는 stream-json으로도 감지 가능 (TUI-only 분류는 과장). Claude의 적응 행동 관찰만 TUI-only.

**GATE**: Phase 0 결과 평가. **PASSED**
- Novel finding 1건 (S5 contract drift) → Track C 가치 입증됨
- S1 rejection loop: PASS (retry ≤ 3 또는 conservative refusal) → 현재 LLM 행동 정상
- Phase 1 진행 결정: Docker 구축으로 S2 검증 가치 있음

## Phase 1: Docker Desktop WSL2 Integration 활성화

**Goal**: Docker 샌드박스 환경 구축의 전제조건.

- [x] **1.1**: Docker Desktop 열기 (Windows)
- [x] **1.2**: Settings → Resources → WSL Integration → Ubuntu 활성화
- [x] **1.3**: Docker Desktop 재시작
- [x] **1.4**: WSL2에서 확인: `docker run --rm hello-world` ✓
- [x] **1.5**: Docker Compose 확인: `docker compose version` → v5.1.0 ✓
- [ ] **1.6**: WSL2 메모리 설정 (선택): `~/.wslconfig`에 `[wsl2]\nmemory=8GB\nautoMemoryReclaim=dropcache` (vmmem 비대화 방지)

**GATE**: `docker run hello-world` 성공? 실패 시: Docker Desktop 로그 확인, WSL 재설치 시도. 3회 실패 → S2를 수동 테스트로 전환하고 Docker 포기.

## Phase 2: Docker 테스트 이미지 빌드

**Goal**: 두 플러그인이 설치된 샌드박스 환경.

- [x] **2.1**: `evidence/track-c/Dockerfile` 생성 ✓
- [x] **2.2**: Claude Code 버전: 2.1.81 (최신)
- [x] **2.3**: 이미지 빌드: `docker build --build-arg CLAUDE_CODE_VERSION=2.1.81 -t claude-memory-test evidence/track-c/` ✓
- [x] **2.4**: 기본 검증: 컨테이너 내 `claude --version` → 2.1.81 ✓
- [x] **2.5**: 인증: 호스트 `~/.claude` read-only 마운트로 OAuth 인증 전달 (`claude auth status --json` → `loggedIn: true, subscriptionType: max`) ✓
- [x] **2.5a**: 인증 검증 ✓
- [x] **2.5b**: stream-json 검증: `claude -p "hello" --output-format stream-json --verbose` → 정상 출력 ✓
- [x] **2.6**: 플러그인 마운트 검증: 두 플러그인 동시 로딩 성공 (`plugins: [claude-memory, claude-code-guardian]`). **주의**: Guardian SessionStart hook이 `:ro` 마운트로 인해 `/root/.claude/session-env/` 생성 실패 — Phase 3에서 writable 영역 필요
- [x] **2.7**: Guardian 경로: `/home/idnotbe/projects/claude-code-guardian` ✓

**GATE**: 컨테이너에서 Claude Code + 두 플러그인 실행 가능? 인증 성공? 실패 시: Phase 1 Docker 설정 재검토.

## Phase 3: S2 — Cross-Plugin Popup Ordering (Docker + tmux)

**Goal**: memory + Guardian 동시 로딩 시 예기치 않은 dialog/popup 검증. **TUI 관찰이 필요한 유일한 시나리오.**

- [x] **3.1**: 자동화 테스트 스크립트: `evidence/track-c/run-s2-test.sh` (Docker + tmux + pipe-pane 로깅)
- [x] **3.2**: 온보딩 다이얼로그 자동 통과: .claude.json 복원 + trust dialog Enter + theme skip
- [x] **3.3**: 두 가지 트리거 프롬프트 전송: (1) decision-like content → memory triage (2) direct write → guard interaction
- [x] **3.4**: `tmux capture-pane` + `tmux pipe-pane` 로그 수집 ✓
- [x] **3.5**: Evidence 분석: strict popup pattern matching (false positive 제거: "permission-mode" 등 명령줄 텍스트 제외)
- [x] **3.6**: 결과 기록: `evidence/track-c/runs/s2-run-20260322-143329/` (6 captures + raw log)
- [x] **3.7**: 자동 정리: /exit → tmux kill-session
- [x] **3.8**: 1회 실행 (결과가 deterministic — Guardian path blocking은 LLM 비결정성과 무관)

**S2 결과 요약:**
- **Unexpected popup: NONE** — 표준 Write 권한 다이얼로그(default permission mode)만 출현
- **NOVEL FINDING #2: Guardian path-blocking이 memory plugin 차단**
  - `PreToolUse:Read` hook: Guardian이 project 외부 경로 읽기 차단 → memory retrieval 실패
  - `PreToolUse:Write` hook: Guardian이 `/tmp/` 쓰기 차단 → memory write temp file 실패
  - Claude가 적응하여 project 내부 `.claude/memory/`에 쓰기 시도 → 표준 권한 다이얼로그 출현
- **결론**: cross-plugin "popup"은 없지만, cross-plugin "compatibility issue"가 존재. Guardian의 path 제한이 memory plugin의 정상 운영을 방해.

**GATE**: PASSED — S2 목적 달성. Unexpected popup 없음 확인 + novel cross-plugin compatibility finding.

## Phase 4: Evaluation & Decision

**Goal**: 전체 결과 평가 + 유지/퇴역 결정.

- [x] **4.1**: Phase 0 (Track A+) 결과:
  - S1 Rejection Loop: 3/3 PASS — retry ≤ 3 또는 conservative refusal. Novel bug 없음.
  - S3 SIGINT Resilience: 8/8 PASS — triage-data.json 무손상. Novel bug 없음.
  - S4 Stderr Audit: 20/20 PASS — 금지 패턴 미검출. Novel bug 없음.
  - S5 Contract Drift: 6/6 PASS — **Novel Finding #1**: `--verbose` 필수 (v2.1.81 contract drift)
- [x] **4.2**: Phase 3 (Docker S2) 결과:
  - Cross-plugin popup: NONE (표준 Write 권한 다이얼로그만 출현)
  - **Novel Finding #2**: Guardian path-blocking → memory plugin 작업 차단 (TUI 관찰 전용)
- [x] **4.3**: Novel findings (기존 pytest 미탐지):
  1. S5: Claude Code v2.1.81 contract drift (--verbose 필수) — pytest에서 재현 가능 (이미 S5 test에 반영됨)
  2. S2: Guardian↔Memory cross-plugin path blocking — pytest 단독 재현 불가 (TUI 관찰 + 두 플러그인 동시 로딩 필요)
- [x] **4.4**: 효과성 판단:
  - Novel finding 2건 → **Track C 유지**
  - Finding #1 (S5): pytest로 전환 완료 (test_contract_drift.py에 --verbose 반영)
  - Finding #2 (S2): pytest 전환 불가 — Docker+tmux S2 유지
  - S1/S3/S4: novel bug 0건 → pytest 수준에서 충분, Track C 시나리오로서는 퇴역 가능
- [x] **4.5**: `research/track-c-automated-interactive-testing.md` 업데이트: Section 10 실제 결과 추가, R2 판정 재평가 ✓
- [x] **4.6**: Docker 이미지 유지 결정: S2용 `claude-memory-test` 이미지 + `evidence/track-c/` 보존 ✓

**GATE**: 최종 결정 (R1+R2 검증 후 수정):
- **Track C 휴면 (dormant)** — 인프라 보존, 정기 실행 취소
- Finding #1 (S5 contract drift): 실제 발견, pytest에 흡수 완료. Track C S5 시나리오 퇴역.
- Finding #2 (S2 Guardian blocking): **Configuration observation** (R2 반론 수용). Guardian의 설계된 동작 + 테스트 환경 불일치. CFL 연구에 이미 문서화됨. Novel bug 아님.
- S1/S3/S4: pytest 충분. 퇴역.
- S2/S5: 퇴역. Docker 인프라 + 레시피 보존.
- **재활성 트리거**: (1) 사용자 TUI-only 버그 보고, (2) Guardian/memory 대규모 변경, (3) Claude Code TUI 구조 변경
- 참고: `temp/track-c-synthesis-final.md` (R1 vs R2 종합), `temp/track-c-verify-final-r1.md`, `temp/track-c-verify-final-r2.md`

## Files Changed

| File | Changes |
|------|---------|
| tests/conftest.py | `claude_authenticated()` 공유 헬퍼 추가 (OAuth + API key 감지) |
| tests/test_triage_interruption.py | S3: SIGINT resilience test |
| tests/test_hook_stderr.py | S4: stderr audit for all hooks |
| tests/test_contract_drift.py | S5: hook contract drift via stream-json (OAuth skip + --verbose) |
| tests/test_rejection_loop.py | S1: agentic rejection loop via stream-json (OAuth skip + --verbose) |
| evidence/track-c/Dockerfile | Docker test image (both plugins) |
| evidence/track-c/run-s2-test.sh | S2 자동화 테스트 스크립트 (Docker + tmux) |
| evidence/track-c/docker-memory-config.json | Docker 컨테이너용 memory config (ops 동일) |
| evidence/track-c/runs/ | Evidence storage (gitignored) |
| .gitignore | evidence/track-c/runs/ 추가 |
| research/track-c-automated-interactive-testing.md | 결과 반영 업데이트 |

## Decision Log

| Decision | Rationale |
|----------|-----------|
| 기존 3개 시나리오 → 5개 교체 | 기존 시나리오(self-test, retrieval, no-popup)는 pytest 중복. 새 S1-S5는 genuinely untested integration surface (3-model 합의). |
| S1/S3/S4/S5는 Docker 없이 | Codex 실증: `--output-format stream-json`이 rejection loop 감지 가능. S3/S4는 subprocess 테스트. Docker 오버헤드 불필요 (R2 + Gemini 합의). |
| S2만 Docker + tmux | Cross-plugin popup은 TUI에서만 관찰 가능. stream-json은 dialog 렌더링 미포함 (R1 확인). |
| Docker sandbox (not bare tmux) | Self-referential paradox 해결 (fresh project), 인증 격리 (container), atomic cleanup (`docker rm -f`), 재현성 (Dockerfile). |
| OAuth 인증 지원 (API key + OAuth) | Max plan OAuth 인증으로 S1/S5 실행 가능. `claude auth status --json`으로 인증 감지 (토큰 미노출, 만료 자동 검증). Docker 내에서도 `claude auth login`으로 OAuth 사용 가능. CI는 ANTHROPIC_API_KEY 사용. (이전 가정 "OAuth 불가" 수정됨) |
| stream-json에 --verbose 필수 (v2.1.81) | S5가 감지한 contract drift. `claude -p --output-format stream-json`은 이제 `--verbose` 플래그 필요. |
| Phase 0 먼저 (Docker 전) | 4/5 시나리오가 Docker 불필요. 즉시 가치 확보 후 Docker 투자 결정. |
| Kill criteria: 효과성만 | User: "비용/시간은 상관 없다. 기능하는지가 중요하다." 비용/시간 임계치 제거. |
| 분기별 재평가 | Track C 유지 시, 3분기 연속 novel bug 0건이면 퇴역. |
| S1/S3/S4 Track C 퇴역 | Novel finding 0건. pytest 수준에서 충분히 커버됨. Track C 시나리오로서는 퇴역하되 pytest 테스트는 유지. |
| S2/S5 Track C 유지 | S5: contract drift 모니터링 (Claude Code 업데이트 시). S2: TUI 전용 cross-plugin 호환성 테스트 (분기별). |
| Docker 이미지 유지 | S2 Docker 테스트를 위해 `claude-memory-test` 이미지 유지. `evidence/track-c/Dockerfile` + `run-s2-test.sh` 보존. |
| Guardian path 호환성 | Novel Finding #2로 확인: Guardian의 path-outside-project 차단이 memory plugin 방해. 향후 Guardian `allowedExternalReadPaths`/`allowedExternalWritePaths`에 memory plugin 경로 추가 검토. |

## Research References

| File | Content |
|------|---------|
| research/track-c-automated-interactive-testing.md | 최종 연구 문서 (R1+R2 검증) |
| temp/track-c-effectiveness-analysis.md | 5개 시나리오 도출 + 효과성 분석 |
| temp/track-c-docker-research.md | Docker 샌드박스 실현 가능성 연구 |
| temp/track-c-revision-verify-r1.md | 시나리오 기술 검증 |
| temp/track-c-revision-verify-r2.md | 시나리오 반론 검증 |
| temp/track-c-final-verify-r1.md | 최종 구조 검증 (stream-json S1 재분류) |
| temp/track-c-final-verify-r2.md | 최종 반론 검증 (Docker 대안 분석) |
| temp/track-c-wsl-live-test.md | WSL2 tmux 실증 (8/8 PASS) |
| temp/track-c-docker-context.md | Docker 접근 context |
| temp/track-c-revision-synthesis.md | Hybrid approach 합성 |
| temp/auth-feasibility-analysis.md | OAuth 인증 실현 가능성 분석 |
| temp/auth-research.md | Claude Code CLI 인증 연구 |
| temp/auth-verify-r1.md | R1 구조 검증: OAuth 접근 |
| temp/auth-verify-r2.md | R2 보안/엣지케이스 검증: OAuth 접근 |
