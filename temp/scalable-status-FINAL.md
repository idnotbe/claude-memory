# 최종 추천안 (검증 2라운드 반영)

**날짜:** 2026-02-22
**분석 경로:** 리서치(KEPs/PEPs/RFCs/Backlog.md) → 5개 방안 비교 → Vibe-check → 검증 R1(비판) → 검증 R2(실용) → 수정

---

## 결정 사항

| 항목 | 결정 |
|------|------|
| 디렉토리명 | `action-plans/` (사용자 확정) |
| 상태 관리 | **최소 frontmatter + archive 패턴** |

---

## 추천: 최소 Frontmatter + Archive 패턴

### 핵심 원칙

1. **이미 작동하는 패턴을 확장한다** -- `retrieval-improvement-plan.md`가 이미 `**Status:** IN PROGRESS` 사용 중. 이 패턴을 표준화.
2. **frontmatter는 최소 필드만** -- status와 progress 2개. 나머지(title, priority, depends_on 등)는 본문에 이미 있으므로 중복하지 않음.
3. **archive는 위생 활동** -- 파일이 쌓이면 _done/으로 정리. 필수가 아님.
4. **CLAUDE.md에 규칙 통합** -- LLM이 시스템을 인지하고 유지할 수 있도록.

### Frontmatter 스키마 (최소)

```yaml
---
status: not-started        # not-started | active | blocked | done
progress: "미시작"          # 현재 진행 상태 (자유 텍스트)
---
```

**왜 2개 필드만인가** (검증 R1 반영):

| 필드 | 포함? | 이유 |
|------|:-----:|------|
| `status` | O | 사용자가 요청한 핵심: "어떤 게 다 된 것이고, 진행 중이고, 시작도 안한 것인지" |
| `progress` | O | Vibe-check 피드백: 상세 진행 상황이 한눈에 보여야 함 |
| ~~plan_id~~ | X | 파일명이 이미 ID 역할 (중복 = drift 위험) |
| ~~title~~ | X | H1 제목이 이미 존재 |
| ~~priority~~ | X | 5개 active 파일에서 우선순위는 의존성 체인으로 자명 |
| ~~depends_on~~ | X | 본문에 이미 "의존성: Plan #2" 형태로 기술 |
| ~~created/updated~~ | X | 본문에 "날짜:" 이미 존재 + git이 추적 |
| ~~summary~~ | X | 본문에 "배경", "목적" 섹션 이미 존재 |

### 디렉토리 구조

```
action-plans/
  README.md                                    # 시스템 규칙 (간결)
  plan-retrieval-confidence-and-output.md       # active (파일명 변경 없음)
  plan-search-quality-logging.md                # active
  plan-poc-retrieval-experiments.md              # active
  plan-guardian-conflict-memory-fix.md           # active
  retrieval-improvement-plan.md                  # active (이미 Status 있음)
  _done/                                        # 완료 파일 (나중에 정리 시)
  _ref/                                         # 참고 문서
    MEMORY-CONSOLIDATION-PROPOSAL.md
    TEST-PLAN.md
```

**변경 사항:**
- 파일명 변경 없음 (불필요한 rename 방지)
- `_done/`은 빈 디렉토리로 시작 (`.gitkeep` 포함)
- `_ref/`에 역사적/참고 문서 이동

### 구체적 마이그레이션 예시

#### plan-retrieval-confidence-and-output.md (기존 내용 상단에 추가)
```yaml
---
status: not-started
progress: "미시작. Action #1 (confidence_label 개선)부터 시작 예정"
---
```

#### plan-search-quality-logging.md
```yaml
---
status: not-started
progress: "미시작. Plan #2 로깅 인프라 -- 독립 실행 가능"
---
```

#### plan-poc-retrieval-experiments.md
```yaml
---
status: not-started
progress: "미시작. Plan #2 로깅 인프라 완료 후 진행"
---
```

#### plan-guardian-conflict-memory-fix.md
```yaml
---
status: not-started
progress: "미시작. 독립 실행 가능 (~45분). SKILL.md 강화 + staging guard"
---
```

#### retrieval-improvement-plan.md (이미 Status 있음, frontmatter 추가)
```yaml
---
status: active
progress: "S1/S2/S3/S5/S5F/P3 완료. S4 (tests) 다음"
---
```

### CLAUDE.md 추가 섹션

```markdown
## Action Plans

실행 계획 파일은 `action-plans/`에 있다. 각 파일 상단에 YAML frontmatter로 상태를 관리한다.

- `status`: not-started | active | blocked | done
- `progress`: 현재 진행 상태 (자유 텍스트)

**규칙:**
- plan 파일 작업 시작/완료 시 frontmatter의 status와 progress를 업데이트할 것
- 완료된 plan은 `action-plans/_done/`으로 이동 가능 (선택)
- `action-plans/_ref/`는 참고/역사적 문서
```

### 참조 업데이트 목록

| 파일 | 위치 | 현재 | 변경 후 |
|------|------|------|---------|
| CLAUDE.md | L75 | `plans/TEST-PLAN.md` | `action-plans/_ref/TEST-PLAN.md` |
| CLAUDE.md | L99 | `plans/TEST-PLAN.md` | `action-plans/_ref/TEST-PLAN.md` |
| README.md | L442 | `plans/TEST-PLAN.md` | `action-plans/_ref/TEST-PLAN.md` |
| README.md | L414 | `MEMORY-CONSOLIDATION-PROPOSAL.md` | `action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md` |
| SKILL.md | L225 | `MEMORY-CONSOLIDATION-PROPOSAL.md` | `action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md` |

---

## 왜 이 방식이 장기적으로 작동하는가

### 7개 파일 (현재)
- frontmatter 한눈에 확인: `grep -A1 "^status:" action-plans/*.md`
- 또는 파일 열어서 첫 3줄 확인

### 50개 파일 (중기)
- Root에 10-20개 active, 나머지 _done/에
- `ls action-plans/*.md` = active만 보임
- LLM context 부담: 최소

### 500개+ 파일 (장기)
- Root은 여전히 10-20개 active
- _done/ 내부를 연도별 구분 가능 (`_done/2026/`)
- 필요 시 간단한 query 스크립트 추가:
  ```bash
  grep -l "status: active" action-plans/*.md
  ```

### INDEX.md 대비 핵심 장점
- **drift 없음**: 각 파일이 자기 상태의 source of truth
- **context window 안전**: 1000개여도 active 파일 frontmatter만 읽으면 됨 (~2K tokens)
- **관리 포인트 분산**: 중앙 파일 하나가 아닌 각 파일이 독립적

---

## Gemini/Codex CLI 사용 불가 사유

| 도구 | 상태 | 원인 |
|------|------|------|
| Gemini CLI | 실패 | non-interactive 모드(`-p` 플래그)에서 GEMINI_API_KEY 환경변수 필요. 프로젝트에서 interactive로 열면 OAuth 브라우저 인증이 가능하지만, Claude Code 내 Bash에서는 non-interactive만 가능 |
| Codex CLI | 실패 | ChatGPT 계정으로 codex/o3 모델 미지원 + 사용량 한도 초과 |

대신 웹 리서치(KEPs/PEPs/RFCs/Backlog.md 등 대형 프로젝트 사례) + vibe-check + 독립 검증 2라운드로 보완.
