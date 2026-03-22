# Closed Feedback Loop v2: Phase Redesign

**Date**: 2026-03-22 | **Status**: Draft | **Supersedes**: research/closed-feedback-loop.md (v1)
**Cross-model validation**: Codex 5.3 (adversarial review), Gemini 3.1 Pro (adversarial review)

---

## 0. Design Philosophy Change from v1

### v1의 근본 문제

v1은 "ops 레포에서 발생하는 문제를 claude-memory 레포로 가져온다"는 cross-repo promotion 모델이었다. 사용자 피드백이 명확히 지적한 문제:

1. **ops 환경 재현 불가**: ops 폴더의 정확한 환경을 가져오기 어렵다
2. **수동 의존**: 상황이 발생할 때마다 수동으로 가져와야 한다
3. **로그 불충분**: 로그에 남기라고 했는데도 실제 화면에 보이는 정보가 로그에 없다
4. **closed loop 불가**: 외부 데이터에 의존하면 자율적 개선 루프가 돌지 않는다

### v2의 핵심 전환

**재귀적 자기 설치(Recursive Self-Installation)**: claude-memory 레포 안에서 claude-memory 플러그인을 설치하고, claude-code-guardian도 붙여서, ops와 유사한 환경을 레포 내부에 구축한다. 모든 데이터 수집, 분석, 개선이 이 레포 안에서 완결된다.

**다층 증거 수집(Multi-Layer Evidence Capture)**: 로그만으로는 현상을 충분히 잡지 못한다. CLI 출력 (stdout/stderr/stream-json)을 자동 캡처하고, TUI 팝업 같은 대화형 현상은 수동 캡처 트랙으로 보완한다. "로그에 없는 정보"를 가능한 모든 채널에서 수집한다.

**수동 먼저, 자동화 나중(Manual First)**: 사람이 한 loop를 직접 해보고, 잘 되면 ralph loop로 자동화한다.

### Honest Limitations (Cross-Model Validation에서 식별)

이 설계의 한계를 솔직히 인정한다:

1. **TUI 팝업 관찰 불가**: `claude -p` (비대화형 모드)에서는 Guardian approval dialog 같은 TUI 팝업이 발생하지 않는다. 이 프레임워크는 CLI-visible 출력 (stdout, stderr, stream-json 이벤트)만 자동으로 검증할 수 있다. 실제 TUI 팝업 검증은 별도의 **Interactive Verification Track** (수동 캡처 + 체크리스트)으로 보완한다.

2. **Guardian 수정 범위**: 이 레포에서 Guardian 충돌을 **탐지**할 수 있지만, Guardian 자체의 버그를 **수정**할 수는 없다. claude-memory 측 완화(mitigation)만 이 루프의 범위다.

3. **커버리지 완전성**: "100% 커버리지"는 자체 정의한 요구사항 목록에 대한 것이며, 예측 불가능한 UX 문제나 미식별 엣지케이스를 모두 포착할 수는 없다. **Residual Risk Register** 를 유지하여 알려진 미커버 영역을 추적한다.

---

## Phase 1: Evidence Contract (증거 계약)

### 1.1 Goal (목표)

claude-memory 플러그인이 실제 동작할 때 발생하는 **CLI-visible 현상**을 구조적으로 캡처하는 증거 수집 체계 구축. stdout, stderr, stream-json 이벤트, JSONL 로그를 포함하며, TUI 팝업은 별도 수동 트랙으로 보완.

### 1.2 What Changes from v1 and Why

| v1 | v2 | Why |
|----|-----|-----|
| JSONL 로그만 수집 | 로그 + stderr + stdout + stream-json 이벤트 전체 | "로그에 없는 정보가 작업 화면에는 보인다" |
| ops에서 로그 가져옴 | claude-memory 레포 내에서 직접 생성 | "독립적으로 claude-memory 레포에서도 개선" |
| 시나리오 레지스트리 (JSON) | 시나리오 + 캡처 프로토콜 + 수동 TUI 체크리스트 | CLI + TUI 양쪽 커버 |
| Deterministic oracle only | Deterministic + CLI visual evidence + manual TUI track | 팝업 같은 현상은 별도 트랙 |

### 1.3 Detailed Design

#### 1.3.1 Dual-Track Evidence Architecture

**Track A: Automated CLI Capture** (이 프레임워크의 주 영역)
- `claude -p` + `--output-format stream-json` 의 모든 출력
- stderr 분리 캡처
- JSONL 플러그인 로그
- Workspace 파일시스템 상태 스냅샷

**Track B: Manual Interactive Verification** (보완 트랙)
- 사람이 실제 대화형 `claude` 세션에서 메모리 관련 작업 수행
- 스크린샷 또는 `asciinema rec` 으로 TUI 캡처
- Guardian approval popup, 화면 깜빡임, 예상치 못한 메시지 관찰 기록
- `evidence/manual/` 에 날짜별 저장
- 체크리스트 기반: `evidence/manual-checklist.md`

이 dual-track 접근은 사용자 피드백의 핵심을 정확히 반영한다: "실제 ops에서 메모리 관련 팝업이나 화면이 나올 때 캡쳐해서 주면, 새로운 에러라고 찾아낸다."

#### 1.3.2 Automated Capture Protocol

모든 `claude -p` 실행 시 다음을 캡처:

```
evidence/
  runs/
    run-{timestamp}-{scenario_id}/
      stdout.txt          # claude -p 의 전체 stdout (ANSI stripped)
      stderr.txt          # claude -p 의 전체 stderr (ANSI stripped)
      stdout-raw.txt      # ANSI 포함 원본 (script -e 캡처)
      output.json         # --output-format stream-json 결과
      logs/               # 플러그인 JSONL 로그 복사
        memory-events.jsonl
      workspace/           # 실행 후 workspace 스냅샷
        .claude/memory/    # 메모리 파일 상태
      metadata.json        # 실행 메타데이터
  manual/                  # Track B: 수동 캡처
    2026-03-22/
      screenshot-001.png
      asciinema-session.cast
      observations.md
  manual-checklist.md      # 수동 검증 체크리스트
```

#### 1.3.3 Screen Capture: Practical Approach

`claude -p`의 출력 캡처 전략 (cross-model validation 반영):

1. **`script -e -q -c "..." output.typescript`**: `-e` 플래그로 child process의 exit code를 보존 (Codex 지적 반영)
2. **ANSI stripping**: raw 캡처 후 `sed 's/\x1b\[[0-9;]*m//g'` 또는 Python `strip-ansi`로 정리. ANSI 파싱이 아닌 단순 제거 후 plaintext 분석 (Gemini 지적 반영)
3. **Forbidden string regex**: ANSI-stripped plaintext에서 `Error:`, `Traceback`, `BLOCKED`, `permission denied`, `approve` 등의 패턴을 regex로 탐지. 복잡한 ANSI 구조 분석은 하지 않음.
4. **stream-json**: `--output-format stream-json`이 구조화된 이벤트를 제공하므로, 이것을 주 분석 소스로 사용. stdout plaintext는 보조.

**명시적으로 하지 않는 것:**
- ANSI escape sequence의 의미론적 파싱 (spinner, color 등)
- TUI 레이아웃 재구성
- Guardian approval dialog 캡처 (이것은 Track B 수동 트랙의 영역)

#### 1.3.4 Evidence Schema

```json
{
  "run_id": "run-20260322-143000-SCN-RET-001",
  "scenario_id": "SCN-RET-001",
  "plugin_commit": "05ebd42",
  "claude_version": "2.1.81",
  "guardian_version": "1.0.0",
  "timestamp": "2026-03-22T14:30:00Z",
  "environment": {
    "permission_mode": "auto",
    "plugins_loaded": ["claude-memory", "claude-code-guardian"],
    "plugins_expected": ["claude-memory", "claude-code-guardian"],
    "plugin_set_match": true,
    "workspace_path": "/tmp/cfl-run-xxxxx",
    "composite_plugin_dir": "/tmp/cfl-plugins-xxxxx"
  },
  "captures": {
    "stdout_lines": 42,
    "stderr_lines": 3,
    "stderr_contains_errors": false,
    "log_events_count": 15,
    "stream_json_events": 28
  },
  "verdict": "PASS",
  "child_exit_code": 0,
  "wrapper_exit_code": 0,
  "checks": {
    "expected_signals": {"found": 3, "missing": 0},
    "forbidden_signals": {"found": 0},
    "files_created": ["decisions/example.json"],
    "files_valid_schema": true,
    "guardian_blocks": 0,
    "unexpected_stderr": [],
    "plugin_set_verified": true
  },
  "duration_ms": 45000
}
```

변경사항 (cross-model 반영):
- `child_exit_code` / `wrapper_exit_code` 분리 (Codex: script(1)이 child exit code를 숨길 수 있음)
- `plugins_expected` + `plugin_set_match` (Codex: 로드된 플러그인 세트 검증)
- `composite_plugin_dir` (self-contained 보장)

#### 1.3.5 Scenario Registry

```
evidence/
  scenarios/
    SCN-RET-001.json    # retrieval 기본 검색
    SCN-CAP-001.json    # auto-capture 트리거
    SCN-UX-001.json     # CLI 화면 노이즈 없음
    SCN-GRD-001.json    # Guardian 호환성
    SCN-SAVE-001.json   # 전체 저장 흐름
```

시나리오 정의:
```json
{
  "id": "SCN-UX-001",
  "name": "quiet_operation_no_popups",
  "description": "플러그인이 조용히 동작하는지 CLI-level에서 검증. Guardian 에러, 예상치 못한 stderr 출력 없음.",
  "prompt": "What is the capital of France?",
  "setup": {
    "memories": ["test-fixtures/decision-sample.json"],
    "config_overrides": {},
    "plugins_required": ["claude-memory", "claude-code-guardian"]
  },
  "checks": {
    "expected_in_stdout": [],
    "forbidden_in_stdout_regex": ["[Ee]rror", "permission", "denied", "approve"],
    "forbidden_in_stderr_regex": ["Traceback", "[Ee]rror", "BLOCKED", "guardian"],
    "expected_files": [],
    "forbidden_files": [],
    "max_stderr_lines": 5,
    "max_duration_ms": 60000,
    "require_child_exit_zero": true
  },
  "requirement_ids": ["REQ-4.1"],
  "tier": 2,
  "verification_scope": "cli-only",
  "notes": "TUI popup 검증은 Track B (manual-checklist.md) 참조. 이 시나리오는 CLI-visible 출력만 검증."
}
```

### 1.4 Acceptance Criteria

1. 3개 이상의 시나리오가 정의되어 있고, 각각 실행 시 `evidence/runs/` 에 구조화된 증거 디렉토리가 생성됨
2. stdout, stderr (ANSI-stripped), JSONL 로그, workspace 스냅샷이 모두 캡처됨
3. 동일 시나리오를 2회 실행했을 때, metadata.json의 verdict가 동일함 (재현성)
4. stderr에 forbidden regex 매칭이 있으면 자동으로 `unexpected_stderr`에 기록됨
5. Evidence schema가 JSON Schema로 정의되어 검증 가능
6. `child_exit_code`와 `wrapper_exit_code`가 분리 기록됨 (`script -e` 사용)
7. Manual verification checklist (`evidence/manual-checklist.md`)가 존재하고 TUI 검증 항목 포함

### 1.5 Dependencies

- Phase 2에 workspace 격리 구조 제공
- Phase 3+4의 요구사항 추적에 `requirement_ids` 매핑 제공

---

## Phase 2: Recursive Self-Testing Loop (재귀적 자기 테스트 루프)

### 2.1 Goal (목표)

claude-memory 레포 **내부에서** claude-memory 플러그인 + claude-code-guardian을 composite plugin directory로 구성하여, 실제 ops 환경과 유사한 조건에서 동작시키며, 결과를 수집하는 **진정한 자기 완결적** 루프 구축.

### 2.2 What Changes from v1 and Why

| v1 | v2 | Why |
|----|-----|-----|
| 외부에서 `claude -p` 실행 | 레포 내부에서 재귀적 자기 설치 후 실행 | "claude-memory 레포 안에서 closed loop" |
| claude-memory만 테스트 | claude-memory + guardian 동시 테스트 | "ops와 유사 환경" |
| `--plugin-dir .` | Composite plugin directory (symlink 기반) | guardian behavior 캡처 + self-contained |
| `bypassPermissions` | `auto` 모드 | 실제 사용과 유사한 permission 동작 |
| Guardian 전역 설치 의존 | 레포 내 guardian 참조 (pinned) | 진정한 self-contained (clean checkout에서도 동작) |

### 2.3 Detailed Design

#### 2.3.1 Composite Plugin Directory Architecture

Cross-model validation에서 두 모델 모두 "self-contained라고 하면서 전역 Guardian에 의존하는 것은 모순"이라고 지적했다. 이를 해결:

```
claude-memory/                          # 개발 레포 (HOST)
  hooks/scripts/                        # 소스 코드
  tests/                                # pytest 유닛 테스트
  evidence/                             # CFL 증거 저장소
    bootstrap.py                        # 환경 구성 스크립트
    runner.py                           # 메인 루프 실행기
    guardian-ref/                        # Guardian 참조 (git submodule or pinned copy)
      .claude-plugin/plugin.json
      hooks/hooks.json
      ...

실행 시 생성되는 임시 구조:
  /tmp/cfl-plugins-{run_id}/            # Composite plugin directory
    claude-memory -> /path/to/claude-memory/  (symlink to dev source)
    claude-code-guardian -> /path/to/evidence/guardian-ref/  (symlink)

  /tmp/cfl-workspace-{run_id}/          # 격리된 실행 환경 (GUEST)
    .claude/
      memory/                           # 격리된 메모리 저장소
        memory-config.json              # 테스트용 설정
    dummy-project-file.txt              # CWD가 유효한 프로젝트임을 보장
```

**Plugin loading**: `--plugin-dir`가 반복 가능하다는 것이 확인됨 (Codex 검증). 따라서:
```bash
claude -p "$PROMPT" \
  --plugin-dir /path/to/claude-memory \
  --plugin-dir /path/to/evidence/guardian-ref \
  --permission-mode auto
```

대안: `--plugin-dir`가 반복 불가능한 경우, composite directory에 두 플러그인을 symlink하고 단일 `--plugin-dir`를 사용.

**Bootstrap assertion**: 실행 전 로드된 플러그인 세트가 정확히 시나리오가 요구하는 것과 일치하는지 검증. 불일치 시 run을 FAIL 처리.

#### 2.3.2 Guardian Reference Management

Guardian을 레포 내에서 관리하는 3가지 옵션:

| 옵션 | 장점 | 단점 |
|------|------|------|
| A: git submodule | 버전 고정, 자동 업데이트 | submodule 관리 복잡성 |
| B: pinned copy (evidence/guardian-ref/) | 단순, 명시적 | 수동 업데이트 필요 |
| C: bootstrap script가 특정 버전 clone | 항상 최신 가능 | 네트워크 의존 |

**권장: 옵션 B** (pinned copy). Guardian의 hooks.json + plugin.json + hook scripts만 최소한으로 복사. 버전을 `evidence/guardian-ref/VERSION` 파일에 기록. 업데이트는 수동이지만, closed loop 내에서는 안정성이 더 중요.

#### 2.3.3 Runner Design

```python
# evidence/runner.py (개념적 설계)

class CFLRunner:
    """claude-memory 레포 내에서 실행되는 자기 완결적 테스트 러너."""

    def __init__(self, plugin_source: str, guardian_ref: str, scenarios_dir: str):
        self.plugin_source = plugin_source   # claude-memory 레포 루트
        self.guardian_ref = guardian_ref      # evidence/guardian-ref/
        self.scenarios_dir = scenarios_dir

    def run_scenario(self, scenario_path: str) -> RunResult:
        # 0. 사전 검증
        self.verify_prerequisites()

        # 1. 격리 워크스페이스 + composite plugin dir 생성
        workspace, plugin_dir = self.create_isolated_environment(scenario_path)

        # 2. 메모리 사전 배치 (시나리오 setup에 따라)
        self.seed_memories(workspace, scenario)

        # 3. claude -p 실행 (screen capture 포함)
        capture = self.execute_claude(
            workspace=workspace,
            prompt=scenario["prompt"],
            permission_mode="auto",
            plugin_dirs=[self.plugin_source, self.guardian_ref],
            capture_screen=True
        )

        # 4. Plugin set assertion
        if not self.verify_plugin_set(capture, scenario["setup"]["plugins_required"]):
            return RunResult(verdict="ERROR", reason="plugin set mismatch")

        # 5. 증거 수집
        evidence = self.collect_evidence(workspace, capture)

        # 6. 판정 (결정적 오라클)
        verdict = self.evaluate(evidence, scenario["checks"])

        # 7. 결과 저장
        return self.save_result(scenario, evidence, verdict)

    def create_isolated_environment(self, scenario_path):
        """격리된 workspace + composite plugin directory 생성."""
        run_id = f"run-{timestamp()}-{scenario['id']}"

        # Workspace (격리된 CWD)
        workspace = Path(tempfile.mkdtemp(prefix=f"cfl-workspace-"))
        (workspace / ".claude" / "memory").mkdir(parents=True)

        # Plugin directory -- symlink 방식
        # (--plugin-dir 가 반복 가능하면 직접 전달, 아니면 composite)
        return workspace, [self.plugin_source, self.guardian_ref]

    def execute_claude(self, workspace, prompt, permission_mode, plugin_dirs, capture_screen):
        """claude -p 실행 + 전체 출력 캡처."""
        cmd = [
            "claude", "-p", prompt,
            "--permission-mode", permission_mode,
            "--output-format", "stream-json",
        ]
        for pd in plugin_dirs:
            cmd.extend(["--plugin-dir", pd])

        # script -e 래핑으로 child exit code 보존 (Codex 지적 반영)
        if capture_screen:
            typescript_path = workspace / "stdout-raw.txt"
            cmd = ["script", "-e", "-q", "-c", shlex.join(cmd), str(typescript_path)]

        result = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=120
        )

        # ANSI strip for clean analysis
        stdout_clean = strip_ansi(result.stdout)
        stderr_clean = strip_ansi(result.stderr)

        return CaptureResult(
            stdout=stdout_clean,
            stderr=stderr_clean,
            stdout_raw=result.stdout,
            returncode=result.returncode,  # script -e propagates child exit
            typescript=typescript_path.read_text() if capture_screen else None
        )
```

#### 2.3.4 Guardian Co-Testing (Scope Boundaries)

Guardian과의 상호작용 테스트에서 명확한 범위 구분:

**이 루프에서 할 수 있는 것 (detect + mitigate):**
- Guardian이 claude-memory의 hook 출력에 반응하여 발생하는 stderr 경고 탐지
- claude-memory 측 코드 수정으로 Guardian 충돌 완화 (예: agent file의 tools 제한, output format 변경)
- Guardian 없는 기준선과 비교하여 Guardian 영향 분리

**이 루프에서 할 수 없는 것 (Guardian repo의 영역):**
- Guardian 자체의 패턴 매칭 로직 수정
- Guardian의 false positive 판정 변경
- Guardian의 hook 우선순위 변경

```python
# Guardian 공존 시나리오
GUARDIAN_COMPARISON = {
    "with_guardian": {
        "plugins": ["claude-memory", "claude-code-guardian"],
        "description": "실제 ops 환경과 동일. Guardian 영향 관찰."
    },
    "without_guardian": {
        "plugins": ["claude-memory"],
        "description": "Guardian 영향 분리를 위한 기준선. 차이가 곧 Guardian의 영향."
    }
}
```

#### 2.3.5 Initial Scenario Set (5개)

1. **SCN-RET-001** (Retrieval): 사전 배치된 메모리가 검색되는지
2. **SCN-CAP-001** (Auto-capture): Stop 훅이 트리거되어 메모리가 저장되는지
3. **SCN-UX-001** (Screen Noise): CLI-level에서 불필요한 출력이 없는지
4. **SCN-GRD-001** (Guardian): Guardian 존재 시 CLI-visible 충돌 없는지
5. **SCN-SAVE-001** (Full Save): 전체 저장 흐름이 완료되는지

#### 2.3.6 Meta-Validation: Known-Bad Build

러너 자체의 신뢰성을 검증하기 위해, 의도적으로 실패하는 시나리오를 포함:

```json
{
  "id": "SCN-META-001",
  "name": "known_bad_build_must_fail",
  "description": "의도적 버그 (broken triage script)가 FAIL 판정을 받는지 검증",
  "setup": {
    "inject_bug": "syntax_error_in_triage",
    "plugins_required": ["claude-memory"]
  },
  "checks": {
    "expect_verdict": "FAIL",
    "forbidden_in_stderr_regex": []
  },
  "notes": "이 시나리오가 PASS하면 러너에 버그가 있는 것"
}
```

### 2.4 Acceptance Criteria

1. `evidence/runner.py`가 claude-memory 레포 루트에서 실행 가능 (clean checkout에서도)
2. 5개 시나리오 모두 격리된 워크스페이스에서 실행, 교차 오염 없음
3. Composite plugin directory로 Guardian + Memory 동시 로드 확인
4. Plugin set assertion: 예상과 다른 플러그인 세트에서 ERROR 판정
5. 알려진 나쁜 빌드 (SCN-META-001)가 FAIL 판정을 받음 (meta-validation)
6. 결과가 `evidence/runs/`에 Phase 1 스키마로 저장됨
7. Guardian 없는 기준선 vs Guardian 있는 실행의 차이가 기록됨
8. `evidence/guardian-ref/` 에 Guardian 참조가 pinned copy로 존재

### 2.5 Dependencies

- Phase 1의 증거 스키마와 시나리오 레지스트리
- Spike test: `--plugin-dir` 반복 가능 여부 확인 (Week 1 사전 조건)
- `evidence/guardian-ref/`에 Guardian pinned copy 준비

---

## Phase 3: Requirement Traceability + Complete Test Coverage (요구사항 추적 + 완전한 테스트 커버리지)

### 3.1 Goal (목표)

PRD의 모든 요구사항을 식별하고 테스트에 매핑하며, 누락된 엣지케이스를 테스트로 추가하고, 로그 분석을 자동화하여 수동 개입 없이 문제를 발견하는 체계 구축.

**Phase 3/4 통합 (Cross-model 반영)**: v1 초안에서 Phase 3 (테스트 커버리지)과 Phase 4 (요구사항 추적)가 순환 의존이었다 -- Phase 3이 요구사항 마커를 필요로 하는데, Phase 4가 마커를 도입. 이를 하나의 Phase로 통합한다.

### 3.2 What Changes from v1 and Why

| v1 | v2 | Why |
|----|-----|-----|
| Cross-repo promotion | 완전한 테스트 커버리지 (레포 내부) | "ops 환경을 가져올 수 없으니 레포 안에서 다 만든다" |
| Phase 3 (coverage) + Phase 4 (traceability) 분리 | 하나의 Phase로 통합 | 순환 의존 해소 (Codex 지적) |
| ops 로그 분석 후 이슈 생성 | 자동 로그 분석이 테스트의 일부 | "로그 분석이 자동화 되어야 한다" |
| "100% 커버리지" 주장 | Deterministic coverage + residual risk register | 달성 불가능한 것은 솔직히 인정 (Codex 지적) |

### 3.3 Detailed Design

#### 3.3.1 Pytest Requirement Markers (먼저 도입)

```python
# conftest.py 확장
def pytest_configure(config):
    config.addinivalue_line("markers",
        "requirement(id): PRD requirement this test verifies")
    config.addinivalue_line("markers",
        "edge_case(desc): Edge case description for traceability")

# 사용 예
@pytest.mark.requirement("REQ-3.1.1")
@pytest.mark.edge_case("empty transcript produces zero scores")
def test_triage_empty_transcript():
    ...
```

#### 3.3.2 Requirement Traceability Matrix

모든 PRD 요구사항을 식별하고 테스트 매핑:

```
evidence/
  requirements/
    requirements.json        # 전체 요구사항 레지스트리
    coverage-report.json     # 자동 생성 커버리지 리포트
    gap-analysis.json        # 미커버 요구사항 목록
    residual-risks.json      # 알려진 미커버 영역 (솔직한 한계)
```

```json
{
  "REQ-3.1.1": {
    "title": "Stop hook triage scoring",
    "source": "PRD 3.1.1",
    "verification_type": "deterministic",
    "tier1_tests": ["test_memory_triage::test_score_decision", "..."],
    "tier2_scenarios": ["SCN-CAP-001"],
    "edge_cases": [
      "empty_transcript",
      "transcript_with_only_system_messages",
      "transcript_exceeding_max_messages",
      "concurrent_stop_events",
      "unicode_heavy_transcript"
    ],
    "status": "covered | partial | uncovered"
  },
  "REQ-4.1": {
    "title": "Minimal Screen Noise",
    "source": "PRD 4.1",
    "verification_type": "hybrid",
    "tier1_tests": ["test_regression_popups::test_*"],
    "tier2_scenarios": ["SCN-UX-001"],
    "manual_track": "evidence/manual-checklist.md#screen-noise",
    "residual_risk": "TUI 팝업은 claude -p에서 관찰 불가. Track B 수동 검증 필요.",
    "status": "partial"
  }
}
```

#### 3.3.3 Residual Risk Register

100% 커버리지를 주장하는 대신, 알려진 미커버 영역을 솔직히 기록:

```json
{
  "residual_risks": [
    {
      "id": "RR-001",
      "area": "TUI Popup Verification",
      "description": "Guardian approval dialog, 화면 깜빡임 등 TUI-only 현상은 claude -p로 자동 검증 불가",
      "mitigation": "Track B 수동 검증 + existing test_regression_popups.py 패턴 매칭",
      "requirements_affected": ["REQ-4.1"]
    },
    {
      "id": "RR-002",
      "area": "LLM Non-Determinism",
      "description": "동일 시나리오에서 LLM이 다른 출력을 생성하여 결과가 달라질 수 있음",
      "mitigation": "파일시스템 상태 (파일 존재, 유효 JSON)로만 판정. LLM 출력 내용은 불검증.",
      "requirements_affected": ["REQ-3.1.2", "REQ-3.2.1"]
    },
    {
      "id": "RR-003",
      "area": "Guardian-Side Bugs",
      "description": "Guardian 자체의 버그는 이 레포에서 수정 불가",
      "mitigation": "탐지만 가능. Guardian 측 이슈는 별도 보고.",
      "requirements_affected": ["REQ-4.1"]
    }
  ]
}
```

#### 3.3.4 Edge Case Coverage Strategy

기존 1097개 테스트를 분석하여 누락된 엣지케이스 식별:

| 영역 | 현재 커버 | 누락 가능 엣지케이스 |
|------|----------|-------------------|
| Triage | 키워드 매칭, 임계값 | 동시 6개 카테고리 트리거, 최대 길이 transcript, 빈 transcript |
| Retrieval | FTS5 검색, 점수 | 인덱스 없음, 인덱스 깨짐, 1000+ 메모리, 검색어 없음 |
| Write | CRUD, OCC | 디스크 풀, permission denied, 동시 쓰기, 경로 순회 |
| Guard | 허용/거부 | 심볼릭 링크 공격, 상대 경로 조작, 빈 input |
| Index | 빌드, 검증 | 깨진 JSON 파일, 고아 파일, 인덱스 락 |
| Enforce | 롤링 윈도우 | 한계 0, 한계 초대형, 모든 retired, 빈 카테고리 |

#### 3.3.5 Automated Log Analysis

Phase 2의 실행 결과 로그를 자동으로 분석. 기존 `memory_log_analyzer.py`의 보안 속성(경로 안전성, 메모리 제한)을 유지하면서 확장:

```python
# evidence/log_analyzer.py

class CFLLogAnalyzer:
    """Phase 2 실행 결과 로그의 자동 분석.
    기존 hooks/scripts/memory_log_analyzer.py 의 패턴을 활용."""

    def analyze_run(self, run_dir: Path) -> AnalysisReport:
        # 1. JSONL 이벤트 로그 파싱
        events = self.parse_log_events(run_dir / "logs/memory-events.jsonl")

        # 2. 패턴 분석
        patterns = {
            "error_events": self.find_errors(events),
            "slow_operations": self.find_slow_ops(events, threshold_ms=5000),
            "missing_events": self.find_missing_expected_events(events),
            "duplicate_events": self.find_duplicates(events),
            "category_coverage": self.check_category_coverage(events),
        }

        # 3. stderr 분석 (ANSI-stripped plaintext에서 forbidden regex 탐지)
        stderr_findings = self.analyze_stderr_plaintext(run_dir / "stderr.txt")

        # 4. Log-stderr 교차 대조 (간소화: ANSI 파싱 대신 plaintext 매칭)
        #    - 로그에 error 이벤트가 없는데 stderr에 Error 문자열이 있으면 = discrepancy
        #    - 로그에 있는 이벤트가 stderr에 반영되지 않으면 = 정상 (로그가 더 상세)
        discrepancies = self.cross_reference_simplified(events, stderr_findings)

        return AnalysisReport(
            patterns=patterns,
            stderr_findings=stderr_findings,
            discrepancies=discrepancies,
            recommendations=self.generate_recommendations(patterns, discrepancies)
        )

    def analyze_stderr_plaintext(self, stderr_path: Path) -> list:
        """ANSI-stripped stderr에서 forbidden 패턴을 regex로 탐지.
        복잡한 ANSI 구조 분석은 하지 않음 (Gemini/Codex 지적 반영)."""
        if not stderr_path.exists():
            return []
        text = stderr_path.read_text()
        findings = []
        FORBIDDEN_PATTERNS = [
            r"Traceback", r"Error:", r"BLOCKED", r"permission denied",
            r"guardian.*block", r"ImportError", r"ModuleNotFoundError",
        ]
        for pattern in FORBIDDEN_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                findings.append({"pattern": pattern, "count": len(matches)})
        return findings

    def cross_reference_simplified(self, events, stderr_findings) -> list:
        """로그 vs stderr 간소화된 교차 대조.
        ANSI 파싱 없이, 구조화된 로그 이벤트와 plaintext stderr의 불일치만 탐지."""
        discrepancies = []
        log_has_errors = any(e.get("level") == "ERROR" for e in events)
        stderr_has_errors = len(stderr_findings) > 0

        if stderr_has_errors and not log_has_errors:
            discrepancies.append({
                "type": "stderr_error_not_in_log",
                "description": "stderr에 에러 패턴이 있지만 JSONL 로그에 ERROR 이벤트 없음",
                "stderr_findings": stderr_findings,
                "action": "로그 누락 가능성 -- 해당 코드 경로에 로깅 추가 필요"
            })
        return discrepancies
```

#### 3.3.6 Log Analysis as Test

```python
# tests/test_cfl_log_analysis.py

class TestLogAnalysis:
    """Phase 2 실행 결과의 로그 분석 자동화 테스트."""

    def test_no_unexpected_errors_in_logs(self, latest_run):
        analysis = CFLLogAnalyzer().analyze_run(latest_run)
        assert len(analysis.patterns["error_events"]) == 0

    def test_no_stderr_errors_missing_from_logs(self, latest_run):
        """stderr에 에러가 있으면 로그에도 있어야 한다."""
        analysis = CFLLogAnalyzer().analyze_run(latest_run)
        assert len(analysis.discrepancies) == 0

    def test_all_expected_hook_events_present(self, latest_run):
        analysis = CFLLogAnalyzer().analyze_run(latest_run)
        assert len(analysis.patterns["missing_events"]) == 0
```

#### 3.3.7 Unified Coverage Dashboard

Tier 1 (pytest)와 Tier 2 (live scenario) 결과를 결합하되, **독립적으로 생성 가능** (Gemini 지적: Tier 2 실행 없이도 Tier 1 리포트 가능):

```python
# evidence/coverage_report.py

def generate_coverage_report(tier2_cache=True):
    """Tier 1 + Tier 2 통합 커버리지.
    tier2_cache=True: 최신 캐시된 Tier 2 결과 사용 (Tier 2 재실행 불필요)"""

    requirements = load_requirements()
    pytest_results = load_pytest_results("results.json")  # 항상 fresh

    if tier2_cache:
        scenario_results = load_cached_scenario_results("evidence/runs/latest/")
    else:
        scenario_results = load_scenario_results("evidence/runs/")

    for req_id, req in requirements.items():
        req["tier1_status"] = check_tier1(req, pytest_results)
        req["tier2_status"] = check_tier2(req, scenario_results) if scenario_results else "NOT_RUN"
        req["overall_status"] = compute_overall(req)

    gaps = [r for r in requirements.values() if r["overall_status"] != "PASS"]

    if gaps:
        generate_gap_action_plan(gaps)

    return CoverageReport(requirements=requirements, gaps=gaps)
```

### 3.4 Acceptance Criteria

1. 모든 기존 테스트에 `@pytest.mark.requirement()` 마커 추가
2. 모든 PRD 요구사항이 `requirements.json`에 등록, 각각 `verification_type` 분류
3. `coverage-report.py` 실행 시 Tier1 (즉시) + Tier2 (캐시) 리포트 생성
4. Deterministic 요구사항은 100% 테스트 커버리지 (uncovered 0개)
5. Hybrid/manual 요구사항은 residual risk register에 등록
6. 각 영역별 엣지케이스가 테스트로 존재
7. `log_analyzer.py`가 Phase 2 실행 결과를 자동 분석
8. Log-stderr 교차 대조에서 discrepancy 자동 감지 (ANSI 파싱 없이, plaintext regex)
9. 갭 발견 시 action plan 자동 생성 (템플릿 기반)

### 3.5 Dependencies

- Phase 1의 증거 스키마 (로그 분석 입력 포맷)
- Phase 2의 실행 결과 (Tier 2 분석 대상 데이터)

---

## Phase 4: Automated Gap-to-Action Pipeline (자동 갭 발견 및 Action Plan 생성)

### 4.1 Goal (목표)

Phase 3의 커버리지 리포트에서 실패한 요구사항을 자동으로 action plan으로 변환하고, 기존 action plan과의 중복을 방지하며, Phase 5의 개선 루프에 입력을 제공하는 파이프라인 구축.

### 4.2 What Changes from v1 and Why

| v1 | v2 | Why |
|----|-----|-----|
| 요구사항 추적이 Phase 4 | 추적은 Phase 3에 통합, Phase 4는 gap-to-action pipeline | 순환 의존 해소 |
| 추적만 | 추적 → 갭 발견 → action plan 자동 생성 → 루프 입력 | "루프를 닫기 위해" |
| 중복 방지 미정의 | Requirement ID 기반 exact match + 기존 plan 상태 확인 | Codex 지적 반영 |

### 4.3 Detailed Design

#### 4.3.1 Gap-to-Action-Plan Pipeline

```
Phase 3 coverage report 실행
  → gap-analysis.json 생성 (FAIL 요구사항 목록)
  → 각 FAIL 요구사항에 대해:
    → action-plans/ 에서 동일 requirement ID를 가진 기존 plan 검색
    → 기존 plan 있고 status != done → 기존 plan에 새 증거 추가
    → 기존 plan 있고 status == done → 회귀(regression) plan 새로 생성
    → 기존 plan 없음 → 새 plan 생성
```

#### 4.3.2 Action Plan Template

```markdown
---
status: not-started
progress: auto-generated from coverage gap
source: cfl-coverage-report
requirement: REQ-X.Y.Z
created: 2026-03-22
---

# Fix: {requirement title}

## Problem
요구사항 {REQ-ID} ({title})가 테스트에서 FAIL.

## Evidence
- Tier 1 실패 테스트: {list}
- Tier 2 실패 시나리오: {list}
- 로그 분석 결과: {summary}
- Discrepancies: {log-stderr 불일치 목록}

## Suggested Fix
(수동으로 분석 후 작성 -- Phase 5 Manual Loop에서)

## Acceptance Criteria
- [ ] 해당 요구사항의 모든 Tier 1 테스트 PASS
- [ ] 해당 Tier 2 시나리오 PASS (해당되는 경우)
- [ ] 회귀 테스트 추가
- [ ] 기존 테스트 전체 PASS (regression 없음)
```

#### 4.3.3 Deduplication Mechanism

```python
def find_existing_plan(requirement_id: str) -> Optional[Path]:
    """action-plans/ 에서 동일 requirement를 대상으로 하는 기존 plan 검색."""
    for plan_path in Path("action-plans").glob("*.md"):
        frontmatter = parse_frontmatter(plan_path)
        if frontmatter.get("requirement") == requirement_id:
            return plan_path
    return None
```

### 4.4 Acceptance Criteria

1. Coverage gap 발견 시 action plan이 자동 생성됨
2. 기존 action plan과 중복되지 않음 (requirement ID 기반 dedup)
3. 회귀 시 별도 plan 생성
4. Action plan에 Phase 3의 증거 (실패 테스트, 시나리오, 로그 분석)가 포함됨
5. 생성된 action plan이 Phase 5 Manual Loop에서 바로 사용 가능한 형태

### 4.5 Dependencies

- Phase 3의 coverage report (입력)
- Phase 3의 log analysis results (증거)
- `action-plans/` 디렉토리 구조 (기존)

---

## Phase 5: Manual-First Improvement Loop, then Automated Ralph Loop (수동 개선 루프 → 자동화)

### 5.1 Goal (목표)

분석 결과를 action plan으로 작성하고, branch 생성 후 수정하고, 테스트 통과하면 PR 생성하는 개선 루프를 **먼저 사람이 수동으로 실행**한 후, 검증되면 ralph loop로 자동화.

### 5.2 What Changes from v1 and Why

| v1 | v2 | Why |
|----|-----|-----|
| Shadow Loop (자동 .patch 생성) | Manual first → 자동화 | "사람이 해본 후, 잘 되면 ralph loop로 자동화" |
| 자동 수정 시도 | 분석 → action plan → branch → 수행 → 테스트 → PR | 명시적 단계 |
| 위험 관리가 주 관심사 | 프로세스 검증이 주 관심사 | 사람이 먼저 프로세스를 검증 |
| Branch isolation만 | Action plan + scope bounding + git cleanliness | 안전성 강화 (Gemini 지적) |

### 5.3 Detailed Design

#### 5.3.1 Manual Loop Protocol (Stage 1: 사람이 실행)

```
Step 1: 분석 결과 확인
  -- evidence/requirements/coverage-report.json 에서 FAIL 요구사항 확인
  -- evidence/runs/ 에서 실패 증거 확인
  -- evidence/requirements/residual-risks.json 에서 미커버 영역 확인
  -- log analyzer 결과에서 패턴 확인

Step 2: Action Plan 작성/확인
  -- action-plans/fix-{issue}.md (Phase 4에서 자동 생성된 것 확인 또는 수동 작성)
  -- status: active, progress: "시작"

Step 3: Branch 생성
  -- git checkout -b fix/{issue}

Step 4: Action Plan 수행 (오류 수정)
  -- 소스 코드 수정
  -- 테스트 추가/수정

Step 5: 테스트 실행
  -- pytest tests/ -v (Tier 1)
  -- python3 evidence/runner.py --scenario-filter {관련 시나리오} (Tier 2)
  -- python3 evidence/log_analyzer.py --run latest (로그 분석)

Step 6: 통과 시 PR 생성
  -- git commit
  -- gh pr create --title "fix: {issue}" --body "..."
  -- action-plans/fix-{issue}.md → status: done

Step 7: 실패 시
  -- action-plans/fix-{issue}.md 에 실패 원인 기록
  -- 재시도 또는 approach 변경
```

#### 5.3.2 Ralph Loop Automation (Stage 2: 사람이 검증 후 자동화)

Manual loop가 3회 이상 성공적으로 완료된 후, 동일 패턴을 자동화:

```bash
#!/bin/bash
# evidence/ralph-loop.sh
# 사전 조건: manual loop가 3+ 회 성공
set -euo pipefail

MAX_ITERATIONS=5
PROGRESS_FILE="evidence/progress.txt"
PLUGIN_DIR="$(pwd)"

# Git cleanliness check (Gemini 지적 반영)
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree is dirty. Commit or stash changes first." >> "$PROGRESS_FILE"
  exit 1
fi

for i in $(seq 1 $MAX_ITERATIONS); do
  echo "=== Iteration $i ($(date -Iseconds)) ===" >> "$PROGRESS_FILE"

  # 1. 최우선 실패 요구사항 선택
  FAILING=$(python3 evidence/pick_failing.py)
  [ -z "$FAILING" ] && echo "ALL PASS -- loop complete" >> "$PROGRESS_FILE" && exit 0

  # 2. Action plan 자동 생성 (Phase 4 pipeline)
  python3 evidence/generate_action_plan.py --requirement "$FAILING"

  # 3. Branch 생성 (clean main에서)
  BRANCH="fix/${FAILING}-auto-${i}"
  git checkout -b "$BRANCH" main

  # 4. Fresh context로 수정 시도
  #    Scope bounding: 수정 범위를 해당 requirement 관련 파일로 제한 (Gemini 지적 반영)
  RELATED_FILES=$(python3 evidence/get_related_files.py --requirement "$FAILING")
  claude -p "$(cat <<EOF
Read the action plan at action-plans/fix-${FAILING}.md.
Read the failing test evidence at evidence/runs/latest/.
Fix the issue. You may ONLY modify these files: ${RELATED_FILES}
Run tests to verify your changes.
EOF
)" \
    --permission-mode auto \
    --plugin-dir "$PLUGIN_DIR" \
    2> "evidence/runs/fix-attempt-${i}-stderr.txt"

  # 5. Quality gates
  # 5a. Compile check
  for f in hooks/scripts/memory_*.py; do python3 -m py_compile "$f"; done
  COMPILE_EXIT=$?

  # 5b. Full test suite (must not regress)
  pytest tests/ -v --timeout=30
  PYTEST_EXIT=$?

  # 5c. Targeted scenario
  python3 evidence/runner.py --scenario-filter "$FAILING"
  RUNNER_EXIT=$?

  # 5d. Log analysis
  python3 evidence/log_analyzer.py --run latest
  ANALYZER_EXIT=$?

  # 5e. Verify the targeted requirement flipped to PASS
  python3 evidence/coverage_report.py --check-requirement "$FAILING"
  COVERAGE_EXIT=$?

  # 6. 판정: ALL gates must pass
  if [ $COMPILE_EXIT -eq 0 ] && [ $PYTEST_EXIT -eq 0 ] && \
     [ $RUNNER_EXIT -eq 0 ] && [ $ANALYZER_EXIT -eq 0 ] && \
     [ $COVERAGE_EXIT -eq 0 ]; then
    git add -A
    git commit -m "fix: $FAILING (auto-fix iteration $i)"
    gh pr create \
      --title "fix: $FAILING" \
      --body "Auto-generated fix from CFL ralph loop iteration $i.
Requirement: $FAILING
Quality gates: compile OK, pytest OK, scenario OK, log analysis OK, coverage check OK"
    echo "SUCCESS: $FAILING fixed in iteration $i" >> "$PROGRESS_FILE"
  else
    git checkout main
    git branch -D "$BRANCH"
    echo "FAIL: $FAILING attempt $i -- compile=$COMPILE_EXIT pytest=$PYTEST_EXIT runner=$RUNNER_EXIT analyzer=$ANALYZER_EXIT coverage=$COVERAGE_EXIT" >> "$PROGRESS_FILE"
  fi

  echo "" >> "$PROGRESS_FILE"
done
```

#### 5.3.3 Safety Constraints

1. **Never auto-merge**: PR만 생성, merge는 사람이 리뷰 후
2. **Never modify global plugin**: 항상 `--plugin-dir .` (레포 내 소스만 수정)
3. **Compile check**: 모든 수정 후 `python3 -m py_compile` 필수
4. **Test regression**: 기존 테스트가 깨지면 즉시 discard
5. **Cost cap**: 1 iteration당 최대 $5, 전체 loop 최대 $25
6. **Single-concern**: 한 번에 하나의 요구사항만 수정
7. **Scope bounding**: 수정 가능한 파일을 해당 requirement 관련 파일로 제한 (Gemini 지적)
8. **Git cleanliness**: dirty working tree에서는 실행 거부
9. **Targeted verification**: 대상 requirement가 실제로 PASS로 전환되었는지 확인
10. **Progress log**: 모든 시도를 `evidence/progress.txt`에 기록 (학습 누적)

#### 5.3.4 Stage Gate: Manual to Automated

자동화 전환 기준:

- [ ] Manual loop를 3회 이상 성공적으로 완료
- [ ] 각 manual loop에서 action plan -> fix -> test -> PR 프로세스 검증
- [ ] Ralph loop의 prompt가 충분히 구체적 (manual에서 패턴 추출)
- [ ] Cost estimation이 ROI 양호 ($16/loop vs 수동 1시간)
- [ ] Edge case: ralph loop가 무한 반복하지 않는 것 확인 (MAX_ITERATIONS + dampening)
- [ ] Scope bounding이 효과적 (수정이 관련 파일에 국한)

### 5.4 Acceptance Criteria

1. Manual loop protocol이 문서화되어 있고 1회 이상 성공적으로 실행됨
2. Manual loop에서 생성된 action plan -> branch -> test -> PR 흐름이 검증됨
3. `evidence/progress.txt`에 모든 시도가 기록됨
4. Ralph loop가 dirty working tree를 거부함
5. Ralph loop가 scope-bounded 수정만 수행함
6. Ralph loop가 targeted requirement의 PASS 전환을 검증함
7. Safety constraints가 모두 적용됨 (auto-merge 없음, global plugin 수정 없음)
8. 3회 manual 성공 후에만 자동화 전환 가능

### 5.5 Dependencies

- Phase 3의 커버리지 리포트 + residual risk register (FAIL 요구사항 식별)
- Phase 4의 gap-to-action pipeline (action plan 생성)
- Phase 2의 runner (자동 수정 후 검증)
- Phase 3의 log analyzer (수정 후 로그 분석)
- Manual loop 3회 성공 (자동화 전환 사전 조건)

---

## Cross-Phase Architecture

### File Structure

```
evidence/                           # CFL 루트
  bootstrap.py                      # 환경 구성 (composite plugin dir, workspace)
  runner.py                         # Phase 2: 메인 러너
  log_analyzer.py                   # Phase 3: 자동 로그 분석
  coverage_report.py                # Phase 3: 커버리지 리포트 생성
  pick_failing.py                   # Phase 5: 실패 요구사항 선택
  generate_action_plan.py           # Phase 4: action plan 자동 생성
  get_related_files.py              # Phase 5: requirement -> 관련 파일 매핑
  ralph-loop.sh                     # Phase 5 Stage 2: 자동화 루프
  progress.txt                      # 학습 로그 (append-only)
  manual-checklist.md               # Track B: 수동 TUI 검증 체크리스트

  guardian-ref/                     # Guardian pinned copy (self-contained)
    VERSION                         # Guardian 버전 기록
    .claude-plugin/plugin.json
    hooks/hooks.json
    hooks/scripts/...

  scenarios/                        # Phase 1: 시나리오 정의
    SCN-RET-001.json
    SCN-CAP-001.json
    SCN-UX-001.json
    SCN-GRD-001.json
    SCN-SAVE-001.json
    SCN-META-001.json               # Meta-validation: known-bad must fail

  fixtures/                         # 테스트용 메모리 파일
    decision-sample.json
    constraint-sample.json

  requirements/                     # Phase 3: 요구사항 추적
    requirements.json
    coverage-report.json
    gap-analysis.json
    residual-risks.json             # 솔직한 한계 목록

  runs/                             # Phase 2: 실행 결과
    run-{timestamp}-{scenario}/
      stdout.txt                    # ANSI-stripped
      stderr.txt                    # ANSI-stripped
      stdout-raw.txt                # raw (script -e 캡처)
      output.json                   # stream-json
      logs/memory-events.jsonl
      workspace/.claude/memory/
      metadata.json

  manual/                           # Track B: 수동 캡처
    {date}/
      screenshots/
      asciinema/
      observations.md

  schemas/                          # Phase 1: JSON 스키마
    evidence.schema.json
    scenario.schema.json
```

### Implementation Priority

```
Week 1: Phase 1 + Phase 2 spike
  - Evidence schema 정의
  - 3개 시나리오 작성
  - SPIKE: --plugin-dir 반복 가능 여부 확인
  - SPIKE: Guardian + Memory 동시 로드 확인
  - Guardian pinned copy 준비 (evidence/guardian-ref/)
  - Minimal runner (1개 시나리오)
  - Manual checklist 초안

Week 2: Phase 2 완성 + Phase 3 시작
  - Runner 5개 + 1 meta-validation 시나리오 지원
  - ANSI-stripped 캡처 구현 (script -e)
  - Log analyzer 기본 구현 (plaintext regex, ANSI 파싱 없음)
  - Requirement markers 추가 시작
  - requirements.json 초안

Week 3: Phase 3 완성 + Phase 4
  - 모든 기존 테스트에 requirement markers 추가
  - 엣지케이스 테스트 추가
  - Coverage report 생성 (Tier 1 즉시 + Tier 2 캐시)
  - Residual risk register 작성
  - Gap-to-action-plan pipeline 구현

Week 4: Phase 5 Manual Loop
  - Manual loop 1회차 실행
  - Progress log 시작
  - 프로세스 검증

Week 5+: Phase 5 반복 + 자동화 판단
  - Manual loop 2-3회차
  - 패턴 추출 → ralph loop 구현
  - 자동화 전환 판단
```

### Risk Matrix (v2 + Cross-Model Validation)

| # | Risk | Severity | Phase | Mitigation |
|---|------|----------|-------|------------|
| 1 | **TUI 팝업 자동 검증 불가** (Codex + Gemini 지적) | CRITICAL | 1 | Track B 수동 검증 + existing popup regression tests. 한계를 솔직히 인정. |
| 2 | **Self-contained 주장 vs Guardian 의존** (Codex + Gemini 지적) | HIGH | 2 | Composite plugin dir + Guardian pinned copy. 전역 상태 의존 제거. |
| 3 | **ANSI screen-scraping 불안정** (Gemini 지적) | HIGH | 3 | ANSI 파싱 포기. Strip 후 plaintext regex만 사용. stream-json이 주 소스. |
| 4 | **Auto-fix가 global plugin 수정** | CRITICAL | 5 | --plugin-dir . 만 사용. PR만 생성, auto-merge 절대 금지. |
| 5 | **Phase 3/4 순환 의존** (Codex 지적) | HIGH | 3-4 | Phase 3으로 통합. Markers를 먼저 도입. |
| 6 | **script(1)이 child exit code 숨김** (Codex 지적) | MEDIUM | 2 | `script -e` 사용. child/wrapper exit code 분리 기록. |
| 7 | **Ralph loop workspace dirty** (Gemini 지적) | MEDIUM | 5 | `git status --porcelain` 사전 검증. Dirty 시 거부. |
| 8 | **커버리지 100% 허위 주장** (Codex 지적) | MEDIUM | 3 | Residual risk register 유지. "알려진 미커버" 솔직히 기록. |
| 9 | **Ralph loop 무한 반복** | MEDIUM | 5 | MAX_ITERATIONS=5 + scope bounding + manual 3회 성공 후에만. |
| 10 | **자가 오염** (테스트 프롬프트가 triage 트리거) | HIGH | 2 | Per-run 격리 + 비대상 훅 config 비활성화. |
| 11 | **E2E 비용** | LOW | 2-5 | 시나리오 수 제한 + on-demand 실행. |
| 12 | **venv 경로 이탈** | MEDIUM | 2 | symlink 또는 시스템 pydantic. |
| 13 | **Coverage report latency** (Gemini 지적) | MEDIUM | 3 | Tier 1 즉시 + Tier 2 캐시. 독립 실행 가능. |

---

## Cross-Model Validation Summary

### Codex 5.3 Review (Adversarial)

**Critical findings incorporated:**
1. TUI popup verification is impossible in `claude -p` -> added dual-track (Track A automated + Track B manual)
2. Self-contained claim is overstated when depending on global Guardian -> added composite plugin dir + pinned copy
3. Phase 3/4 circular dependency -> merged into single Phase 3 with markers-first approach
4. `script(1)` hides child exit code -> added `script -e` flag
5. Plugin set isolation undefined -> added plugin_set_match assertion in evidence schema
6. Overclaiming coverage -> added residual risk register
7. Existing `test_regression_popups.py` and `memory_log_analyzer.py` should be reused -> acknowledged

**Codex positive assessment preserved:**
- Existing popup-regression suite already embeds Guardian patterns locally (self-contained practice)
- Manual-first pipeline and append-only progress logging are well-designed

### Gemini 3.1 Pro Review (Adversarial)

**Critical findings incorporated:**
1. Screen capture vs `claude -p` contradiction -> explicit limitation acknowledgment + Track B
2. ANSI cross-referencing is hand-waving -> replaced with ANSI-strip + plaintext regex
3. Composite symlink directory for truly self-contained Guardian loading
4. Ralph loop state corruption -> git cleanliness check + scope bounding
5. Coverage report latency -> decoupled Tier 1/2 reporting with caching

**Gemini positive assessment preserved:**
- Manual-First Pipeline (Phase 5) is a "superb maturity model"
- Append-only progress logging is "highly resilient agentic pattern"
- Requirement traceability mapping is "excellent enterprise-grade testing practice"

---

## Guardian Co-Installation Hazards (Thinkdeep Analysis)

Vibe-check 단계에서 실제 Guardian 코드베이스를 분석한 결과, 4가지 추가 위험이 발견됨:

| # | Hazard | Severity | Mitigation |
|---|--------|----------|------------|
| 1 | **Guardian가 memory-drafter의 /tmp staging 쓰기를 차단** -- Guardian의 PreToolUse:Write hook이 /tmp 경로 Write를 거부할 수 있음 | HIGH | Guardian config에 `allowedExternalWritePaths` 설정으로 staging 경로 허용 |
| 2 | **Guardian Stop auto-commit과 memory triage Stop hook 경합** -- 두 플러그인 모두 Stop hook을 사용하여 race condition 가능 | HIGH | Dogfood 환경에서 Guardian auto-commit 비활성화 |
| 3 | **`.claude/memory/` 데이터가 git dirty tree 유발** -- 메모리 파일이 git tracked이면 ralph loop의 `git status --porcelain` 검증 실패 | MEDIUM | `.gitignore`에 `.claude/memory/` 추가 (테스트 워크스페이스에서) |
| 4 | **두 플러그인이 동일 Write tool call에 PreToolUse 동시 발화** -- 병렬 평가로 인한 잠재적 간섭 | LOW | 실제 문제 없음 -- 병렬 평가이며 각각 다른 것을 검사. 모두 approve해야 진행. |

이 hazards는 Phase 2의 composite plugin directory 설정 시 Guardian config를 적절히 조정하여 해결한다. `evidence/guardian-ref/`의 pinned copy에 이 설정을 포함시킨다.

### --plugin-dir Decision Tree (Spike Test 결과에 따른 분기)

Week 1 spike test 결과에 따라 다음 경로 중 하나를 선택:

```
--plugin-dir 반복 가능? (claude -p --plugin-dir A --plugin-dir B)
  ├─ YES -> 직접 전달: --plugin-dir /path/to/claude-memory --plugin-dir /path/to/evidence/guardian-ref
  │         장점: 단순, symlink 불필요
  │         주의: 전역 설치 플러그인이 추가 로드되지 않는지 확인
  │
  └─ NO  -> Composite symlink directory:
            /tmp/cfl-plugins-{run_id}/
              claude-memory -> symlink to dev source
              claude-code-guardian -> symlink to evidence/guardian-ref/
            사용: --plugin-dir /tmp/cfl-plugins-{run_id}/
            주의: symlink traversal이 올바르게 동작하는지 확인

두 경우 모두:
  - Plugin set assertion 필수 (예상 세트와 실제 로드 세트 일치 검증)
  - 전역 설치 플러그인이 간섭하지 않는지 확인
  - 실패 시: Guardian 테스트를 별도 실행으로 분리 (fallback of last resort)
```

---

## Key Design Decisions Summary

1. **Self-contained**: Composite plugin directory + Guardian pinned copy. 전역 상태 의존 없음.
2. **Dual-track evidence**: Track A (automated CLI capture) + Track B (manual TUI capture). 한계를 솔직히 인정.
3. **Recursive self-installation**: 자신을 플러그인으로 설치하여 실제 동작 검증.
4. **Guardian co-testing**: Detect + mitigate (이 레포 범위). Fix는 Guardian repo 범위.
5. **Manual first**: 자동화 전에 사람이 프로세스를 검증. 3회 성공 후 자동화.
6. **Deterministic coverage + residual risks**: 달성 가능한 커버리지는 100%, 나머지는 솔직히 기록.
7. **Automated log analysis**: ANSI 파싱 없이, plaintext regex + structured JSONL. stream-json이 주 소스.
8. **Log-stderr cross-reference**: 로그에 없지만 stderr에 보이는 것을 자동 감지 (간소화된 방식).
9. **Scope-bounded auto-fix**: Ralph loop에서 수정 가능한 파일을 requirement 관련 파일로 제한.
10. **Meta-validation**: Known-bad build가 FAIL 판정을 받는지 검증하여 러너 자체의 신뢰성 보장.
