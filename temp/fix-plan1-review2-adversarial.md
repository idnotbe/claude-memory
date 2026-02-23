# Adversarial Review Report (Review #2)

**Reviewer:** reviewer-adversarial
**Date:** 2026-02-22
**Target:** `action-plans/plan-retrieval-confidence-and-output.md` (post-edit, 12 fixes applied)
**Method:** Systematic + Advanced adversarial attacks, external validation (Gemini 3.1 Pro via pal clink)

---

## Final Verdict: PASS WITH NOTES

1차 검증의 PASS 판정에 동의한다. editor의 12건 수정은 모두 정확하며 새로운 모순을 도입하지 않았다. 그러나 **수정 범위 밖의 pre-existing 이슈 7건**을 발견했으며, 이 중 2건은 구현 시 혼란을 야기할 수 있는 MEDIUM 수준이다.

---

## Phase 1: Systematic Attacks

### Finding #1: Empty `<memory-context>` Wrapper in Tiered All-LOW Case
- **Severity:** MEDIUM
- **Location:** Action #2 (lines 153-268), specifically lines 164-174 and 213-214
- **Attack:** Tiered 모드에서 모든 결과가 LOW일 때, `_output_results()`는 여전히 `<memory-context>` 래퍼를 무조건 출력한다 (현재 코드 lines 285, 301). Plan은 "모든 결과가 LOW인 경우 -- Action #3의 all-low-confidence hint가 이 경로를 처리" (line 213-214)라고 명시하지만, `_output_results()` 내부에서 래퍼 출력 억제 로직을 설명하지 않는다.
- **Impact:** 구현자가 `_output_results()`를 그대로 호출하면 빈 `<memory-context></memory-context>` + `<memory-note>` hint가 동시 출력되어 Claude 컨텍스트에 불필요한 빈 래퍼가 주입된다.
- **1차 검증 놓친 이유:** 1차 검증은 수정된 12건의 정확성에 집중했으며, tiered 모드의 edge case 흐름을 end-to-end로 추적하지 않았다.
- **범위:** Pre-existing -- editor 수정 이전부터 plan에 존재하던 설계 공백. editor의 수정 범위 밖.

### Finding #2: `abs_floor` Forwarding Gap in `_output_results()`
- **Severity:** MEDIUM
- **Location:** Lines 105-106 vs Lines 243-246
- **Attack:** Plan line 106은 "`_output_results()` (line 299): `confidence_label()` 호출 시 `cluster_count=0` 전달"만 명시하고, `abs_floor` 전달을 언급하지 않는다. 한편 plan line 244-246에서 `_output_results()` 시그니처에 `abs_floor` 파라미터를 추가한다. 그러나 `_output_results()` 내부에서 `abs_floor`를 `confidence_label()`에 전달하는 흐름이 명시적으로 기술되지 않는다.
- **Impact:** 구현자가 `_output_results()`에 `abs_floor`를 받지만 내부 `confidence_label()` 호출에 전달하는 것을 누락할 수 있다. Plan line 140의 체크리스트 "`_output_results()`에서 복합 점수 기반 cluster_count 계산 + `abs_floor` 전달"이 이를 암시하지만, "전달 대상"(confidence_label)이 명시되지 않아 모호하다.
- **1차 검증 놓친 이유:** 1차 검증은 line 106의 cluster_count=0 수정이 올바른지에 집중했으며, abs_floor 데이터 흐름의 완전성을 검증하지 않았다.
- **범위:** Pre-existing -- 원본 plan 설계의 명세 공백.

### Finding #3: Header LOC vs Cross-Cutting LOC Table Mismatch
- **Severity:** LOW
- **Location:** Line 11 vs Lines 452-460
- **Attack:** Header (line 11): "~60-80 LOC (코드) + ~100-200 LOC (테스트)" = 총 ~160-280. Cross-cutting table (lines 455-460): "코드 소계: ~66-105", "테스트 소계: ~130-240", "총계: ~196-345". 코드는 66-105 vs 60-80 (상한 불일치: 105 > 80). 테스트는 130-240 vs 100-200 (양쪽 불일치: 130 > 100, 240 > 200). 총계 196-345 vs 160-280 (상한 불일치: 345 > 280).
- **Impact:** 낮음. LOC 추정치는 대략적 범위이며, 상세 테이블이 더 신뢰할 수 있다. 그러나 header가 과소 추정이므로 의사결정자가 잘못된 규모감을 가질 수 있다.
- **범위:** Pre-existing.

### Finding #4: 영향받는 파일 요약 Table에 `cluster_detection_enabled` 설정 누락
- **Severity:** LOW
- **Location:** Line 425
- **Attack:** Line 425의 `assets/memory-config.default.json` 변경 내용이 "`confidence_abs_floor`, `output_mode` 추가"로만 기술되어 있으나, line 127과 143에서 `cluster_detection_enabled`도 이 파일에 추가하도록 명시한다. 요약 테이블에서 누락.
- **Impact:** 낮음. 상세 Action #1 설명에는 있으므로 구현 시 놓칠 가능성 낮음.
- **범위:** Pre-existing. completeness reviewer도 동일 이슈 보고 (Gemini finding #3).

### Finding #5: Line 74 "모든 성공적인 쿼리" Overstatement
- **Severity:** LOW
- **Location:** Line 74
- **Attack:** Plan: "원안 임계치(`>= 3`)는 `max_inject=3`(기본값)에서 **모든 성공적인 쿼리**에 발동하는 논리 오류 (tautology)". Finding #2 수학적 증명 (temp/41-finding2-cluster-logic.md Section 2.4): "the probability that all 3 have `ratio > 0.90` is **> 70%**". 즉, 70%+ 확률이지 100%가 아니다. "모든 성공적인 쿼리"는 과장이며, 정확한 표현은 "대다수의 성공적인 쿼리"이다.
- **Impact:** 낮음. Finding #2의 핵심 결론(tautology, dead code)은 유효하며, 이 표현은 단순히 수사적 과장.
- **범위:** Pre-existing. completeness reviewer 보고의 line 103번 항목과 동일 root.

### Finding #6: Action #2 Test Estimate Inflation
- **Severity:** INFO
- **Location:** Line 223 vs Lines 262-265
- **Attack:** Line 223: "신규 테스트 필요: ~15-30개". Lines 262-265의 상세 체크리스트: ~6 + ~4 + ~2 + ~3 = ~15개. "30"은 상세 체크리스트의 2배이며, 상한이 과도하게 팽창되어 있다.
- **Impact:** 없음. 추정치 범위의 상한은 edge case 추가 테스트를 포함할 수 있으므로 반드시 오류는 아님.
- **범위:** Pre-existing.

### Finding #7: `_emit_search_hint()` Helper가 Action #2의 MEDIUM Hint를 포함하지 않음
- **Severity:** LOW
- **Location:** Lines 303-313 (Action #3) vs Lines 208-211 (Action #2)
- **Attack:** Action #3의 `_emit_search_hint()` 헬퍼는 `"no_match"` 과 `"all_low"` 두 가지 reason만 지원한다. 그러나 Action #2 (line 208-211)에서 MEDIUM 결과 그룹 뒤에 별도의 `<memory-note>` 검색 유도 문구를 정의한다. DRY 원칙을 위한 헬퍼 함수가 Action #2의 note를 포함하지 않아, 구현 시 일부 `<memory-note>` 생성이 헬퍼 외부에서 직접 print()로 이루어져야 한다.
- **Impact:** 낮음. DRY 위반이지만 기능적 문제는 아님. 구현자가 헬퍼에 reason 추가하거나 별도로 처리할 수 있다.
- **범위:** Pre-existing -- 원본 plan의 설계 결정.

---

## Phase 2: Advanced Attacks

### Finding #8 (Reverse-Trace): Finding #5 (Import Hardening)에 대한 Action Item 부재
- **Severity:** MEDIUM (주의 필요)
- **Location:** Line 488 vs Action #1-#4 전체
- **Attack:** Deep Analysis Finding #5는 "Most impactful fix" (~36 LOC)로, `memory_retrieve.py`와 `memory_search_engine.py`에 module-level try/except import hardening을 추가하는 실제 코드 변경이다. 검토 이력 (line 488)에 요약이 추가되었지만, 4개 Action 중 어디에도 Finding #5의 구현 체크리스트가 없다. Finding #5는 어느 plan에서 추적되는가?
- **검증:** `41-final-report.md`의 "Plan File Updates" 섹션은 이 plan, `plan-search-quality-logging.md`, `plan-poc-retrieval-experiments.md` 세 곳의 수정을 명시하지만, Finding #5의 구현 자체는 어떤 plan의 Action item으로도 기술되지 않았다. Finding #5는 **plan 수정(text fix)**이 아닌 **코드 변경(code fix)**이므로, 별도의 Action item 또는 독립 task로 추적되어야 한다.
- **Impact:** 중간. Finding #5가 구현 추적 없이 빠질 위험이 있다. "Most impactful fix"가 검토 이력의 한 줄 요약으로만 존재하고 구현 계획이 없다.
- **범위:** Pre-existing -- editor의 수정(Issue F)은 검토 이력에 Finding #5 **언급을 추가**한 것이지, Action item을 생성한 것이 아니다. editor의 임무 범위에 해당하지 않지만, 이 plan의 완전성에 대한 구조적 공백이다.

---

## Gemini 3.1 Pro Attack Vector Validation

Gemini가 제기한 6개 공격 중 나의 독립 분석과의 일치/불일치:

| # | Gemini 발견 | Gemini 심각도 | 내 판정 | 이유 |
|---|------------|-------------|---------|------|
| 1 | cluster_count 계산 체크리스트 모순 | CRITICAL | **FALSE POSITIVE** | Line 140은 "cluster_count 계산 + abs_floor 전달"이라고 되어 있으나, line 253의 수정 후 텍스트 "cluster_count=0 고정 전달 확인"이 이를 override한다. 두 체크리스트는 다른 Action(#1 vs #2)에 속하며, line 140은 "계산"이라는 표현이 모호하지만 맥락상 "0 고정 전달"을 의미한다. Gemini가 line 144 reference는 오류 -- 실제 line 140. |
| 2 | Empty XML wrapper | HIGH | **VALID -- Finding #1과 합치** | 내 Finding #1과 동일. |
| 3 | Fragmented hint refactor | HIGH | **VALID -- Finding #7과 합치** | 내 Finding #7과 동일. 심각도는 LOW로 하향 -- 기능 문제가 아닌 DRY 위반. |
| 4 | abs_floor forwarding gap | MEDIUM | **VALID -- Finding #2와 합치** | 내 Finding #2와 동일. |
| 5 | "모든 성공적인 쿼리" 과장 | MEDIUM | **VALID -- Finding #5와 합치** | 내 Finding #5와 동일. LOW로 하향. |
| 6 | LOC 통계 불일치 | LOW | **VALID -- Finding #3, #4, #6과 합치** | 세 가지 하위 이슈를 묶은 것. |

**Gemini CRITICAL 판정에 대한 반론:** Gemini는 line 140의 "cluster_count 계산"을 문자 그대로 해석하여 CRITICAL로 판정했다. 그러나 이 체크리스트 항목의 전체 텍스트는 "`_output_results()`에서 복합 점수 기반 cluster_count 계산 + `abs_floor` 전달 (현행 `entry.get("score", 0)` 유지 -- Deep Analysis: raw_bm25 사용 기각)"이며, 괄호 내 "현행 코드 유지" 맥락과 line 253의 Action #2 체크리스트 "cluster_count=0 고정 전달 확인 (비활성)"을 함께 읽으면, 이 항목은 "cluster_count 값을 결정하여 전달"을 의미한다 (비활성 상태에서는 0). 표현이 모호하지만 모순은 아니다. **그러나**, Gemini의 지적이 완전히 무효하지는 않다 -- "계산"이라는 단어가 구현자에게 "실제 cluster_count를 계산하라"는 인상을 줄 수 있다. 이것은 **표현 모호성 (LOW)** 수준이지 CRITICAL 모순은 아니다.

---

## 1차 검증 결과에 대한 평가

### reviewer-accuracy: PASS -- 동의
editor의 12건 수정 자체는 기술적으로 정확하다. 내 발견은 모두 수정 범위 밖의 pre-existing 이슈.

### reviewer-completeness: PASS WITH NOTES -- 동의
completeness reviewer의 pre-existing 이슈 3건 중 2건 (Line 474, Summary table)은 내 분석에서도 확인됨. 3번째 (테스트 LOC 미갱신)도 Finding #3에서 재확인.

### Gemini의 FAIL 판정 (completeness review 내 인용) -- 동의하지 않음
completeness reviewer의 반론에 동의. editor의 임무는 master-briefing의 6개 이슈 수정이었으며, pre-existing 불일치 수정은 범위 밖.

---

## 발견 요약

| # | 심각도 | 발견 | 범위 | 1차 검증에서 |
|---|--------|------|------|-------------|
| 1 | MEDIUM | Empty `<memory-context>` wrapper in tiered all-LOW case | Pre-existing | 미보고 |
| 2 | MEDIUM | `abs_floor` forwarding gap in `_output_results()` | Pre-existing | 미보고 |
| 3 | LOW | Header LOC vs cross-cutting table mismatch | Pre-existing | completeness 부분 보고 |
| 4 | LOW | 영향받는 파일 요약에 `cluster_detection_enabled` 누락 | Pre-existing | completeness Gemini 보고 |
| 5 | LOW | "모든 성공적인 쿼리" overstatement | Pre-existing | completeness 부분 보고 |
| 6 | INFO | Action #2 test estimate inflation | Pre-existing | 미보고 |
| 7 | LOW | `_emit_search_hint()` missing MEDIUM hint reason | Pre-existing | 미보고 |
| 8 | MEDIUM (주의) | Finding #5 구현 Action item 부재 | Pre-existing | 미보고 |

**Editor 수정 12건에 의해 도입된 새로운 오류: 0건**

---

## 결론

editor의 수정 작업 자체는 **정확하고 완전하며 새로운 문제를 도입하지 않았다.** 1차 검증의 PASS 판정은 유효하다.

다만, 수정 범위 밖에서 발견된 pre-existing 이슈 중 **3건의 MEDIUM** (Finding #1, #2, #8)은 구현 단계에서 혼란 또는 누락을 야기할 수 있으므로, 구현 착수 전 plan text 보완을 권장한다:

1. **Finding #1 (MEDIUM):** Action #2에 "tiered 모드 all-LOW 시 `<memory-context>` 래퍼 출력 억제" 명세 추가.
2. **Finding #2 (MEDIUM):** Line 106의 "호출 지점 변경"에 `abs_floor=abs_floor` 전달 명시.
3. **Finding #8 (MEDIUM):** Finding #5 (import hardening, ~36 LOC) 구현을 별도 Action item 또는 독립 task로 추적.
