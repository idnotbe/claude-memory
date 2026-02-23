# Working Memory: plan-poc-retrieval-experiments.md 분석

## 목표
plan-poc-retrieval-experiments.md의 내용을 설명하고, Deep Analysis(7-agent, 5-phase)와의 연관성을 상세히 분석한다.

## 파일 위치
- Plan: `action-plans/plan-poc-retrieval-experiments.md`
- Deep Analysis 문서: `temp/41-*.md` (11개 파일)
- 관련 Plan 파일: `action-plans/plan-retrieval-confidence-and-output.md`, `action-plans/plan-search-quality-logging.md`

## Plan 구조 요약
- PoC #4: Agent Hook 실험 (1일 time-box)
- PoC #5: BM25 정밀도 측정 (25-30 파일럿 → 50+ 확장)
- PoC #6: Nudge 준수율 측정 (PARTIALLY UNBLOCKED)
- PoC #7: OR-query 정밀도 (#5 데이터 재활용)
- 실행 순서: #4(spike) → #5 → #7 → #6

## Deep Analysis → Plan 영향 매핑

### 직접 연관 (Finding → Plan 변경)
| Finding | Plan 변경 위치 | 변경 내용 |
|---------|--------------|----------|
| #3 (PoC #5 Measurement) | lines 196-213 | Triple-field 로깅, label_precision, human annotation |
| #4 (PoC #6 Dead Path) | lines 295-307 | BLOCKED → PARTIALLY UNBLOCKED, --session-id |

### 간접 연관 (Finding → Plan 방법론에 영향)
| Finding | 영향 | 설명 |
|---------|------|------|
| #1 (Score Domain Paradox) | PoC #5 측정 대상 변경 | raw_bm25 거부 → composite score 유지 → dual precision 계산 방식 재정의 |
| #5 (Logger Import Crash) | 전체 PoC 로깅 의존성 | emit_event 안전 임포트 패턴 → 로깅 인프라 안정성 확보 |
| NEW-1 | PoC #5 향후 분석 대상 | apply_threshold noise floor 왜곡 → PoC #5 데이터로 실증 |
| NEW-4 | raw_bm25 거부의 원인 | ranking-label inversion → Finding #1 해결 방향 결정 |

## 자가비판 체크리스트
- [ ] Finding #2 (Cluster Tautology)의 plan-poc 연관성 확인 → 직접 연관 없으나 #5 방법론에 미약한 영향
- [ ] NEW-2, NEW-3, NEW-5의 연관성 검토 완료
- [ ] Key Course Correction의 plan-poc 영향 정리 완료
- [ ] Process Assessment의 plan-poc 시사점 정리 완료
