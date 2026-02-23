# plan-retrieval-confidence-and-output.md 핵심 의사결정 흐름 분석

**작성일:** 2026-02-22
**분석가:** 의사결정 프로세스 분석가
**분석 대상:** 7-agent Deep Analysis 파이프라인이 plan-retrieval-confidence-and-output.md에 남긴 의사결정 궤적

---

## 1. raw_bm25 코드 변경의 흥망성쇠

### 1.1 문제의 출발점 -- 복합 점수 도메인의 발견

이 이야기는 V2-adversarial 검토에서 처음 시작된다. 검토자들은 `memory_retrieve.py`의 코드를 라인별로 추적하면서 **아무도 런타임 데이터 흐름을 실제로 따라간 적이 없다**는 사실을 발견했다.

핵심은 `score_with_body()` 함수의 단 두 줄이었다:

```python
r["raw_bm25"] = r["score"]            # line 256: 원본 BM25 저장
r["score"] = r["score"] - body_bonus  # line 257: 복합 점수로 IN-PLACE 변이
```

`raw_bm25` 필드는 line 256에서 보존되지만, 하류(downstream)에서 **소비되지 않고 있었다.** `_output_results()` 함수(line 283, 299)는 변이된 복합 점수를 그대로 `confidence_label()`에 전달하고 있었다. 마스터 브리핑(`41-master-briefing.md`)은 이 흐름을 다음과 같이 정리한다:

```
1. query_fts()        -> 원본 BM25 점수 (음수 float)
2. score_with_body():257 -> r["score"] = r["score"] - body_bonus  (IN-PLACE 변이)
3. apply_threshold()  -> 변이된 복합 점수 기준으로 필터
4. _output_results():283 -> best_score = max(abs(변이된 점수들))
5. _output_results():299 -> confidence_label(변이된 점수, 변이된 best_score)
```

이 발견이 Finding #1 "Score Domain Paradox"로 명명되었고, CRITICAL 심각도가 부여되었다.

### 1.2 첫 번째 제안 -- raw_bm25를 사용하라

`analyst-score`는 `41-finding1-3-score-domain.md`에서 문제를 두 가지 결함으로 분리했다:

**결함 A -- best_score 오계산 (line 283):**

body_bonus가 붙은 복합 점수로 `best_score`를 계산하면, 그 값이 부풀어 오른다. 예를 들어 `raw_bm25=-2.0, body_bonus=3`인 엔트리의 복합 점수는 `-5.0`이 된다. 이 값이 `best_score`로 쓰이면 다른 엔트리들의 ratio가 압축된다.

**결함 B -- confidence_label() 오분류 (line 299):**

복합 점수가 `confidence_label()`에 들어가면, body_bonus의 단순 정수 덧셈이 BM25 corpus-scale 비율 계산을 왜곡한다. 이로 인해 (1) 허위 클러스터 발생(body_bonus가 ratio를 1.0 쪽으로 압축), (2) abs_floor 교정 무효화(BM25 도메인 기준 교정값이 복합 도메인에서 틀림) 두 가지 문제가 생긴다.

**제안된 수정 (2줄 변경):**

```python
# line 283 변경:
# BEFORE:
best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)
# AFTER:
best_score = max((abs(entry.get("raw_bm25", entry.get("score", 0))) for entry in top), default=0)

# line 299 변경:
# BEFORE:
conf = confidence_label(entry.get("score", 0), best_score)
# AFTER:
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_score)
```

`entry.get("raw_bm25", entry.get("score", 0))` 패턴은 안전한 fallback 체인을 형성한다:
- FTS5 경로: `raw_bm25` 존재 -> 원본 BM25 사용
- 레거시 경로: `raw_bm25` 없음 -> `score` 사용 (변이 없는 키워드 점수)
- `body_bonus=0`인 경우: `raw_bm25 == score` -> 차이 없음

분석가들은 이 수정에 "매우 높은 신뢰도(Very High)"를 부여했다. Codex 5.3와 Gemini 3 Pro 모두 동의했다.

### 1.3 V1 검증에서의 승인

V1 검증(`41-v1-incorporated.md`)에서 `v1-code-verifier`와 `v1-design-verifier` 모두 PASS WITH NOTES를 부여했다. raw_bm25 수정 자체는 변경 없이 "confirmed correct"로 통과했다. V1 라운드가 제기한 사항들은 다른 부분들(emit_event 위치, judge fallback stderr 경고)에 관한 것이었다.

Solution Synthesis(`41-solution-synthesis.md`)는 이 시점에서 Finding #1의 상태를 다음과 같이 정리했다:

| # | Finding | Severity | Solution | LOC | Confidence |
|---|---------|----------|----------|-----|-----------|
| 1 | Score Domain Paradox | CRITICAL | `raw_bm25` with fallback (lines 283, 299) | ~2 | Very High |

V1 라운드에서 제기된 V2 검증 질문 중 첫 번째가 바로 이것이었다: "공격자가 raw_bm25 fallback이 현재 변이된 점수보다 더 나쁜 결과를 내도록 만들 수 있는가?"

이 질문이 V2-adversarial 라운드로 넘어갔다.

### 1.4 V2 adversarial에서의 공격 성공 -- Attack 1a

`v2-adversarial`은 `41-v2-adversarial.md`에서 Finding #1에 대해 직접적인 공격을 시도했다. Attack 1a는 성공(SUCCESS -- CRITICAL)으로 판정되었다.

**공격 시나리오:**

```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0  (복합 점수 기준 #1 랭킹)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5  (복합 점수 기준 #2 랭킹)

raw_bm25로 신뢰도 라벨링 시:
  best_score = max(abs(-1.0), abs(-3.5)) = 3.5
  Entry A ratio = 1.0 / 3.5 = 0.286 -> "low" 라벨
  Entry B ratio = 3.5 / 3.5 = 1.0   -> "high" 라벨

결과: #1 랭킹 엔트리가 "low", #2 랭킹 엔트리가 "high"
```

**왜 이것이 심각한가?**

v2-adversarial은 Action #2(계층적 출력, Tiered Output)를 참조하면서 이 역전이 단순한 라벨 의미론의 문제가 아니라 **기능적 버그**임을 지적했다. Action #2는 신뢰도 라벨을 행동 트리거로 사용한다:
- HIGH -> 전체 `<result>` 주입
- MEDIUM -> 축약 `<memory-compact>` 주입
- LOW -> **침묵(출력 없음)**

body 키워드 매칭이 3개나 되어 #1 랭킹을 받은 Entry A가 raw_bm25 기준으로는 "low"를 받아 **침묵**되고, body 증거가 전혀 없는 Entry B가 "high"를 받아 **전체 주입**된다. 가장 관련성 높은 결과가 사라지고 덜 관련된 결과가 표시되는 것이다.

외부 모델들의 반응:
- **Gemini 3.1 Pro:** "검색 시스템의 계약을 위반했다(You have broken the contract of the retrieval system)." raw_bm25 수정을 전면 기각 권고.
- **Codex 5.3:** "body 증거로 부스트된 엔트리가 'low'로 라벨링되면 오해 소지가 있다(Entries boosted by strong body evidence can be top-ranked but labeled 'low,' which is misleading)." 복합 점수 유지 + 별도 `bm25_confidence` 속성 권고.

v2-adversarial 스스로도 자신의 분석에 대한 vibe-check를 수행했다: "나는 Attack 1a를 break로 부르는 데 너무 공격적인가?" 그 결론은 다음과 같다:

> "분석가들의 의미론적 주장("신뢰도는 BM25 품질을 의미해야 한다")은 격리하여 보면 타당하다. 그러나 이 계획은 이미 신뢰도 라벨을 계층적 주입의 행동 트리거로 사용하기로 확정했다(Action #2: LOW = 침묵). 라벨이 행동을 구동하면 라벨-랭킹 역전은 기능적 버그가 된다."

### 1.5 최종 기각 결정과 그 논리

Deep Analysis 최종 보고서(`41-final-report.md`)는 Finding #1의 결론을 다음과 같이 정리했다:

**최종 처분:**
1. **2줄 코드 변경을 기각(REJECT).** Line 283과 299는 변경하지 않는다.
2. **abs_floor를 복합 점수 도메인 기준으로 재교정한다.** 계획 문서에 abs_floor가 복합 점수(BM25 - body_bonus, 일반 코퍼스에서 대략 0-15 범위)에서 동작함을 명시한다.
3. **raw_bm25는 진단 로깅에만 사용한다.** PoC #5 분석을 위한 세 필드 로깅(raw_bm25 + score + body_bonus)에서만 소비한다.
4. **심각도 하향:** CRITICAL -> HIGH. 계층적 출력 기본값이 "legacy"이므로 즉각적인 행동적 영향은 없다.

기각의 핵심 논리는 plan-retrieval-confidence-and-output.md에 다음과 같이 기록되었다:

> "라벨이 Action #2에서 행동 트리거(침묵/축약/전체)로 사용되므로, 라벨은 반드시 랭킹과 단조 관계를 유지해야 함."

이로 인한 코드 변경량: **0 LOC** (기존 코드 유지, 계획 문서 텍스트만 수정).

### 1.6 외부 모델들의 독립적 확인

이 기각 결정을 Plan #1 문서(`plan-retrieval-confidence-and-output.md:93`)는 다음과 같이 기록했다:

> **외부 검증:** Gemini 3.1 Pro ("검색 시스템의 계약을 위반"), Codex 5.3 ("body 증거로 부스트된 엔트리가 'low'로 라벨링되면 오해 소지")가 독립적으로 raw_bm25 기각을 확인.

두 외부 모델 모두 제시된 세 가지 해결 옵션 중 "복합 점수 유지"를 지지했으며, 별도 `bm25_confidence` 진단 속성 추가를 권장했다(단, 이 역시 즉각적 구현은 불필요하다는 판단).

---

## 2. 클러스터 감지 기능의 진화

### 2.1 원래 제안 -- >= 3 임계치

클러스터 감지 아이디어는 V1-robustness 검토에서 처음 제기되었다. 문제는 명확했다: "api payload" 같은 쿼리로 점수 `-4.10, -4.05, -4.02, -4.00, -3.98`을 반환하면 모든 결과가 ratio > 0.95가 되어 모두 "high"가 된다.

**원안:** 3개 이상 결과가 ratio > 0.90이면 "medium"으로 캡.

```python
def confidence_label(score, best_score, cluster_count=0):
    ...
    if cluster_count >= 3:
        return "medium"  # 클러스터 감지 발동
```

이 아이디어는 plan-retrieval-confidence-and-output.md Action #1에 포함되었다. 설정 토글(`cluster_detection_enabled`)은 있었지만, 이 시점에서는 다소 낙관적으로 "유용한 기능"으로 간주되고 있었다.

### 2.2 V2-fresh에서의 문제 제기

V2-fresh 검토자는 클러스터 감지와 `max_inject` 기본값(3) 사이의 상호작용에 주목했다. 결과가 항상 최대 `max_inject`개로 잘리는데, `max_inject=3`에서 `cluster_count >= 3`은 **모든 성공적인 쿼리**에 발동할 수 있다는 우려가 제기되었다.

검토 이력에 따르면 이 문제는 "V2-Fresh Eyes: NEEDS WORK → fixed"로 기록되어 있다. 원안의 `cluster_count >= 3` 임계치가 문제임을 인식하고 수정이 시도되었다.

**수정안:** `cluster_count > max_inject` (max_inject 초과 시에만 발동)

이 수정이 plan-retrieval-confidence-and-output.md에 반영되었으나, 마스터 브리핑은 이것이 Finding #2의 시작점이 되었다고 기록한다.

### 2.3 V2-adversarial에서의 수학적 증명 -- Cluster Tautology

`analyst-logic`은 `41-finding2-cluster-logic.md`에서 이 문제를 형식적으로 증명했다.

**공식 정의:**
- `m = max_inject` (기본값: 3)
- `R` = `apply_threshold()` 잘림 후 결과 집합
- `N = |R|`, 단 `N <= m` (구조적 보장: `return results[:limit]`)
- `C = |{i in R : ratio_i > 0.90}|` (클러스터 카운트)

**tautology 증명 (m=3에서):**

```
1. N <= m = 3    (잘림에 의한 상한)
2. C <= N <= 3   (클러스터 카운트는 결과 수를 초과할 수 없음)
3. 따라서 C > 3은 불가능
4. 즉 cluster_count > max_inject는 DEAD CODE -- 수학적으로 절대 성립 불가
```

**옵션 분석 (5가지):**

| 옵션 | m=1 | m=3 | m=5 | 판정 |
|------|-----|-----|-----|------|
| A: C > m | 절대 불가 | 절대 불가 | 절대 불가 | Dead code |
| B: 잘리기 전 카운트 | 작동 | 작동 | 작동 | 유일하게 수학적으로 건전 |
| C: C >= 4 | 불가(N<=1) | 불가(N<=3) | 작동 | 임의적 선택, 원칙 없음 |
| D: C >= ceil(0.8*m) | 100% 오탐(!) | tautology 유지 | 작동 | m=1, m=3에서 치명적 |
| E: ratio > 0.95 | 구조적 결함 유지 | 구조적 결함 유지 | 동일 | 조정 가능 손잡이이나 근본 해결 아님 |

특히 **원안 수정 (Option A: `cluster_count > max_inject`)이 사실상 기능을 완전히 비활성화하는 것과 동일**함이 증명되었다. 이 역설적 결론은 단순히 임계치를 바꿨을 뿐인데 기능이 영구적으로 죽어버리는 것이다.

Option B(잘리기 전 카운트)만이 수학적으로 건전하지만, `apply_threshold()`의 인터페이스를 변경해야 하고, 이미 기본값이 `false`인 비활성 기능을 위한 파이프라인 리팩터링은 불필요한 엔지니어링이다.

**vibe-check 결과:**

Gemini 3 Pro는 다음과 같이 말했다:
> "당신은 절대 과도하게 복잡하게 만들고 있지 않다. 문서화하고 넘어가라는 본능이 가장 시니어한 엔지니어링 결정이다. 당신은 'Zombie Logic'을 올바르게 식별했다 -- 기본 제약 조건 하에서 복잡한 것을 하는 것처럼 보이지만 실제로는 아무것도 하지 않거나 사소한 것을 하는 코드."

### 2.4 최종 "비활성 유지" 결정

최종 보고서는 다음을 결정했다:

1. **기능 비활성 유지** (`cluster_detection_enabled: false` 기본값)
2. **tautology 문서화** (계획 문서에 수학적 증명 내용 기록)
3. **Option B 구현 보류** (비활성 기능을 위한 불필요한 엔지니어링)
4. **향후 활성화 조건 명시:** 잘리기 전 카운팅(pre-truncation counting)으로 구현하고, `max_inject > 3` 필요

plan-retrieval-confidence-and-output.md는 이를 다음과 같이 최종 기록했다:

> **수학적 증명 (Cluster Tautology):** 원안 임계치(`>= 3`)는 `max_inject=3`(기본값)에서 **모든 성공적인 쿼리**에 발동하는 논리 오류 (tautology). 잘린 후 결과 N ≤ max_inject이므로 C ≤ N ≤ max_inject → `C > max_inject`는 **수학적으로 불가능** (dead code).

코드 변경량: **0 LOC** (기존 비활성 상태 유지, 계획 문서 텍스트만 수정).

---

## 3. 핵심 통찰

### 3.1 왜 7-agent 파이프라인이 이 특정 버그를 찾는 데 필요했는가?

**단순한 답:** 이전 4번의 검토 라운드에서는 아무도 런타임 데이터 흐름을 실제로 추적하지 않았기 때문이다.

마스터 브리핑(`41-master-briefing.md`)은 이 핵심 blindspot을 명확하게 지적한다:

> "V2-adversarial 검토가 5가지 발견을 했다. 핵심 맹점: 모든 검토자가 함수 시그니처를 격리하여 검증했지만 **아무도 실제 런타임 데이터 흐름을 추적하지 않았다.** `memory_retrieve.py:257`의 `body_bonus` 변이가 진원지다."

구체적으로 무엇이 일어났는가:

1. **초기 계획 단계:** Action #1을 설계한 사람들은 `confidence_label()`이 BM25 점수를 받는다고 가정했다. 이 가정은 문서에 명시되지 않았고, 실제 코드를 따라가 보면 틀린 가정이었다.

2. **Engineering Review와 Adversarial Review:** 함수 시그니처와 계획의 논리를 검토했지만, 실제 `score` 필드가 무엇인지 확인하지 않았다.

3. **V1-Robustness와 V1-Practical:** 클러스터 감지 설정 문제, 롤백 수 교정 등을 발견했지만, 점수 도메인 문제는 발견하지 못했다.

4. **V2-Fresh Eyes:** `cluster_count >= 3`과 `max_inject=3` 상호작용 문제를 제기했으나, 해결책으로 제시한 `cluster_count > max_inject`가 dead code임을 검증하지 않았다.

5. **V2-Adversarial (6번째 라운드):** 비로소 런타임 데이터 흐름을 공격 대상으로 설정하고 추적했다.

6. **Deep Analysis (7-agent, 7번째):** analyst-score가 `score` 필드의 모든 소비자를 문서화하고, analyst-logic이 클러스터 tautology를 수학적으로 증명하고, v2-adversarial이 raw_bm25 수정의 역전 효과를 concrete 시나리오로 공격했다.

최종 보고서는 이 프로세스의 가치와 비용을 솔직하게 평가한다:

> **발견된 가치:** Finding #5(임포트 충돌)는 실제 핫 경로 충돌 방지. V2 adversarial 라운드가 ranking-label inversion(NEW-4)을 발견했고, 이것은 분석가들의 수정안이 검증 없이 배포됐다면 회귀로 출시될 뻔했다.
>
> **과잉:** Finding #2, #3, #4는 LOW 심각도이며 멀티-에이전트 리뷰가 아닌 계획 텍스트 메모로 처리할 수 있었다.
>
> **향후 권장:** 트리아지 크기 조정 사용. <50 LOC 수정 = 2-agent 파이프라인(분석가 + 검증자). 전체 멀티-phase 파이프라인은 >200 LOC 아키텍처 변경에만 사용.

### 3.2 "신뢰도 라벨이 행동 트리거가 되면 랭킹과 단조 관계를 유지해야 한다"는 원칙이 어떻게 도출되었는가?

이 원칙은 **단일 발견이 아니라 세 단계 추론의 수렴**으로 도출되었다.

**1단계 -- 의미론적 주장 (분석가들):**

analyst-score는 `confidence_label()`이 "BM25 매칭 품질"을 측정해야 한다고 주장했다. 복합 점수(BM25 + body_bonus)는 검색 품질의 "블렌드된 관련성"을 나타내므로, 순수 BM25 품질을 측정하려면 raw_bm25를 사용해야 한다는 논리였다. 이 주장은 Codex와 Gemini도 동의했다. (Finding #1 해결책으로 raw_bm25 사용이 "Very High" 신뢰도로 채택된 배경.)

**2단계 -- 역전 발견 (V2-adversarial):**

v2-adversarial은 분석가들의 의미론적 주장이 격리하여 보면 타당하다고 인정하면서도, **계획 전체의 맥락**에서 치명적임을 보였다. 핵심 전환점:

> "비판적 질문: 누가 라벨을 소비하는가? 인간이 XML 출력을 읽는다면, 의미론적 유연성은 괜찮다. 무엇을 표시하거나 숨길지 결정하는 코드라면, 라벨은 반드시 랭킹과 단조 관계를 유지해야 한다."

이 질문이 핵심이었다. Action #2는 신뢰도 라벨을 코드가 소비하는 행동 트리거로 만들었다. "low" = 침묵은 단순한 표시 속성이 아니라 **정보를 주입할지 말지 결정하는 논리**다.

**3단계 -- 원칙 추출 (Deep Analysis 최종 보고서):**

Final Report는 이 발견을 원칙으로 명문화했다:

> "분석가들이 복합 점수가 신뢰도 비율을 왜곡한다는 것을 올바르게 식별했지만, 하류 결과를 고려하지 않았다: **신뢰도 라벨이 행동 결정을 구동할 때(계층적 출력), 라벨은 랭킹과 단조 관계를 유지해야 한다.**"

plan-retrieval-confidence-and-output.md는 이를 직접적으로 기록했다:

> "이는 의도적 설계: 라벨이 Action #2에서 행동 트리거(침묵/축약/전체)로 사용되므로, 라벨은 반드시 랭킹과 단조 관계를 유지해야 함."

**원칙 도출의 구조:**

```
분석가의 의미론적 주장: "confidence = BM25 품질"
    +
Action #2의 설계 결정: "confidence = 행동 트리거 (LOW = 침묵)"
    +
V2-adversarial의 구체 시나리오: "Entry A (#1 랭킹) -> LOW -> 침묵"
    =
원칙: "행동 트리거 라벨은 랭킹과 단조 관계 필수"
```

이 원칙이 도출되지 않았다면, raw_bm25 수정은 코드에 들어갔을 것이고, Action #2 계층적 출력 모드가 활성화되는 순간 가장 관련성 높은 결과들이 침묵되는 회귀가 발생했을 것이다.

---

## 4. 의사결정 타임라인 요약

| 단계 | 주체 | raw_bm25 상태 | 클러스터 감지 상태 |
|------|------|--------------|----------------|
| Action #1 초안 | 계획자 | (언급 없음) | >= 3 임계치, 활성 |
| V1-Robustness | 검토자 | (언급 없음) | 설정 토글 추가 (enabled/disabled) |
| V2-Adversarial 발견 | v2-adversarial | **CRITICAL: 복합 점수 사용 중** | **CRITICAL: tautology 발견** |
| Analyst 분석 | analyst-score | **승인: raw_bm25 사용 권고** | (analyst-logic이 별도 담당) |
| Analyst 분석 | analyst-logic | N/A | **수학적 증명: 모든 옵션 부적합** |
| Solution Synthesis | 종합 | **채택: 2줄 수정 (Very High 신뢰)** | **결론: 비활성 유지** |
| V1 Verification | v1-verifier | **PASS: 코드 정확함** | **PASS: 증명 검증됨** |
| **V2 Adversarial 공격** | v2-adversarial | **Attack 1a 성공: 랭킹-라벨 역전** | **공격 실패: 이미 비활성** |
| Deep Analysis | 7-agent | **기각: 0 LOC 변경** | **유지: 비활성, 계획 텍스트 수정** |
| 최종 Plan 문서 | plan-retrieval... | **복합 점수 유지 (의도적 설계)** | **비활성 유지 (tautology 명시)** |

---

## 5. 이 사례에서 배울 수 있는 교훈

**교훈 1: 라벨의 소비자를 명시하라.**

신뢰도 라벨이 처음 설계될 때, 그것이 "정보성 메타데이터"인지 "행동 트리거"인지 명확히 규정되지 않았다. 이 모호성이 분석가들로 하여금 의미론적으로 타당하지만 시스템적으로 잘못된 수정을 제안하게 만들었다.

**교훈 2: 임계치는 전체 파이프라인 맥락에서 검증하라.**

`>= 3` 임계치, `> max_inject` 임계치 모두 격리하여 보면 합리적으로 보였다. 파이프라인의 구조적 제약(잘린 후 결과 수 <= max_inject)을 함께 고려하면 dead code임이 드러난다.

**교훈 3: 외부 검증이 맹점을 찾지 못할 수 있다.**

Codex와 Gemini는 raw_bm25 수정에 동의했다. 그러나 두 모델 모두 Action #2와의 상호작용을 놓쳤다. 외부 검증은 제시된 질문에 답하지만, 제시되지 않은 맥락은 파악하지 못할 수 있다.

**교훈 4: 프로세스 과잉을 피하라.**

7-agent 파이프라인은 실제 버그를 찾았지만, 비용도 컸다. Finding #2, #3, #4는 간단한 계획 텍스트 메모로 충분했다. 파이프라인 크기는 변경 규모에 비례해야 한다.
