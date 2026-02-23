# 기술적 정확성 검증 분석: plan-retrieval-confidence-and-output.md vs Deep Analysis 결과

**작성일:** 2026-02-22
**검토 대상:**
- 문서 A: `/home/idnotbe/projects/claude-memory/action-plans/plan-retrieval-confidence-and-output.md`
- 문서 B (군):
  - `temp/41-final-report.md`
  - `temp/41-finding1-3-score-domain.md`
  - `temp/41-finding2-cluster-logic.md`
  - `temp/41-v2-adversarial.md`

---

## 1. Plan 내 Deep Analysis 결과 반영 정확성

### 1-A. Line 81-93의 "핵심 수정" 블록 vs. 41-final-report.md Finding #1 최종 결정

**검증 결과: 대체로 정확하게 반영되어 있으나, 한 가지 표현 오류 존재**

plan의 line 81-93("핵심 수정" 블록)은 Finding #1의 최종 결정을 다음과 같이 서술한다:

> "최종 결정: `confidence_label()`은 복합 점수(BM25 - body_bonus)를 그대로 사용 (현재 코드 유지, 코드 변경 없음)."

41-final-report.md의 Finding #1 최종 결정(line 17)은 다음과 같다:

> "REJECTED as code change. Keep composite score for confidence_label. Calibrate abs_floor to composite domain (plan text fix). Log raw_bm25 for diagnostics only."

두 문서는 핵심 결정 -- raw_bm25 코드 변경을 기각하고 복합 점수를 유지한다 -- 에서 일치한다.

**그러나 표현 오류가 있다.** plan line 93에는 다음 내용이 포함된다:

> "외부 검증: Gemini 3.1 Pro ('검색 시스템의 계약을 위반'), Codex 5.3 ('body 증거로 부스트된 엔트리가 low로 라벨링되면 오해 소지')가 독립적으로 raw_bm25 기각을 확인."

41-v2-adversarial.md의 외부 검증 섹션(line 42-43)에서 Gemini 3.1 Pro의 원문 인용은 다음과 같다:

> "You have broken the contract of the retrieval system."

plan의 한글 표현 "검색 시스템의 계약을 위반"은 의미상 근사하나 원문과 완전히 동일한 번역이 아니다. 또한 Codex 5.3의 원문 인용(41-v2-adversarial.md line 43)은 다음과 같다:

> "Entries boosted by strong body evidence can be top-ranked but labeled 'low,' which is misleading."

plan에서는 이를 "body 증거로 부스트된 엔트리가 'low'로 라벨링되면 오해 소지"로 요약했는데, 핵심 맥락("top-ranked but labeled 'low'"이라는 역전 현상)이 생략되어 있다. 이는 사소한 요약 손실이다.

**결론적으로 Finding #1 최종 결정의 반영은 사실상(substantively) 정확하다.** 기각 이유(Ranking-Label Inversion, NEW-4), 최종 결정(복합 점수 유지), raw_bm25의 진단 용도 한정, abs_floor 도메인 재교정 지시 모두 plan에 올바르게 포함되어 있다.

---

### 1-B. Line 73-78의 클러스터 감지 내용 vs. 41-finding2-cluster-logic.md 수학적 증명

**검증 결과: 결론은 정확하나 수학적 증명의 핵심 논리 일부가 단순화되어 표현됨**

plan line 73-78의 클러스터 관련 서술을 항목별로 검증한다.

**항목 1 (line 74):**
> "원안 임계치(`>= 3`)는 `max_inject=3`(기본값)에서 모든 성공적인 쿼리에 발동하는 논리 오류 (tautology)."

41-finding2-cluster-logic.md의 수학적 증명(Section 2)은 이를 더 정확하게 규정한다: 모든 성공적인 쿼리가 아니라, "3개 결과를 반환하며 그 3개 모두 ratio > 0.90인 경우"에 발동한다. apply_threshold의 25% noise floor로 인해 소규모 코퍼스에서는 이 조건이 70% 이상의 빈도로 성립한다(Section 2.4). plan의 "모든 성공적인 쿼리" 표현은 약간 과장되어 있다. 그러나 실질적 의미에서 이 둘의 차이는 크지 않다.

**항목 2 (line 75):**
> "수정안 `cluster_count > max_inject`도 동일한 dead code: 잘린 후 집합에서 C > max_inject는 성립 불가."

41-finding2-cluster-logic.md Section 3.2 및 Option A의 정식 증명과 일치한다:
> "C <= N <= m, therefore C > m is impossible"

이 부분은 수학적으로 정확하게 반영되어 있다.

**항목 3 (line 76):**
> "유일한 유효 구현: Option B (pre-truncation counting) -- 잘리기 전 전체 결과에서 클러스터 비율 계산. 그러나 비활성 기능에 대한 구현은 불필요한 엔지니어링."

41-finding2-cluster-logic.md Section 3.1의 결론표 및 Section 4의 권고("the only mathematically sound option")와 일치한다. 단, plan에서는 Option B가 "다른 질문을 측정한다"는 중요한 뉘앙스(Section 3.3, "measures a different question")를 생략하고 있다. Option B는 post-truncation 집합에서 top-K 결과의 유사성이 아닌 전체 후보 풀의 밀도를 측정하므로 의미론적으로 다르다.

**항목 4 (line 77):**
> "최종 결정: 기능 비활성 유지 (`cluster_detection_enabled: false`). 향후 활성화 시 pre-truncation counting으로 구현."

41-finding2-cluster-logic.md Section 4의 Primary Recommendation과 일치한다.

**결론: 클러스터 관련 내용은 핵심 수학적 결론에서 정확하나, "모든 성공적인 쿼리에 발동"이라는 표현이 다소 과장되어 있으며, Option B의 의미론적 한계가 생략되어 있다.** 이는 실행 판단에 영향을 주지 않는 수준의 단순화이다.

---

### 1-C. Line 491의 검토 이력 vs. 41-final-report.md 최종 결과

**검증 결과: 정확하게 반영됨**

plan line 491의 검토 이력 테이블:

```
| Deep Analysis (7-agent) | raw_bm25 code change REJECTED | Ranking-label inversion (NEW-4) breaks tiered output. Composite score is intentional. Cluster tautology proven dead code. |
```

41-final-report.md의 Executive Summary와 Finding-by-Finding Analysis에서 확인한 내용:

- Finding #1의 최종 결정(line 59): "REJECT the 2-line code change." -- plan과 일치
- NEW-4의 역할(line 87): ranking-label inversion이 raw_bm25 기각의 원인 -- plan과 일치
- Finding #2의 최종 결정(line 70): "Keep disabled. Document the tautology." -- "Cluster tautology proven dead code"와 의미 일치
- 7개 에이전트 수행은 41-final-report.md line 4("7 agents across 5 phases")로 확인됨

**이 항목은 정확히 반영되어 있다.**

---

## 2. Plan에서 반영되지 않았거나 불일치하는 부분

### 2-A. NEW-1 (apply_threshold noise floor distortion) 반영 여부

**결론: plan에 명시적 언급 없음 -- 반영 부족**

41-final-report.md의 Newly Discovered Issues 테이블(line 29):

```
| NEW-1 | apply_threshold noise floor distortion | LOW-MEDIUM | Deferred -- let PoC #5 data inform |
```

41-finding1-3-score-domain.md Section 8.1에서 NEW-1을 상세히 기술한다:

- apply_threshold의 25% noise floor는 복합 점수를 기준으로 계산됨
- body_bonus가 높은 entry (예: raw=-2.0, bonus=3, composite=-5.0)가 베스트일 때 noise floor = 1.25
- body_bonus=0인 raw=-1.0 entry(composite=-1.0)는 noise floor 미만으로 폐기됨
- 이는 유효한 BM25 매칭을 조용히(silently) 폐기하는 문제

`plan-retrieval-confidence-and-output.md` 전체를 검토한 결과, NEW-1은 어디에도 언급되지 않는다. plan의 Action #1 Section의 "변경하지 않는 파일" 표(line 437)에서 `memory_search_engine.py`에 대해 "apply_threshold()는 수정 불필요 -- 독립적 선택 임계치"로만 기술하고 있으며, noise floor distortion이라는 별도 추적 대상 이슈의 존재를 기록하지 않았다.

**평가:** 이것은 실제 반영 공백이다. NEW-1은 LOW-MEDIUM severity로 분류되어 있고 "Deferred"로 처리되었으나, plan에 별도 추적 항목("TODO: track separately")이나 주석 없이 완전히 누락되었다. plan 파일 자체가 구현 계획이므로, 알려진 관련 이슈를 "비활성 상태로라도" 기록하는 것이 이상적이다. plan의 주석(line 437)은 `memory_search_engine.py`를 수정하지 않는 이유만 기술할 뿐, noise floor distortion의 존재 자체를 인식하지 못한 것처럼 보인다.

---

### 2-B. NEW-4 (Ranking-label inversion) 문서화 충분성

**결론: 핵심 내용은 반영되어 있으나, 조건 범위가 불완전하게 기술됨**

plan line 87에서 NEW-4를 기술한다:

> "Deep Analysis 결과 -- Ranking-Label Inversion (NEW-4, HIGH): `raw_bm25` 사용 시 랭킹-라벨 역전 발생."

41-v2-adversarial.md의 NEW-4 정의(line 247-266)에서 severity = HIGH, scope 조건 3가지를 명시한다:

1. raw_bm25 fix가 적용된 경우
2. entry가 약한 title/tag 매칭(low raw_bm25)이지만 강한 body 매칭(high body_bonus)인 경우
3. Tiered output mode가 활성화된 경우(Action #2)

plan에서는 이 세 가지 조건 중 3번("tiered output 활성화 시에만 행동 영향 발생")을 명확히 기술하지 않았다. 41-final-report.md line 62에는 다음이 명시되어 있다:

> "Severity downgrade: CRITICAL -> HIGH. Labels are informational metadata in the LLM context (not retrieval-critical), and tiered output defaults to 'legacy' (no behavioral impact)."

즉 legacy 모드(기본값)에서 NEW-4의 severity는 행동에 영향을 미치지 않는다. plan은 이 중요한 모드 의존성을 명시적으로 문서화하지 않았다.

또한 41-v2-adversarial.md는 대안 해결책 3가지(line 47-51: reject fix / add separate attribute / sub-linear scaling)를 제시했는데, plan에서는 이 중 Option 1(reject fix)만 선택 결과로 기록하고 나머지 대안들은 언급하지 않는다. 이는 향후 "왜 이 결정이 내려졌는가"를 추적할 때 컨텍스트 손실이 된다.

**평가:** NEW-4는 plan에 반영되어 있으나 불완전하다. 구체적으로 "tiered 모드 비활성(기본값 legacy)에서는 behavioral impact 없음"이라는 조건부 severity 정보와 대안 검토 이력이 누락되어 있다.

---

## 3. 기술적 세부사항 정확성 검증

### 3-A. Line 62의 점수 예시 실제 BM25 동작과의 부합성

plan line 62:

> "'api payload' 같은 쿼리로 scores `-4.10, -4.05, -4.02, -4.00, -3.98` 반환 시 모두 ratio > 0.95 -> 모두 'high'"

**검증:**

BM25 점수의 특성을 실제 코드와 대조한다. `memory_search_engine.py:261-289`의 `apply_threshold()`는:
1. 점수를 내림차순 정렬 (더 음수 = 더 좋음, line 281)
2. 25% noise floor 적용 (line 284-287)

예시 점수 `-4.10, -4.05, -4.02, -4.00, -3.98`에서:
- best_abs = abs(-4.10) = 4.10
- noise_floor = 4.10 * 0.25 = 1.025
- 모든 점수가 abs > 1.025를 만족하므로 필터 통과
- 그런데 `apply_threshold()`는 `results[:limit]`으로 max_inject개만 반환함 (기본 max_inject=3)
- 따라서 실제로 confidence_label()에 전달되는 것은 5개가 아니라 3개 (`-4.10, -4.05, -4.02`)

예시에서 5개 결과를 나열한 것은 max_inject 잘림을 무시한 것이다. 이는 클러스터 감지 설명의 맥락(max_inject 이전의 전체 결과 집합)에서라면 타당하지만, confidence_label()의 실제 입력은 max_inject개로 이미 잘린 집합이다.

ratio 계산: `-4.02 / -4.10 = 0.980 > 0.95` -- 예시에서의 수치는 실제 BM25 스케일과 내적으로는 일관성 있다. 소규모 코퍼스에서 관련 쿼리에 대한 BM25 점수가 이 범위에 몰릴 수 있음은 41-finding2-cluster-logic.md Section 2.4의 경험적 추정("probability > 70%")과 부합한다.

**결론: 예시의 수치 자체는 BM25 동작과 일관성이 있으나, "5개 결과"라는 예시는 max_inject=3 기본값 하에서 confidence_label()이 실제로 받는 집합 크기를 오도할 수 있다.** 이 예시는 apply_threshold() 잘림 전 전체 결과를 묘사하는 것으로 해석해야 정확하다. plan 자체에서 이 구분이 명시적이지 않아 혼동의 여지가 있다.

---

### 3-B. Line 102의 abs_floor 권장 범위 "1.0-3.0" 복합 점수 도메인에서의 합리성

plan line 102:

> "`abs_floor`: 절대 하한선. `abs(best_score) < abs_floor`이면 'high' 불가. 복합 점수 도메인 기준 교정 (일반 코퍼스에서 권장 시작값 1.0-3.0)"

**검증:**

복합 점수 도메인의 범위는 `BM25 - body_bonus`로 정의된다. 구체적으로:
- raw BM25 점수: FTS5 BM25는 음수 (더 음수 = 더 좋음), 소규모 코퍼스에서 일반적으로 -1.0 ~ -15.0 범위
- body_bonus: 0-3 (정수, `min(3, len(body_matches))`, `memory_retrieve.py:247`)
- 복합 점수: raw_bm25 - body_bonus, 예: -2.0 - 3 = -5.0, abs = 5.0

41-finding1-3-score-domain.md Section 3에서 analyst는 abs_floor를 복합 점수 도메인으로 교정하도록 권고하면서도 구체적 범위는 제시하지 않았다. 41-final-report.md line 60에서는 다음을 명시한다:

> "abs_floor should be calibrated to composite domain. The plan should document that abs_floor operates on composite scores (BM25 - body_bonus, range approximately 0-15 for typical corpora)"

즉 Deep Analysis는 복합 점수의 일반적 범위를 "0-15"로 추정했다. plan의 권장 시작값 "1.0-3.0"은 이 0-15 범위의 하위 20%에 해당하는 값이다.

**합리성 분석:**

abs_floor의 목적은 "약한 단일 매칭"이 항상 "high"로 분류되는 것을 방지하는 것이다. 0-15 복합 점수 범위에서:
- abs_floor = 1.0: 복합 점수 < 1.0인 결과만 "high" 불가로 캡. 즉 BM25 점수가 대략 -1.0 이내이고 body_bonus가 0인 경우에만 캡 발동. 이는 매우 약한 하한선이다.
- abs_floor = 3.0: 복합 점수 < 3.0인 결과를 "high" 불가로 캡. body_bonus=0인 경우 raw BM25가 -3.0보다 약한(절대값 작은) 매칭을 제한한다.

**중요한 잠재적 문제:**

abs_floor 조건이 `abs(best_score) < abs_floor`로 설정되어 있다 (plan line 102). 이 조건은 **개별 entry의 점수**가 아니라 **최고 점수(best_score)**를 기준으로 한다. 즉, 단 하나의 약한 결과만 있을 때 "high"가 아닌 레이블을 부여하는 것이 목적이라면, `abs(score) < abs_floor`가 아닌 `abs(best_score) < abs_floor`를 사용하는 것이 맞다(모든 결과를 한번에 캡).

그런데 best_score는 현재 복합 점수(`entry.get("score", 0)`, memory_retrieve.py line 283)로 계산된다. 소규모 코퍼스에서 body_bonus=3인 강한 매칭이 있으면 best_score의 절대값이 5 이상이 될 수 있어, abs_floor=3.0이 발동하지 않는다. 이 경우 abs_floor의 목적(약한 단일 매칭 방지)이 달성되지 않는다.

**결론: abs_floor "1.0-3.0" 범위는 복합 점수 도메인의 전체 스케일(0-15)에서 보수적으로 설정된 초기값으로서 합리적이다.** 그러나 이 범위가 어떤 데이터에 기반한 것인지는 명시되지 않았으며, plan 자체에서도 "로깅 인프라 구축 후 데이터 기반 조정"(line 68)을 권고하고 있어 현재 값은 임시 추정치임을 인정한다. 권장 범위가 0-15 스케일에서 논리적으로 문제가 없는 범위이므로 기술적 오류라고 보기는 어렵다. 다만 실제 코퍼스 데이터 없이는 이 범위의 효과를 예측하기 어렵다는 한계가 있다.

---

## 4. 종합 평가

### 일치 항목 (Aligned)

| 항목 | 평가 |
|------|------|
| Finding #1 최종 결정(raw_bm25 기각) | 정확히 반영 |
| Finding #2 수학적 증명 핵심 결론 | 정확히 반영 (약간의 단순화) |
| line 491 검토 이력 테이블 | 정확히 반영 |
| NEW-4 발생 이유(Ranking-Label Inversion) | 반영됨 |
| 복합 점수 유지 결정의 근거 | 정확히 반영 |
| Option A (`cluster_count > max_inject`)의 dead code 증명 | 정확히 반영 |

### 불일치/누락 항목 (Misaligned or Missing)

| 항목 | 심각도 | 설명 |
|------|--------|------|
| NEW-1 (apply_threshold noise floor distortion) | 중간 | plan에 완전히 누락됨. 관련 이슈로서 추적이 필요한 사항 |
| NEW-4의 조건부 severity (legacy 모드에서는 behavioral impact 없음) | 낮음 | 모드 의존성 미기술 -- 실행에 영향 없으나 컨텍스트 손실 |
| NEW-4의 대안 해결책 검토 이력 | 낮음 | 3가지 대안 중 선택 결과만 기록, 검토 과정 생략 |
| line 62의 5개 결과 예시 | 낮음 | max_inject=3 잘림 이전/이후 구분이 불명확 |
| "모든 성공적인 쿼리에 발동" 표현 | 낮음 | 더 정확히는 "대다수의 3-결과 쿼리에 발동" |
| abs_floor 조건 로직의 미묘함 | 낮음 | best_score 기반 캡의 의미론적 설명 불충분 |

### 최종 판단

plan-retrieval-confidence-and-output.md는 Deep Analysis 결과의 핵심 결정들을 **실질적으로(substantively) 정확하게** 반영하고 있다. 구현자가 이 plan을 따라 작업할 경우 Deep Analysis의 주요 의도와 일치하는 코드를 생성할 수 있다.

단, NEW-1(apply_threshold noise floor distortion)의 완전한 누락은 향후 이 이슈를 별도 추적하려 할 때 plan을 참조하면 발견할 수 없다는 문제가 있다. 이 이슈는 41-final-report.md에 공식 기록되어 있으므로, plan에 "NEW-1: apply_threshold noise floor distortion은 별도 추적 -- temp/41-finding1-3-score-domain.md Section 8.1 참조"와 같은 참조 항목을 추가하는 것이 이상적이다.
