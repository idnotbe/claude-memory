# Action Plans 폴더 개선 분석 -- Working Memory

**날짜:** 2026-02-22
**목표:** (1) 폴더 명칭 최적화, (2) 파일 상태 관리 체계 수립

---

## 현재 상태 파악

### 프로젝트 내 디렉토리 네이밍 컨벤션
- `hooks/` -- kebab이 아닌 단어
- `hooks/scripts/` -- 단수형 아님, 복수형
- `.claude-plugin/` -- **kebab-case**
- `.claude/memory/` -- 단어
- `action plans/` -- **공백 포함** (유일한 예외)
- `assets/`, `commands/`, `skills/`, `tests/`, `temp/`, `research/` -- 단수/복수 단어
- `.pytest_cache/` -- **snake_case**
- `__pycache__/` -- **snake_case** (Python 표준)

**결론:** 프로젝트는 대부분 lowercase 단일 단어 또는 kebab-case 사용. 공백 포함 디렉토리는 `action plans`만 존재.

### action plans 파일들 현황
| 파일 | 상태 표기 | 의존성 | 날짜 |
|------|-----------|--------|------|
| retrieval-improvement-plan.md | "Status: IN PROGRESS" (헤더에 명시) | 없음 (마스터 플랜) | 2026-02-20 |
| plan-retrieval-confidence-and-output.md | Plan #1 | 없음 | 2026-02-22 |
| plan-search-quality-logging.md | Plan #2 | Plan #1 의존 | 2026-02-22 |
| plan-poc-retrieval-experiments.md | Plan #3 | Plan #2 의존 | 2026-02-22 |
| plan-guardian-conflict-memory-fix.md | Plan #4 | 독립 | 2026-02-22 |
| MEMORY-CONSOLIDATION-PROPOSAL.md | 상태 없음 | 불명 | 2026-02-16 |
| TEST-PLAN.md | 상태 없음 | 불명 | 2026-02-16 |

**핵심 문제:**
1. 파일명에 상태 정보 없음 (일부 헤더에만 존재)
2. 공백 디렉토리명 → 쉘 스크립트에서 항상 인용부호 필요
3. 파일이 7개만인데도 이미 혼란 발생 → 스케일 문제

---

## Q1: 명칭 분석 (수집 중)

### 후보 목록
1. `action-plans/` (kebab-case)
2. `action_plans/` (snake_case)
3. `plans/` (단순화)
4. `backlog/` (상태 내포)
5. `roadmap/` (방향성 내포)
6. `tasks/` (이미 .claude/tasks 존재하므로 충돌 가능)
7. `playbooks/` (실행 가이드라인 뉘앙스)
8. `ops/` (운영 계획)

### 평가 기준
- 프로젝트 네이밍 컨벤션 일관성
- 쉘 호환성 (공백 없음)
- 의미 전달 명확성
- 간결성
- 한국어/영어 혼용 환경에서의 직관성

## Q2: 상태 관리 분석 (수집 중)

### 후보 방안
- A: 파일명 접두사 방식 (예: `01-wip-`, `02-done-`)
- B: 상위 README.md 인덱스 방식
- C: 하위 디렉토리 분리 (todo/, doing/, done/)
- D: YAML frontmatter + 빌드 스크립트
- E: 파일명 접미사 방식 (예: `-wip`, `-done`)
- F: 체크박스 기반 INDEX.md

---

## 외부 의견 (수집 예정)
- [ ] Gemini 3 Pro via clink
- [ ] Codex 5.3 via clink
- [ ] Vibe-check

---

## 진행 로그
- 15:30 작업 시작, 현재 상태 파악 완료
- 15:35 외부 의견 수집 시도 (Gemini: API키 없음, Codex: 한도 초과) → 웹 리서치로 대체
- 15:40 웹 리서치 2건 완료 (네이밍 컨벤션 + 상태 관리 베스트 프랙티스)
- 15:45 자체 분석 초안 작성 (naming-analysis.md, status-mgmt-analysis.md)
- 15:50 Vibe-check 완료 → 핵심 피드백: plans/ 이름 변경 이력 사용자 확인 필요, INDEX.md 구체적 템플릿 필요
- 15:55 독립 검증 2라운드 완료
  - V1: git 역사 오해 수정, INDEX.md 마찰 재평가, 자동생성 INDEX 대안 발견
  - V2: plans/가 이미 커밋 상태 확인, 참조 깨짐 없음 확인, 실용 INDEX.md 초안 제시
- 16:00 최종 보고서 작성 완료 (action-plans-final-recommendation.md)

## 생성 파일 목록
- `temp/action-plans-naming-analysis.md` -- Q1 초안 분석 (검증 전)
- `temp/action-plans-status-mgmt-analysis.md` -- Q2 초안 분석 (검증 전)
- `temp/action-plans-final-recommendation.md` -- **최종 보고서** (검증 반영)
