# plan-retrieval-confidence-and-output.md 종합 분석 보고서

**작성일:** 2026-02-22
**분석 방법:** 3개 병렬 subagent (기술적 정합성, 의사결정 흐름, 미래 영향) + 자가비판 교차검증
**원본 파일:** `action-plans/plan-retrieval-confidence-and-output.md`
**관련 Deep Analysis 문서:** `temp/41-*.md` (11개 파일)

---

## 1. plan 파일 개요

`plan-retrieval-confidence-and-output.md`는 메모리 검색 시스템의 4가지 개선을 다루는 구현 계획이다:

| Action | 목적 | 핵심 변경 대상 |
|--------|------|--------------|
| #1 | confidence_label() 절대 하한선 + 클러스터 감지 | 신뢰도 분류의 정확도 개선 |
| #2 | 계층적 출력 (Tiered Output) | HIGH/MEDIUM/LOW에 따른 차별화된 주입 형식 |
| #3 | Hint 개선 | HTML 주석 -> XML 태그, all-low hint 추가 |
| #4 | Agent Hook PoC | type:"agent" hook 실험 (별도 브랜치) |

상태: not-started. 주 대상 파일: `hooks/scripts/memory_retrieve.py`.

---

## 2. Deep Analysis에서 이 plan에 직접 관련된 사항

### 2-A. Key Course Correction (핵심 방향 수정)

**raw_bm25 코드 변경이 기각(REJECT)되었다.**

이것이 Deep Analysis의 가장 중요한 결과이다. 전체 이야기를 시간순으로 정리하면:

**[1단계] 문제 발견:** V2-adversarial 검토가 `memory_retrieve.py:257`에서 `r["score"] = r["score"] - body_bonus`라는 in-place 변이를 추적했다. `confidence_label()`이 순수 BM25가 아닌 변이된 복합 점수를 받고 있었다. 이전 4라운드 검토에서는 아무도 이 런타임 데이터 흐름을 실제로 따라가지 않았다.

**[2단계] 수정 제안:** analyst-score가 2줄 코드 변경을 제안했다. `entry.get("score", 0)` 대신 `entry.get("raw_bm25", entry.get("score", 0))`를 사용하는 것. Codex, Gemini 모두 동의. V1 검증도 PASS.

**[3단계] 공격 성공:** V2-adversarial의 Attack 1a가 이 수정안 자체를 깨뜨렸다:

```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (랭킹 #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (랭킹 #2)

raw_bm25 기준 라벨링:
  best_score = 3.5
  Entry A ratio = 1.0/3.5 = 0.286 -> "low"   (랭킹 #1인데 LOW!)
  Entry B ratio = 3.5/3.5 = 1.0   -> "high"  (랭킹 #2인데 HIGH!)
```

**[4단계] 기능적 버그 확인:** Action #2에서 LOW = 침묵(출력 없음)이므로, 가장 관련성 높은 #1 랭킹 결과가 침묵되고 #2만 주입된다. 이것은 "랭킹-라벨 역전(Ranking-Label Inversion, NEW-4)"이라 명명되었다.

**[5단계] 핵심 원칙 도출:**
> "신뢰도 라벨이 행동 트리거(침묵/축약/전체)로 사용되면, 라벨은 반드시 랭킹과 단조 관계(monotonic relationship)를 유지해야 한다."

이 원칙은 세 가지 논리의 수렴으로 도출:
- 분석가의 의미론적 주장: "confidence = BM25 품질"
- Action #2의 설계 결정: "confidence = 행동 트리거 (LOW = 침묵)"
- V2-adversarial의 구체 시나리오: "#1 랭킹 결과가 침묵됨"

**[6단계] 최종 결정:** 코드 변경 0 LOC. 복합 점수(BM25 - body_bonus)를 그대로 사용. raw_bm25는 진단 로깅에만 사용. abs_floor를 복합 점수 도메인 기준으로 재교정.

**[7단계] 외부 독립 확인:**
- Gemini 3.1 Pro: "검색 시스템의 계약을 위반했다"
- Codex 5.3: "body 증거로 부스트된 엔트리가 top-ranked이면서 'low'로 라벨링되면 오해 소지"

---

### 2-B. Final Dispositions (최종 처분) 중 이 plan 관련 항목

5개 Finding 중 이 plan에 직접 영향을 미친 것은 **Finding #1**과 **Finding #2**이다.

#### Finding #1: Score Domain Paradox (점수 도메인 역설)
- **원래 심각도:** CRITICAL -> **최종 심각도:** HIGH
- **최종 처분:** 코드 변경 기각. 복합 점수 유지. abs_floor를 복합 도메인 기준 교정. raw_bm25는 진단 로깅 전용.
- **코드 변경:** 0 LOC
- **plan 반영 위치:** line 81-93 "핵심 수정" 블록
- **심각도 하향 이유:** tiered output 기본값이 "legacy"이므로 즉각적인 행동적 영향 없음 (라벨이 정보성 메타데이터로만 사용)

#### Finding #2: Cluster Tautology (클러스터 동어반복)
- **원래 심각도:** CRITICAL -> **최종 심각도:** LOW
- **최종 처분:** 비활성 유지. 수학적으로 dead code임이 증명됨.
- **코드 변경:** 0 LOC (plan 텍스트만 수정)
- **plan 반영 위치:** line 73-78 클러스터 감지 섹션

**수학적 증명 요약:**
- `max_inject=3`(기본값)에서 apply_threshold() 잘림 후 결과 수 N <= 3
- 클러스터 카운트 C <= N <= 3
- 따라서 `C > max_inject`(= `C > 3`)는 수학적으로 불가능 -> dead code
- 5가지 대안(Option A~E) 분석 결과, Option B(잘리기 전 카운팅)만 건전하나 비활성 기능을 위한 구현은 불필요한 엔지니어링
- Gemini: "Zombie Logic -- 복잡해 보이지만 실제로는 아무것도 하지 않는 코드"

#### 나머지 Finding들은 다른 plan 파일에 영향
| Finding | 영향 대상 plan |
|---------|--------------|
| #3 PoC #5 Measurement | plan-poc-retrieval-experiments.md |
| #4 PoC #6 Dead Path | plan-poc-retrieval-experiments.md |
| #5 Logger Import Crash | plan-search-quality-logging.md |

---

### 2-C. 5 Newly Discovered Issues 중 이 plan 관련 항목

#### NEW-1: apply_threshold noise floor distortion (LOW-MEDIUM)
- **내용:** apply_threshold()의 25% noise floor가 복합 점수 기준으로 계산됨. body_bonus가 높은 항목이 best_score를 높이면, raw_bm25는 의미 있지만 body_bonus=0인 항목이 부당하게 제거될 수 있음.
- **구체 예시:** best 항목이 raw=-2.0, bonus=3 -> composite=-5.0 -> floor=1.25. victim 항목이 raw=-1.0, bonus=0 -> composite=-1.0 -> floor 미달로 제거. 하지만 raw_bm25=-1.0은 의미 있는 매칭.
- **plan 반영:** **누락됨.** plan의 "변경하지 않는 파일" 섹션(line 437)에서 memory_search_engine.py를 제외했지만, 이 이슈의 존재 자체를 기록하지 않음.
- **처분:** Deferred -- PoC #5 데이터로 실제 영향 확인 후 결정.
- **이 plan과의 관계:** abs_floor와 noise floor가 이론적으로 독립이지만 실제로는 상호작용함. apply_threshold()가 body_bonus 편향으로 결과를 제거하면, abs_floor로 교정하려는 "약한 매칭의 과신" 문제가 이미 편향된 집합에만 적용됨.

#### NEW-4: Ranking-label inversion (HIGH)
- **내용:** raw_bm25 사용 시 랭킹-라벨 역전 발생 (위 2-A 참조)
- **plan 반영:** line 87에 기록됨. 단, "tiered 모드 비활성(기본값 legacy)에서는 behavioral impact 없음"이라는 조건부 severity 정보가 누락.
- **처분:** raw_bm25 코드 변경 기각으로 해결됨.

#### 나머지 NEW 이슈들
| 이슈 | 이 plan과의 관계 |
|------|----------------|
| NEW-2 Judge import vulnerability | Finding #5와 동일 클래스. plan-search-quality-logging.md 관련 |
| NEW-3 Empty XML after judge rejection | 별도 추적. plan에 직접 영향 없음 |
| NEW-5 ImportError masks transitive | Finding #5 개선. e.name 스코핑으로 해결 |

---

### 2-D. Process Assessment (프로세스 평가) 관련

7-agent, 5-phase Deep Analysis 파이프라인에 대한 자체 평가:

**발견된 가치:**
- V2-adversarial 라운드가 랭킹-라벨 역전(NEW-4)을 발견. 이것이 없었다면 raw_bm25 수정이 코드에 들어갔을 것이고, Action #2 tiered output 활성화 시 **가장 관련성 높은 결과가 침묵되는 회귀**로 출시될 뻔했다.
- 4라운드 검토에서 아무도 런타임 데이터 흐름을 추적하지 않았다는 구조적 맹점을 노출.

**과잉으로 평가된 부분:**
- Finding #2(클러스터 tautology), #3(PoC 측정), #4(세션 ID)는 LOW 심각도로, 멀티-에이전트 리뷰 대신 plan 텍스트 메모로 충분했음.

**향후 권고:** 트리아지 크기 조정. <50 LOC 수정 = 2-agent 파이프라인(분석가 + 검증자). >200 LOC 아키텍처 변경에만 전체 파이프라인 사용.

**이 plan과의 관계:** 7-agent 파이프라인이 이 plan의 핵심 가정(raw_bm25 사용)을 뒤집었다. plan의 코드 변경량은 ~48 LOC에 불과했지만, 방향 자체가 바뀌었으므로 프로세스 비용 대비 가치가 있었다.

---

## 3. 향후 구현에 미치는 구체적 영향

### 3-A. Action #1 변경량 감소

Deep Analysis로 인해 불필요해진 체크리스트 항목 5개:
- 클러스터 감지 로직 구현 (~8-12 LOC)
- cluster_count 계산 로직 (~5-8 LOC)
- 클러스터 감지 테스트 (~25-40 LOC)
- 조합 시나리오 테스트 (~15-25 LOC)
- raw_bm25 사용 코드 변경 (2 LOC, 기각됨)

**코드:** ~20-35 LOC -> ~13-25 LOC (-7~-10)
**테스트:** ~35-65 LOC -> ~25-40 LOC (-10~-25)

### 3-B. Action #2 안전성 강화

복합 점수 유지로 confidence 라벨과 랭킹의 단조 관계가 보장됨. Action #2 코드 자체는 변경 불필요. 설계 불변식이 확립되어 기반이 더 안전해짐.

### 3-C. 전체 plan 총 변경량 재추정

| 항목 | Deep Analysis 전 | Deep Analysis 후 |
|------|-----------------|-----------------|
| 코드 소계 | ~66-105 LOC | ~59-95 LOC |
| 테스트 소계 | ~130-240 LOC | ~120-215 LOC |
| **총계** | **~196-345 LOC** | **~179-310 LOC** |

숫자적 감소보다 중요한 것은 설계 방향의 명확화와 핵심 불변식의 확립이다.

---

## 4. plan의 기술적 정확성 평가

### 정확하게 반영된 항목
- Finding #1 최종 결정(raw_bm25 기각, 복합 점수 유지)
- Finding #2 수학적 증명(tautology, dead code)
- line 491 검토 이력 테이블
- NEW-4 발생 이유와 핵심 원칙

### 불완전하거나 누락된 항목
| 항목 | 심각도 | 설명 |
|------|--------|------|
| NEW-1 완전 누락 | 중간 | apply_threshold noise floor distortion이 plan 어디에도 기록되지 않음 |
| NEW-4 조건부 severity | 낮음 | "legacy 모드에서는 behavioral impact 없음"이라는 모드 의존성 미기술 |
| "모든 성공적인 쿼리" 과장 | 낮음 | 더 정확히는 "대다수의 3-결과 쿼리(>70%)" |
| line 62의 5개 결과 예시 | 낮음 | max_inject=3 잘림 이전/이후 구분 불명확 |

### 미해결 위험 요소
1. **abs_floor 교정 불확실성:** 복합 점수 도메인에서 적정값은 경험적 데이터 없이 알 수 없음
2. **NEW-1 장기적 영향:** PoC #5 데이터 수집 전까지 불명확
3. **tiered output의 복합 점수 편향:** body_bonus 비대칭 분포에서 의미 있는 매칭이 침묵될 가능성 -> tiered output "legacy" 기본값 유지의 추가 근거

---

## 5. 이 사례에서 도출된 교훈

1. **라벨의 소비자를 명시하라.** 신뢰도 라벨이 "정보성 메타데이터"인지 "행동 트리거"인지 처음부터 규정해야 한다.
2. **임계치는 전체 파이프라인 맥락에서 검증하라.** 격리된 함수 시그니처 검증은 런타임 데이터 흐름의 왜곡을 놓칠 수 있다.
3. **외부 검증도 맹점을 가진다.** Codex와 Gemini 모두 raw_bm25 수정에 동의했지만, Action #2와의 상호작용을 놓쳤다.
4. **프로세스 크기는 변경 규모에 비례해야 한다.** 48 LOC에 7-agent는 과잉이었으나, 핵심 버그를 찾았으므로 이번에는 정당화됨.

---

## 분석 방법론 참고

| 에이전트 | 역할 | 결과 파일 |
|---------|------|----------|
| 기술적 정합성 | plan vs Deep Analysis 내용 일치 검증 | temp/plan1-perspective-technical.md |
| 의사결정 흐름 | raw_bm25 기각까지의 논리 전개 추적 | temp/plan1-perspective-decision-flow.md |
| 미래 영향 | 향후 구현에 미치는 구체적 영향 분석 | temp/plan1-perspective-future-impact.md |
| 자가비판 | 3개 보고서 간 모순/누락/과장 검증 | (인라인 결과) |
