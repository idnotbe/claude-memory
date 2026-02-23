# action-plans/ 마이그레이션 Working Memory

**날짜:** 2026-02-22
**목표:** `action plans/` (공백) → `action-plans/` (kebab-case) 마이그레이션 + frontmatter + archive 패턴 적용

## 현재 상태

### `action plans/` 내 파일 (7개)
| 파일 | 유형 | 마이그레이션 대상 |
|------|------|-----------------|
| MEMORY-CONSOLIDATION-PROPOSAL.md | 역사적 문서 | → `_ref/` |
| TEST-PLAN.md | 참고 문서 | → `_ref/` |
| plan-guardian-conflict-memory-fix.md | 활성 계획 | → root + frontmatter |
| plan-poc-retrieval-experiments.md | 활성 계획 | → root + frontmatter |
| plan-retrieval-confidence-and-output.md | 활성 계획 | → root + frontmatter |
| plan-search-quality-logging.md | 활성 계획 | → root + frontmatter |
| retrieval-improvement-plan.md | 활성 계획 (이미 Status 있음) | → root + frontmatter |

### 업데이트 필요한 참조 (non-temp)
| 파일 | 라인 | 현재 | 변경 후 |
|------|------|------|---------|
| CLAUDE.md | L75 | `plans/TEST-PLAN.md` | `action-plans/_ref/TEST-PLAN.md` |
| CLAUDE.md | L99 | `plans/TEST-PLAN.md` | `action-plans/_ref/TEST-PLAN.md` |
| README.md | L414 | `MEMORY-CONSOLIDATION-PROPOSAL.md` | `action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md` |
| README.md | L442 | `plans/TEST-PLAN.md` | `action-plans/_ref/TEST-PLAN.md` |
| SKILL.md | L225 | `MEMORY-CONSOLIDATION-PROPOSAL.md` | `action-plans/_ref/MEMORY-CONSOLIDATION-PROPOSAL.md` |

### `plans/` 디렉토리
- 존재하지 않음 (이미 `action plans/`로 이름 변경됨)

## 작업 순서

1. [x] 현재 상태 파악
2. [ ] retrieval-improvement-plan.md의 현재 Status 확인
3. [ ] 디렉토리 생성: `action-plans/`, `action-plans/_done/`, `action-plans/_ref/`
4. [ ] 파일 이동: `action plans/` → `action-plans/`
   - MEMORY-CONSOLIDATION-PROPOSAL.md → `_ref/`
   - TEST-PLAN.md → `_ref/`
   - 나머지 5개 → root
5. [ ] 각 활성 plan 파일에 frontmatter 추가
6. [ ] `action-plans/README.md` 작성
7. [ ] 참조 업데이트: CLAUDE.md, README.md, SKILL.md
8. [ ] CLAUDE.md에 Action Plans 섹션 추가
9. [ ] .gitignore 확인
10. [ ] Vibe check
11. [ ] 독립 검증 R1
12. [ ] 독립 검증 R2
13. [ ] 변경 요약 보고

## 완료 상태

### 검증 결과
| 검증 | 결과 |
|------|------|
| R1 (Explore subagent) | PASS -- 7개 항목 전부 통과 |
| Vibe check | PASS -- 2개 minor follow-up (둘 다 해결됨) |
| R2 (Adversarial general-purpose) | PASS -- 1개 known issue (duplicate status, 의도적 유지) |
| hooks/plugin/commands grep | PASS -- stale plans/ 참조 없음 |

### 알려진 이슈 (의도적 유지)
- `retrieval-improvement-plan.md`에 YAML frontmatter `status: active` + body `**Status:** IN PROGRESS` 공존
  - 이유: 기존 내용 변경 금지 원칙 + CLAUDE.md가 frontmatter를 canonical로 선언
- `_ref/` 문서에 frontmatter 없음 -- 설계대로 (참고 문서는 frontmatter 불필요)
- temp/ 파일의 옛 plans/ 참조 -- working notes이므로 업데이트 불필요
