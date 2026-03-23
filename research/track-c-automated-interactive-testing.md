# Track C: Automated Interactive Testing for claude-memory

**Research Document** | Date: 2026-03-22 | Status: Complete (v2, 실제 구현 + 결과 반영)
**Purpose**: CFL Phase 1 보완 — interactive Claude 세션 자동화를 통한 TUI 증거 수집 가능성 조사
**Supersedes**: 없음 (CFL v2의 Track A/B를 보완하는 새 트랙)

> **v2 Update (2026-03-22)**: Track C를 실제로 구축하고 실행한 결과, **novel finding 2건**을 발견. R2의 "DON'T BUILD" 판정은 잘못된 것으로 판명됨 — TUI-only 버그가 실존했다. Section 10에 실제 결과 추가.

---

## 1. Core Question & Answer

**질문**: claude-memory와 guardian이 설치된 환경에서 interactive Claude 세션을 자동화하여 팝업, permission dialog 등 TUI 요소를 증거로 수집할 수 있는가?

**답**: **기술적으로 가능하다.** tmux를 harness로 사용하면 된다. 하지만 **현재 시점에서 구축할 가치가 있는지는 의문**이다.

---

## 2. Feasibility: 실증 확인 (PROVEN)

### 2.1 핵심 발견

WSL2 (Linux 6.6.87.2, tmux 3.4)에서 실제 테스트 수행:

- `tmux capture-pane -p -J`: Claude Code TUI를 ANSI-free plaintext로 완벽 캡처
- `tmux pipe-pane`: 모든 출력 (transient 포함) 연속 기록
- `tmux send-keys`: 키 입력 주입 + dialog 응답 자동화 가능
- **Claude Code는 alternate screen 미사용** → `capture-pane -p` 단독 충분
- Korean/Unicode 완벽 보존
- WSL2 특유의 제한: **해당 use case에서 없음**

### 2.2 캡처된 실제 TUI

```
 ▐▛███▜▌   Claude Code v2.1.81
▝▜█████▛▘  Opus 4.6 (1M context) with high effort · Claude Max
  ▘▘ ▝▝    ~/projects/claude-memory

❯ echo hello

● Bash(echo hello)
  ⎿  hello

✶ Flummoxing…       ← TRANSIENT (pipe-pane에서만 캡처)
```

### 2.3 탐지 가능한 TUI 패턴

| 요소 | 패턴 | capture-pane | pipe-pane |
|------|------|:---:|:---:|
| 프롬프트 (idle) | `❯ ` | YES | YES |
| 도구 호출 | `● Bash(echo hello)` | YES | YES |
| 도구 출력 | `⎿  hello` | YES | YES |
| 사고 중 | `✶ Flummoxing…` | TRANSIENT | YES |
| Hook progress | `Evaluating session...` | TRANSIENT | YES |
| 모델/상태 | `Opus 4.6 │ 2.4% │ [main]` | YES | YES |
| Permission dialog | 미검증 (별도 카탈로깅 필요) | 예상: YES | 예상: YES |

---

## 3. Proposed Architecture (v0 — If Built)

### 3.1 접근: tmux-first, pexpect-ready

3개 모델 (Opus 4.6, Codex 5.3, Gemini 3.1 Pro) 교차 검증 결과:

| 관점 | Codex | Gemini | Opus (종합) |
|------|-------|--------|-------------|
| 추천 도구 | tmux (좁은 범위) | pexpect (tmux 포기) | tmux for v0 |
| 핵심 우려 | 과설계, 범위 | 폴링 오버헤드, `❯` spoofing | 실용성 |

**tmux 선택 이유**: 이미 설치됨, WSL 검증 완료, `capture-pane -p -J`가 ANSI 파싱 제거, 시각 디버깅(`tmux attach`) 가능.

**pexpect 마이그레이션 트리거**: idle spoofing 3회 이상, flaky 테스트 3건 이상, 시나리오 10개 초과 시.

### 3.2 핵심 구성요소

```
evidence/track-c/
  smoke.py           # 전체 러너 (~200줄, 1 파일)
  runs/              # 실행 결과
    run-{ts}/
      metadata.json  # 시나리오, 시간, verdict
      snapshots/     # capture-pane 스냅샷
      pipe-pane.raw  # 연속 로그
```

### 3.3 v0 시나리오 (3개)

| ID | 검증 대상 | 기존 테스트와 중복? |
|----|-----------|:---:|
| SCN-TC-RET-001 | Retrieval hook이 interactive에서 fire | 부분적 (subprocess 수준은 커버됨) |
| SCN-TC-UX-001 | `--permission-mode auto`에서 팝업 없음 | 예 (test_regression_popups.py) |
| SCN-TC-META-001 | Runner self-test | N/A (harness 검증) |

### 3.4 기술적 수정사항 (R1 blockers)

**BLOCKER 1 — Idle detection**: `len(last) < 5` → 정확한 매칭으로 교체
```python
def _is_idle(self, screen: str) -> bool:
    lines = [l for l in screen.splitlines() if l.strip()]
    if not lines:
        return False
    last = lines[-1].strip()
    return re.fullmatch(r"❯\s*", last) is not None
```
추가 고려: cursor show signal (`\x1b[?25h`)을 pipe-pane에서 감지하면 더 안정적 (Gemini 제안).

**BLOCKER 2 — Process cleanup**: `os.killpg()` → `tmux send-keys C-c`
```python
def cleanup_session(session_name: str):
    subprocess.run(["tmux", "send-keys", "-t", session_name, "C-c"])
    time.sleep(1)
    subprocess.run(["tmux", "send-keys", "-t", session_name, "/exit", "Enter"])
    # 폴링 후 kill-session
    for _ in range(10):
        r = subprocess.run(["tmux", "has-session", "-t", session_name],
                          capture_output=True)
        if r.returncode != 0:
            return  # 세션 이미 종료
        time.sleep(1)
    subprocess.run(["tmux", "kill-session", "-t", session_name])
```

### 3.5 HOME 격리

```python
import tempfile, shutil
def create_isolated_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="cfl-home-"))
    os.chmod(home, 0o700)
    mock_claude = home / ".claude"
    mock_claude.mkdir(mode=0o700)
    # 인증 파일만 복사 (symlink 아님)
    for src in [Path.home() / ".claude.json",          # 최상위 auth metadata
                Path.home() / ".claude" / "claude.json",
                Path.home() / ".claude" / "credentials.json"]:
        if src.exists():
            dst = (home / ".claude.json") if src.name == "claude.json" and src.parent == Path.home() else (mock_claude / src.name)
            shutil.copy2(src, dst)
            os.chmod(dst, 0o600)
    return home
```

**필수**: Claude 실행 시 `--plugin-dir`로 플러그인 경로 명시 (격리 HOME에서는 플러그인 자동 탐색 불가).

### 3.6 Track A / B / C 역할 분담

```
검증 필요한 것이 TUI/dialog 관련인가?
  ├─ NO → Track A (claude -p, 빠르고 결정적)
  └─ YES
       ├─ 프로그래밍으로 트리거 가능? → YES → Track C (tmux)
       └─ NO 또는 시각적 충실도 필요 → Track B (수동)
```

---

## 4. Adversarial Analysis: Why NOT to Build (R2)

R2 검증자가 **DON'T BUILD** 판정을 내렸다. 핵심 논거:

### 4.1 [CRITICAL] "Closed Loop"는 여전히 열려있다

Track C는 세 번째 partial view를 추가할 뿐이다:
- Track A: CLI output (TUI 없음)
- Track B: TUI 시각 관찰 (자동화 없음)
- Track C: TUI의 plaintext 근사치 (실제 렌더링이 아님)

Track C는 색상, 레이아웃, 겹치는 패널, transient 타이밍을 검증하지 못한다. 루프는 닫히지 않았고, 관리할 partial view가 하나 더 늘었을 뿐이다.

### 4.2 [CRITICAL] Self-referential paradox

Track C는 플러그인 자체 레포 안에서 테스트한다. 실제 버그는 **소비자 레포**에서 발생한다:
- 다른 CLAUDE.md, 다른 hooks, 다른 파일 구조
- "플러그인 레포에서 동작하지만 사용자 레포에서 깨지는" 버그를 찾을 수 없다
- CFL v2 Risk #17이 이미 경고: ALL PASS가 "버그 없음"인지 "시나리오 부족"인지 구별 불가

### 4.3 [HIGH] Maintenance tax > bug-finding value

- Claude Code TUI가 업데이트될 때마다 harness가 깨질 수 있다
- 깨진 시나리오가 플러그인 버그인지 TUI 변경인지 **수동으로 판별해야** 한다
- 월간 2-4시간 유지보수 추정 → 실제 기능 개발 시간 감소

### 4.4 [HIGH] 기존 커버리지와 중복

3개 v0 시나리오 중 2개는 기존 1232개 pytest 테스트가 이미 커버:
- Retrieval hook fire → `test_memory_retrieve.py`에서 subprocess 수준 테스트
- Popup 없음 → `test_regression_popups.py`에서 37+ 회귀 테스트
- 나머지 1개는 harness 자체 검증 (플러그인 테스트가 아님)

### 4.5 [HIGH] 보안 우려

- `/tmp`에 인증 토큰 복사 → 권한 설정 필수 (`0700`/`0600`)
- `--permission-mode auto` + 자동 프롬프트 → unsandboxed RCE 위험 (CFL v2 Risk #14)
- pipe-pane 로그에 민감 정보 포함 가능 → `.gitignore`에 `evidence/` 추가 필수
- 크래시 시 `/tmp`에 인증 토큰 잔존

### 4.6 The Kill Question

> **"interactive TUI 모드에서만 발현되고, 기존 1232개 테스트가 놓치는 버그를 실제로 경험한 적이 있는가?"**
>
> 답이 "예"라면 Track C가 정당화된다. 답이 "아니오"라면 이것은 premature optimization이다.

---

## 5. Cross-Model Consensus (전체)

### 5.1 5-Phase 검증 이력

| Phase | 참여자 | 주요 결론 |
|-------|--------|-----------|
| Phase 1: Architecture | architect + codex + gemini | tmux feasible, prompt idle, HOME 격리, `-J` flag |
| Phase 1: Feasibility | feasibility + codex + gemini | FEASIBLE, tmux-only, alt screen 미사용 실증 |
| Phase 2: Synthesis | team-lead + codex + gemini | tmux-first, `❯` spoofing 완화, v0 scope 축소 |
| Phase 2: WSL | wsl-research | NO BLOCKERS |
| Phase 3: R1 Technical | verify-r1 + codex + gemini | PROCEED WITH FIXES, 2 blocker |
| Phase 3: R2 Adversarial | verify-r2 + codex + gemini | DON'T BUILD |

### 5.2 전 모델 합의 사항

1. tmux `capture-pane -p -J`는 기술적으로 동작한다
2. HOME 격리가 필수이다 (symlink 아닌 복사)
3. Process group cleanup에 job control 고려 필요
4. Claude Code TUI는 안정적 API가 아니다 (버전 취약)
5. v0라도 보안 기본기 필수 (chmod, gitignore)

### 5.3 미해결 분기점

| 주제 | R1 입장 | R2 입장 | 해결 |
|------|---------|---------|------|
| Build 여부 | PROCEED WITH FIXES | DON'T BUILD | **사용자 판단** (Section 6) |
| tmux vs pexpect | tmux sufficient | 중립 | tmux for v0 (if built) |
| 보안 위험 수준 | 완화 가능 | Non-trivial | 구축 시 반드시 완화 |

---

## 6. Recommendation

### 6.1 ~~현재 권장: 구축하지 않는다~~ → **실제 결과: 구축하여 novel finding 2건 발견**

R2의 핵심 논거는 설득력이 있었으나, **실제 실행 결과가 뒤집었다**:
- ~~기존 1232개 테스트가 이미 강력하다~~ → S5가 contract drift를 감지 (기존 테스트 미탐지)
- ~~3개 시나리오의 marginal 정보 이득이 유지보수 비용을 정당화하지 못한다~~ → S2가 cross-plugin 호환성 문제를 감지 (TUI 전용)
- ~~TUI-only 버그의 문서화된 이력이 없다~~ → **Novel Finding #2가 TUI 전용** (Guardian path blocking은 `claude -p` stream-json에서 관찰 불가)

**결론: Track C 유지. S2/S5 활성, S1/S3/S4 퇴역 (pytest 충분).**

### 6.2 구축 트리거 조건

다음 중 하나라도 발생하면 Track C 구축을 재고한다:

1. **TUI-only 버그 발생**: interactive 모드에서만 재현되고 기존 테스트가 놓치는 버그를 실제로 경험
2. **소비자 레포 테스트 필요**: 별도 fixture 프로젝트에서 설치 → 사용 시나리오 검증 필요성 대두
3. **CI/CD 통합**: 자동화된 릴리스 파이프라인에서 interactive smoke test가 필요

### 6.3 구축 시 필수 선행조건

Track C를 구축하기로 결정한다면:

1. R1 blocker 2건 수정 (idle 정확 매칭 + C-c cleanup)
2. `.gitignore`에 `evidence/track-c/runs/` 추가
3. HOME 격리에 `tempfile.mkdtemp()` + `chmod 0700` 사용
4. `--permission-mode auto` 대신 `--permission-mode default` + 명시적 dialog 응답 고려
5. Permission dialog 패턴 수동 카탈로깅 (1회 관찰 세션)
6. **별도 fixture 프로젝트**에서 실행하여 self-referential paradox 완화

---

## 7. Risk Matrix

| # | 리스크 | 심각도 | 상태 |
|---|--------|--------|------|
| 1 | "Closed loop" 여전히 열림 | CRITICAL | 인정. Track C는 closure가 아닌 coverage 확장. |
| 2 | Self-referential paradox | CRITICAL | 완화: fixture 프로젝트에서 실행 (구축 시). |
| 3 | `❯` spoofing by LLM output | HIGH | 완화: regex 정확 매칭 + pipe-pane cursor signal. |
| 4 | Claude TUI 버전 취약 | HIGH | 완화: version gate. 근본 해결 불가. |
| 5 | Maintenance tax | HIGH | 완화: v0를 200줄 이하로 유지. |
| 6 | /tmp 인증 토큰 노출 | HIGH | 완화: mkdtemp + chmod 0700/0600. |
| 7 | pipe-pane 민감 데이터 | HIGH | 완화: .gitignore + 보존 기간 정책. |
| 8 | --permission-mode auto RCE | HIGH | 완화: default mode + 명시적 응답. |
| 9 | Transient TUI 누락 (snapshots) | MEDIUM | pipe-pane이 보완. |
| 10 | 범위 확대 (scope creep) | MEDIUM | v0 → 200줄, 3 시나리오 하드 캡. |

---

## 8. Verification Summary

**R1 (Technical)**: PROCEED WITH FIXES — 2 BLOCKER, 4 HIGH, 4 MEDIUM, 2 LOW
- 설계는 건전. idle 탐지와 프로세스 정리에 구현 수준 버그.
- `temp/track-c-verify-r1.md`

**R2 (Adversarial)**: DON'T BUILD — 2 CRITICAL, 5 HIGH, 3 MEDIUM, 1 LOW
- 문제가 존재하는지 증명되지 않았다. 유지보수 비용 > 발견 가치.
- `temp/track-c-verify-r2.md`

**합성**: R1과 R2의 긴장은 의도된 것. "할 수 있는가" (R1: 예)와 "해야 하는가" (R2: 아니오)는 다른 질문이다.

---

## 9. References

### Source Files

| 파일 | 역할 |
|------|------|
| `temp/track-c-context.md` | 연구 범위/프로토콜 |
| `temp/track-c-architecture.md` | 아키텍처 상세 설계 (~1040 lines) |
| `temp/track-c-feasibility.md` | 실증 테스트 결과 |
| `temp/track-c-wsl-check.md` | WSL2 호환성 검증 |
| `temp/track-c-draft-v1.md` | 종합 초안 (v1) |
| `temp/track-c-verify-r1.md` | R1 기술 검증 |
| `temp/track-c-verify-r2.md` | R2 반론 검증 |

### Related

- `research/closed-feedback-loop.md` — CFL 전체 문서 (Track A/B 설계)
- `action-plans/_ref/TEST-PLAN.md` — 보안 테스트 요구사항

### Cross-Model Participants

| 모델 | 역할 | 참여 단계 |
|------|------|-----------|
| Opus 4.6 | 종합, 합성, vibe check | 전체 |
| Codex 5.3 | 기술 검증 (실증 probe 포함) | Architecture, Synthesis, R1, R2 |
| Gemini 3.1 Pro | 반론, 보안 분석 | Architecture, Feasibility, Synthesis, R1, R2 |

---

## 10. Actual Results (v2 — Post-Implementation)

### 10.1 Implementation Summary

Track C를 실제로 구축하고 5개 시나리오를 모두 실행함.

| Phase | 내용 | 결과 |
|-------|------|------|
| Phase 0 | S1/S3/S4/S5 pytest + stream-json | 37/37 PASS, Novel Finding #1 |
| Phase 1 | Docker Desktop WSL2 Integration | ✓ (hello-world, Compose v5.1.0) |
| Phase 2 | Docker 이미지 빌드 + 플러그인 마운트 | ✓ (OAuth 인증, 두 플러그인 동시 로딩) |
| Phase 3 | S2 Docker + tmux TUI 테스트 | ✓ Novel Finding #2 |
| Phase 4 | 평가 + 결정 | Track C 유지 (S2/S5 활성) |

### 10.2 Novel Findings

**Finding #1 — S5 Contract Drift (Phase 0)**:
- Claude Code v2.1.81에서 `--output-format stream-json`을 `-p`와 사용 시 `--verbose` 플래그 필수
- 이전 버전에서는 불필요했음
- S5가 설계 목적대로 contract drift를 감지한 첫 실제 사례
- pytest로 재현 가능 → test_contract_drift.py에 반영됨

**Finding #2 — S2 Guardian↔Memory Cross-Plugin Compatibility (Phase 3)**:
- Guardian의 PreToolUse:Read hook이 project 외부 경로 읽기 차단 → memory retrieval 실패
- Guardian의 PreToolUse:Write hook이 `/tmp/` 쓰기 차단 → memory write temp file 실패
- Claude가 적응하여 project 내부 `.claude/memory/`에 쓰기 시도
- **TUI 관찰 없이는 발견 불가능** — `claude -p` stream-json은 이 상호작용을 노출하지 않음
- pytest 단독 재현 불가 (두 플러그인 동시 로딩 + interactive TUI 필요)

### 10.3 R2 "DON'T BUILD" 판정 재평가

| R2 논거 | 실제 결과 | 판정 |
|---------|----------|------|
| "TUI-only 버그의 문서화된 이력 없음" | Finding #2가 TUI-only (stream-json에서 관찰 불가) | **R2 오류** |
| "기존 1232개 테스트가 충분" | S5가 contract drift 감지 (기존 테스트 미탐지) | **R2 오류** |
| "3개 시나리오의 marginal 이득 < 유지보수 비용" | 2/5 시나리오에서 novel finding → 40% hit rate | **R2 과소평가** |
| "Self-referential paradox" | Docker sandbox + fresh project로 완화됨 | **R2 valid but mitigated** |
| "Maintenance tax" | v0 bash 스크립트 (~100줄) + Dockerfile, 유지보수 최소 | **R2 과대평가** |

**v2.1 Update (R1+R2 최종 검증 후 수정)**: R2 반론이 Finding #2를 configuration artifact로 재분류. Kill Question의 답은 **"아직 아니오"** — Finding #2는 known risk의 재확인이지 novel TUI-only bug이 아님. 상세: `temp/track-c-synthesis-final.md`.

### 10.4 최종 결정 (R1+R2 검증 후 수정)

**Track C 전체 휴면 (dormant):**
- **S5**: pytest에 완전 흡수됨. Track C 시나리오로서 퇴역.
- **S2**: R2 반론 수용 — Finding #2는 configuration artifact. 정기 실행 취소.
- **S1/S3/S4**: Novel finding 0건. 이전에 퇴역됨.
- **Docker 인프라**: 보존 (Dockerfile + run-s2-test.sh + docker-memory-config.json). 삭제 안 함.
- **재활성 조건**: (1) 사용자 TUI-only 버그 보고, (2) Guardian/memory 대규모 변경, (3) Claude Code TUI 구조 변경.

### 10.5 교훈

1. **테스트 환경 ≠ 실환경**: Docker에서 Guardian default config 사용 → 인위적 발견. 실환경 일치가 필수.
2. **Known risk 재발견 ≠ Novel finding**: CFL 연구에 문서화된 내용을 재확인한 것일 뿐.
3. **R2 반론 검증의 가치**: 확인 편향을 방지. R2가 없었다면 불필요한 분기별 유지보수가 시작되었을 것.
4. **인프라 가치**: Docker + tmux + TUI 캡처 레시피가 검증됨 — 필요할 때 즉시 재사용 가능.
5. **stream-json vs TUI 구분**: blocking event는 stream-json 감지 가능. 적응 행동만 TUI-only. 명확히 구분할 것.

### 10.6 검증 참조

| 검증 | 파일 | 결론 |
|------|------|------|
| R1 구조 | `temp/track-c-verify-final-r1.md` | STRUCTURALLY SOUND, Finding #2 TUI-only 정밀화 필요 |
| R2 반론 | `temp/track-c-verify-final-r2.md` | FINDINGS OVERSTATED, Finding #2는 config artifact |
| 종합 | `temp/track-c-synthesis-final.md` | R2 우세, Track C 휴면 결정 |
