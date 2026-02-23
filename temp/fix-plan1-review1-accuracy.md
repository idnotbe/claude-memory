# Accuracy Review: plan-retrieval-confidence-and-output.md 수정 검증 (v2 -- 12건 전체 포함)

**검증자:** reviewer-accuracy
**날짜:** 2026-02-22
**대상:** `action-plans/plan-retrieval-confidence-and-output.md` (editor 수정 후)
**참조:** `temp/fix-plan1-editor-output.md`, `temp/fix-plan1-master-briefing.md`, `temp/41-final-report.md`, `temp/41-finding2-cluster-logic.md`

---

## 최종 판정: PASS WITH NOTES

12건 수정 모두 기술적으로 정확하며, Deep Analysis 원본 결론과 일치한다.
Notes는 editor 수정 범위 밖의 pre-existing LOC 추정치 불일치 1건.

---

## 검증 방법론

1. **원본 대조**: 수정된 plan 파일의 각 이슈를 Deep Analysis 최종 보고서(`41-final-report.md`) 및 Finding #2 증명(`41-finding2-cluster-logic.md`)과 라인 단위 대조
2. **소스 코드 검증**: `memory_retrieve.py`, `memory_search_engine.py`, `test_memory_retrieve.py`의 실제 코드와 plan 내 코드 참조(라인 번호, 함수 시그니처, 테스트 개수) 교차 검증
3. **외부 모델 교차 검증**: Gemini 3.1 Pro (via pal clink, codereviewer role)에게 6개 핵심 기술 주장의 정확성 독립 확인 -- 모두 CORRECT 판정
4. **메타인지 검증**: vibe-check 스킬로 확인 편향(confirmation bias) 및 누락 각도 점검

---

## Part 1: 원본 이슈 수정 (A-F) 검증

### Issue A (높음): Line 103 -- post-truncation counting 설명 수정
**판정: PASS**

- **수정 내용**: "잘린 후 집합에서 계산" -> "현재 비활성 -- 호출 시 항상 0 전달. 향후 활성화 시 pre-truncation counting으로 구현 필요"
- **Deep Analysis 대조**: `41-finding2-cluster-logic.md` Section 2.2에서 post-truncation counting은 `C <= N <= max_inject`이므로 dead code임을 수학적으로 증명. Section 4 "Keep Disabled + Document"가 최종 권고. 수정 텍스트가 정확히 일치.
- **코드 검증**: `memory_retrieve.py:299`에서 `confidence_label(entry.get("score", 0), best_score)` 호출 확인 -- cluster_count 파라미터 미사용 (현재 시그니처에 없음). `memory_search_engine.py:289`에서 `return results[:limit]`으로 truncation 발생. 비활성 상태 기술이 정확.

### Issue B (중간): Line 141 -- 비활성 기능 구현 체크리스트 수정
**판정: PASS**

- **수정 내용**: "클러스터 감지 로직 구현: cluster_count >= 3이면 최대 medium" -> "클러스터 감지 기능 비활성 유지 확인"
- **Deep Analysis 대조**: `41-final-report.md` Finding #2 최종 결론: "Keep disabled. Replace dead-code threshold in plan text. Proven mathematically." 수정이 이 결론을 정확히 반영.
- **내부 일관성**: Line 72 (`default: false`), Line 77-78 (비활성 유지), Line 103 (항상 0 전달)과 일관.

### Issue C (낮음): Line 68 -- "BM25 모드" 구식 표현 수정
**판정: PASS**

- **수정 내용**: "BM25 모드에서 1.0-2.0" -> "복합 점수 도메인 기준 1.0-3.0"
- **Deep Analysis 대조**: `41-final-report.md` Finding #1: "Recalibrate abs_floor to composite domain" 및 "range approximately 0-15 for typical corpora". "복합 점수 도메인"이 정확한 용어.
- **코드 검증**: `memory_retrieve.py:256-257`에서 `r["raw_bm25"] = r["score"]` 후 `r["score"] = r["score"] - r.get("body_bonus", 0)` -- in-place mutation. `memory_retrieve.py:299`에서 mutated (composite) score가 `confidence_label()`에 전달됨. "BM25 모드"는 부정확.

### Issue D (낮음): Line 68 vs 102 -- abs_floor 권장값 통일
**판정: PASS**

- **수정 내용**: Line 68과 102 모두 `1.0-3.0`으로 통일
- **검증**: 문서 내 확인으로 두 곳 모두 `1.0-3.0` 기재 확인. 내부 불일치 해소.
- **범위 적절성**: 복합 점수 도메인 ~0-15에서 1.0-3.0은 약 7%-20%에 해당. 로깅 인프라 구축 후 조정 전제 시작값으로 합리적.

### Issue E (중간): Lines 148-149 -- obsolete 클러스터 테스트 축소
**판정: PASS**

- **수정 내용**: 클러스터 구현 테스트 ~8개 -> cluster_count=0 기본값 확인 테스트 ~2개로 축소
- **Deep Analysis 대조**: `41-finding2-cluster-logic.md` Section 4: "implementing it for a disabled feature is wasted engineering". 비활성 기능의 구현 테스트 삭감은 이 결론의 직접적 귀결.
- **수치 확인**: Line 117 "~10-12개" = ~8개(abs_floor) + ~2개(cluster_count=0). 산술적으로 일관.

### Issue F (낮음): Line 490 -- 검토 이력에 Finding #5 추가
**판정: PASS**

- **수정 내용**: Deep Analysis 행에 "Import hardening (Finding #5, ~36 LOC): module-level try/except + e.name scoping for memory_logger/judge imports." 추가
- **Deep Analysis 대조**: `41-final-report.md` Finding #5: "~36 LOC", "module-level try/except", "`e.name` check", "Most impactful fix. Prevents hook crashes on partial deployments." 모든 기술 용어와 수치가 정확히 일치.

---

## Part 2: Gemini 추가 발견 Cascade 수정 (5건) 검증

### Cascade 1: Line 106 cluster_count 계산 -> 비활성
**판정: PASS**

- "cluster_count=0 전달 (비활성)"이 Line 103 (항상 0 전달), Line 141 (비활성 유지 확인)과 일관.

### Cascade 2: Lines 119-121 클러스터 테스트 축소
**판정: PASS**

- Line 148의 "~2개"와 일치. Issue E와 동일 근거.

### Cascade 3: Line 117 신규 테스트 수 조정 (~15-25 -> ~10-12)
**판정: PASS**

- abs_floor ~8개 + cluster_count=0 ~2개 = ~10개. 범위 표현 "~10-12"은 합리적.

### Cascade 4: Line 255 cluster_count 계산 -> 비활성
**판정: PASS**

- Action #2 Progress 섹션의 "cluster_count=0 고정 전달 확인"이 비활성화 결정과 일관.

### Cascade 5: Line 110 apply_threshold 상호작용 설명 수정
**판정: PASS**

- "abs_floor를 도입하여 점수 미달 결과가 high로 분류되는 오분류를 우선 방어"가 Action #1의 abs_floor 목적과 정확히 부합. 클러스터 감지 보류와 모순 없음.

---

## Part 3: 완전성 검증 추가 발견 (1건) 검증

### Line 474: `cluster_detection_enabled` default: true -> false
**판정: PASS**

- 문서 전체 `cluster_detection_enabled` 전수 조사 (Line 72, 77, 78, 127, 133, 413, 474): **모두 `false`**. 일관성 확인.
- "pre-existing 불일치"라는 editor의 판단: Deep Analysis 이후 최종 결정이 `false`로 변경되었으나 Line 474만 업데이트되지 않은 것은 합리적 설명. 수정 자체의 정확성은 의심의 여지 없음.

---

## 소스 코드 참조 교차 검증

| Plan 참조 | 실제 코드 | 일치 여부 |
|-----------|----------|----------|
| `confidence_label()` at line 161-174 | `memory_retrieve.py:161-174` | 일치 |
| `score_with_body()` in-place 변이 at line 257 | `memory_retrieve.py:257` `r["score"] = r["score"] - r.get("body_bonus", 0)` | 일치 |
| `raw_bm25` 보존 at line 256 | `memory_retrieve.py:256` `r["raw_bm25"] = r["score"]` | 일치 |
| `_output_results()` at line 262-301 | `memory_retrieve.py:262-301` | 일치 |
| `confidence_label()` 호출 at line 299 | `memory_retrieve.py:299` `conf = confidence_label(entry.get("score", 0), best_score)` | 일치 |
| `apply_threshold()` at `memory_search_engine.py:283-288` | 실제: `memory_search_engine.py:283-289` (noise floor + truncation) | 일치 (1줄 차이는 return문 포함 여부) |
| `TestConfidenceLabel` 17개 테스트 at lines 493-562 | 실측: 17개 `test_*` 메서드 (lines 497-562) | 일치 |
| 3곳의 HTML 주석 hint (lines 458, 495, 560) | `memory_retrieve.py:458, 495, 560` 모두 `<!-- No matching memories found... -->` | 일치 |
| `max_inject = 3` default at line 343 | `memory_retrieve.py:343` `max_inject = 3` | 일치 |

---

## 외부 교차 검증 결과

### Gemini 3.1 Pro (via pal clink, codereviewer role)

6개 핵심 기술 주장 모두 **CORRECT** 판정:

| # | 주장 | 판정 | 근거 |
|---|------|------|------|
| 1 | Cluster tautology 수학적 증명 | CORRECT | Finding #2 Section 2.2 확인 |
| 2 | Ranking-label inversion | CORRECT | composite score 유지가 정확 |
| 3 | abs_floor 복합 점수 도메인 범위 1.0-3.0 | CORRECT | 0-15 도메인에서 합리적 |
| 4 | TestConfidenceLabel 17개 테스트 | CORRECT | 코드 직접 확인 |
| 5 | Finding #5 import hardening ~36 LOC | CORRECT | 검토 이력 기재 정확 |
| 6 | cluster_detection_enabled default: false | CORRECT | Deep Analysis 합의 |

### Vibe-Check 메타인지 검증

- **판정**: 리뷰 방법론 적절, 확인 편향 위험 낮음
- **추가 확인 제안 2건**:
  1. LOC 추정치 헤더 vs 상세 테이블 불일치 -- 확인 결과 pre-existing (아래 Notes 참조)
  2. Line 474 "pre-existing" 주장 -- git history로 검증 가능하나 수정 자체는 무조건 정확

---

## Notes (사소한 관찰, 정확성 이슈 아님)

### Note 1: LOC 추정치 헤더 vs 상세 테이블 불일치 (pre-existing)

Line 11의 요약 "~60-80 LOC (코드) + ~100-200 LOC (테스트)"와 Lines 450-460의 상세 테이블 "~66-105 (코드) + ~130-240 (테스트)"가 불일치. 이는 editor의 12건 수정과 **무관한 pre-existing 불일치**이며, 이번 수정의 정확성에 영향 없음. 향후 plan 업데이트 시 통일 권장.

### Note 2: 용어 일관성 확인 완료

문서 전체에서 다음 용어가 일관되게 사용됨:
- "복합 점수" / "composite score" (BM25 - body_bonus)
- "pre-truncation counting" (향후 유효한 구현 방식)
- "dead code" (post-truncation counting의 성격)
- "ranking-label inversion" (raw_bm25 사용 시 발생하는 문제)

---

## 결론

**PASS WITH NOTES** -- 12건 수정 모두 기술적으로 정확:

- Deep Analysis 원본 결론과 정확히 일치
- 소스 코드 참조 9개 항목 모두 실측 확인
- 외부 모델(Gemini 3.1 Pro) 독립 교차 검증 6/6 통과
- 문서 내부 일관성 확인 완료 (`cluster_detection_enabled` 7개소 모두 `false`, `abs_floor` 범위 2개소 모두 `1.0-3.0`)
- Note 1의 LOC 추정치 불일치는 pre-existing이며 이번 수정 범위 밖
