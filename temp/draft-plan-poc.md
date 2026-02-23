# Plan #3: PoC 실험 계획 (Proof-of-Concept Experiments)

**날짜:** 2026-02-22
**작성자:** plan3-drafter
**상태:** Draft
**검증 소스:** Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check
**의존성:** Plan #2 (로깅 인프라스트럭처)

---

## 배경 (Background)

### 왜 PoC 실험이 필요한가

현재 claude-memory 플러그인은 BM25 기반 자동 검색 + 컨텍스트 주입 아키텍처로 동작한다. 이전 분석(Session 9)에서 4가지 즉시 실행 가능한 개선 액션(#1-#4)과 4가지 데이터 수집 후 결정할 실험(PoC #4-#7)이 도출되었다.

**PoC가 필요한 핵심 이유:**

1. **아키텍처 불확실성 해소** -- Agent hook (`type: "agent"`)이 UserPromptSubmit에서 동작하는 것은 확인되었으나, 실제 레이턴시와 output 메커니즘(컨텍스트 주입 가능 여부)은 미측정. 이것이 향후 retrieval 아키텍처 방향을 결정한다.

2. **검색 품질 정량화** -- 현재 BM25 검색의 정밀도(precision)와 재현율(recall)에 대한 정량적 데이터가 전무. "느낌상 잘 동작한다"를 "precision@3 = X%"로 바꿔야 한다.

3. **OR-query 오염도 측정** -- `build_fts_query()`가 OR로 토큰을 결합하므로, "React error handling" 쿼리에서 "error" 단독 매칭이 무관한 결과를 주입하는 문제의 실제 빈도를 측정해야 한다.

4. **축약 주입 효과 검증** -- Action #2 (tiered output) 도입 후 MEDIUM confidence 축약 주입에 포함된 `/memory:search` 사용 권고를 Claude가 실제로 따르는지 측정해야 한다.

**모든 PoC는 Plan #2의 로깅 인프라에 의존한다.** 로그 없이는 사후 분석이 불가능하다.

---

## 목적 (Purpose)

각 PoC가 어떤 의사결정을 지원하는지:

| PoC | 의사결정 | 결과에 따른 후속 조치 |
|-----|---------|---------------------|
| #4 Agent Hook | Agent hook을 retrieval 파이프라인에 통합할 것인가? | YES: 하이브리드 아키텍처 설계 / NO: command hook 유지 |
| #5 BM25 정밀도 | 현재 검색 품질이 충분한가? Action #1 교정 후 개선 폭은? | 정밀도 낮음: 검색 알고리즘 개선 우선 / 높음: 현행 유지 |
| #6 Nudge 준수율 | Claude가 축약 주입의 검색 권고를 따르는가? | 높음: tiered output 전략 유효 / 낮음: 대안 필요 |
| #7 OR-query 정밀도 | 단일 토큰 매칭의 false positive가 심각한가? | 심각: min-should-match 또는 AND 폴백 도입 / 경미: 현행 유지 |

---

## 관련 정보 (Related Info)

### 실행 순서 및 근거

**결정된 순서: #4 (time-boxed) -> #5 -> #7 -> #6**

이 순서에 대해 Codex 5.3, Gemini 3 Pro, Vibe-check의 의견을 종합했다:

| 소스 | 추천 순서 | 핵심 근거 |
|------|----------|----------|
| Codex 5.3 | #4(spike) -> #5 -> #7 -> #6 | "최대 불확실성(agent hook)을 먼저 해소, 그 다음 baseline 데이터 수집" |
| Gemini 3 Pro | #4 -> #5 -> #7 -> #6 | "Agent hook은 아키텍처 dealbreaker. 결과 불문 1일 내 완료 가능" |
| Vibe-check | #5 -> #7 -> #4 -> #6 | "Baseline 없이 아키텍처 결정은 성급. 다만 #4가 아키텍처를 바꿀 수 없다면 (ok/false만 반환) 우선순위 낮춤 타당" |

**합의:** #4를 **엄격하게 시간 제한된 스파이크**(최대 1일)로 먼저 실행. 결과 불문 빠르게 종료하고 #5로 진입. #7은 #5의 라벨링 데이터셋을 재활용하므로 #5 직후. #6은 Action #2 구현 후에야 측정 가능하므로 최후순위.

### Plan #2 (로깅 인프라) 의존성 매핑

| PoC | 소비하는 로그 이벤트 (Plan #2) | 추가 필요 로깅 | 데이터 추출 방법 |
|-----|------------------------------|--------------|----------------|
| #4 Agent Hook | `retrieval.search` (`duration_ms`) | agent hook 전용 타이밍 로그 (별도 브랜치) | `jq '.duration_ms'` 비교 (command vs agent) |
| #5 BM25 정밀도 | `retrieval.search` (`data.results`, `data.candidates_found`) | 없음 -- Plan #2 스키마로 충분 | `cat logs/retrieval/*.jsonl \| jq` → 수동 라벨링 대조 |
| #6 Nudge 준수율 | `retrieval.inject` (`data.output_mode`) | **skill 호출 로깅** -- `/memory:search` 호출 시 `search.query` 이벤트와 session_id 상관관계 | `retrieval.inject`에서 `output_mode="compact"` 필터 → 동일 `session_id`의 후속 `search.query` 이벤트 조인 |
| #7 OR-query 정밀도 | `retrieval.search` (`data.query_tokens`, `data.results`) | **토큰별 매칭 정보** -- 각 결과가 어떤 쿼리 토큰에 의해 매칭되었는지 (Plan #2 스키마에 `matched_tokens` 필드 추가 권장) | `jq` 필터: `data.results[] \| select(.matched_token_count == 1)` → 수동 라벨링 대조 |

**중요: PoC #6의 추가 요구사항**

Plan #2의 현재 설계에서는 `/memory:search` skill 호출을 별도 이벤트로 기록하지 않는다. `search.query` 이벤트는 `memory_search_engine.py` CLI 호출 시 발생하지만, skill 호출과의 인과 관계를 추적하려면:

1. `retrieval.inject` 이벤트에 `session_id` + `turn_id` 포함 (Plan #2에서 이미 `session_id` 지원)
2. `search.query` 이벤트에 동일한 `session_id` 포함
3. **귀인 윈도우(attribution window)** 정의: compact 주입 후 3턴 이내 또는 5분 이내의 `/memory:search` 호출을 "준수"로 간주

Codex와 Gemini 모두 이 상관관계의 신뢰성에 우려를 표했다. Codex는 "인과 관계 주장을 위해 무작위 A/B 필요"라 지적했고, Gemini는 "시간 윈도우 제약에 의존하면 brittle"이라 평가했다.

### 코드 참조

| 파일 | 라인 | PoC 관련 |
|------|------|---------|
| `hooks/hooks.json` | 43-55 | #4 -- 현재 UserPromptSubmit hook (command type) |
| `hooks/scripts/memory_retrieve.py` | 161-174 | #5 -- `confidence_label()` 상대 비율 문제 |
| `hooks/scripts/memory_retrieve.py` | 262-301 | #5, #6 -- `_output_results()` 주입 포맷 |
| `hooks/scripts/memory_retrieve.py` | 458, 495, 560 | #5 -- 0-result hint 발생 지점 |
| `hooks/scripts/memory_search_engine.py` | 205-226 | #7 -- `build_fts_query()` OR 결합 |
| `hooks/scripts/memory_search_engine.py` | 283-288 | #5, #7 -- `apply_threshold()` 25% noise floor |
| `temp/agent-hook-verification.md` | 전체 | #4 -- Agent hook 출력 메커니즘 분석 |

### 샘플 사이즈 결정 근거

| 소스 | #5 권장 샘플 사이즈 | 근거 |
|------|-------------------|------|
| Codex 5.3 | 50-80 (paired set) | "20-30은 pilot calibration에만 유효. 사전/사후 비교에는 paired set 필요" |
| Gemini 3 Pro | 50-100 (task type별 계층화) | "20-30은 통계적으로 부족, 메트릭 jitter 발생" |
| Vibe-check | 20-30 OK (rough estimate) | "precision@k with k=3-5에서 60-150개 binary 판정. 60% vs 90% 구분에는 충분" |

**결정:** 파일럿 라운드 25-30개로 시작, 방법론 검증 후 50개 이상으로 확장. 쿼리를 5개 유형으로 계층화 (직접 매칭, 모호한 쿼리, 무관한 쿼리, 다중 개념, 식별자 중심).

### #7 측정 지표 결정 근거

| 소스 | 권장 지표 | 근거 |
|------|----------|------|
| Codex 5.3 | 쿼리 수준 pollution rate + 보조로 token-support 지표 | "주 지표: top-k에 단일 토큰 무관 결과 포함 여부. 진단용: token_support_count" |
| Gemini 3 Pro | 쿼리 수준 Precision@3 | "토큰 정밀도는 내부 구현 디테일. LLM 현실은 주입된 문서로 결정" |
| Vibe-check | 쿼리 수준 분석 | "단일 토큰 매칭이 결과를 지배했는지가 핵심 질문" |

**결정:** 주 지표는 `polluted_query_rate` (top-k에 단일 토큰 전용 무관 결과가 포함된 쿼리 비율). 보조 지표로 `single_token_fp_rate` (전체 무관 결과 중 단일 토큰 매칭 결과 비율).

---

## PoC 상세 설계

### PoC #4: Agent Hook 실험

**목적:** `type: "agent"` hook이 UserPromptSubmit에서 어떻게 동작하는지 실험. 레이턴시, 출력 메커니즘, 플러그인 호환성 확인.

**핵심 질문:**
1. Agent hook의 p50/p95 레이턴시는? (현재 command hook ~100ms 대비)
2. Agent hook이 컨텍스트를 주입할 수 있는가? (`ok: false` + `reason` 필드? 다른 메커니즘?)
3. 플러그인 `hooks/hooks.json`에서 `type: "agent"`가 정상 동작하는가?

**브랜치 격리 필수:** `hooks.json` 변경은 모든 프롬프트에 영향 -- 별도 git 브랜치 (`poc4-agent-hook`)에서 실행.

**로깅 의존성:**
- Plan #2의 `retrieval.search` 이벤트에서 `duration_ms` 필드 활용
- Agent hook 브랜치에서 동일한 `emit_event()` 인터페이스로 타이밍 기록
- `jq '.duration_ms'`로 command hook baseline과 agent hook 레이턴시 비교

**실험 설계:**

```
현재 (baseline):
  hooks.json: type="command" → memory_retrieve.py → stdout → 컨텍스트 주입

실험 A (agent hook 대체):
  hooks.json: type="agent" → prompt로 BM25 검색 지시 → {ok: true/false} 반환
  측정: 레이턴시, 컨텍스트 주입 여부

실험 B (하이브리드):
  hooks.json: [command hook (주입)] + [agent hook (필터링)]
  측정: 결합 레이턴시, 필터링 정확도
```

**Agent Hook 출력 메커니즘 참고** (`temp/agent-hook-verification.md`):
- Command hook: stdout 텍스트 → Claude 컨텍스트에 자동 주입
- Agent hook: `{ "ok": true/false, "reason": "..." }` → 허용/차단 결정
- **핵심 제약:** Agent hook은 임의 텍스트 주입 불가. `ok: false` 시 `reason`이 Claude에게 전달되지만, 이는 "차단 사유"이지 "주입 컨텍스트"가 아님
- 따라서 **메모리 주입에는 여전히 command hook 필요**. Agent hook은 필터링/판단 용도로만 활용 가능

**종료 기준 (Kill Criteria):**
- 레이턴시 p95 > 5초: agent hook을 auto-inject 경로에 부적합으로 판정
- 컨텍스트 주입 불가 확인: 하이브리드 접근(command + agent)으로 전환하거나, 아키텍처 dead-end로 종료
- **최대 1일 time-box.** 결과 불문 1일 후 종료하고 문서화

**종료 후 경로 (리뷰 반영 -- 명시적 실패 경로):**
- Kill criteria 충족 또는 time-box 만료 시:
  1. 브랜치 아카이브 (`poc4-agent-hook` 유지, main에 미병합)
  2. 실험 결과를 `temp/agent-hook-poc-results.md`에 문서화 (레이턴시 데이터, 주입 가능 여부, 결론)
  3. Plan #1의 Action #4를 **WONTFIX** 또는 **DEFERRED**로 표기
  4. PoC #5로 즉시 진행 (agent hook 결과와 무관하게)

---

### PoC #5: BM25 정밀도 측정

**목적:** 현재 BM25 검색의 precision@k와 recall@k를 정량화. Action #1 (절대 하한선 + 클러스터 감지) 사전/사후 비교 baseline 확보.

**핵심 문제 (코드 근거):**

1. **단일 결과 항상 high** (`memory_retrieve.py:161-174`):
   ```python
   ratio = abs(score) / abs(best_score)  # 단일 결과: ratio = 1.0 → 항상 "high"
   ```

2. **상대적 noise floor** (`memory_search_engine.py:283-288`):
   ```python
   noise_floor = best_abs * 0.25  # 약한 best_score → 약한 noise floor
   ```

3. **OR 결합** (`memory_search_engine.py:226`):
   ```python
   return " OR ".join(safe)  # 단일 토큰 매칭으로 무관한 결과 반환
   ```

**로깅 의존성:**
- `retrieval.search` 이벤트: 전체 후보 리스트 (`data.results`), 점수, confidence 라벨
- `retrieval.search` 이벤트: threshold 적용 전/후 후보 수 (`data.candidates_found`, `data.candidates_post_threshold`)
- 로그에서 쿼리별 전체 파이프라인 데이터를 추출하여 수동 라벨링 대상 확보

> **V2-adversarial CRITICAL 반영 -- Score Domain Paradox:**
> 현재 로그의 `data.results[].score`는 `BM25 - body_bonus` 변이값. Plan #2에서 `raw_bm25` 필드를 추가하여 순수 BM25 점수 별도 기록.
>
> - **BM25 품질 질문:** `raw_bm25` 기반 ranking의 precision → "BM25 자체의 검색 품질"
> - **End-to-end 품질 질문:** 최종 `score` 기반 ranking의 precision → "사용자가 실제로 받는 결과의 품질"
> - **Action #1 사전/사후 비교 주의:** Action #1은 `confidence_label()`만 변경하며 ranking은 불변. 따라서 precision@k 값은 Action #1 전후 동일할 것이 **정상** (null result가 아님). 측정 대상은 "ranking quality"가 아니라 "label quality" -- high/medium/low 분류 정확도 변화를 비교해야 함.

**방법론:**

#### Phase A: 파일럿 (25-30 쿼리)

1. **쿼리 수집:** 실제 프로젝트에서 사용된 프롬프트 25-30개 수집 (로그 기반)
2. **계층화 (5개 유형):**
   - 직접 매칭 (예: "OAuth 설정" → OAuth 관련 메모리)
   - 모호한 쿼리 (예: "에러 처리 방법" → 여러 카테고리 매칭 가능)
   - 무관한 쿼리 (예: "오늘 날씨" → 매칭 없어야 함)
   - 다중 개념 (예: "React 컴포넌트에서 API 에러 처리" → 복합 매칭)
   - 식별자 중심 (예: "user_auth_flow 함수" → 정확한 식별자 매칭)
3. **수동 라벨링:** 각 쿼리에 대해 top-k (k=3, 5) 결과의 관련성을 binary 라벨링 (relevant / not relevant)
4. **메트릭 계산:** precision@3, precision@5, recall@k

#### Phase B: 확장 (50+ 쿼리)

1. 파일럿 방법론 검증 후 50개 이상으로 확장
2. **Paired evaluation:** Action #1 적용 전/후 동일 쿼리셋으로 비교
3. 계층별(stratum) precision 분석 -- 어떤 유형의 쿼리에서 precision이 낮은지 식별
4. 신뢰 구간 보고

**라벨링 품질 보장:**
- **Test-retest reliability (리뷰 반영):** 단일 평가자 환경이므로 inter-annotator agreement 대신 test-retest reliability 사용. 동일 5-6개 쿼리를 1주 간격으로 재라벨링하여 자기 일치도 측정.
  - 원안의 inter-annotator agreement (Cohen's kappa)는 2인 이상 평가자 필요 -- 단일 개발자 프로젝트에서 비현실적.
- 라벨링 루브릭 사전 정의: "이 메모리를 보고 Claude가 더 나은 답변을 할 수 있는가?"

---

### PoC #7: OR-query 정밀도

**목적:** `build_fts_query()`의 OR 결합에서 단일 토큰 매칭이 발생시키는 false positive 비율 측정.

**핵심 문제 (코드 근거):**

`hooks/scripts/memory_search_engine.py:226`:
```python
return " OR ".join(safe)
# "React error handling" → '"react"* OR "error"* OR "handling"*'
# "error"가 "Error logging configuration for backend services" 매칭
# → 무관한 backend 메모리가 React 질문에 주입됨
```

**로깅 의존성:**
- `retrieval.search` 이벤트: `data.query_tokens` (사용된 쿼리 토큰)
- `retrieval.search` 이벤트: `data.results` (각 결과의 점수)
- **추가 권장:** `data.results[].matched_tokens` -- 각 결과가 어떤 쿼리 토큰과 매칭되었는지. 현재 FTS5 `rank` 함수는 전체 점수만 반환하므로, 토큰별 매칭 정보는 별도 구현 필요

**방법론:**

1. **#5의 라벨링 데이터셋 재활용:** PoC #5에서 이미 라벨링된 50+ 쿼리 결과를 사용
2. **오염 분석:**
   - 각 결과에 대해 "몇 개의 쿼리 토큰과 매칭되었는가?" 분석
   - `matched_token_count == 1`인 결과 중 "not relevant" 라벨 비율 산출
3. **주 지표 -- `polluted_query_rate`:**
   - top-k 결과에 단일 토큰 전용 무관 결과가 하나 이상 포함된 쿼리의 비율
   - 계산: `count(queries with single-token irrelevant in top-k) / total_queries`
4. **보조 지표 -- `single_token_fp_rate`:**
   - 전체 무관 결과 중 단일 토큰 매칭 결과의 비율
   - 계산: `count(irrelevant AND single_token_match) / count(irrelevant)`
5. **반사실 분석 (Codex 권장):**
   - 현재 OR baseline과 min-token-support >= 2 필터 적용 시 precision 비교
   - AND/OR 캐스케이드 (AND 먼저, 0결과 시 OR 폴백) 시뮬레이션

**토큰 매칭 정보 추출 방법:**

현재 FTS5는 전체 매치 점수만 반환하므로, 토큰별 매칭은 다음 방법으로 추정:
```python
# 각 결과의 title+tags를 토큰화 → 쿼리 토큰과 교집합 계산
result_tokens = tokenize(result["title"]) | result["tags"]
matched_tokens = query_tokens & result_tokens
matched_token_count = len(matched_tokens)
```
이 방식은 body bonus까지는 반영하지 못하지만, title+tags 수준의 단일 토큰 매칭 오염도를 측정하기에 충분하다.

**결정 임계치 (사전 설정):**
- `polluted_query_rate > 30%`: OR 의미론 개선 우선순위 상승
- `polluted_query_rate > 50%`: min-should-match 또는 AND 폴백 즉시 구현

---

### PoC #6: Nudge 준수율 측정 (**BLOCKED** -- 계측 인프라 미비)

> **V2-adversarial HIGH 반영 -- Dead Correlation Path:**
> `/memory:search` skill은 `memory_search_engine.py` CLI를 호출. CLI 모드에는 `hook_input`이 없으므로 `session_id`가 빈 문자열. `retrieval.inject.session_id`와 `search.query.session_id` 조인은 **구조적으로 0 매칭**을 반환. 이것은 "brittle"이 아니라 **측정 불가능**.
>
> **해제 조건:** `memory_search_engine.py` CLI에 `--session-id` 파라미터 추가 + `/memory:search` skill이 현재 session_id 전달. 구현 비용: ~15 LOC. 이 해제 조건이 충족되기 전까지 PoC #6은 BLOCKED.

**목적:** Action #2 (tiered output) 도입 후, MEDIUM confidence 축약 주입에 포함된 `/memory:search` 사용 권고를 Claude가 실제로 따르는지 측정.

**선행 의존성:**
- **Action #2 구현 완료** (Plan #1) -- tiered output이 없으면 측정 대상 자체가 없음
- **Plan #2 로깅 인프라** -- compact injection 이벤트 기록 필요
- **session_id 상관관계** -- injection 이벤트와 skill 호출 이벤트를 같은 세션으로 연결
- **NEW: `--session-id` CLI 파라미터** -- `memory_search_engine.py`에 추가 필요 (V2-adversarial)

**로깅 의존성:**
- `retrieval.inject` 이벤트: `data.output_mode` (full/compact/silent), `session_id`
- `search.query` 이벤트: `session_id` (동일 세션에서 `/memory:search` 호출 시)
- **추가 필요:** `retrieval.inject` 이벤트에 `turn_id` 또는 타임스탬프 기반 순서 정보 포함

**방법론:**

#### 측정 정의

```
준수율 = (compact 주입 후 N턴/M분 이내 /memory:search 호출 수) / (compact 주입 총 발생 수)
```

**귀인 윈도우 (Attribution Window):**
- 시간: compact 주입 후 5분 이내
- 턴 수: compact 주입 후 3턴 이내
- 둘 중 먼저 도달하는 조건 적용

#### 데이터 수집

1. Action #2 구현 후 N개 세션에 걸쳐 자연스러운 사용 데이터 수집
2. `retrieval.inject` 로그에서 `output_mode="compact"` 이벤트 필터링
3. 동일 `session_id`의 후속 `search.query` 이벤트와 시간순 조인
4. 귀인 윈도우 내 매칭 비율 계산

#### 분석 주의사항 (외부 모델 피드백)

- **Codex 5.3 우려:** "상관관계 ≠ 인과관계. 신뢰할 수 있는 인과 추정을 위해 무작위 A/B (nudge 표시 vs 미표시)가 필요"
- **Gemini 3 Pro 우려:** "세션 ID 기반 cross-event correlation은 brittle. 어떤 nudge가 skill 사용을 유발했는지 확정 불가"
- **Vibe-check 우려:** "로깅 인프라가 skill 호출을 기록하는가? 현재 Plan #2는 retrieval 이벤트만 기록. skill 호출 로깅이 추가 필요"

**위 우려 반영 + 리뷰 피드백 (adversarial MEDIUM -- 방법론 재분류):**

> **중요 변경 (리뷰 반영):** PoC #6은 "의사결정 게이트"에서 **"탐색적 데이터 수집(exploratory data collection)"으로 재분류**.
>
> 근거: 작업 복잡도(confounding variable)가 compact injection과 후속 검색을 동시에 유발 -- 복잡한 쿼리는 (a) 낮은 confidence 매칭(→ compact injection)과 (b) 사용자 후속 검색(→ 작업 자체가 어려움) 둘 다 야기. nudge가 검색을 유발했는지, 작업 복잡도가 유발했는지 구분 불가.
>
> 따라서:
> - v1은 **상관관계 데이터만 수집** (인과 주장 완전 자제)
> - **결정 임계치 제거** -- 이 데이터만으로 제품 결정 불가
> - A/B 테스트(nudge 표시/미표시 무작위화)는 v2에서 설계
> - `search.query` 이벤트 로깅이 Plan #2에 포함되어 있으므로 기본 상관관계 수집은 가능
> - `nudge_id` 추가 고려: compact injection 시 고유 ID 부여하여 상관관계 강화

**데이터 수집 목표 (결정 임계치 대체):**
- compact injection 발생 빈도 파악
- 후속 `/memory:search` 호출 빈도 파악
- 상관관계 보고 (충분한 caveat와 함께)
- v2 A/B 테스트 설계를 위한 baseline 데이터 확보

---

## 위험 및 완화 (Risks & Mitigations)

| 위험 | 심각도 | PoC | 완화 |
|------|--------|-----|------|
| Agent hook이 컨텍스트 주입을 지원하지 않음 | 중간 | #4 | 1일 time-box + 명확한 kill criteria. 주입 불가 시 하이브리드(command+agent) 또는 종료 |
| 샘플 사이즈 부족으로 부정확한 precision 결론 | 중간 | #5 | 파일럿 25-30 → 확장 50+. 계층별 분석으로 약점 특정 |
| 라벨링 편향 (단일 평가자) | 낮음 | #5, #7 | 20% 중복 라벨링 + 라벨링 루브릭 사전 정의 |
| OR → AND 전환 시 recall 급감 | 중간 | #7 | 반사실 분석에서 AND/OR 캐스케이드 시뮬레이션 |
| Nudge 준수율 측정의 인과 추론 불가 | 높음 | #6 | **재분류 (리뷰 반영):** v1은 탐색적 데이터 수집으로 한정. 결정 임계치 제거. A/B 테스트는 v2 |
| Plan #2 로깅 지연으로 PoC 착수 불가 | 중간 | 전체 | #4는 로깅 없이 수동 측정 가능. #5 파일럿도 수동 실행 가능 |
| Agent hook 레이턴시가 사용 불가 수준 | 중간 | #4 | 60초 기본 타임아웃 → 필요시 단축. p95 > 5s면 auto-inject 부적합 판정 |

---

## 외부 모델 합의 (External Model Consensus)

### Codex 5.3 (planner 모드)

- **순서:** 하이브리드 추천 -- time-boxed #4 spike → #5 → #7 → #6
- **샘플 사이즈:** 20-30은 pilot only. 의사결정용 50-80 paired queries
- **#7 지표:** 쿼리 수준 pollution rate (주) + 결과 수준 token-support (보조)
- **#6 신뢰성:** 무작위 A/B 없이는 인과 주장 불가. event-linkage 완전성 >= 95% 확인 후 분석
- **추가 제안:** inter-annotator agreement (Cohen's kappa >= 0.6), 반사실 분석(min-should-match 필터)

### Gemini 3 Pro (planner 모드)

- **순서:** #4(spike) → #5(baseline) → #7(fix) → #6(analytics last)
- **샘플 사이즈:** 50-100 queries stratified by task type
- **#7 지표:** 쿼리 수준 Precision@3. "토큰 정밀도는 내부 디테일, LLM 현실은 주입된 문서로 결정"
- **#6 신뢰성:** "Feasible but brittle. 시간 윈도우 제약에 의존"
- **추가 제안:** AND/OR 캐스케이드 폴백 (AND 먼저, 0결과시 OR), LLM-as-judge로 라벨링 부트스트랩

### Vibe-check 피드백 반영

- #4의 아키텍처 변경 가능성은 제한적 (ok/false만 반환) → time-box로 빠르게 종료하되 과도한 기대 금지
- #7은 #5의 부분집합 분석으로 처리 가능 → 별도 실험보다 #5 데이터 재활용 권장
- #6은 현재 로깅이 skill 호출을 기록하지 않음 → Plan #2에 추가 요구사항 전달 필요

---

## 진행 상황 (Progress)

### PoC #4: Agent Hook 실험 (SEPARATE BRANCH)
- [ ] `poc4-agent-hook` 브랜치 생성
- [ ] 최소 agent hook 구성 (`hooks.json`에 `type: "agent"` 추가)
- [ ] agent hook prompt 작성 (BM25 검색 결과 읽기 + 관련성 판단)
- [ ] 20개 통제된 프롬프트로 p50/p95 레이턴시 측정 (command hook baseline 대비)
- [ ] 컨텍스트 주입 가능 여부 검증 (`reason` 필드, `additionalContext` 등)
- [ ] 플러그인 `hooks/hooks.json`에서 `type: "agent"` 정상 동작 확인
- [ ] 결과 문서화: 레이턴시, 주입 가능 여부, 추천 아키텍처 경로
- [ ] Kill criteria 평가 후 종료/계속 결정
- [ ] 브랜치 정리 (main merge 또는 archive)

### PoC #5: BM25 정밀도 측정
- [ ] 라벨링 루브릭 정의 ("이 메모리를 보고 Claude가 더 나은 답변을 할 수 있는가?")
- [ ] 5개 쿼리 유형 정의 및 예시 작성
- [ ] 파일럿 쿼리셋 수집 (25-30개, 로그 기반 또는 수동 작성)
- [ ] 파일럿 쿼리 실행 + top-k 결과 수집 (k=3, k=5)
- [ ] 수동 라벨링 (relevant / not relevant)
- [ ] 파일럿 precision@3, precision@5, recall@k 계산
- [ ] 파일럿 방법론 검증 + 필요시 루브릭 수정
- [ ] 확장 쿼리셋 수집 (50개 이상)
- [ ] 확장 라벨링 + test-retest reliability 측정 (5-6개 쿼리 1주 간격 재라벨링)
- [ ] Action #1 적용 전 baseline 메트릭 확정
- [ ] Action #1 적용 후 동일 쿼리셋으로 사후 메트릭 계산
- [ ] 계층별(stratum) 분석 + 신뢰 구간 보고

### PoC #7: OR-query 정밀도
- [ ] #5 라벨링 데이터셋에서 다중 토큰 쿼리 추출
- [ ] 각 결과의 토큰 매칭 정보 추출 (title+tags 토큰화 → 쿼리 토큰 교집합)
- [ ] `polluted_query_rate` 계산 (주 지표)
- [ ] `single_token_fp_rate` 계산 (보조 지표)
- [ ] 반사실 분석: min-token-support >= 2 필터 적용 시 precision 변화
- [ ] 반사실 분석: AND/OR 캐스케이드 시뮬레이션
- [ ] 결정 임계치 평가 (pollution rate > 30%/50%)
- [ ] 개선 방안 권고 (min-should-match, AND 폴백, 가중 OR 등)

### PoC #6: Nudge 준수율 측정
- [ ] 선행 의존성 확인: Action #2 구현 완료 여부
- [ ] Plan #2에 `/memory:search` skill 호출 로깅 추가 요청 전달
- [ ] 귀인 윈도우 정의 확정 (시간/턴 수 기준)
- [ ] 데이터 수집 기간 설정 (N개 세션, M일)
- [ ] `retrieval.inject` 로그에서 `output_mode="compact"` 이벤트 필터링
- [ ] `search.query` 로그와 session_id 기반 조인
- [ ] 상관관계 데이터 계산 (결정 임계치 없이 탐색적 보고)
- [ ] 결과 보고 (상관관계 only, confounding variable 주의사항 명시, 인과 추론 완전 자제)
- [ ] v2 A/B 테스트 설계를 위한 baseline 데이터 확보 여부 평가

---

## 부록: 측정 지표 요약

| 지표 | PoC | 정의 | 목표 |
|------|-----|------|------|
| precision@3 | #5 | top-3 결과 중 relevant 비율 | baseline 확보, Action #1 후 개선 측정 |
| precision@5 | #5 | top-5 결과 중 relevant 비율 | 상동 |
| recall@k | #5 | 전체 relevant 중 top-k에 포함된 비율 | recall 손실 없이 precision 개선 확인 |
| polluted_query_rate | #7 | 단일 토큰 무관 결과가 top-k에 포함된 쿼리 비율 | < 30% 목표 |
| single_token_fp_rate | #7 | 무관 결과 중 단일 토큰 매칭 비율 | 진단용 (임계치 없음) |
| agent_hook_p95_latency | #4 | agent hook p95 응답 시간 | < 5s (auto-inject 적합성) |
| nudge_compliance_rate | #6 | compact 주입 후 /memory:search 호출 비율 | 탐색적 수집 (결정 임계치 없음, 리뷰 반영) |

---

## 부록: Cross-Plan 구현 순서 (리뷰 반영)

세 플랜 간의 구현 순서를 명시한다. 특히 `memory_retrieve.py`가 Plan #1과 Plan #2 모두에서 수정되므로 순서가 중요.

```
1. Plan #2 Phase 1-2: 로거 모듈 생성 + retrieval.search 이벤트 (최소 실행 가능 로깅)
2. PoC #5 Phase A: 파일럿 baseline (현재 retrieval 상태에서 25-30 쿼리 측정)
3. Plan #1 Actions #1-#3: confidence 교정, tiered output, hint 개선
4. Plan #2 Phase 3-4: 수정된 코드에 나머지 계측 + 마이그레이션
5. PoC #5 Phase B: 사후 비교 (Action #1 적용 후 동일 쿼리셋)
6. PoC #7: OR-query 분석 (#5 데이터 재활용)
7. PoC #6: Nudge 준수율 탐색적 수집 (Action #2 구현 후)
8. Plan #1 Action #4: Agent Hook PoC (독립, 별도 브랜치에서 병행)
```

**핵심 근거:**
- Plan #2 최소 로깅이 먼저 -- PoC #5의 baseline 데이터 캡처 필요
- PoC #5 baseline이 Plan #1 Actions 전에 -- 사전/사후 비교를 위해 변경 전 측정 필수
- Plan #1 Actions 후 Plan #2 나머지 계측 -- 수정된 코드에 로깅 포인트 추가해야 정확
- Action #4(Agent Hook)는 전 과정과 독립적으로 병행 가능
