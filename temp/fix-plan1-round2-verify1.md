# 독립 검증 #1: Round 2 수정 (15건) 정확성 + 일관성 검증

**검증자:** 독립 검증자 #1 (Claude Opus 4.6)
**날짜:** 2026-02-23
**대상:** `action-plans/plan-retrieval-confidence-and-output.md` (Round 2 수정 후)
**참조 문서:**
- `temp/fix-plan1-round2-working.md` (수정 기록)
- `temp/fix-plan1-review2-adversarial.md` (원본 이슈 -- adversarial)
- `temp/fix-plan1-review2-fresh.md` (원본 이슈 -- fresh-eyes)

---

## 최종 판정: PASS

15건 모두 정확하고 일관적이다. 새로운 불일치는 도입되지 않았다. 사소한 관찰 1건(NOTE-1)이 있으나 판정에 영향을 주지 않는다.

---

## A. 각 수정의 정확성 검증 (15건)

### MEDIUM 3건

#### M1: Tiered all-LOW 시 빈 wrapper 억제 명세 (plan line 215-216)

- **원본 이슈 (adversarial #1):** tiered 모드에서 모든 결과가 LOW일 때 `_output_results()`가 빈 `<memory-context></memory-context>` 래퍼를 출력하는 설계 공백
- **수정 내용:** "tiered 모드에서 모든 결과가 LOW일 경우, `_output_results()`는 `<memory-context>` 래퍼를 출력하지 않고 `_emit_search_hint("all_low")`만 호출하여 빈 래퍼 주입을 방지한다." + 체크리스트 항목 추가 (line 260)
- **정확성:** CORRECT. `_output_results()` 내부에서 래퍼 억제를 처리하는 것은 설계적으로 타당하다. confidence 계산 로직이 `_output_results()` 내부에 있으므로, 호출자가 이를 중복 계산하지 않아도 된다.
- **코드 교차 검증:** 현재 `_output_results()` (line 285, 301)는 무조건 wrapper를 출력한다. 수정 명세는 이 동작을 tiered 모드에서 조건부로 변경하라는 것으로, 구현자에게 명확한 지침을 제공한다.
- **체크리스트 일치:** line 260 "모든 결과 LOW 시 `<memory-context>` 래퍼 생략, `_emit_search_hint("all_low")`만 호출"은 본문 명세와 정확히 일치한다.
- **판정: PASS**

#### M2: abs_floor -> confidence_label() 전달 명시 (plan line 108, 142)

- **원본 이슈 (adversarial #2):** line 106에서 `confidence_label()` 호출 시 `cluster_count=0`만 명시하고 `abs_floor` 전달을 언급하지 않음. line 140의 "abs_floor 전달" 대상이 불명확.
- **수정 내용:**
  - Line 108: "confidence_label() 호출 시 `abs_floor=abs_floor`, `cluster_count=0` 전달"
  - Line 142: "cluster_count=0 고정 전달 + `abs_floor`를 `confidence_label()`에 전달"
- **정확성:** CORRECT. 데이터 흐름이 이제 명확하다: main() -> abs_floor 설정 파싱 -> `_output_results(abs_floor=...)` -> 내부에서 `confidence_label(score, best_score, abs_floor=abs_floor, cluster_count=0)` 호출.
- **코드 교차 검증:**
  - `confidence_label()` 시그니처 변경 (plan line 98-101): `abs_floor: float = 0.0` 파라미터 존재. MATCH.
  - `_output_results()` 시그니처 변경 (plan line 245-247): `abs_floor: float = 0.0` 파라미터 존재. MATCH.
  - 호출 체인: main() -> _output_results(abs_floor) -> confidence_label(abs_floor=abs_floor). 완전한 파이프라인.
- **판정: PASS**

#### M3: Finding #5 미추적 구현 노트 (plan line 497)

- **원본 이슈 (adversarial #8):** Deep Analysis Finding #5 (import hardening, ~36 LOC)가 검토 이력 한 줄 요약으로만 존재하고, 어떤 Action item에서도 구현이 추적되지 않음.
- **수정 내용:** 검토 이력 아래에 "미추적 구현 사항" 단락 추가. Finding #5는 Actions #1-#4 범위 밖이므로 별도 plan (`plan-import-hardening.md`)으로 추적 필요. "Most impactful fix"로 우선 구현 권장.
- **정확성:** CORRECT. Finding #5는 `memory_retrieve.py`와 `memory_search_engine.py`의 module-level import hardening으로, 신뢰도/출력 개선과는 무관한 인프라 안정성 수정이다. 별도 plan으로 분리하는 것은 scope 관리 원칙에 부합한다.
- **판정: PASS**

### LOW/INFO 7건 + Fresh 2건 + 추가 3건

#### L1: Header LOC 통일 (plan line 11)

- **원본 이슈 (adversarial #3, fresh A1/D4):** Header "~60-80 + ~100-200"이 상세 테이블 "~66-105 + ~130-240"과 불일치.
- **수정 내용:** Header를 `~66-105 LOC (코드) + ~130-240 LOC (테스트)`로 변경.
- **정확성:** CORRECT. 상세 테이블 (lines 457-466) 수치와 정확히 일치:
  - 코드: 20-35 + 40-60 + 6-10 = 66-105. MATCH.
  - 테스트: 35-65 + 80-150 + 15-25 = 130-240. MATCH.
- **판정: PASS**

#### L2: config 목록에 cluster_detection_enabled 추가 (plan line 431)

- **원본 이슈 (adversarial #4):** 영향받는 파일 요약 테이블에서 `assets/memory-config.default.json` 변경 내용이 `confidence_abs_floor`, `output_mode`만 기재하고 `cluster_detection_enabled` 누락.
- **수정 내용:** `confidence_abs_floor`, `cluster_detection_enabled`, `output_mode` 추가로 변경.
- **정확성:** CORRECT. Action #1 설정 변경 (lines 124-131)에서 `cluster_detection_enabled: false`가 명시되어 있으므로, 요약 테이블에도 반영되어야 한다.
- **판정: PASS**

#### L3: "모든" -> "대다수(70%+)" (plan line 74)

- **원본 이슈 (adversarial #5):** `temp/41-finding2-cluster-logic.md` Section 2.4에서 확률이 "> 70%"로 명시되어 있으나, plan은 "모든 성공적인 쿼리"라고 과장.
- **수정 내용:** "대다수(70%+)의 성공적인 쿼리에 발동하는 논리 오류"
- **정확성:** CORRECT. `temp/41-finding2-cluster-logic.md` line 67: "the probability that all 3 have `ratio > 0.90` is **> 70%**". "대다수(70%+)"는 이 수치를 정확히 반영한다.
- **판정: PASS**

#### L4: 테스트 추정 ~15-30 -> ~15-20 (plan line 225)

- **원본 이슈 (adversarial #6):** 상세 체크리스트 합계 ~15개인데 상한이 30으로 과도하게 팽창.
- **수정 내용:** `~15-20개`로 변경.
- **정확성:** CORRECT. 체크리스트 합계 (lines 265-268): ~6 + ~4 + ~2 + ~3 = ~15. 상한 20은 edge case 추가를 위한 합리적 여유분이다. 30은 2배로 과도했다.
- **판정: PASS**

#### L5: _emit_search_hint에 medium_present reason 추가 (plan lines 307-319)

- **원본 이슈 (adversarial #7):** 헬퍼 함수가 "no_match"과 "all_low"만 지원하고, Action #2의 MEDIUM 검색 유도 문구를 포함하지 않아 DRY 위반.
- **수정 내용:** `elif reason == "medium_present":` 분기 추가 (lines 313-315).
- **정확성:** CORRECT. Action #2 (line 210-212)의 MEDIUM 검색 유도 문구와 Action #3의 헬퍼 함수가 이제 통합되어 DRY 원칙을 충족한다. 호출 지점 (line 261)도 체크리스트에 추가되었다.
- **판정: PASS**

#### L6: 구현 결론 1줄 요약 추가 (plan line 83)

- **원본 이슈 (fresh B1):** 역사적 논쟁 (Score Domain Paradox, 거부된 제안 등)이 가독성을 저하시킴. 구현 요약이 먼저 나와야 함.
- **수정 내용:** blockquote 앞에 1줄 요약 추가: "> **구현 결론:** `confidence_label()`은 복합 점수(BM25 - body_bonus)를 그대로 사용한다 (코드 변경 없음). 아래는 이 결정에 이른 검토 이력이다."
- **정확성:** CORRECT. 구현자가 상세 이력을 읽기 전에 핵심 결론을 파악할 수 있다. 결론 내용도 plan의 나머지 부분과 일치 (line 91: "복합 점수를 그대로 사용", line 103: "현행 코드 유지").
- **판정: PASS**

#### L7: body_bonus 정의 추가 (plan line 85)

- **원본 이슈 (fresh B3):** `body_bonus` 용어가 정의 없이 사용됨.
- **수정 내용:** "body_bonus`는 본문 토큰 매칭 보너스(0-3점, `score_with_body()` line 247에서 계산)" 추가.
- **정확성:** CORRECT.
- **코드 교차 검증:** `memory_retrieve.py` line 247: `result["body_bonus"] = min(3, len(body_matches))`. `min(3, ...)` 확인 -- 0-3점 범위 MATCH. line 247 MATCH.
- **판정: PASS**

#### F1: abs_floor domain 비율 설명 추가 (plan line 68)

- **원본 이슈 (fresh B2):** abs_floor 1.0-3.0과 0-15 도메인의 관계가 불명확.
- **수정 내용:** "(0-15 범위에서 하위 약 7-20%, 약한 매칭 tail 대상)" 추가.
- **정확성:** CORRECT. 수학적 검증: 1.0/15 = 6.67% (약 7%), 3.0/15 = 20.0%. "약 7-20%"는 정확하다.
- **판정: PASS**

#### F2: Gate E (Action #4 검증 게이트) 추가 (plan line 453)

- **원본 이슈 (fresh C4):** Action #4에 검증 게이트 기준이 없음.
- **수정 내용:** "Gate E (Action #4 후): Agent hook이 `feat/agent-hook-poc` 브랜치에서 정상 로드되고, 4가지 핵심 질문(레이턴시, 컨텍스트 주입 메커니즘, Plugin 호환성, 하이브리드 연쇄)에 대한 답변이 `temp/agent-hook-poc-results.md`에 문서화됨"
- **정확성:** CORRECT. 4가지 핵심 질문은 Action #4 관련 정보 (lines 369-373)의 정확한 반영이다:
  1. 레이턴시 (line 370) - MATCH
  2. 컨텍스트 주입 메커니즘 (line 371) - MATCH
  3. Plugin 호환성 (line 372) - MATCH
  4. 하이브리드 연쇄 (line 373) - MATCH
- **판정: PASS**

#### 추가: Action #2 체크리스트에 all-LOW wrapper 생략 + medium_present 항목 (plan lines 260-261)

- **수정 내용:** 두 개의 체크리스트 항목 추가:
  - line 260: "tiered 모드: 모든 결과 LOW 시 `<memory-context>` 래퍼 생략, `_emit_search_hint("all_low")`만 호출"
  - line 261: "tiered 모드: MEDIUM 결과 존재 시 `_emit_search_hint("medium_present")` 호출"
- **정확성:** CORRECT. M1과 L5 수정의 체크리스트 반영이다. 본문 명세 (lines 210, 215-216)와 일관적이다.
- **판정: PASS**

#### 추가: medium_present 분기 조건 명시 (plan line 210)

- **수정 내용:** `_emit_search_hint("medium_present")` 호출의 분기 조건 명시: "`not any(high) and any(medium)` 또는 MEDIUM 결과가 1개 이상일 때"
- **정확성:** MOSTLY CORRECT. (NOTE-1 참조) 두 조건이 "또는"로 연결되어 있으나, 의미적으로 약간 모호하다. 첫 번째 조건 (`not any(high) and any(medium)`)은 HIGH가 없고 MEDIUM이 있을 때만 발동하고, 두 번째 조건 ("MEDIUM 결과가 1개 이상")은 HIGH 존재 여부와 무관하게 발동한다. 그러나 이것은 구현자에게 "두 가지 가능한 정책 중 택일"을 제시하는 것으로 해석 가능하며, 구현 시점에 결정할 설계 세부사항이다.
- **판정: PASS (NOTE-1)**

---

## B. 수정 간 일관성 검증

### B1. M1 <-> L5 연계

- M1은 all-LOW 시 wrapper 억제 + `_emit_search_hint("all_low")` 호출을 명시한다.
- L5는 `_emit_search_hint()` 헬퍼에 `"medium_present"` reason을 추가한다.
- `"all_low"` reason은 이미 Round 1에서 추가되어 있었으므로 (원본 plan의 Action #3), M1과 L5는 서로 보완적이며 모순 없다.
- **판정: 일관적**

### B2. M2 <-> 시그니처 명세 연계

- M2는 `abs_floor`가 `_output_results()` -> `confidence_label()`로 전달됨을 명시한다.
- plan line 98-101의 시그니처: `abs_floor: float = 0.0` 파라미터 존재.
- plan line 245-247의 시그니처: `abs_floor: float = 0.0` 파라미터 존재.
- **판정: 일관적**

### B3. L1 <-> 상세 테이블

- Header (line 11): `~66-105 + ~130-240`
- 상세 테이블 (lines 457-466): 코드 소계 `~66-105`, 테스트 소계 `~130-240`
- **판정: 일관적 (정확히 일치)**

### B4. L4 <-> 체크리스트 합계

- 본문 추정 (line 225): `~15-20개`
- 체크리스트 합계 (lines 265-268): ~6 + ~4 + ~2 + ~3 = ~15
- 15 < 20, 여유분 5개는 합리적.
- **판정: 일관적**

### B5. L5 <-> M1 <-> 체크리스트

- `_emit_search_hint()` 지원 reasons: `"no_match"`, `"all_low"`, `"medium_present"` (3가지)
- M1은 `"all_low"` 호출을 명시, L5는 `"medium_present"` 호출을 명시
- 체크리스트 (line 260): `_emit_search_hint("all_low")` - MATCH
- 체크리스트 (line 261): `_emit_search_hint("medium_present")` - MATCH
- **판정: 일관적**

### B6. F2 <-> Action #4 핵심 질문

- Gate E의 4가지 기준과 Action #4 관련 정보 (lines 369-373)의 4가지 핵심 질문이 1:1 대응.
- **판정: 일관적**

### B7. 기존 텍스트(Round 1 수정 포함)와의 일관성

- Round 1에서 수정된 12건과 Round 2의 15건 사이에 충돌 없음.
- Round 1의 주요 수정 (cluster_count 의미론, abs_floor 코퍼스 의존성 경고, 롤백 수 정정 등)은 Round 2 수정에 의해 영향받지 않음.
- **판정: 일관적**

---

## C. 코드 교차 검증

### C1. 라인 번호 정확성 (주요 참조)

| Plan 참조 | 주장 | 실제 코드 | 상태 |
|-----------|------|----------|------|
| `confidence_label()` line 161-174 | 함수 정의 | `memory_retrieve.py:161-174` | MATCH |
| `score_with_body()` line 247 | body_bonus 계산 | `memory_retrieve.py:247` (`min(3, len(body_matches))`) | MATCH |
| `raw_bm25` line 256 | 보존 | `memory_retrieve.py:256` (`r["raw_bm25"] = r["score"]`) | MATCH |
| `r["score"]` 변이 line 257 | body_bonus 적용 | `memory_retrieve.py:257` (`r["score"] = r["score"] - r.get("body_bonus", 0)`) | MATCH |
| `_output_results()` line 262-301 | 함수 정의 | `memory_retrieve.py:262-301` | MATCH |
| `conf = confidence_label(...)` line 299 | 호출 지점 | `memory_retrieve.py:299` | MATCH |
| `<memory-context>` wrapper line 285, 301 | 출력 | `memory_retrieve.py:285, 301` | MATCH |
| Hint line 458, 495, 560 | `<!-- -->` 형식 | `memory_retrieve.py:458, 495, 560` | MATCH |
| `apply_threshold()` line 283-288 | noise floor | `memory_search_engine.py:283-289` (end off by 1) | CLOSE |
| `main()` config parsing line 353-384 | 설정 파싱 | `memory_retrieve.py:349-384` (start off by 4) | CLOSE |

**결과:** 10/10 참조가 유효. 2건은 1-4줄 차이로 CLOSE지만, 올바른 함수/블록을 가리킴.

### C2. body_bonus 범위 검증

- Plan (line 85): "0-3점"
- Code (line 247): `min(3, len(body_matches))` -- `len(body_matches)`는 0 이상, `min(3, x)`는 0-3 범위. MATCH.

### C3. abs_floor 도메인 범위 검증

- Plan (line 68): "0-15 범위"
- 복합 점수 = BM25 - body_bonus. BM25 점수는 코퍼스에 따라 변동하나 일반적으로 0 ~ -12 범위 (abs 0-12). body_bonus 0-3 추가 시 abs 0-15 범위는 합리적 추정.
- REASONABLE.

---

## D. 외부 검증

### Gemini 3.1 Pro (pal clink)

Gemini 3.1 Pro에 15건 수정을 제출하여 독립 검증을 수행했다. 결과:

- **M1:** "sound and correct design decision" -- `_output_results()` 내부에서 처리하는 것이 단일 진실의 원천을 유지한다고 확인.
- **M2:** "correctly resolves the data flow gap" -- abs_floor 파이프라인이 완전하다고 확인.
- **M3:** "Highly appropriate" -- scope 분리가 단일 책임 원칙에 부합한다고 확인.
- **수치 검증:** F1의 7-20% 수학적 정확성 확인 (1/15 = 6.67%, 3/15 = 20%).
- **L1 LOC 합산:** 정확 확인.
- **L3 70%+:** "technically precise" 확인.
- **전체 판정:** "No contradictions introduced. The plan is technically sound, mathematically accurate, and internally consistent."

---

## E. 관찰 사항 (Notes)

### NOTE-1: medium_present 분기 조건의 미묘한 모호성 (Severity: INFO)

**위치:** plan line 210

**내용:** `_emit_search_hint("medium_present")` 호출 조건이 "`not any(high) and any(medium)` 또는 MEDIUM 결과가 1개 이상일 때"로 명시되어 있다. "또는"로 연결된 두 조건은 의미적으로 다르다:
- 조건 A: HIGH가 없고 MEDIUM이 있을 때만 hint 발생 (HIGH 결과가 있으면 침묵)
- 조건 B: MEDIUM이 1개 이상이면 무조건 hint 발생 (HIGH 존재 여부 무관)

조건 B는 조건 A의 상위 집합(HIGH가 있어도 MEDIUM이 있으면 hint 발생)이므로, 둘을 "또는"로 연결하면 사실상 조건 B가 적용된다. 이것은 구현 시점에 결정할 설계 세부사항으로 해석 가능하지만, 구현자에게 약간의 혼란을 줄 수 있다.

**영향:** 없음. 어느 쪽을 택하든 기능적 문제는 아니다. 구현 시점에 자연스럽게 결정될 사안이다.

**판정에 대한 영향:** 없음. PASS 유지.

---

## F. 검증 요약

### 정확성 (A)

| # | 수정 | 원본 이슈 해결 | 기술적 정확성 | 수치 일관성 | 판정 |
|---|------|--------------|-------------|-----------|------|
| M1 | all-LOW wrapper 억제 | YES | YES | N/A | PASS |
| M2 | abs_floor 전달 명시 | YES | YES | N/A | PASS |
| M3 | Finding #5 미추적 노트 | YES | YES | N/A | PASS |
| L1 | Header LOC 통일 | YES | YES | 66-105 + 130-240 = MATCH | PASS |
| L2 | cluster_detection_enabled 추가 | YES | YES | N/A | PASS |
| L3 | "모든" -> "대다수(70%+)" | YES | YES | 70%+ = MATCH (finding2 ref) | PASS |
| L4 | 테스트 추정 조정 | YES | YES | 15-20 vs sum ~15 = OK | PASS |
| L5 | medium_present reason 추가 | YES | YES | N/A | PASS |
| L6 | 구현 결론 1줄 요약 | YES | YES | N/A | PASS |
| L7 | body_bonus 정의 | YES | YES | 0-3점 = MATCH (code L247) | PASS |
| F1 | abs_floor domain 비율 | YES | YES | 7-20% = MATCH (1/15, 3/15) | PASS |
| F2 | Gate E 추가 | YES | YES | 4 questions = MATCH | PASS |
| 추가1 | 체크리스트 항목 추가 | YES | YES | N/A | PASS |
| 추가2 | medium_present 분기 조건 | YES | YES (NOTE-1) | N/A | PASS |
| 추가3 | (추가2에 포함) | -- | -- | -- | -- |

### 일관성 (B)

- 15건 수정 간 모순: **0건**
- 기존 텍스트와의 새로운 불일치: **0건**
- Round 1 수정과의 충돌: **0건**

### 코드 교차 검증 (C)

- 라인 번호 참조: **10/10 유효** (2건 1-4줄 오차)
- body_bonus 범위: **MATCH**
- abs_floor 도메인: **REASONABLE**

### 외부 검증 (D)

- Gemini 3.1 Pro: **전량 PASS, 수치 정확성 독립 확인**

---

## 최종 판정: PASS

15건의 Round 2 수정은 모두 원본 이슈를 정확히 해결하고, 기술적으로 정확하며, 서로 일관적이고, 기존 텍스트와 충돌하지 않는다. 사소한 관찰 1건(NOTE-1: medium_present 분기 조건의 미묘한 모호성)이 있으나 구현을 방해하지 않는 INFO 수준이다.
