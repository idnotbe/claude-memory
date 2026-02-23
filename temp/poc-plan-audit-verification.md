# plan-poc-retrieval-experiments.md 감사 결과 -- 교차 검증

**작성일:** 2026-02-22
**검증 방법:** 2개 독립 subagent (Opus + Sonnet) + 직접 재검증

## Subagent 간 불일치 및 해소

### Finding #1 (Score Domain Paradox) 반영 여부
- **Subagent 1 (Opus):** PARTIAL -- raw_bm25 코드 변경 REJECTION이 명시적으로 기록되지 않음
- **Subagent 2 (Sonnet):** YES -- raw_bm25를 진단 로깅으로만 기술함으로써 암묵적 반영
- **직접 재검증 결과:** **PARTIAL** (Opus가 정확)
  - L196-213에 triple-field 로깅, dual precision, label_precision은 기록됨
  - 그러나 "raw_bm25 코드 변경 REJECTED" / "confidence_label()은 composite score 유지"라는 명시적 결정 없음
  - "abs_floor을 composite domain으로 교정"이라는 final report의 핵심 해결책도 없음
  - **이 plan만 읽는 사람은 왜 raw_bm25를 confidence_label에 사용하지 않는지 알 수 없음**

### NEW-4 (ranking-label inversion) 반영 여부
- **Subagent 1 (Opus):** NO -- 전혀 언급 없음
- **Subagent 2 (Sonnet):** YES -- 결과가 반영됨
- **직접 재검증 결과:** **PARTIAL** (Opus에 더 가까움)
  - NEW-4의 구체적 내용(Entry A low / Entry B high 역전)은 plan에 없음
  - "ranking-label inversion"이라는 용어 자체가 plan에 없음
  - 검토 이력 L505의 "PoC #5 score domain paradox"가 이를 지칭하나, 그 paradox의 코드 변경이 다시 뒤집어졌다는 사실은 불명확

## 최종 감사 테이블 (교차 검증 완료)

| 항목 | 최종 판정 | Plan 라인 | 비고 |
|------|-----------|----------|------|
| Finding #1 (Score Domain) | **PARTIAL** | L196-213, L505 | 결과(triple-field)는 기록, 결정(REJECTED)과 이유(NEW-4) 누락 |
| Finding #2 (Cluster Tautology) | **NO** | -- | Plan #1 범위, 합리적 누락 |
| Finding #3 (PoC #5 Measurement) | **YES** | L204-213, L506 | label_precision, dual precision, annotation 완전 반영 |
| Finding #4 (PoC #6 Dead Path) | **YES** | L297-307, L315, L506 | --session-id 4개 항목 모두 정확 |
| Finding #5 (Import Crash) | **NO** | -- | Plan #2 범위, 합리적 누락. 단 의존성 노트 권장 |
| NEW-1 (noise floor) | **PARTIAL** | L181-184 | 현상은 기존 기술, NEW-1로서의 처분(defer to PoC #5) 미기재 |
| NEW-2 (judge import) | **NO** | -- | Plan #2 범위 |
| NEW-3 (empty XML) | **NO** | -- | 별도 추적 대상 |
| NEW-4 (ranking-label inversion) | **PARTIAL** | L505 (간접) | 구체적 역전 시나리오 미기재, 이름조차 없음 |
| NEW-5 (transitive ImportError) | **NO** | -- | Plan #2 범위 |

## 구조적 점검 (양 subagent 일치)

| 점검 | 결과 | 상세 |
|------|------|------|
| 구현 순서 | **YES, 2단계** | PoC 순서 (L52) + Cross-Plan 8단계 (L473-492) |
| 진행 체크박스 | **YES, 33개 전부 미체크** | L411-455, `[ ]` 형식, `[x]` 없음 |
| YAML frontmatter | **README.md 완전 일치** | status: not-started, progress: 자유텍스트 |

## 핵심 발견: Plan은 중간 버전(Solution Synthesis) 기반

근거:
1. Finding #1의 raw_bm25 REJECTION이 명시적으로 기록되지 않음
2. NEW-4 (ranking-label inversion) 이름/내용이 plan에 없음
3. L196 "V2-adversarial + Deep Analysis 최종 반영" 헤더의 내용은 Finding #3, #4만 완전 반영
4. 검토 이력 L506 "Deep Analysis (7-agent)"은 최종 보고서를 요약하지만 핵심 변경(REJECTION)을 생략

## PoC #6 체크리스트 누락 항목
`--session-id` CLI 파라미터 구현이 PoC #6의 선행 조건임에도 L447-455 체크리스트에 없음
