# Deep Analysis <-> PoC 실험 계획 연결 분석

**날짜:** 2026-02-22
**분석 대상:**
- `action-plans/plan-poc-retrieval-experiments.md` (PoC 실험 계획)
- `temp/41-final-report.md` (Deep Analysis 최종 보고서)
- `temp/41-v2-adversarial.md` (V2 Adversarial 공격 보고서)
- `temp/41-v1-incorporated.md` (V1 피드백 통합)
- `temp/41-finding1-3-score-domain.md`, `temp/41-finding2-cluster-logic.md`, `temp/41-finding4-5-integration.md` (개별 분석)

---

## 1. Finding별 PoC 영향 분석

---

### Finding #1: Score Domain Paradox (최종 심각도: HIGH)

**최종 처분:** raw_bm25 코드 변경 REJECTED. composite score로 confidence_label 유지. abs_floor를 composite 도메인에 재교정 (plan text 수정만).

#### 1.1 직접 수정된 PoC 계획 섹션

**PoC #5 (BM25 정밀도 측정) -- 직접 영향, 핵심 변경:**

- **plan-poc 196-213행:** V2-adversarial + Deep Analysis 반영 블록 전체가 Finding #1의 산물이다. 이 블록은 다음을 규정한다:
  - **Triple-field 로깅:** `raw_bm25`, `score` (composite), `body_bonus` 3개 필드 기록
  - **Dual precision 계산:** 두 score 도메인(raw_bm25, composite)에서 각각 precision 산출
  - **label_precision 지표 도입:** Action #1 사전/사후 비교 시 precision@k가 아닌 label 분류 정확도를 측정

- **plan-poc 부록 지표 요약 (461-469행):** precision@3, precision@5의 정의는 유지되나, 이들이 Action #1 전후로 **동일한 것이 정상**이라는 해석 프레임이 추가됨

#### 1.2 간접 영향

**PoC #7 (OR-query 정밀도) -- 간접 영향:**

- PoC #7은 PoC #5의 라벨링 데이터셋을 재활용한다 (plan-poc 264행). Finding #1에 의해 PoC #5의 로깅 스키마가 triple-field로 확장되었으므로, PoC #7에서도 `raw_bm25` vs `composite` 기준 각각의 오염 분석이 가능해진다. 구체적으로:
  - 단일 토큰 매칭 결과의 `body_bonus` 분포를 확인할 수 있다
  - body_bonus가 높은 결과가 단일 토큰으로만 title/tag 매칭되었지만 body에서 강하게 매칭되는 "오탐인 줄 알았으나 실은 관련 있는" 사례를 식별할 수 있다

**PoC #4 (Agent Hook) -- 영향 없음:**

- Agent hook 실험은 score 도메인과 무관하다. 레이턴시와 출력 메커니즘만 측정한다.

**PoC #6 (Nudge 준수율) -- 영향 없음:**

- Nudge 준수율은 confidence label의 행동적 결과(tiered output)를 측정하나, Finding #1의 최종 처분이 "composite 유지"이므로 label 계산 로직 자체는 변경되지 않는다.

#### 1.3 의존성 체인

```
Finding #1 (Score Domain)
  -> Plan #1 Action #1의 abs_floor 교정 도메인 변경 (composite로 명시)
    -> PoC #5의 baseline/사후 비교 프레임 변경 (precision@k -> label_precision)
      -> PoC #7의 데이터셋이 추가 필드(body_bonus)를 포함
```

#### 1.4 Deep Analysis 없이의 결과

Deep Analysis가 없었다면:

- **V2-adversarial의 raw_bm25 코드 변경이 그대로 적용**되어 ranking-label inversion 발생 가능 (NEW-4)
- PoC #5가 **precision@k로 Action #1 전후 비교**를 시도 -> 동일한 값을 얻고 "Action #1이 효과 없다"는 **잘못된 결론** 도출
- label_precision 개념이 없으므로 "high 라벨이 얼마나 정확한가"라는 올바른 질문이 제기되지 않았을 것
- body_bonus의 기여도를 분리 분석할 수 없어 검색 품질 개선 방향이 모호해졌을 것

---

### Finding #2: Cluster Tautology (최종 심각도: LOW)

**최종 처분:** 기능 비활성 유지. plan text에서 `cluster_count > max_inject` 사양 제거 (dead code). 코드 변경 0 LOC.

#### 2.1 직접 수정된 PoC 계획 섹션

**PoC #5 -- 없음 (직접 수정 없음):**

- Finding #2는 PoC 실험 계획 문서 자체를 직접 수정하지 않는다. cluster detection은 Plan #1 Action #1의 일부이며, PoC 계획 문서에는 cluster 관련 언급이 없다.

#### 2.2 간접 영향

**PoC #5 -- 간접 영향 (중요):**

- PoC #5의 사전/사후 비교 대상인 "Action #1"에서 cluster detection 구성요소가 사실상 dead code임이 확인됨
- 이는 PoC #5의 **측정 범위를 축소**한다: 사전/사후 비교에서 cluster detection의 기여분이 사라지므로, label_precision 변화는 순수하게 `abs_floor` 도입에 의한 것만 반영
- **측정 해석의 명확화:** PoC #5 결과가 "Action #1 전체 효과"가 아니라 "abs_floor 단독 효과"를 보여준다는 점을 인식해야 함

**PoC #4, #6, #7 -- 영향 없음:**

- Cluster detection은 confidence label 부여 로직에만 관여하며, 이 세 PoC의 측정 대상과 무관

#### 2.3 의존성 체인

```
Finding #2 (Cluster Tautology)
  -> Plan #1 Action #1에서 cluster detection 제거/비활성 확정
    -> PoC #5 사전/사후 비교의 독립변수가 "abs_floor만"으로 축소
      -> PoC #5 결과 해석 시 cluster 효과를 기대하면 안 됨 (null 결과가 아님)
```

#### 2.4 Deep Analysis 없이의 결과

- PoC #5에서 cluster detection이 활성화된 상태로 Action #1 적용 -> **대부분의 3-결과 쿼리에서 모든 high가 medium으로 강등**
- label_precision_high가 급감하지만 이것이 "cluster detection이 작동한 결과"인지 "abs_floor 효과"인지 구분 불가
- 최악의 경우: "Action #1이 검색 품질을 **악화**시켰다"는 잘못된 결론 -> 유익한 abs_floor 개선까지 함께 롤백

---

### Finding #3: PoC #5 Measurement Invalidity (최종 심각도: LOW)

**최종 처분:** Triple-field 로깅 + label_precision 지표 + human annotation 방법론. 모두 plan text 수정. 코드 변경 0 LOC.

#### 3.1 직접 수정된 PoC 계획 섹션

**PoC #5 (BM25 정밀도 측정) -- 핵심 직접 영향:**

Finding #3은 PoC #5의 **방법론 자체**를 개정한다. plan-poc에서 수정된 영역:

- **196-213행 (V2-adversarial + Deep Analysis 반영 블록):**
  - Triple-field 로깅 도입
  - Dual precision 계산 (raw_bm25 기반 + composite 기반)
  - label_precision 지표 정의 (`label_precision_high = count(high AND relevant) / count(high)`)
  - 관련성 ground truth: **인간 어노테이션** (기존 계획에는 구체적 방법론 미명시)

- **206-209행 (label_precision 지표):** Action #1이 ranking을 변경하지 않으므로 precision@k가 사전/사후 동일한 것이 **정상**이라는 명시적 설명 추가. 이것은 "null result"가 아닌 "expected result"로 재프레이밍

- **211-213행 (관련성 ground truth):** 루브릭 기반 인간 어노테이션 방법론 추가. "이 메모리를 보고 Claude가 더 나은 답변을 할 수 있는가?"

#### 3.2 간접 영향

**PoC #7 (OR-query 정밀도) -- 간접 영향:**

- PoC #7은 PoC #5의 라벨링 데이터셋을 재활용한다. Finding #3에 의해 라벨링 품질이 향상(명시적 루브릭 + human annotation)되면, PoC #7의 `polluted_query_rate` 계산의 신뢰성도 향상
- triple-field 로깅으로 인해 PoC #7에서 단일 토큰 매칭 결과의 body_bonus를 확인할 수 있음 -> OR-query 오염이 body_bonus에 의해 완화되는 사례 식별 가능

**Plan #2 (로깅 인프라) -- 직접 영향 (cross-plan):**

- Finding #3은 Plan #2의 로깅 스키마에 `body_bonus` 필드 추가를 요구한다 (final-report 145-148행). 이 변경은 PoC #5에서 소비되는 데이터 형식을 결정

#### 3.3 의존성 체인

```
Finding #3 (PoC #5 Measurement)
  -> Plan #2 로깅 스키마에 body_bonus 필드 추가
    -> PoC #5가 dual precision 계산 가능
      -> PoC #7이 body_bonus 보정된 오염 분석 가능

Finding #3 (label_precision 도입)
  -> PoC #5 Phase B의 사전/사후 비교 지표 변경
    -> Plan #1 Action #1 효과 측정의 정확성 향상
```

#### 3.4 Deep Analysis 없이의 결과

- PoC #5가 composite score만 로깅 -> BM25 자체 품질 vs body_bonus 기여 분리 불가
- Action #1 사전/사후 비교에서 precision@k 동일 -> "효과 없음"이라는 잘못된 결론 (label_precision 개념 부재)
- human annotation 루브릭 미정의 -> 라벨링 일관성 저하, test-retest reliability 악화
- PoC #7의 오염 분석에서 body_bonus의 보상 효과를 고려하지 못해 OR-query 오염도를 과대평가할 가능성

---

### Finding #4: PoC #6 Dead Correlation Path (최종 심각도: LOW)

**최종 처분:** `memory_search_engine.py`에 `--session-id` CLI 파라미터 + env var 폴백 추가. ~12 LOC.

#### 4.1 직접 수정된 PoC 계획 섹션

**PoC #6 (Nudge 준수율) -- 핵심 직접 영향, 상태 변경:**

- **plan-poc 295-307행 (전체 대체):** PoC #6 제목이 "PARTIALLY UNBLOCKED -- Deep Analysis 반영"으로 변경
- **V2-adversarial 발견 (297-299행):** CLI 모드에서 `session_id`가 빈 문자열이므로 `retrieval.inject.session_id`와 `search.query.session_id` 조인이 **구조적으로 0 매칭**을 반환한다는 치명적 결함 기록
- **Deep Analysis 해결 (300-307행):** `--session-id` argparse 파라미터 + `CLAUDE_SESSION_ID` env var 우선순위 + emit_event 호출 시 session_id 전달. SKILL.md 변경 없음 (LLM은 session_id에 접근 불가)
- **선행 의존성 (315행):** `--session-id` CLI 파라미터가 새로운 선행 의존성으로 추가
- **현재 상태 (306-307행):** 수동 상관관계만 가능. 자동 skill-to-hook 상관관계는 `CLAUDE_SESSION_ID` env var 대기

#### 4.2 간접 영향

**PoC #4, #5, #7 -- 영향 없음:**

- `--session-id`는 cross-event correlation 전용이며, 다른 PoC의 측정 대상(레이턴시, precision, 오염도)과 무관

**Plan #2 (로깅 인프라) -- 간접 영향:**

- `search.query` 이벤트에 session_id를 포함시키는 것은 Plan #2의 로깅 스키마 설계에 반영되어야 함
- `emit_event("search.query", ..., session_id=session_id)` 호출이 memory_logger 모듈의 인터페이스를 요구하므로, Plan #2의 로거 구현과 Finding #5의 import 하드닝이 함께 작동해야 함

#### 4.3 의존성 체인

```
Finding #4 (Dead Correlation Path)
  -> memory_search_engine.py에 --session-id 파라미터 추가 (~12 LOC)
    -> PoC #6가 BLOCKED -> PARTIALLY UNBLOCKED로 상태 전환
      -> 수동 CLI 테스트로 탐색적 상관관계 데이터 수집 가능

Finding #4 + Finding #5 (cross-dependency):
  -> --session-id 값이 emit_event()를 통해 로그에 기록됨
    -> Finding #5의 import 하드닝이 emit_event 실패 시 noop fallback 보장
      -> 부분 배포 시에도 --session-id 파싱은 정상 동작 (로깅만 noop)
```

#### 4.4 Deep Analysis 없이의 결과

- PoC #6이 **완전히 BLOCKED 상태로 유지** -- session_id 조인이 구조적으로 0 매칭을 반환한다는 사실을 실행 후에야 발견
- N개 세션 데이터 수집 후 "상관관계 데이터가 전혀 없다"는 결론 도출 -> **시간 낭비**
- 최악의 경우: 0% 준수율이라는 잘못된 결론 -> nudge 전략 자체를 폐기하는 성급한 결정 (실제로는 측정 장치의 결함)

---

### Finding #5: Logger Import Crash + Judge Hardening (최종 심각도: HIGH)

**최종 처분:** module-level try/except for memory_logger + judge import 하드닝 + e.name scoping + stderr 경고. ~36 LOC.

#### 5.1 직접 수정된 PoC 계획 섹션

**PoC 계획 문서에 대한 직접 수정: 없음.**

Finding #5는 plan-poc 문서 자체를 변경하지 않는다. 이 Finding은 **인프라 안정성**에 관한 것이며, PoC 실험의 방법론이나 지표를 변경하지 않는다.

#### 5.2 간접 영향 (중요: 전체 PoC 실행 가능성)

**전체 PoC (#4, #5, #6, #7) -- 간접이지만 필수적 영향:**

Finding #5는 모든 PoC의 **실행 전제 조건**에 영향을 미친다:

- **Plan #2 로깅 인프라 의존:** 모든 PoC가 Plan #2의 로깅 이벤트에 의존한다 (plan-poc 66-71행). Plan #2가 `memory_logger.py`를 도입할 때, Finding #5의 import 하드닝이 없으면:
  - `memory_retrieve.py`가 `from memory_logger import emit_event`에서 크래시 -> 전체 retrieval hook 중단
  - 이는 PoC 데이터 수집뿐 아니라 **정상적인 메모리 검색 기능 자체가 중단**됨을 의미

- **부분 배포 시나리오:** Plan #2의 로깅 모듈 개발 중 일시적으로 `memory_logger.py`가 불완전할 수 있음. Finding #5 없이는 이 기간 동안 retrieval hook이 크래시

- **Judge와의 상호작용:** PoC #5에서 judge 활성화 상태로 precision 측정 시, `memory_judge.py`의 import가 실패하면 전체 hook 크래시. Finding #5의 judge 하드닝이 이를 방지하고 graceful fallback (top-k) 제공

**NEW-2 (Judge Import Vulnerability):**

- Finding #5와 동일한 bug class. PoC #5에서 judge를 활성화하여 judge 필터링 후의 precision을 측정하려면, 이 하드닝이 필수
- 하드닝 없이 `judge_enabled=true` + module missing = hook 크래시 -> PoC 실험 자체 불가

#### 5.3 의존성 체인

```
Finding #5 (Import Hardening)
  -> Plan #2 memory_logger.py 배포 시 크래시 방지 (fail-open)
    -> 모든 PoC의 로깅 데이터 수집이 안전하게 동작
      -> PoC #5, #6, #7의 로그 기반 분석 가능

Finding #5 (Judge Hardening)
  -> judge_enabled=true + missing module = graceful fallback
    -> PoC #5에서 judge 활성/비활성 조건 모두 안전하게 측정 가능

Finding #5 + NEW-5 (e.name scoping)
  -> transitive dependency 실패와 module missing 구분
    -> 배포 오류 진단 가능 (silent degradation 방지)
```

#### 5.4 Deep Analysis 없이의 결과

- Plan #2 로깅 모듈 배포 시 **retrieval hook 크래시 위험** -> 모든 PoC 데이터 수집 중단
- Judge 활성화 상태에서 PoC #5 실행 시 hook 크래시 -> judge 효과 측정 불가
- transitive dependency 실패 시 silent degradation -> "로깅이 배포되었는데 데이터가 없다"는 유령 버그 (e.name 없이는 진단 불가)
- **가장 심각한 실질적 위험:** Finding #5는 다른 Finding과 달리 **plan text 수정이 아닌 실제 코드 변경**이며, 이것이 없으면 Plan #2 -> PoC 파이프라인 전체가 불안정해짐

---

## 2. New Issue별 PoC 영향 분석

---

### NEW-1: apply_threshold Noise Floor Distortion (LOW-MEDIUM)

**처분:** Deferred -- PoC #5 데이터로 실제 영향 확인 후 결정

**PoC 영향:**

- **PoC #5 -- 직접 관련:** 이 이슈 자체가 "PoC #5 데이터가 결정한다"는 disposition을 받았다. triple-field 로깅(Finding #3)으로 body_bonus 값을 확인할 수 있으므로, PoC #5 결과에서 "body_bonus 높은 best 결과가 body_bonus 낮은 valid 결과를 noise floor로 제거한 사례"를 식별 가능
- **PoC #7 -- 간접 관련:** noise floor distortion에 의해 제거된 결과는 PoC #7의 분석 대상에서 이미 빠져 있으므로, OR-query 오염도가 과소평가될 수 있음 (실제로는 OR로 매칭되었지만 noise floor가 먼저 제거)
- **Deep Analysis 없이:** noise floor distortion 자체가 발견되지 않았을 것. PoC #5에서 "왜 일부 합리적인 BM25 매칭이 결과에 포함되지 않는가?"라는 질문이 제기되어도, body_bonus에 의한 noise floor 인플레이션이라는 원인을 식별하기 어려웠을 것

---

### NEW-2: Judge Import Vulnerability (HIGH)

**처분:** Finding #5와 함께 수정됨

**PoC 영향:**

- **PoC #5 -- 직접 관련:** judge 활성화 상태에서 precision 측정 시 필수. Finding #5 분석 중 발견되었으며, judge 하드닝 코드에 포함
- **기타 PoC -- 없음:** judge는 retrieval 파이프라인의 선택적 필터이며, 다른 PoC의 측정 대상이 아님
- **Deep Analysis 없이:** judge 활성화 시 hook 크래시 -> PoC #5에서 "judge 포함 precision"을 측정할 수 없었을 것. judge를 비활성화하고 측정하면 실제 사용 시나리오와 괴리

---

### NEW-3: Empty XML After Judge Rejection (LOW)

**처분:** 별도 추적. 현재 fix scope에 포함하지 않음

**PoC 영향:**

- **PoC #5 -- 미미한 간접 영향:** judge가 모든 candidate를 거부하면 빈 `<memory-context></memory-context>`가 출력됨. 이는 토큰 낭비이지만, precision 측정에는 영향 없음 (0/0 케이스로 처리)
- **PoC #6 -- 없음:** nudge 측정과 무관
- **Deep Analysis 없이:** 이 이슈는 발견되지 않았겠으나, 실질적 영향이 LOW이므로 PoC 결과에 의미있는 차이 없음

---

### NEW-4: Ranking-Label Inversion (HIGH)

**처분:** raw_bm25 코드 변경 rejection으로 해결됨

**PoC 영향:**

- **PoC #5 -- 핵심 간접 영향:** NEW-4가 Finding #1의 코드 변경을 뒤집은 핵심 발견이다. 이것이 없었다면:
  - raw_bm25로 confidence_label을 계산 -> body_bonus가 높은 #1 ranked 결과가 "low"로 라벨링
  - tiered output에서 가장 관련성 높은 결과가 **침묵** (silence)
  - PoC #5가 이 regression을 baseline에 포함시켜 측정 -> "기존 시스템보다 악화"라는 결론

- **PoC #6 -- 간접 영향:** tiered output의 compact injection 빈도가 왜곡됨. body_bonus 높은 결과가 "low"로 라벨링 -> silence 처리 -> compact 주입이 줄어들고 대신 결과가 아예 표시되지 않음 -> nudge 발생 빈도 자체가 감소 -> 준수율 측정의 모수가 줄어듦

- **Deep Analysis 없이:** **가장 심각한 미발견 위험.** raw_bm25 fix가 적용된 상태로 모든 PoC 진행 -> ranking-label inversion이 PoC #5 baseline을 오염 + PoC #6의 측정 모수를 축소. V2-adversarial이 이것을 발견하지 못했다면, regression이 production에 반영되었을 것

---

### NEW-5: ImportError Masks Transitive Failures (MEDIUM)

**처분:** e.name scoping으로 해결됨

**PoC 영향:**

- **전체 PoC -- 간접이지만 진단에 중요:** `memory_logger.py`가 존재하지만 내부 import가 실패하는 경우, e.name 없이는 silent noop fallback -> "로깅이 배포되었는데 로그가 생성되지 않는다"는 유령 버그
- PoC 데이터 수집 기간에 이 문제가 발생하면, N일간 데이터가 누락된 후에야 발견 -> 실험 재시작 필요
- **Deep Analysis 없이:** transitive dependency 실패 시 silent degradation. 디버깅에 시간 소모

---

## 3. Key Course Correction: raw_bm25 Rejection이 PoC #5에 미치는 영향

### 배경

Deep Analysis 과정에서 가장 극적인 전환은 Finding #1의 **raw_bm25 코드 변경 rejection**이다. 분석 팀(analyst-score)이 "raw_bm25로 confidence_label을 계산해야 한다"고 제안했고, 이것이 V1 검증까지 통과했다. 그러나 V2-adversarial이 이 fix의 치명적 결함을 발견했다:

```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (ranked #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (ranked #2)

raw_bm25 기반 라벨: A="low", B="high"
-> tiered output에서 #1 결과가 침묵, #2 결과가 전체 주입
```

### PoC #5에 대한 구체적 영향

**rejection 이전 (raw_bm25 fix가 적용될 예정이었을 때):**

- PoC #5는 raw_bm25 기반 confidence label의 precision을 측정할 예정이었다
- label_precision_high가 body_bonus 높은 결과에서 체계적으로 낮아지는 현상을 관찰했을 것
- 이를 "BM25 품질 문제"로 해석했을 가능성 (실제로는 fix에 의한 regression)

**rejection 이후 (composite 유지):**

- PoC #5는 composite score 기반 label의 precision을 측정한다
- body_bonus가 ranking과 labeling 모두에서 일관되게 반영됨
- label_precision_high는 body_bonus에 의한 왜곡 없이 "composite 기준으로 high인 결과가 실제로 관련있는가"를 측정
- **단, raw_bm25를 triple-field 로깅으로 기록하므로, BM25 자체 품질은 별도로 분석 가능** (diagnostic 용도)

**핵심 차이:**

| 측면 | rejection 전 | rejection 후 |
|------|------------|------------|
| confidence_label 입력 | raw_bm25 | composite (= BM25 - body_bonus) |
| label-ranking 일관성 | 보장 안 됨 (inversion 가능) | 보장됨 |
| tiered output 안전성 | #1 결과 침묵 가능 | 안전 |
| PoC #5 baseline 유효성 | 오염됨 | 유효 |
| BM25 자체 품질 분석 | label에 반영 | raw_bm25 로그 필드로 별도 분석 |

---

## 4. Process Assessment 분석: 분석 비례성 평가

### Final Report의 자체 평가 (temp/41-final-report.md:176-184행)

> "v2-fresh verifier correctly identified process bloat: 7 agents / 5 phases / 10+ documents for ~48 LOC of code changes."

### 이 평가가 PoC 계획에 시사하는 바

**비례적이었던 부분:**

1. **Finding #5 (import hardening):** ~36 LOC의 실제 크래시 방지. 모든 PoC의 실행 가능성에 영향. 이 코드 없이 Plan #2 로깅을 배포하면 retrieval hook이 크래시 -- 7-agent 분석의 가치를 정당화하는 발견
2. **NEW-4 (ranking-label inversion):** V2 adversarial round에서 발견. 이것이 없었다면 regression이 production에 진입하고 PoC #5 baseline을 오염 -- 다단계 검증 프로세스의 핵심 가치

**과도했던 부분:**

1. **Finding #2 (cluster tautology):** 수학적 증명은 엄밀하지만, 기능이 이미 `false`로 비활성화되어 있으므로 plan text 메모로 충분. 독립된 분석 에이전트를 할당할 필요 없었음
2. **Finding #3 (PoC #5 measurement):** plan text 수정만 필요한 항목에 deep analysis pipeline을 적용. 경험 있는 단일 리뷰어가 "Action #1은 ranking을 변경하지 않으므로 precision@k는 동일"이라고 지적하면 충분
3. **Finding #4 (dead correlation path):** ~12 LOC의 argparse 추가. V2-adversarial 공격 테스트(null byte, unicode, concurrent access)는 local CLI tool에 대해 과도한 보안 분석

**PoC 계획에 대한 함의:**

PoC 실험 계획 문서에 대한 **실질적 변경**은 다음 세 가지로 압축된다:

1. PoC #5의 측정 방법론 개정 (label_precision + triple-field + human annotation)
2. PoC #6의 BLOCKED -> PARTIALLY UNBLOCKED 상태 전환
3. PoC #5의 baseline 안전성 보장 (raw_bm25 rejection)

이 세 가지는 7-agent 파이프라인 없이 2-agent (analyst + adversarial verifier)로도 도출할 수 있었다. 단, **NEW-4 (ranking-label inversion)는 adversarial round가 없었다면 발견되지 않았을 것**이므로, 최소한 adversarial 검증 단계는 정당화된다.

**Final Report의 권고사항과 일치:**

> "Use triage sizing. <50 LOC fixes = 2-agent pipeline (analyst + verifier). Reserve the full multi-phase pipeline for >200 LOC architectural changes."

PoC 계획 자체는 코드 변경이 아닌 문서이므로, 향후 유사한 plan 문서 리뷰에는 2-agent pipeline이 적절하다. 단, plan에 의해 **구동되는** 코드 변경(이 경우 Finding #5의 ~36 LOC)은 별도로 triage해야 한다.

---

## 5. 종합 영향 매트릭스

| Finding/Issue | PoC #4 Agent Hook | PoC #5 BM25 정밀도 | PoC #6 Nudge 준수율 | PoC #7 OR-query 정밀도 |
|:---:|:---:|:---:|:---:|:---:|
| **Finding #1** (Score Domain) | -- | **핵심 직접** (measurement reframing) | 간접 (tiered output 무결성) | 간접 (body_bonus 분리 분석) |
| **Finding #2** (Cluster Tautology) | -- | 간접 (Action #1 효과 범위 축소) | -- | -- |
| **Finding #3** (PoC #5 Measurement) | -- | **핵심 직접** (방법론 전면 개정) | -- | 간접 (라벨링 품질 향상) |
| **Finding #4** (Dead Correlation) | -- | -- | **핵심 직접** (BLOCKED -> PARTIALLY UNBLOCKED) | -- |
| **Finding #5** (Import Crash) | 간접 (인프라 안정성) | **필수 전제** (로깅 크래시 방지) | **필수 전제** (로깅 크래시 방지) | **필수 전제** (로깅 크래시 방지) |
| **NEW-1** (Noise Floor) | -- | 직접 (데이터가 결정) | -- | 간접 (과소평가 가능성) |
| **NEW-2** (Judge Import) | -- | 직접 (judge 활성화 시) | -- | -- |
| **NEW-3** (Empty XML) | -- | 미미 | -- | -- |
| **NEW-4** (Ranking-Label Inversion) | -- | **핵심** (baseline 오염 방지) | 간접 (측정 모수 보존) | -- |
| **NEW-5** (e.name Scoping) | 간접 | 간접 (진단) | 간접 (진단) | 간접 (진단) |

**범례:**
- **핵심 직접**: PoC의 방법론, 지표, 또는 실행 가능성을 직접 변경
- **필수 전제**: PoC 실행 자체의 안전성/안정성에 필수
- 간접: PoC 결과의 해석이나 품질에 영향
- --: 영향 없음

---

## 6. 최종 결론

### Deep Analysis의 PoC 계획에 대한 순가치

**양적 요약:**

- PoC 계획에 대한 직접 텍스트 변경: ~110행 (196-213행 블록, 295-307행 블록, 기타 산재된 수정)
- 이 변경을 위해 생산된 분석 문서: ~1,500행 이상 (5개 분석 문서 + 2개 검증 문서 + 최종 보고서)
- 비율: 분석 문서 ~14행당 plan 변경 1행

**질적 요약:**

Deep Analysis가 PoC 계획에 기여한 가장 가치 있는 발견:

1. **NEW-4 (ranking-label inversion):** raw_bm25 fix 적용 시 PoC #5 baseline이 오염되었을 것. 이 regression은 PoC 데이터 수집 후에야 (또는 영영) 발견되었을 가능성 -- adversarial 검증의 핵심 가치
2. **Finding #3 (label_precision):** precision@k가 Action #1 전후 동일한 것이 "정상"이라는 인사이트. 이 없이는 "null result"를 "효과 없음"으로 오해
3. **Finding #4 (dead correlation):** PoC #6이 구조적으로 0 매칭을 반환한다는 사실을 실행 전에 발견. 시간 낭비 방지
4. **Finding #5 (import hardening):** 모든 PoC의 로깅 인프라 안정성 전제 조건

**과도한 부분:**

- Finding #2의 수학적 증명은 PoC 계획에 대해 "cluster detection 효과를 기대하지 마라"는 한 문장의 메모로 충분
- V2-adversarial의 공격 3 (null byte, unicode, concurrent CLI) ~70행은 PoC 계획과 무관한 보안 분석

**최종 판정:** Deep Analysis는 PoC 계획에 대해 **불균형적으로 무거운 프로세스**였으나, 발견된 가치(특히 NEW-4와 Finding #5)가 프로세스 비용을 정당화한다. 향후에는 Final Report의 triage sizing 권고를 적용하여 plan 문서 리뷰를 2-agent로 축소하되, adversarial 검증 단계는 유지해야 한다.
