# plan-poc-retrieval-experiments.md 상세 분석 보고서

**작성일:** 2026-02-22
**대상 파일:** `action-plans/plan-poc-retrieval-experiments.md`
**분석 범위:** 플랜 내용 설명 + Deep Analysis(7-agent, 5-phase)와의 연관성 심층 분석

---

## 1부: 플랜 내용 설명

### 1.1 개요

이 플랜은 claude-memory 플러그인의 **메모리 검색(retrieval) 파이프라인**을 정량적으로 평가하기 위한 4개의 PoC(Proof-of-Concept) 실험 계획서다.

현재 플러그인은 BM25 기반 전문 검색(FTS5)으로 사용자 프롬프트와 관련된 메모리를 자동 검색하여 Claude 컨텍스트에 주입한다. 그런데 이 검색의 실제 품질에 대한 정량적 데이터가 전무하다. "느낌상 잘 동작한다"를 "precision@3 = X%"로 바꿔야 한다는 것이 핵심 동기다.

### 1.2 4개 PoC 실험

| PoC | 목적 | 핵심 질문 |
|-----|------|----------|
| **#4 Agent Hook** | agent hook이 UserPromptSubmit에서 어떻게 동작하는지 실험 | 레이턴시? 컨텍스트 주입 가능? |
| **#5 BM25 정밀도** | 현재 BM25 검색의 precision@k, recall@k 정량화 | 검색 품질이 충분한가? |
| **#6 Nudge 준수율** | 축약 주입의 `/memory:search` 사용 권고를 Claude가 따르는지 측정 | tiered output 전략이 유효한가? |
| **#7 OR-query 정밀도** | 단일 토큰 매칭의 false positive 비율 측정 | OR 결합의 오염도가 심각한가? |

### 1.3 실행 순서

`#4(spike, 1일 time-box) → #5 → #7 → #6`

- #4를 먼저: 최대 불확실성(agent hook 아키텍처) 해소
- #5 → #7: #7이 #5의 라벨링 데이터셋을 재활용
- #6 최후순위: Action #2(tiered output) 구현 후에야 측정 가능

### 1.4 외부 모델 합의

Codex 5.3, Gemini 3 Pro, Vibe-check 3개 소스에서 순서, 샘플 사이즈, 측정 지표에 대한 의견을 종합했다. 합의 결과:
- 파일럿 25-30 → 확장 50+ (Codex/Gemini는 50+ 필수, Vibe-check는 25-30 OK)
- 주 지표: `polluted_query_rate` (#7), `precision@k` (#5)
- PoC #6은 "탐색적 데이터 수집"으로 재분류 (인과 추론 불가)

---

## 2부: Deep Analysis와의 연관성

### 2.1 Key Course Correction -- raw_bm25 코드 변경 기각

**이것이 가장 핵심적인 전환점이다.**

Deep Analysis의 초기 분석(analyst-score)은 Finding #1(Score Domain Paradox)의 해결책으로 `memory_retrieve.py`의 라인 283, 299에서 `confidence_label()`이 mutated composite score 대신 `raw_bm25`를 사용하도록 2줄 코드 변경을 제안했다.

그러나 V2-adversarial 라운드에서 **ranking-label inversion(NEW-4)**이 발견되었다:

```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (ranked #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (ranked #2)

raw_bm25로 confidence 계산 시:
  Entry A ratio = 1.0/3.5 = 0.286 → "low"
  Entry B ratio = 3.5/3.5 = 1.0   → "high"

결과: #1 결과가 "low", #2 결과가 "high"
```

이것이 왜 치명적인가? Action #2(tiered output)에서 confidence label이 주입 형태를 결정하기 때문이다:
- HIGH → 전체 주입
- LOW → **침묵(주입 안 함)**

즉, 가장 관련성 높은 #1 결과가 침묵되고, 덜 관련 있는 #2가 전체 주입되는 역전 현상이 발생한다.

**plan-poc에 미치는 영향:**
- PoC #5의 측정 프레임이 완전히 바뀌었다
- raw_bm25 기각 → composite score 유지 → `label_precision` 지표가 composite 도메인에서 동작
- "Action #1 전후 비교"의 대상이 `precision@k`(변하지 않음)가 아닌 `label_precision`(라벨 분류 정확도)으로 재정의

### 2.2 Final Dispositions (5 Findings) -- 각 Finding의 plan-poc 연관성

#### Finding #1: Score Domain Paradox (최종 HIGH)

**연관 유형:** 간접 but 강력

- 코드 변경 기각(0 LOC)이지만, PoC #5의 측정 방법론에 근본적 영향
- `abs_floor`를 composite 도메인(~0-15 range)에 맞게 보정해야 한다는 결론
- Triple-field 로깅(raw_bm25 + score + body_bonus)은 PoC #5 데이터 분석의 기반
- **자가비판:** plan의 "Deep Analysis 최종 반영" 블록(라인 196-213)은 raw_bm25 기반 dual precision을 언급하는데, 이는 기각된 코드 변경의 논리를 아직 담고 있다. dual precision 자체는 유효하지만 "BM25 자체의 검색 품질" vs "사용자가 실제로 받는 결과의 품질"의 해석이 달라져야 한다.

#### Finding #2: Cluster Tautology (최종 LOW)

**연관 유형:** 간접, 미약

- 직접적 plan 변경 없음
- 그러나 PoC #5의 "Action #1 사전/사후 비교"에서 cluster detection이 dead code임이 증명되었으므로, Action #1의 독립변수가 "abs_floor만"으로 축소
- Deep Analysis 없이 cluster detection이 활성화된 상태로 PoC를 실행했다면, 대부분의 3-결과 쿼리에서 high→medium 강등이 발생하여 잘못된 label_precision 분석으로 이어졌을 가능성

#### Finding #3: PoC #5 Measurement Invalidity (최종 LOW)

**연관 유형:** 직접 -- plan의 PoC #5 섹션 전면 개정

plan-poc-retrieval-experiments.md의 라인 196-213에 반영된 내용:
1. **Triple-field 로깅:** `raw_bm25`, `score`(복합), `body_bonus` 3개 필드
2. **Dual precision:** 두 도메인 모두에서 precision 계산
3. **label_precision 지표:** Action #1 전후 비교는 `label_precision_high/medium` 측정
4. **인간 어노테이션:** 관련성 ground truth 판정을 위한 루브릭 ("이 메모리를 보고 Claude가 더 나은 답변을 할 수 있는가?")

**핵심 교훈:** precision@k가 Action #1 전후 동일한 것은 **정상 결과**다. Action #1은 라벨만 바꾸고 랭킹은 불변이기 때문이다. 이를 모르고 측정하면 "효과 없음"이라는 잘못된 결론을 내릴 뻔했다.

#### Finding #4: PoC #6 Dead Correlation Path (최종 LOW)

**연관 유형:** 직접 -- PoC #6 상태 변경 (BLOCKED → PARTIALLY UNBLOCKED)

plan-poc-retrieval-experiments.md의 라인 295-307에 반영된 내용:

**발견된 문제:** `/memory:search` skill은 `memory_search_engine.py` CLI를 호출하는데, CLI 모드에는 `hook_input`이 없으므로 `session_id`가 항상 빈 문자열이다. `retrieval.inject.session_id`와 `search.query.session_id`의 JOIN은 **구조적으로 0 매칭**을 반환한다. 즉, PoC #6의 핵심 측정인 "compact 주입 후 `/memory:search` 호출" 상관관계를 아예 추적할 수 없었다.

**해결책 (~12 LOC):**
1. `memory_search_engine.py`에 `--session-id` argparse 파라미터 추가
2. 우선순위: `CLI arg > CLAUDE_SESSION_ID env var > 빈 문자열`
3. `emit_event("search.query", ...)` 호출 시 session_id 전달

**자가비판:** "PARTIALLY UNBLOCKED"라는 표현은 실질적 측정 가능성보다 낙관적이다. 자동 skill-to-hook 상관관계는 여전히 불가능하다(CLAUDE_SESSION_ID 환경변수 미존재). 수동 CLI 테스트만 가능하며, 이는 "Claude의 자발적 행동 측정"이라는 원래 목적과는 다르다.

#### Finding #5: Logger Import Crash (최종 HIGH)

**연관 유형:** 간접 but 중요 -- 모든 PoC의 실행 전제 조건

- Plan #2(로깅 인프라) 배포 시 `memory_logger.py` 임포트로 retrieval hook이 크래시되는 것을 방지
- `e.name` scoping 패턴으로 "모듈 부재"(fallback)와 "전이적 의존성 실패"(fail-fast)를 구분
- Judge import도 동일 패턴으로 hardening (NEW-2 해결)
- **이것 없이는 로깅 데이터 수집 자체가 불안정** → 모든 PoC의 기반

### 2.3 5 Newly Discovered Issues -- plan-poc 연관성

| Issue | 심각도 | plan-poc 연관성 | 상세 |
|-------|--------|----------------|------|
| **NEW-1** (apply_threshold noise floor 왜곡) | LOW-MEDIUM | PoC #5 데이터로 검증 예정 | body_bonus가 25% noise floor를 왜곡하여 유효한 BM25 매칭 결과를 폐기할 가능성. PoC #5 triple-field 로깅 데이터로 실제 발생 빈도를 실증해야 함 |
| **NEW-2** (Judge import 취약점) | HIGH | Finding #5와 함께 해결됨 | judge_enabled=true + 모듈 부재 시 크래시. PoC 실행 시 judge가 켜진 환경에서 데이터 수집이 중단될 수 있었음 |
| **NEW-3** (Judge가 모든 후보 거부 시 빈 XML) | LOW | PoC #5 데이터에서 발현 가능 | Judge가 모든 후보를 필터링하면 빈 `<memory-context/>` 출력. 토큰 낭비이나 기능적 버그는 아님 |
| **NEW-4** (Ranking-label inversion) | HIGH | **가장 극적인 영향** | raw_bm25 코드 변경 기각의 직접적 원인. PoC #5 baseline을 오염시키고 PoC #6의 tiered output 전제를 무너뜨렸을 regression. Deep Analysis의 최대 가치 발견 |
| **NEW-5** (ImportError가 전이적 실패를 은폐) | MEDIUM | Finding #5의 `e.name` scoping으로 해결 | 모듈은 존재하지만 내부 의존성 실패 시 silent degradation. 로깅 모듈이 조용히 꺼지면 PoC 데이터 수집이 불완전해짐 |

### 2.4 Process Assessment -- plan-poc 시사점

**Final Report의 자체 평가:**
> "7 agents / 5 phases / 10+ documents for ~48 LOC of code changes"

plan-poc-retrieval-experiments.md에 대한 실질적 변경은 약 110행이며, 이를 위해 1,500행 이상의 분석 문서가 생산되었다 (14:1 비율). 이는 명백히 과도한 프로세스였다.

**그러나 프로세스가 정당화되는 이유:**
1. **NEW-4 발견:** V2-adversarial 라운드가 아니었다면, raw_bm25 코드 변경이 그대로 적용되어 tiered output에서 regression이 발생했을 것
2. **Finding #5:** 실제 hot-path crash 방지
3. **Finding #4:** PoC #6이 실행 후에야 "데이터 0건" 문제를 발견했을 것 → 시간 낭비 방지

**향후 권장:** triage sizing 적용. plan text만 수정하는 경우 = 2-agent pipeline (analyst + verifier). 코드 변경이 포함되면 별도 triage.

---

## 3부: 비판적 분석 -- 간과된 문제점

### 3.1 plan의 "Deep Analysis 반영" 블록은 기각된 분석의 흔적을 담고 있다

plan 라인 196-213의 "V2-adversarial + Deep Analysis 최종 반영" 블록은 `41-solution-synthesis.md` (V1 라운드)의 내용을 반영한 것이다. `41-final-report.md` (V2 라운드)에서 raw_bm25 코드 변경이 기각되었는데, raw_bm25 기반 dual precision의 해석이 수정되지 않았다.

composite score로 ranking과 confidence_label이 결정된다면, "raw_bm25 기반 ranking precision"은 순수 진단 지표로만 의미가 있다. plan은 이 구분을 하지 않는다.

### 3.2 PoC #7의 토큰 매칭 추정 방식이 body_bonus를 반영하지 않는다

plan의 PoC #7(라인 280-287)은 `title+tags` 토큰화로 매칭을 추정한다. 그러나 body에서만 발생하는 단일 토큰 오염(예: "error"가 body에서만 매칭)은 측정하지 못한다. Finding #1에서 body_bonus의 존재와 영향이 명확해졌는데, PoC #7의 방법론은 이를 반영하여 수정되지 않았다.

### 3.3 `--session-id` 구현이 PoC #6 체크리스트에 명시되어 있지 않다

plan의 PoC #6 체크리스트(라인 447-455)에 `--session-id` CLI 파라미터 구현이 명시적 항목으로 없다. 이는 PoC #6의 선행 조건임에도 불구하고 누락되었다.

### 3.4 실험 순서의 재검토가 이루어지지 않았다

Finding #1 기각으로 PoC #5 baseline의 긴급성이 높아졌지만, 실험 순서(#4 먼저)는 재검토되지 않았다.

---

## 4부: 연결 요약 다이어그램

```
Deep Analysis (7-agent, 5-phase)
├── Finding #1 (Score Domain Paradox) ──→ raw_bm25 코드 변경 기각
│   ├── NEW-4 발견 (ranking-label inversion)
│   └──→ PoC #5 방법론 변경: label_precision + dual precision
│
├── Finding #2 (Cluster Tautology) ──→ dead code 증명
│   └──→ PoC #5: Action #1 독립변수 축소 (abs_floor만)
│
├── Finding #3 (PoC #5 Measurement) ──→ [직접 반영]
│   ├── Triple-field 로깅 (raw_bm25 + score + body_bonus)
│   ├── label_precision 지표 도입
│   └── Human annotation 루브릭 명시화
│
├── Finding #4 (PoC #6 Dead Path) ──→ [직접 반영]
│   ├── --session-id CLI 파라미터 (~12 LOC)
│   └── BLOCKED → PARTIALLY UNBLOCKED
│
├── Finding #5 (Import Crash) ──→ 모든 PoC 로깅 안정성 기반
│   ├── e.name scoping 패턴
│   ├── Judge hardening (NEW-2 해결)
│   └── NEW-5 해결 (전이적 ImportError 구분)
│
├── NEW-1 (noise floor 왜곡) ──→ PoC #5 데이터로 향후 검증
└── NEW-3 (빈 XML) ──→ 별도 추적
```
