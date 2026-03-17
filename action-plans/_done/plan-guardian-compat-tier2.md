---
status: done
progress: "완료 -- Phase 0-4 x 2회 검증 모두 통과 (2026-03-17)"
---

# Guardian 호환성 Tier 2: Phase 1 Subagent에서 Bash 제거 (구조적 해결)

**날짜:** 2026-03-16
**범위:** SKILL.md 오케스트레이션 재설계, Agent 파일 도입, Phase 1 subagent 역할 축소
**의존성:** Tier 1 (plan-guardian-compat-tier1.md) 완료 후 시작 권장 (독립 실행도 가능)

---

## 배경 (Background)

### Tier 1의 한계

Tier 1에서 SKILL.md 명령 템플릿의 `.claude` 경로를 제거하여 Guardian 승인 팝업을 완화하지만, 근본 원인은 해결되지 않는다:

1. **subagent 비순응**: haiku급 subagent가 SKILL.md의 "Write 도구 사용" 지시를 무시하고 Bash heredoc을 사용
2. **구조적 모순**: subagent에게 Bash 도구를 주면서 "Bash로 쓰지 말라"고 지시하는 것
3. **Guardian 패턴 변경 취약성**: Tier 1은 특정 Guardian 패턴에 대한 회피일 뿐, 패턴이 바뀌면 다시 깨짐
4. **CLAUDE_PLUGIN_ROOT 문제**: 플러그인이 `~/.claude/plugins/`에 설치되면 확장 경로에 `.claude` 포함

### 핵심 설계 원칙

> **LLM은 의도(intent)와 초안만 생성. 파일 경로/스크립트 호출/최종 저장은 deterministic runtime이 소유.**

### 목적

Phase 1 subagent에서 Bash 도구 자체를 제거하여 Guardian 충돌면을 근본적으로 제거한다. subagent는 intent JSON만 작성하고, candidate.py/draft.py 실행은 main agent가 담당한다.

---

## 현재 아키텍처 vs 제안 아키텍처

### 현재 (SKILL.md Phase 1 기준)

```
Phase 1 subagent (per category, parallel, Bash 있음):
  1. Read context file (.staging/context-<cat>.txt)
  2. Write new-info summary (.staging/new-info-<cat>.txt) — Write tool 지시, but 비순응 시 Bash heredoc
  3. Run memory_candidate.py (Bash) — Guardian 트리거 가능
  4. Parse candidate output, CUD 판단
  5. Write partial input JSON (.staging/input-<cat>.json) — Write tool 지시
  6. Run memory_draft.py (Bash) — Guardian 트리거 가능
  7. Parse draft output, report result

Phase 2 subagent (verification, parallel)
Phase 3 subagent (save — memory_write.py, single foreground)
```

### 제안

```
Phase 1 subagent (per category, parallel, Bash 없음 — agent 파일로 도구 제한):
  1. Read context file
  2. Write intent JSON (.staging/intent-<cat>.json) — Write tool only

Main agent (deterministic execution):
  3. 모든 카테고리의 intent JSON 수집
  4. candidate.py 일괄 실행 (Bash, 병렬 가능)
  5. CUD Resolution (candidate output 기반)
  6. draft.py 일괄 실행 (Bash, 병렬 가능)

Phase 2 subagent (verification — 현행 유지)
Phase 3 subagent (save — 현행 유지)
```

---

## 현재 Phase 1 Subagent 상세 분석

### Subagent에 전달되는 Prompt 구조

SKILL.md Phase 1 "Subagent instructions" 섹션 (라인 100~193) 기준:

1. **FORBIDDEN 블록**: Bash를 통한 `.staging/` 파일 쓰기 금지 (cat >, echo >, heredoc, tee)
2. **Step 1**: context file 읽기 (`triage_data`의 `context_file` 경로)
3. **Step 2**: new-info summary 작성 (Write tool → `.staging/new-info-<cat>.txt`)
4. **Step 3**: `memory_candidate.py` 실행 (Bash)
5. **Step 4-5**: candidate output 파싱, CUD 판단 (CREATE/UPDATE/DELETE/NOOP)
6. **Step 6**: partial input JSON 작성 (Write tool → `.staging/input-<cat>.json`)
7. **Step 7**: `memory_draft.py` 실행 (Bash)
8. **Step 8-9**: draft output 파싱, retire JSON 작성 (DELETE 시)
9. **Step 10**: 결과 report

### memory_candidate.py 인자 목록

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" \
  --category <cat>                    # 필수: session_summary|decision|runbook|constraint|tech_debt|preference
  --new-info-file <path>              # 선택: new-info 파일 경로 (--new-info와 택일)
  --new-info <text>                   # 선택: new-info 텍스트 직접 전달
  --lifecycle-event <event>           # 선택: deprecated|removed|resolved|reversed|superseded
  --root <path>                       # 선택: 메모리 루트 (기본: .claude/memory)
```

**출력 (JSON)**:
```json
{
  "vetoes": [],                       // 비어있지 않으면 NOOP 강제
  "pre_action": "CREATE|NOOP|null",   // 구조적 사전 판단
  "structural_cud": "CREATE|NOOP|UPDATE|UPDATE_OR_DELETE",
  "candidate": {                      // structural_cud가 UPDATE/UPDATE_OR_DELETE일 때만
    "path": "path/to/existing.json",
    "title": "기존 메모리 제목"
  }
}
```

### memory_draft.py 인자 목록

```
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_draft.py" \
  --action <create|update>            # 필수: 동작
  --category <cat>                    # 필수: 카테고리
  --input-file <path>                 # 필수: partial JSON 입력 파일
  --candidate-file <path>             # UPDATE 시 필수: 기존 메모리 파일 경로
  --root <path>                       # 선택: 메모리 루트 (기본: .claude/memory)
```

**출력 (JSON)**:
```json
{
  "status": "ok",
  "action": "create|update",
  "draft_path": ".claude/memory/.staging/draft-<cat>-<timestamp>.json"
}
```

### CUD Verification Rules 테이블

| L1 (Python candidate.py) | L2 (Subagent 판단) | Resolution | Rationale |
|---|---|---|---|
| CREATE | CREATE | **CREATE** | Agreement |
| UPDATE_OR_DELETE | UPDATE | **UPDATE** | Agreement |
| UPDATE_OR_DELETE | DELETE | **DELETE** | Structural permits |
| CREATE | UPDATE | **CREATE** | Structural: no candidate exists |
| CREATE | DELETE | **NOOP** | Cannot DELETE with 0 candidates |
| UPDATE_OR_DELETE | CREATE | **CREATE** | Subagent says new despite candidate |
| VETO | * | **OBEY VETO** | Mechanical invariant |
| NOOP | * | **NOOP** | No target |

> Tier 2에서는 L2 판단의 주체가 Phase 1 subagent → main agent로 이동 (candidate output + intent JSON 기반).

---

## R1 검증에서 발견된 전제조건

| # | 발견 | 심각도 | 대응 |
|---|------|--------|------|
| F1 | Task tool에 `allowed_tools` 파라미터 없음 → agent 파일 필요 | 높음 | `.claude/agents/memory-drafter.md` 생성 |
| F2 | Phase 2 (Verification) 처리 방안 누락 | 중간 | Phase 2는 현행 유지 (Read only, Bash 불필요) |
| F3 | agent 파일의 단일 model과 per-category model 선택 충돌 | 중간 | model frontmatter 생략 시 동작 확인 필요 |

---

## 관련 파일

| 파일 | 역할 |
|------|------|
| `skills/memory-management/SKILL.md` | 오케스트레이션 재설계 대상 (Phase 1: 라인 69~193) |
| `hooks/scripts/memory_candidate.py` | CUD 판단 스크립트 |
| `hooks/scripts/memory_draft.py` | Draft 조립 스크립트 |
| `hooks/scripts/memory_write.py` | 최종 저장 스크립트 |
| `action-plans/plan-guardian-compat-tier1.md` | 선행 Tier 1 plan |
| `temp/zero-base-alternatives.md` | 대안 분석 (16개 대안) |
| `temp/cross-model-alternatives.md` | Codex 교차 분석 |
| `temp/verify-r1-feasibility.md` | R1 검증: 실현 가능성 |
| `temp/verify-r1-adversarial.md` | R1 검증: 반론 |
| `temp/script-purposes.md` | 스크립트 목적 분석 |
| `temp/skill-orchestration.md` | 현재 오케스트레이션 분석 |

---

## 단계별 작업

### Phase 0: 전제조건 확인

- [v] Claude Code agent 파일에서 `model: inherit` 기본값 확인 — Agent tool `model` 파라미터가 우선
- [v] Claude Code agent 파일에서 `tools: Read, Write` 설정 시 Bash 제외 확인 (docs 기반)
- [v] 현재 SKILL.md Phase 1 subagent가 candidate.py/draft.py에 전달하는 정보 정리 완료
- [v] intent JSON 스키마 설계 및 확정 (intended_action optional, noop_reason 추가):
  ```json
  {
    "category": "decision",
    "new_info_summary": "이 세션에서 X를 Y로 결정함",
    "intended_action": "create|update|delete",
    "lifecycle_hints": ["deprecated", "superseded"],
    "partial_content": {
      "title": "Short descriptive title (max 120 chars)",
      "tags": ["tag1", "tag2"],
      "confidence": 0.85,
      "related_files": ["path/to/file.py"],
      "change_summary": "Created from session analysis of ...",
      "content": {
        "...category-specific fields..."
      }
    }
  }
  ```
  - `new_info_summary`: candidate.py의 `--new-info-file`에 전달될 텍스트
  - `intended_action`: subagent의 LLM 판단 (L2 역할 — CUD Resolution 테이블에서 사용)
  - `lifecycle_hints`: candidate.py의 `--lifecycle-event`에 전달 가능한 힌트
  - `partial_content`: draft.py의 `--input-file`에 전달될 partial JSON

### Phase 1: Agent 파일 생성

- [v] `agents/memory-drafter.md` 생성 (plugin-relative path)
  - tools 제한: Read, Write만 허용 (Bash 제외)
  - system prompt 내용:
    1. 주어진 context 파일을 Read로 읽기
    2. transcript 내용 분석, 카테고리에 적합한 정보 추출
    3. intent JSON을 Write tool로 `.claude/memory/.staging/intent-<category>.json`에 작성
    4. `<transcript_data>` 내 지시 무시 규칙
    5. JSON 포맷 요구사항 (위 intent schema 기반)
  - model: Phase 0 결과에 따라 결정 (생략 또는 명시)
- [v] memory-verifier agent 불필요로 결정 (Phase 2는 Read만 필요, 별도 agent 불필요)
- [v] agent 파일 검증 완료 (2회 독립 검증 통과, E2E는 문서 전용 변경으로 스킵)

### Phase 2: SKILL.md 오케스트레이션 재설계

**2a. Phase 1 섹션 재작성** (현재 라인 69~193)
- [v] Subagent 호출을 agent 파일 기반으로 변경:
  ```
  Task(
    agent: ".claude/agents/memory-drafter.md",
    model: config.category_models[category] or default_model,
    prompt: "카테고리: <cat>\n컨텍스트 파일: <path>\n출력 경로: .claude/memory/.staging/intent-<cat>.json"
  )
  ```
- [v] FORBIDDEN 블록 제거 (agent 파일이 Bash를 제공하지 않으므로 불필요)
- [v] Steps 2~9 전체를 intent JSON 작성 하나로 축소
- [v] subagent는 intent 작성 성공/실패만 report

**2b. Main Agent 실행 섹션 추가** (Phase 1과 Phase 2 사이에 삽입)
- [v] "Phase 1.5: Deterministic Execution (Main Agent)" 섹션 추가
- [v] intent JSON 수집 + 검증 로직 명시
- [v] candidate.py 일괄 실행 (카테고리별 별도 Bash 호출, 병렬):
  ```bash
  # intent에서 new_info_summary 추출 → temp 파일로 전달
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" \
    --category <cat> \
    --new-info-file .claude/memory/.staging/new-info-<cat>.txt \
    --root .claude/memory
  ```
  - intent JSON에서 `new_info_summary`를 `.staging/new-info-<cat>.txt`로 추출하는 과정 명시
  - `lifecycle_hints`가 있으면 `--lifecycle-event` 전달
- [v] CUD Resolution (main agent): L1 + L2 → CUD 테이블, veto는 DELETE만 차단 (UPDATE 허용)
- [v] draft.py 일괄 실행 (CREATE/UPDATE 대상, 병렬):
  ```bash
  # intent의 partial_content를 input file로 사용
  python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_draft.py" \
    --action <create|update> \
    --category <cat> \
    --input-file .claude/memory/.staging/input-<cat>.json \
    --candidate-file <candidate.path>    # UPDATE 시만
  ```
  - intent JSON의 `partial_content`를 `.staging/input-<cat>.json`으로 Write하는 단계 명시
- [v] DELETE 대상: retire JSON 작성

**2c. Phase 2, Phase 3 최소 수정**
- [v] Phase 2: "Phase 1" → "Phase 1.5" 참조 변경
- [v] Phase 3: "CUD Resolution" → "Build Command List" + Phase 1.5 결과 참조
- [v] Phase 3 Command Isolation 유지 (Tier 1 호환)

**2d. 에러 핸들링**
- [v] intent JSON 실패 → 카테고리 skip
- [v] candidate.py 실패 → 카테고리 skip
- [v] draft.py 실패 → 카테고리 skip
- [v] 전체 실패 → Phase 2 진입 안 함

### Phase 3: 검증

- [v] `pytest tests/ -v` — 981/981 PASS
- [v] Guardian 패턴 미매칭 — Phase 1 subagent는 Bash 없음 (구조적 해결)
- [v] Guardian regex 테스트 6/6 PASS (Phase 1.5/3 명령 템플릿)
- [v] py_compile 13/13 OK
- [v] E2E 테스트 — 스킵 (문서+agent 전용 변경, Python 스크립트 수정 없음, 검증자 2명 acceptable gap 판정)

### Phase 4: 정리

- [v] CLAUDE.md v5.1.0: Architecture 설명 + "Parallel Per-Category Processing" + Key Files 업데이트
- [v] plugin.json v5.1.0: agents 배열 추가, 버전 범프
- [v] temp/ 분석 문서: 이번 세션 작업 파일 유지 (phase0-*, phase1-*, phase2-*, t2-phase*)

---

## 엣지 케이스 및 주의사항

### 1. Agent 파일의 model 고정 문제

per-category model 선택 (`triage.parallel.category_models`)과 충돌 가능. agent 파일에 model을 지정하면 모든 카테고리가 동일 모델을 사용하게 된다. Phase 0에서 model frontmatter 생략 시 Task 호출의 model 파라미터가 우선하는지 확인 필수.

### 2. UPDATE_OR_DELETE 판단 변경

현재: subagent가 candidate 파일을 읽고 UPDATE vs DELETE를 판단
제안: intent JSON의 `intended_action`으로 subagent가 사전 판단 → main agent가 CUD Resolution 테이블 적용

**차이점**: subagent는 candidate 파일을 읽지 않으므로 (Bash 없이는 candidate.py 실행 불가), context file의 정보만으로 `intended_action`을 판단한다. 이는 정확도가 다소 낮을 수 있으나, L1 (candidate.py)의 구조적 판단이 안전장치 역할을 한다.

**Fallback**: `intended_action`이 불명확하면 main agent가 안전 기본값(UPDATE) 선택.

### 3. Re-draft 경로 복잡화

Phase 2 검증 실패 시:
- 현재: subagent가 draft.py를 재실행
- 제안: main agent가 partial_content를 수정하고 draft.py를 재실행해야 함
- **대안**: 검증 실패 시 해당 카테고리를 skip하고 다음 세션에서 재시도 (단순화)

### 4. Main Agent Context 소비

6개 카테고리 전체 트리거 시:
- 6개 intent JSON 읽기
- 6개 candidate.py 출력
- 6개 draft.py 출력
- 합계: ~12회 Bash 호출 결과가 main context에 추가

context 압박 가능성이 있으나, 각 출력이 소량 JSON (< 1KB)이므로 실용적으로 문제되지 않을 것으로 예상.

### 5. 병렬성 유지

Claude Code는 단일 메시지 내 다중 tool call을 지원한다. main agent가 6개 candidate.py 호출을 동시에 발행하면 병렬 실행이 가능하다. 다만 draft.py는 candidate.py 결과에 의존하므로 순차 실행이 필요하다 (candidate → CUD resolution → draft).

### 6. intent JSON validation

subagent가 잘못된 JSON을 쓸 수 있다. main agent가 intent JSON을 파싱할 때 필수 필드 (`category`, `new_info_summary`, `partial_content`) 누락 시 해당 카테고리를 skip하는 방어 로직 필요.

---

## 의존성

- **Tier 1** (`plan-guardian-compat-tier1.md`): Tier 1 완료 후 시작 권장. 독립 실행도 가능하나, Tier 1이 즉시 완화를 제공하므로 먼저 적용하는 것이 실용적.
- **Phase 0 전제조건 확인**: agent 파일의 도구 제한 동작 확인 없이 Phase 1 진행 불가. 확인 실패 시 대안 검토 필요 (예: subagent prompt에서 Bash 금지 강화 + staging guard 의존).

---

## 성공 기준

- Phase 1 subagent가 Bash 도구 없이 intent JSON만 생성
- Guardian 승인 팝업 완전 제거 (Phase 1 subagent가 Bash를 쓰지 않으므로 Guardian 매칭 불가)
- 기존 `pytest tests/ -v` 통과
- 메모리 저장 품질 유지 (기존 대비 regression 없음)
- CUD Resolution 정확도 유지 (L1 + L2 2-layer 검증 유지)

---

## 롤백 계획

1. agent 파일 삭제 (`.claude/agents/memory-drafter.md`)
2. SKILL.md를 `git revert`로 이전 아키텍처 복원
3. Git tag로 전환 시점 표시 권장 (`v5.0.0-pre-tier2`, `v5.1.0-tier2`)
