# Deep Analysis가 plan-retrieval-confidence-and-output.md의 향후 구현에 미치는 영향

**작성일:** 2026-02-22
**작성자:** 소프트웨어 아키텍처 영향 분석
**분석 대상:**
- `/home/idnotbe/projects/claude-memory/action-plans/plan-retrieval-confidence-and-output.md`
- `/home/idnotbe/projects/claude-memory/temp/41-final-report.md`
- `/home/idnotbe/projects/claude-memory/temp/41-finding1-3-score-domain.md`
- `/home/idnotbe/projects/claude-memory/temp/41-finding2-cluster-logic.md`
- `/home/idnotbe/projects/claude-memory/temp/41-v2-adversarial.md`
- `/home/idnotbe/projects/claude-memory/temp/41-master-briefing.md`

---

## 1. Action #1 구현에 대한 구체적 영향

### 1-A. "raw_bm25를 confidence_label에 전달" 코드 변경의 운명

Deep Analysis 이전의 흐름을 먼저 정리한다.

원래 V2-adversarial 리뷰(`41-v2-adversarial.md`)는 `memory_retrieve.py:257`에서 `score` 필드가 `BM25 - body_bonus` 복합값으로 in-place 변이됨을 발견하고, `confidence_label()`이 순수 BM25가 아닌 복합 점수를 받는다는 점을 **CRITICAL** 버그로 분류했다. 이 분석에 따라 analyst-score(`41-finding1-3-score-domain.md`)는 두 줄의 코드 수정을 제안했다:

```python
# Line 283 -- best_score 계산 변경
best_score = max((abs(entry.get("raw_bm25", entry.get("score", 0))) for entry in top), default=0)

# Line 299 -- confidence_label 호출 변경
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_score)
```

그러나 V2 adversarial 공격 라운드(`41-v2-adversarial.md`, Attack 1a)가 이 수정안 자체에 치명적 결함을 발견했다. **랭킹-라벨 역전(Ranking-label inversion, NEW-4)** 이다.

```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0  (랭킹 #1 -- 복합 점수 기준)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5  (랭킹 #2)

raw_bm25 기준으로 confidence 계산 시:
  best_score = max(abs(-1.0), abs(-3.5)) = 3.5
  Entry A ratio = 1.0 / 3.5 = 0.286 -> "low"  (랭킹 #1이 LOW!)
  Entry B ratio = 3.5 / 3.5 = 1.0   -> "high" (랭킹 #2가 HIGH!)
```

Action #2의 tiered output에서 LOW = 침묵이므로, 가장 관련성 높은 #1 랭킹 결과가 침묵되고 #2 결과만 주입되는 기능적 버그가 발생한다.

**최종 결정:** `confidence_label()`은 현행 코드(복합 점수 사용)를 그대로 유지한다. 코드 변경 없음(0 LOC). plan 파일이 이를 반영하여 "현행 코드 유지 -- 코드 변경 없음"으로 명시되었다(`plan-retrieval-confidence-and-output.md` 라인 101, 143).

**정리:** 당초 "2줄 코드 변경"으로 계획된 Finding #1 수정은 Deep Analysis 결과 0 LOC 변경(plan 텍스트 수정만)으로 완전히 방향이 바뀌었다.

---

### 1-B. "복합 점수 도메인 유지"가 abs_floor 교정에 미치는 의미

**숫자 범위 관점:**

abs_floor는 `confidence_label()`이 받는 점수의 절대값과 비교된다. raw_bm25를 사용했을 경우 점수 범위는 일반적인 BM25 도메인(소형 코퍼스 기준 대략 -0.5 ~ -10.0 수준)이다.

그러나 복합 점수(BM25 - body_bonus)를 사용하는 경우:
- body_bonus 범위: 0 ~ 3 (정수, `min(3, len(body_matches))` 캡)
- 복합 점수는 body_bonus만큼 더 "음수" 방향으로 이동
- 따라서 abs(composite) 범위는 raw_bm25 범위보다 최대 3 단위 확대됨
- 일반 코퍼스 기준: abs(composite) 대략 0 ~ 15 범위 (plan 라인 91, 102)

**실용적 의미:**

당초 plan에서 abs_floor 권장 시작값은 BM25 모드 기준 1.0-2.0 범위였다. 복합 점수 도메인에서는 이 값이 다르게 해석된다:

- abs_floor=1.0은 복합 점수 기준으로 "body_bonus=0 상태에서 raw_bm25가 -1.0보다 강한 매칭만 통과"를 의미한다.
- 그러나 body_bonus=3인 항목이 있으면 복합 점수가 최대 3 단위 낮아지므로, 동일한 abs_floor=1.0이 원래 의도보다 더 관대하게 동작한다.
- 예: raw_bm25=-0.5(약한 매칭), body_bonus=3 -> composite=-3.5 -> abs=3.5 > abs_floor=1.0 -> "high" 분류. abs_floor의 품질 게이트 기능이 body_bonus에 의해 우회될 수 있다.

**결론:** plan 라인 69의 경고("abs_floor는 코퍼스 의존적 임시 조치. BM25 점수는 비정규화 값으로 스케일 변동")는 여전히 유효하며, 복합 점수 도메인에서는 body_bonus의 정수 오프셋이 추가 불확실성을 만든다. 권장 시작값을 raw_bm25 기준 1.0-2.0에서 복합 도메인 기준 1.0-3.0으로 상향 조정해야 한다(plan 라인 102 반영 완료). 데이터 기반 재교정의 필요성이 raw_bm25 도메인보다 더 높다.

---

### 1-C. 클러스터 감지 "비활성 유지" 결정으로 줄어든 코드 변경량

**원래 계획했던 클러스터 감지 구현 작업:**

plan의 Progress 체크리스트(라인 139-152)에서 클러스터 감지 관련 항목을 식별하면:

- `[ ] 클러스터 감지 로직 구현: cluster_count >= 3이면 최대 "medium"` (라인 141)
- `[ ] _output_results()에서 복합 점수 기반 cluster_count 계산` (라인 142 전반부)
- `[ ] main()에서 retrieval.cluster_detection_enabled 설정 파싱 추가` (라인 146)
- `[ ] 단위 테스트: 클러스터 감지 (~5개)` (라인 148)
- `[ ] 단위 테스트: 조합 시나리오 (~3개)` (라인 149 -- abs_floor + 클러스터 조합)

Deep Analysis(`41-finding2-cluster-logic.md`) 결과 클러스터 감지는 수학적으로 tautology임이 증명되어 **비활성 유지**로 결정되었다. 이로 인해 다음 작업이 불필요해졌다:

**불필요해진 체크리스트 항목:**

| 항목 | 원래 예상 작업량 | 현재 상태 |
|------|-----------------|----------|
| 클러스터 감지 로직 구현 (cluster_count >= 3) | ~8-12 LOC | 불필요 (기능 비활성) |
| `_output_results()`에서 cluster_count 계산 | ~5-8 LOC | 불필요 (계산값 사용 안 함) |
| `main()`에서 cluster_detection_enabled 파싱 | ~3-5 LOC | 설정 키만 추가 (실제 로직 없음) |
| 단위 테스트: 클러스터 감지 (~5개) | ~25-40 LOC | 불필요 |
| 단위 테스트: 조합 시나리오 (~3개) | ~15-25 LOC | 불필요 |

단, `cluster_detection_enabled: false` 설정 키 자체는 `assets/memory-config.default.json`에 여전히 추가되어야 하므로 설정 파일 변경은 유지된다(라인 145).

`confidence_label()` 함수 시그니처에서 `cluster_count: int = 0` 파라미터도 여전히 추가되지만(라인 139), 실제로 비-제로 값으로 전달되는 코드 경로가 없으므로 이 파라미터는 현재로서는 미래를 위한 인터페이스 예약에 불과하다.

**구체적 코드 변경량 감소:**

클러스터 감지 비활성 유지로 Action #1의 코드 변경량은:
- 원래 예상: ~20-35 LOC (시그니처 확장 + abs_floor + 클러스터 로직 + 설정 파싱)
- Deep Analysis 후: ~10-18 LOC (시그니처 확장 + abs_floor + 설정 파싱만)
- 테스트 변경량: 원래 예상 ~35-65 LOC에서 ~18-35 LOC로 감소

---

### 1-D. Progress 체크리스트 중 불필요해진 항목

plan 라인 139-152의 체크리스트를 항목별로 검토한다:

**여전히 필요한 항목:**
- 라인 139: `confidence_label()` 시그니처 확장 (`abs_floor`, `cluster_count` 파라미터 추가) -- 필요. 단, cluster_count는 현재 호출 시 항상 0으로 전달됨
- 라인 140: 절대 하한선 로직 구현 -- 필요
- 라인 144: `main()`에서 `retrieval.confidence_abs_floor` 설정 파싱 -- 필요
- 라인 145: `assets/memory-config.default.json` 설정 키 추가 -- 필요
- 라인 146: `main()`에서 `retrieval.cluster_detection_enabled` 파싱 -- 필요 (설정 키는 추가하되, 실제로 cluster_count를 계산해 전달하는 로직은 없음)
- 라인 147: 단위 테스트: abs_floor 경계값 (~8개) -- 필요
- 라인 150: 기존 `TestConfidenceLabel` 17개 회귀 테스트 통과 확인 -- 필요
- 라인 151, 152: compile/pytest 확인 -- 필요

**불필요해진 항목:**
- 라인 141: 클러스터 감지 로직 구현 (`cluster_count >= 3` 조건) -- **불필요** (기능 비활성. 미래 활성화 시 pre-truncation counting으로 재구현 예정)
- 라인 142 전반부: `_output_results()`에서 cluster_count 계산 -- **불필요** (cluster_count를 계산해도 confidence_label에 0으로 전달하므로 실질적 의미 없음)
- 라인 143: `confidence_label()` 호출 시 복합 점수 사용 확인 -- **불필요** (현행 코드 유지이므로 "확인"만 필요하나 별도 작업 없음)
- 라인 148: 단위 테스트: 클러스터 감지 (~5개) -- **불필요** (비활성 기능 테스트 불필요)
- 라인 149: 단위 테스트: 조합 시나리오 (~3개) -- **불필요** (클러스터 + abs_floor 조합은 테스트 불가)

**핵심 정리:** 체크리스트 14개 항목 중 5개가 불필요해졌다. 특히 클러스터 감지 테스트 ~8개가 제거되어 테스트 작성 부담이 크게 줄었다.

---

## 2. Action #2 (계층적 출력)에 대한 영향

### 2-A. NEW-4 (Ranking-label inversion) 기각으로 Action #2의 안전성 변화

**기각 전의 위험:**

만약 raw_bm25 수정이 적용되었다면, Action #2의 tiered output은 다음과 같은 시스템적 위험에 노출되었다:

1. body bonus가 높은 항목(body 관련성 있음)이 raw_bm25 기준 LOW로 분류되어 침묵됨
2. body bonus가 없는 항목(title/tag만 매칭)이 HIGH로 분류되어 주입됨
3. 결과적으로 Claude는 실제로 더 관련성 높은 항목(body 증거 있음)을 받지 못하고, 덜 관련된 항목을 받음

이 버그는 tiered output 모드가 활성화될 때만 발현되고, legacy 모드에서는 confidence가 informational attribute로만 사용되어 기능적 영향 없었을 것이다.

**기각 후의 안전성:**

복합 점수(composite score)를 그대로 사용함으로써:
- confidence 라벨은 랭킹 순서와 단조 관계(monotonic relationship)를 유지한다
- 랭킹 #1 항목은 항상 ratio=1.0, HIGH 라벨을 받는다
- 랭킹 #2, #3 항목은 best_score 대비 ratio에 따라 HIGH/MEDIUM/LOW로 분류된다
- tiered output에서 LOW로 침묵되는 항목은 랭킹 하위 항목이며, 이는 의도된 동작이다

**결론:** NEW-4 기각으로 Action #2는 "confidence가 행동 트리거(action trigger)로 사용될 때 랭킹과 단조 관계를 유지해야 한다"는 핵심 불변식을 보장받는다. Action #2의 설계는 Deep Analysis 전보다 더 안전한 기반 위에 서 있다.

---

### 2-B. "LOW = 침묵"이 복합 점수 기반 confidence에서 안전한가

**랭킹-라벨 일관성 분석:**

복합 점수(BM25 - body_bonus) 기반 confidence에서:
- best_score = 결과 중 최대 abs(composite)
- ratio = abs(composite_i) / best_score
- HIGH: ratio >= 0.75
- MEDIUM: ratio >= 0.40
- LOW: ratio < 0.40

단일 결과(N=1): ratio = 1.0, 항상 HIGH -> 침묵 없음. 안전.

복수 결과(N=2): 랭킹 #1은 항상 ratio=1.0 (HIGH). #2는 ratio에 따라 HIGH/MEDIUM/LOW. LOW=침묵은 best_score 대비 40% 미만인 항목에만 적용됨. 이는 "최강 결과와 비교해 60% 이상 품질 차이나는 항목은 노이즈"라는 합리적 기준이다.

**잠재적 위험 시나리오:**

body_bonus가 비대칭적으로 분포된 경우:
- 항목 A: raw_bm25=-2.0, body_bonus=3, composite=-5.0 (랭킹 #1, ratio=1.0, HIGH)
- 항목 B: raw_bm25=-4.0, body_bonus=0, composite=-4.0 (랭킹 #2, ratio=0.8, HIGH)
- 항목 C: raw_bm25=-1.5, body_bonus=0, composite=-1.5 (랭킹 #3, ratio=0.3, LOW)

항목 C가 raw_bm25=-1.5로 의미 있는 텍스트 매칭이 있음에도 침묵된다. 이는 body_bonus=3을 가진 A가 composite 분모를 크게 만들어 C의 ratio를 낮추는 효과 때문이다. 이것이 NEW-1(apply_threshold noise floor distortion)과 유사한 성격의 문제이며, 복합 점수 도메인에서 abs_floor 교정의 어려움과 같은 근원을 가진다.

**결론:** LOW=침묵은 복합 점수 기반 confidence에서 **조건부 안전**하다. 대부분의 경우 합리적으로 동작하지만, body_bonus 분포가 비대칭적일 때 의미 있는 raw_bm25 매칭이 침묵될 수 있다. 이 위험은 tiered output의 기본값을 "legacy"로 유지하는 이유 중 하나이며, PoC #5 데이터를 통해 실증적으로 검증해야 한다.

---

### 2-C. Action #2 코드의 변경 필요성

**필요한 변경:**

Deep Analysis 결과는 Action #2 코드 자체에는 영향을 미치지 않는다. `_output_results()` 함수의 tiered output 로직(HIGH -> `<result>`, MEDIUM -> `<memory-compact>`, LOW -> 침묵)은 confidence 라벨이 어떻게 생성되는지와 무관하게 동작한다.

**confidence_label의 입력이 변하지 않으므로 Action #2 코드는 수정 불필요하다.**

변경 사항은 Action #1(confidence 생성 방법)에만 해당하며, Action #2(confidence 소비 방법)는 계획대로 구현하면 된다.

단, Action #2 구현 시 주의해야 할 사항이 있다: `_output_results()` 함수 시그니처에 `abs_floor` 파라미터가 추가되지만(plan 라인 247-248), 이것은 Action #1에서 계산된 cluster_count를 함수 내부에서 사용할 수 있게 하기 위함이다. Action #2 자체의 output 형식 분기 로직은 이 파라미터와 무관하게 동작한다.

---

## 3. NEW-1 (apply_threshold noise floor distortion)의 잠재적 영향

### 3-A. Action #1의 abs_floor와의 상호작용

**두 임계치의 역할:**

`apply_threshold()` (선택 임계치)와 `confidence_label()`의 abs_floor (분류 임계치)는 plan에서 "독립적"이라고 명시되어 있다(라인 63). 그러나 Deep Analysis는 이 독립성이 실제로는 완전하지 않음을 보여준다.

**상호작용 메커니즘:**

`apply_threshold()`의 noise floor 계산(`memory_search_engine.py:284`):
```
noise_floor = best_composite * 0.25
```

이 floor는 composite score 기준이다. body_bonus가 높은 항목이 best_score를 높이면, floor 값도 올라가 raw_bm25는 의미 있지만 body_bonus=0인 항목들이 제거될 수 있다.

`confidence_label()`의 abs_floor는 이미 `apply_threshold()`를 통과한 결과에만 적용된다. 따라서:

1. `apply_threshold()`가 body_bonus 편향으로 일부 결과를 부당하게 제거하면, abs_floor에 도달하는 결과 집합 자체가 편향된다.
2. abs_floor로 교정하려는 "약한 매칭의 과신" 문제가, 이미 `apply_threshold()`에서 선별된 결과에만 적용되므로 의도한 교정 효과가 제한될 수 있다.
3. 역설적으로: body_bonus=0이면서 raw_bm25가 moderate한 항목이 `apply_threshold()`에서 제거되면, abs_floor가 있어도 그 항목을 구제할 수 없다.

**실제 위험 수준:**

body_bonus는 0-3 정수로 상한이 있고, 일반적인 BM25 점수(-2 ~ -10 범위)에서 최대 3 단위 차이가 실질적 필터링 왜곡을 일으키려면 특정 조건이 필요하다(analyst-score의 worked example: best_raw=-2.0, body_bonus=3 -> floor=1.25, victim_raw=-1.0, body_bonus=0 -> composite=-1.0 < 1.25 -> 제거). 이 조건은 코퍼스와 쿼리 패턴에 따라 빈번하거나 드물 수 있다.

---

### 3-B. PoC #5 데이터 없이 NEW-1을 해결하려 할 때의 위험

**위험 1: 과잉 수정(over-correction)**

`apply_threshold()`를 raw_bm25 기반으로 바꾸면 ranking 순서가 변경된다. body_bonus는 body 관련성의 정당한 신호이므로, 이를 무시한 필터링은 관련성 높은 항목을 오히려 제거할 수 있다.

**위험 2: 인터페이스 변경 파급효과**

`apply_threshold()`는 `memory_search_engine.py`에 있으며, plan에서 명시적으로 "변경하지 않는 파일"로 지정되어 있다(라인 437). 이 파일을 수정하면:
- CLI 검색(`memory_search_engine.py --mode search`)의 동작도 변경됨
- `test_fts5_search_engine.py`의 기존 테스트들이 영향받을 수 있음
- 다른 plan들(plan-search-quality-logging.md 등)과의 충돌 가능성

**위험 3: 경험적 기반 없는 임계치 결정**

noise floor 왜곡이 실제로 얼마나 자주, 어떤 조건에서 발생하는지 데이터 없이는 알 수 없다. PoC #5 로깅(raw_bm25 + score + body_bonus 트리플 필드)이 이 데이터를 제공할 것이다. 데이터 없이 수정하면:
- 문제가 실제로 드물게 발생한다면 불필요한 복잡도를 추가한 것
- 잘못된 임계치를 설정하면 오히려 retrieval 품질이 저하됨

**권장 접근:**

NEW-1은 별도 이슈로 트래킹하고, PoC #5 로깅 인프라 구축 후 데이터를 보고 결정하는 것이 옳다(41-final-report.md의 "Deferred -- let PoC #5 data inform" 처분이 적절하다). 임의로 수정하려 하면 위험 대비 이점이 불분명하다.

---

## 4. 전체 Plan의 총 변경량 재추정

### 4-A. Deep Analysis 전 추정 (plan 라인 452-464)

| 항목 | LOC |
|------|-----|
| Action #1 코드 | ~20-35 |
| Action #2 코드 | ~40-60 |
| Action #3 코드 | ~6-10 |
| **코드 소계** | **~66-105** |
| Action #1 테스트 | ~35-65 |
| Action #2 테스트 | ~80-150 |
| Action #3 테스트 | ~15-25 |
| **테스트 소계** | **~130-240** |
| **총계** | **~196-345** |

---

### 4-B. Deep Analysis 후 예상 변경량

**Action #1 코드:**

| 작업 | Deep Analysis 전 | Deep Analysis 후 |
|------|-----------------|-----------------|
| confidence_label() 시그니처 확장 | ~5 LOC | ~5 LOC (동일) |
| abs_floor 로직 | ~8-12 LOC | ~8-12 LOC (동일) |
| raw_bm25 사용 코드 변경 (lines 283, 299) | ~2 LOC | 0 LOC (기각됨) |
| cluster_count 계산 로직 | ~5-8 LOC | 0 LOC (비활성 유지) |
| cluster_count >= 3 조건 구현 | ~5-8 LOC | 0 LOC (비활성 유지) |
| 설정 파싱 (abs_floor + cluster_enabled) | ~5-8 LOC | ~5-8 LOC (동일) |
| **Action #1 소계** | **~20-35 LOC** | **~13-25 LOC** |

**Action #1 테스트:**

| 작업 | Deep Analysis 전 | Deep Analysis 후 |
|------|-----------------|-----------------|
| abs_floor 경계값 테스트 (~8개) | ~25-40 LOC | ~25-40 LOC (동일) |
| 클러스터 감지 테스트 (~5개) | ~20-30 LOC | 0 LOC (불필요) |
| 조합 시나리오 테스트 (~3개) | ~15-25 LOC | 0 LOC (불필요) |
| 기존 회귀 테스트 확인 | ~0 LOC | ~0 LOC (동일) |
| **Action #1 테스트 소계** | **~35-65 LOC** | **~25-40 LOC** |

**Action #2, #3은 Deep Analysis의 직접적 영향 없음:**

Action #2와 #3은 confidence 라벨의 생성 방법이 아닌 소비 방법에 관한 것이므로, Deep Analysis 결과로 변경량이 달라지지 않는다.

| 항목 | Deep Analysis 전 | Deep Analysis 후 |
|------|-----------------|-----------------|
| Action #2 코드 | ~40-60 LOC | ~40-60 LOC |
| Action #2 테스트 | ~80-150 LOC | ~80-150 LOC |
| Action #3 코드 | ~6-10 LOC | ~6-10 LOC |
| Action #3 테스트 | ~15-25 LOC | ~15-25 LOC |

**Deep Analysis로 인한 순증가:**

Deep Analysis 자체에서 발견된 Finding #4(--session-id CLI 파라미터)와 Finding #5(import 하드닝)는 plan-retrieval-confidence-and-output.md의 범위 밖이며 다른 plan 파일들에 해당한다. 이 파일 범위에서는 순증가 없다.

---

### 4-C. 최종 추정 비교

| 항목 | Deep Analysis 전 | Deep Analysis 후 | 변화 |
|------|-----------------|-----------------|------|
| Action #1 코드 | ~20-35 LOC | ~13-25 LOC | **-7~-10 LOC** |
| Action #2 코드 | ~40-60 LOC | ~40-60 LOC | 변화 없음 |
| Action #3 코드 | ~6-10 LOC | ~6-10 LOC | 변화 없음 |
| **코드 소계** | **~66-105 LOC** | **~59-95 LOC** | **~-7~-10 LOC** |
| Action #1 테스트 | ~35-65 LOC | ~25-40 LOC | **-10~-25 LOC** |
| Action #2 테스트 | ~80-150 LOC | ~80-150 LOC | 변화 없음 |
| Action #3 테스트 | ~15-25 LOC | ~15-25 LOC | 변화 없음 |
| **테스트 소계** | **~130-240 LOC** | **~120-215 LOC** | **~-10~-25 LOC** |
| **총계** | **~196-345 LOC** | **~179-310 LOC** | **~-17~-35 LOC** |

---

## 5. 종합 평가

### 5-A. 가장 중요한 변화: 방향의 명확화

숫자적 변화(~17-35 LOC 감소)보다 더 중요한 것은 **설계 방향의 명확화**다.

Deep Analysis 이전에는 "raw_bm25를 사용할지, composite score를 사용할지"가 미결 상태였으며 불확실성을 내포하고 있었다. Deep Analysis는 이 질문에 명확한 답을 제시했다:

> confidence 라벨이 행동 트리거(action trigger)로 사용될 경우, 라벨은 반드시 랭킹과 단조 관계(monotonic relationship)를 유지해야 한다. 따라서 composite score 사용이 의도적 설계이다.

이 원칙은 향후 모든 confidence 관련 변경의 설계 불변식(design invariant)으로 기능한다. 미래에 body_bonus 공식이 변경되거나 새로운 신호가 추가될 때도, 이 원칙을 위반하지 않는 방식으로 설계해야 한다.

### 5-B. 미해결 위험 요소

Deep Analysis 이후에도 다음 위험 요소가 미해결로 남아 있다:

1. **abs_floor 교정 불확실성**: 복합 점수 도메인에서의 abs_floor 적정값은 여전히 경험적 데이터 없이는 알 수 없다. 기본값 0.0(비활성)은 안전하지만, 실제 활성화 시점의 값 선택이 어렵다.

2. **NEW-1의 장기적 영향**: apply_threshold noise floor 왜곡이 실제 retrieval에 미치는 영향은 PoC #5 데이터 없이는 불명확하다.

3. **tiered output의 복합 점수 편향**: LOW=침묵이 body_bonus 비대칭 분포에서 의미 있는 raw BM25 매칭을 부당하게 침묵시킬 수 있다. 이는 tiered output을 "legacy" 기본값으로 유지해야 하는 추가 근거이다.

이 세 가지는 모두 PoC #5 로깅 인프라 구축 후 데이터를 보고 판단해야 한다. **Plan의 핵심 전략 -- 기본값을 안전하게 유지하고 데이터 기반으로 활성화 결정 -- 이 Deep Analysis 결과로 더욱 강화되었다.**
