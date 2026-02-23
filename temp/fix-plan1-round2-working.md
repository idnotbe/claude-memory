# Working Memory: Pre-existing 이슈 수정 (Round 2)

**목적:** 2차 검증에서 발견된 모든 pre-existing 이슈 수정
**대상:** `action-plans/plan-retrieval-confidence-and-output.md`
**날짜:** 2026-02-23

---

## 이슈 목록 (파일 내 위치순)

### MEDIUM 3건

| # | 이슈 | 위치 | 출처 |
|---|------|------|------|
| M1 | Tiered all-LOW 시 빈 `<memory-context>` 래퍼 출력 억제 명세 부재 | Action #2, lines 213-214 area | adversarial #1 |
| M2 | `_output_results()`에서 `abs_floor` → `confidence_label()` 전달 흐름 미명시 | lines 106, 140 | adversarial #2 |
| M3 | Finding #5 구현을 별도 Action item으로 추적 필요 | line 488 area | adversarial #8 |

### LOW/INFO 7건

| # | 이슈 | 위치 | 출처 |
|---|------|------|------|
| L1 | Header LOC vs 상세 테이블 수치 불일치 | line 11 vs 452-460 | adversarial #3, fresh A1/D4 |
| L2 | 영향받는 파일 요약에 `cluster_detection_enabled` 누락 | line 425 | adversarial #4 |
| L3 | "모든 성공적인 쿼리" 수사적 과장 | line 74 | adversarial #5 |
| L4 | Action #2 테스트 추정 상한 팽창 | line 223 | adversarial #6 |
| L5 | `_emit_search_hint()` MEDIUM hint reason 미포함 | lines 303-313 | adversarial #7 |
| L6 | 역사적 논쟁이 가독성 저하 (Action #1) | lines 45-107 | fresh B1 |
| L7 | `body_bonus` 용어 미정의 | line 83 area | fresh B3 |

### Fresh 추가 발견 (사소)

| # | 이슈 | 위치 | 출처 |
|---|------|------|------|
| F1 | abs_floor/domain 관계 불명확 | line 68 area | fresh B2 |
| F2 | Action #4 검증 게이트 기준 부재 | line 446 area | fresh C4 |

---

## 수정 계획 (위치순)

### 1. Line 11: Header LOC 수정 (L1)
- 현재: `~60-80 LOC (코드) + ~100-200 LOC (테스트)`
- 수정: `~66-105 LOC (코드) + ~130-240 LOC (테스트)` (상세 테이블과 통일)

### 2. Line 68 area: abs_floor domain 관계 명시 (F1)
- 현재: `권장 시작값: 복합 점수 도메인 기준 1.0-3.0`
- 수정: 뒤에 "(0-15 범위에서 하위 약 7-20%, 약한 매칭 tail 대상)" 추가

### 3. Line 74: "모든 성공적인 쿼리" 수정 (L3)
- 현재: `모든 성공적인 쿼리에 발동하는 논리 오류`
- 수정: `대다수(70%+)의 성공적인 쿼리에 발동하는 논리 오류`

### 4. Line 83: body_bonus 정의 추가 (L7)
- 현재: `BM25 - body_bonus` 변이값(복합 점수)
- 수정: `BM25 - body_bonus` (body_bonus: 본문 토큰 매칭 보너스 0-3점, `score_with_body()` line 247에서 계산)

### 5. Lines 81-93: 역사적 논쟁 가독성 개선 (L6)
- 접근: 전체 재구조화 대신, "구현 요약"을 먼저 배치하고 "상세 이력"을 하위로 이동
- blockquote 앞에 1줄 요약 추가

### 6. Line 106: abs_floor 전달 명시 (M2)
- 현재: `confidence_label()` 호출 시 `cluster_count=0` 전달
- 수정: `confidence_label()` 호출 시 `abs_floor=abs_floor`, `cluster_count=0` 전달

### 7. Line 140: abs_floor 전달 대상 명시 (M2 연속)
- 현재: `복합 점수 기반 cluster_count 계산 + abs_floor 전달`
- 수정: `cluster_count=0 고정 전달 + abs_floor를 confidence_label()에 전달`

### 8. Lines 213-214: all-LOW wrapper 억제 명세 추가 (M1)
- 현재: `Action #3의 all-low-confidence hint가 이 경로를 처리.`
- 수정: 상세 명세 추가 -- wrapper 출력 억제 + hint만 출력

### 9. Line 223: 테스트 추정 조정 (L4)
- 현재: `~15-30개`
- 수정: `~15-20개` (체크리스트 합계 ~15개 + 여유분)

### 10. Lines 303-313: _emit_search_hint에 MEDIUM reason 추가 (L5)
- 헬퍼에 "medium_present" reason 추가

### 11. Line 425: cluster_detection_enabled 추가 (L2)
- 현재: `confidence_abs_floor`, `output_mode` 추가
- 수정: `confidence_abs_floor`, `cluster_detection_enabled`, `output_mode` 추가

### 12. Line 446 area: Action #4 검증 게이트 추가 (F2)
- Gate D 뒤에 Action #4 검증 기준 추가

### 13. Line 488 area: Finding #5 추적 노트 추가 (M3)
- 검토 이력 아래에 Finding #5 구현 추적 노트 추가

---

## 진행 상태

- [x] 수정 #1 (L1): Header LOC → ~66-105 + ~130-240
- [x] 수정 #2 (F1): abs_floor domain → "(0-15 범위에서 하위 약 7-20%)" 추가
- [x] 수정 #3 (L3): "모든 성공적인 쿼리" → "대다수(70%+)의"
- [x] 수정 #4 (L7): body_bonus 정의 → "(0-3점, score_with_body() line 247에서 계산)"
- [x] 수정 #5 (L6): 가독성 개선 → "구현 결론:" 1줄 요약 추가
- [x] 수정 #6 (M2): abs_floor 전달 line 108 → "abs_floor=abs_floor, cluster_count=0"
- [x] 수정 #7 (M2): abs_floor 전달 line 142 → "cluster_count=0 고정 전달 + abs_floor를 confidence_label()에 전달"
- [x] 수정 #8 (M1): all-LOW wrapper 억제 → 명세 + 체크리스트 항목 추가
- [x] 수정 #9 (L4): 테스트 추정 → "~15-20개"
- [x] 수정 #10 (L5): MEDIUM hint reason → "medium_present" + 분기 조건 명시
- [x] 수정 #11 (L2): config 파일 목록 → cluster_detection_enabled 추가
- [x] 수정 #12 (F2): Action #4 검증 게이트 → Gate E 추가
- [x] 수정 #13 (M3): Finding #5 추적 → 미추적 구현 사항 노트 + plan-import-hardening.md 참조
- [x] 추가: Action #2 체크리스트에 all-LOW wrapper 생략 + medium_present hint 항목
- [x] 추가: medium_present 분기 조건 명시 (Gemini L5 제안)
- [x] vibe-check: MEDIUM 수정안 확인 완료 (PASS, 조정사항 반영)
- [x] pal clink: Gemini 3.1 Pro 검증 완료 (전량 반영 권고)
- [x] 1차 독립 검증: PASS (temp/fix-plan1-round2-verify1.md)
- [x] 2차 독립 검증: PASS WITH NOTES (temp/fix-plan1-round2-verify2.md)
- [x] 검증 피드백 반영: line 210 분기 조건 "또는" 모호성 제거 → 단일 조건으로 통일

## 최종 상태: 16건 수정 완료 (15건 + 검증 피드백 1건)
