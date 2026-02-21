# LLM Judge 구현 현황 최종 분석

## 조사 대상
두 가지 메모리 검색 경로에서 LLM judge가 구현되어 있는지, 관련성(relevance)과 유용성(usefulness)을 모두 판단하는지 조사.

---

## 경로 1: UserPromptSubmit Hook (자동 주입)

### 구현 상태: IMPLEMENTED

| 항목 | 상태 |
|------|------|
| LLM Judge | memory_judge.py에 구현, memory_retrieve.py에서 호출 |
| 기본 활성화 | **비활성** (judge.enabled: false, opt-in) |
| API 키 필요 | YES (ANTHROPIC_API_KEY) |
| 모델 | claude-haiku-4-5-20251001 (설정 변경 가능) |
| 타임아웃 | 3.0초 |
| 대화 컨텍스트 | 마지막 5턴 (transcript_path에서 추출) |
| 위치 편향 방지 | YES (sha256 시드 기반 결정적 셔플) |
| 실패 시 | 보수적 top-K 폴백 (기본 2개) |

### 판단 기준: **Strict** — 관련성 + 유용성 모두 평가

```
A memory QUALIFIES if:
- It addresses the same topic, technology, or concept          ← 관련성
- It contains decisions, constraints, or procedures that apply NOW  ← 유용성
- Injecting it would improve the response quality              ← 유용성
- The connection is specific and direct, not coincidental      ← 관련성

A memory does NOT qualify if:
- It shares keywords but is about a different topic            ← 관련성 필터
- It is too general or only tangentially related               ← 관련성 필터
- It would distract rather than help                           ← 유용성 필터
- The relationship requires multiple logical leaps             ← 관련성 필터
```

---

## 경로 2: /memory:search 스킬 (사용자 명시적 검색)

### 구현 상태: IMPLEMENTED

| 항목 | 상태 |
|------|------|
| LLM Judge | SKILL.md에서 Task subagent로 오케스트레이션 |
| 기본 활성화 | **비활성** (같은 config 키: judge.enabled: false) |
| API 키 필요 | NO (Task subagent 사용, Claude 자체 컨텍스트 내 실행) |
| 모델 | haiku (Explore subagent) |
| 대화 컨텍스트 | 전체 대화 이력 (subagent가 대화 컨텍스트 전체 접근) |
| 위치 편향 방지 | NO (BM25 순위 그대로 전달) |
| 실패 시 | 필터링 없이 전체 BM25 결과 표시 |

### 판단 기준: **Lenient** — 관련성만 평가, 유용성은 미평가

```
Which of these memories are RELATED to the user's query? Be inclusive --
a memory qualifies if it is about a related topic, technology, or concept,
even if the connection is indirect. Only exclude memories that are clearly
about a completely different subject.
```

---

## 경로 3: Claude Code 자율적 검색 (에이전트가 필요하다고 판단했을 때)

### 구현 상태: NOT IMPLEMENTED / NOT PLANNED

- agents/ 디렉터리 없음
- plugin.json에 에이전트 등록 없음
- Claude가 자율적으로 메모리를 검색하라는 지시 없음
- rd-08-final-plan.md에도 해당 계획 없음
- UserPromptSubmit hook의 자동 주입이 유일한 자동 경로

---

## 핵심 발견: 의도적 비대칭 (Intentional Asymmetry)

| 측면 | 경로 1 (자동 주입) | 경로 2 (명시적 검색) |
|------|-------------------|---------------------|
| 모드 | **Strict** | **Lenient** |
| 기준 | 관련성 + 유용성 | 관련성만 (포괄적) |
| 오탐(FP) 허용도 | **낮음** (암묵적 주입) | **높음** (사용자가 명시적 요청) |
| 설계 근거 | 암묵적 주입은 높은 정밀도 필요 | 명시적 검색은 넓은 재현율 필요 |

**설계 의도** (rd-08-final-plan.md):
- 자동 주입은 사용자 모르게 컨텍스트에 삽입 → 오탐 시 토큰 낭비 + 컨텍스트 오염
- 명시적 검색은 사용자가 직접 결과를 훑음 → 미탐(FN)이 더 큰 문제

---

## 미구현 사항 / 갭 분석

### 1. 경로 3 (자율적 검색) 미존재
사용자가 "Claude Code가 정보가 필요하다고 판단했을 때"라고 했는데, 현재 이 경로는 존재하지 않음. /memory:search는 사용자가 직접 호출해야만 작동.

### 2. 경로 2 유용성 판단 부재
On-demand judge는 "관련된가?"만 판단하고, "현재 작업에 실제로 도움이 되는가?"는 판단하지 않음. "Be inclusive... even if the connection is indirect"가 핵심 지시.

### 3. 경로 2 위치 편향 방지 부재
memory_judge.py는 sha256 셔플을 통해 LLM의 위치 편향을 방지하지만, SKILL.md의 on-demand judge는 BM25 순위 그대로 전달. 잠재적 편향 존재.

### 4. 기본 비활성화
양쪽 모두 judge가 기본 비활성. 즉, 설정을 변경하지 않으면 BM25 결과만으로 작동.

### 5. Dual Verification 취소
원래 S9에서 이중 검증(관련성 judge + 유용성 judge)을 계획했으나, AND-gate 재현율 ~49%로 급락하는 문제로 취소됨. 단일 judge가 양쪽 모두 커버하는 것으로 결론.

---

## 검증 이력
- Round 1: 5개 subagent 병렬 조사 (코드, 계획서, 테스트, judge, 검색엔진)
- Vibe Check: 3가지 핵심 검증 포인트 도출
- Round 2: 2개 독립 검증 subagent (Claim-by-claim 확인, 유용성 기준 심층 분석)
- 모든 5개 Claim CONFIRMED
