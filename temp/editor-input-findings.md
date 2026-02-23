# Editor Input: Deep Analysis Findings for plan-poc-retrieval-experiments.md

**작성일:** 2026-02-22
**작성자:** context-specialist
**권위적 소스:** `temp/41-final-report.md` (최종 보고서)
**보조 소스:** `temp/41-finding1-3-score-domain.md`, `temp/41-finding4-5-integration.md`, `temp/41-solution-synthesis.md`, `temp/41-v2-adversarial.md`, `temp/41-v1-incorporated.md`
**감사 기준:** `temp/poc-plan-audit-verification.md`

---

## Item 1: Finding #1 (Score Domain Paradox) -- raw_bm25 코드 변경 REJECTION

**Final Severity:** HIGH (CRITICAL에서 하향)
**Final Resolution:** raw_bm25 코드 변경 REJECTED. composite score 유지. abs_floor을 composite domain으로 교정.
**Source:** `temp/41-final-report.md:39-62`, `temp/41-v2-adversarial.md:16-51`

### 삽입 위치

Plan 라인 196-213의 기존 `> **V2-adversarial + Deep Analysis 최종 반영 -- Score Domain 및 측정 방법론:**` 블록에 **앞부분을 수정/확장**. 현재 블록은 triple-field 로깅과 dual precision만 다루고 있으며, raw_bm25 코드 변경 REJECTION과 그 이유(NEW-4)가 명시되어 있지 않다.

### 삽입할 텍스트

라인 196 직후 (기존 `> **Triple-field 로깅:**` 앞)에 새 단락 추가:

```
> **Finding #1 최종 결정 -- raw_bm25 코드 변경 REJECTED (Deep Analysis 7-agent):**
>
> 초기 분석에서 `confidence_label()` 호출(memory_retrieve.py:283, 299)에 `raw_bm25`를 사용하도록 변경이 제안되었으나, V2-adversarial 라운드에서 **ranking-label inversion** (NEW-4)이 발견되어 이 코드 변경은 **거부**되었다.
>
> **거부 근거 (NEW-4 ranking-label inversion):**
> ```
> Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (ranked #1)
> Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (ranked #2)
>
> raw_bm25 기반 confidence: A="low", B="high"
> Tiered output(Action #2) 하에서: A는 SILENCE, B는 full injection
> → #1 ranked 결과가 억제되고 #2가 주입되는 기능적 버그
> ```
> Gemini 3.1 Pro ("retrieval system의 contract를 깨뜨림")와 Codex 5.3 ("body evidence로 상위 랭크된 항목이 'low'로 라벨링되면 오해의 소지") 모두 확인.
>
> **최종 해결책:**
> 1. Lines 283, 299의 코드 변경 **없음** -- `confidence_label()`은 현행 composite score 유지
> 2. `abs_floor`을 composite domain (range ~0-15, BM25 - body_bonus)으로 교정
> 3. `raw_bm25`는 진단 로깅 전용 (confidence labeling에 사용하지 않음)
> 4. Severity: CRITICAL → HIGH (라벨은 정보 메타데이터이며, tiered output은 기본값 "legacy"로 동작 영향 없음)
```

---

## Item 2: Finding #2 (Cluster Tautology) -- PoC #5 영향 교차 참조

**Final Severity:** LOW (CRITICAL에서 하향)
**Final Resolution:** 비활성 유지. dead-code 임계치를 plan에서 수정. 수학적으로 증명됨.
**Source:** `temp/41-final-report.md:64-70`

### 삽입 위치

PoC #5 섹션 내, 라인 172 부근 ("목적:" 문단 직후) 또는 라인 196 블록 내에 교차 참조 추가.

### 삽입할 텍스트

라인 172 직후에 추가:

```
> **Deep Analysis 반영 -- Cluster Tautology (Finding #2):**
> `cluster_count > max_inject` 임계치는 수학적으로 불가능(dead code)임이 증명됨: `C <= N <= max_inject`이므로 `C > max_inject`는 성립 불가. 이로 인해 PoC #5의 Action #1 사전/사후 비교에서 클러스터 감지의 독립변수 기여는 **0** -- 실질적으로 `abs_floor` 교정만이 label 변화를 발생시킨다. 상세: Plan #1 참조.
```

---

## Item 3: Finding #3 (PoC #5 Measurement) -- 이미 반영 확인

**Final Severity:** LOW (HIGH에서 하향)
**Final Resolution:** Triple-field 로깅, dual precision, label_precision 지표, 인간 어노테이션 -- 모두 plan에 반영됨.
**Source:** `temp/41-final-report.md:72-78`, audit `temp/poc-plan-audit-verification.md:31`

### 상태: YES -- 완전 반영

Plan 라인 196-213에서 triple-field 로깅, dual precision 계산, label_precision 지표, 인간 어노테이션 방법론이 모두 기록되어 있다. 추가 수정 불필요.

---

## Item 4: Finding #4 (PoC #6 Dead Path) -- 이미 반영 확인

**Final Severity:** LOW (HIGH에서 하향)
**Final Resolution:** `--session-id` CLI 파라미터 추가 (~12 LOC). BLOCKED -> PARTIALLY UNBLOCKED.
**Source:** `temp/41-final-report.md:82-88`, audit `temp/poc-plan-audit-verification.md:32`

### 상태: YES -- 완전 반영

Plan 라인 297-307에서 4개 항목(argparse, 우선순위, emit_event 위치, SKILL.md 변경 없음) 모두 정확히 기록됨. 라인 315에서 `--session-id` CLI 파라미터가 선행 의존성으로 명시됨. 라인 295에서 "PARTIALLY UNBLOCKED" 상태 반영됨.

**단, PoC #6 체크리스트에 `--session-id` 구현 항목이 누락됨 -- Item 11에서 처리.**

---

## Item 5: Finding #5 (Import Crash) -- 로깅 인프라 의존성 노트

**Final Severity:** HIGH
**Final Resolution:** Module-level try/except for memory_logger + judge import hardening + `e.name` scoping + stderr 경고. ~36 LOC.
**Source:** `temp/41-final-report.md:90-119`, `temp/41-finding4-5-integration.md:139-468`

### 삽입 위치

Plan #3(PoC 실험 계획)의 범위 밖이지만 의존성 노트 권장. 적절한 위치: 라인 64 부근 "Plan #2 (로깅 인프라) 의존성 매핑" 테이블 직후, 또는 "위험 및 완화" 섹션(라인 369).

### 삽입할 텍스트

라인 71 직후 (의존성 매핑 테이블과 "중요: PoC #6의 추가 요구사항" 사이)에 추가:

```
> **Deep Analysis 반영 -- Import Crash 방지 (Finding #5, Plan #2 범위):**
> `memory_logger.py` 미배포 시 retrieval hook이 `ModuleNotFoundError`로 크래시하는 문제가 확인됨. Plan #2에서 로거 모듈 생성 시 반드시 fail-open 패턴 적용:
> ```python
> try:
>     from memory_logger import emit_event
> except ImportError as e:
>     if getattr(e, 'name', None) != 'memory_logger':
>         raise  # transitive dependency failure → fail-fast
>     def emit_event(*args, **kwargs): pass
> ```
> `e.name` 스코핑으로 "모듈 미존재"(폴백)와 "전이적 의존성 실패"(fail-fast)를 구분한다. Judge import(memory_retrieve.py:429, 503)에도 동일 패턴 + stderr 경고 적용. 모든 PoC의 로깅 이벤트(`emit_event`)가 이 패턴에 의존하므로 Plan #2 Phase 1의 선행 조건.
```

---

## Item 6: NEW-1 (Noise Floor Distortion) -- PoC #5 deferred

**Final Severity:** LOW-MEDIUM
**Final Disposition:** Deferred -- PoC #5 데이터로 판단
**Source:** `temp/41-final-report.md:29`, `temp/41-finding1-3-score-domain.md:33-52,303-316`

### 삽입 위치

PoC #5 섹션, 라인 180-184 ("상대적 noise floor" 코드 설명) 직후.

### 삽입할 텍스트

라인 184 직후에 추가:

```
> **Deep Analysis 발견 -- NEW-1: apply_threshold noise floor 왜곡 (LOW-MEDIUM, deferred):**
> `apply_threshold()`의 25% noise floor(`memory_search_engine.py:284-287`)가 composite score에서 계산됨. `body_bonus`가 높은(2-3) best entry가 있으면 floor가 과도하게 높아져, `body_bonus=0`이지만 합리적 raw BM25 매칭을 가진 entry가 부당하게 제거될 수 있다:
> ```
> Best: raw=-2.0, bonus=3 → composite=-5.0 → floor=1.25
> Victim: raw=-1.0, bonus=0 → composite=-1.0 → abs(1.0) < 1.25 → 제거됨
> 하지만 raw BM25 -1.0은 유의미한 매칭 (best raw의 50%)
> ```
> **처분:** PoC #5의 triple-field 로깅 데이터(`body_bonus` 필드 포함)로 실제 발생 빈도를 확인한 후 결정. 현재 Plan #1은 `memory_search_engine.py` 변경을 명시적으로 배제하며, `body_bonus` cap(3)과 전형적 BM25 점수 범위를 고려하면 실질적 영향은 제한적.
```

---

## Item 7: NEW-2 (Judge Import Vulnerability) -- Finding #5로 해결

**Final Severity:** HIGH
**Final Disposition:** Finding #5와 동일 클래스, 함께 해결됨
**Source:** `temp/41-final-report.md:30`, `temp/41-finding4-5-integration.md:179-188`, `temp/41-v1-incorporated.md:82-100`

### 삽입 위치

Item 5 (Finding #5 의존성 노트)와 통합. 별도 삽입 불필요 -- Item 5의 텍스트에 "Judge import(memory_retrieve.py:429, 503)에도 동일 패턴 + stderr 경고 적용"으로 이미 포함.

### 추가 삽입 (선택적)

Plan의 "위험 및 완화" 섹션(라인 369) 테이블에 행 추가를 권장:

```
| Judge 모듈 미배포 시 hook 크래시 | 높음 | #5, #6, #7 | Deep Analysis Finding #5 해결: `judge_enabled=true` + 모듈 미존재 시 try/except + stderr 경고로 fail-open. `e.name` 스코핑으로 전이적 실패 구분 |
```

---

## Item 8: NEW-3 (Empty XML After Judge Rejects All) -- 별도 추적

**Final Severity:** LOW
**Final Disposition:** 별도 추적 대상
**Source:** `temp/41-final-report.md:31`, `temp/41-v1-incorporated.md:82-89`

### 삽입 위치

Plan의 "위험 및 완화" 섹션(라인 369) 테이블에 행 추가.

### 삽입할 텍스트

위험 테이블 마지막 행 직후 (라인 379 이후):

```
| Judge가 모든 후보를 거부하면 빈 `<memory-context>` 태그 출력 | 낮음 | #5 | Deep Analysis NEW-3: 빈 XML 태그가 토큰 낭비. `if not top:` 가드 추가 권장. 별도 추적 대상 (현재 fix scope 밖) |
```

---

## Item 9: NEW-4 (Ranking-Label Inversion) -- Finding #1 REJECTION 근거

**Final Severity:** HIGH
**Final Disposition:** raw_bm25 코드 변경 거부로 해결됨
**Source:** `temp/41-final-report.md:32,45-54`, `temp/41-v2-adversarial.md:16-51,247-266`

### 삽입 위치

Item 1에서 삽입하는 Finding #1 REJECTION 블록 내에 이미 포함됨. Entry A/B 예시와 Gemini 3.1 Pro / Codex 5.3 확인이 Item 1 텍스트에 통합되어 있다.

### 추가 삽입

검토 이력 테이블(라인 498-506)의 "Deep Analysis (7-agent)" 행 업데이트:

현재 (라인 506):
```
| Deep Analysis (7-agent) | Methodology refined | PoC #5: label_precision metric + triple-field logging + human annotation. PoC #6: BLOCKED → PARTIALLY UNBLOCKED via --session-id CLI param. |
```

수정:
```
| Deep Analysis (7-agent) | Methodology refined + Finding #1 REJECTED | PoC #5: **raw_bm25 confidence 코드 변경 REJECTED** (NEW-4 ranking-label inversion), label_precision metric + triple-field logging + human annotation, abs_floor composite domain 교정. PoC #6: BLOCKED → PARTIALLY UNBLOCKED via --session-id CLI param. |
```

---

## Item 10: NEW-5 (ImportError Masks Transitive Failures) -- e.name 스코핑

**Final Severity:** MEDIUM
**Final Disposition:** `e.name` 스코핑 패턴으로 해결
**Source:** `temp/41-final-report.md:33,99-103,119`, `temp/41-v2-adversarial.md:161-193,268-288`

### 삽입 위치

Item 5 (Finding #5 의존성 노트)의 텍스트에 이미 `e.name` 패턴이 포함됨. 별도 삽입 불필요.

### 확인

Item 5에서 삽입하는 코드 블록에 다음이 포함됨:
```python
except ImportError as e:
    if getattr(e, 'name', None) != 'memory_logger':
        raise  # transitive dependency failure → fail-fast
```

그리고 설명 텍스트에 "`e.name` 스코핑으로 '모듈 미존재'(폴백)와 '전이적 의존성 실패'(fail-fast)를 구분" 명시. Gemini 3.1 Pro와 Codex 5.3 모두 이 패턴을 독립적으로 권고.

---

## Item 11: PoC #6 체크리스트 -- `--session-id` CLI 파라미터 구현 항목 추가

**Source:** `temp/poc-plan-audit-verification.md:56-57`

### 삽입 위치

PoC #6 진행 체크리스트, 라인 447 ("선행 의존성 확인" 항목) 직후.

### 삽입할 텍스트

라인 447 직후에 새 체크박스 추가:

```
- [ ] `--session-id` CLI 파라미터 구현 (`memory_search_engine.py`에 argparse 추가, 우선순위: CLI arg > `CLAUDE_SESSION_ID` env var > 빈 문자열)
```

---

## 요약: 편집 작업 목록

| # | 위치 (라인 기준) | 작업 | 유형 |
|---|----------------|------|------|
| 1 | L196 직후 | Finding #1 REJECTION + NEW-4 시나리오 블록 삽입 | 신규 blockquote |
| 2 | L172 직후 | Finding #2 cluster tautology PoC #5 영향 교차 참조 | 신규 blockquote |
| 3 | -- | 확인 완료, 수정 불필요 | 없음 |
| 4 | -- | 확인 완료, 수정 불필요 (체크리스트는 Item 11) | 없음 |
| 5 | L71 직후 | Finding #5 import crash 의존성 노트 | 신규 blockquote |
| 6 | L184 직후 | NEW-1 noise floor 왜곡 deferred 노트 | 신규 blockquote |
| 7 | L379 직후 (위험 테이블) | NEW-2 judge crash 위험 행 추가 | 테이블 행 |
| 8 | L379 직후 (위험 테이블) | NEW-3 empty XML 위험 행 추가 | 테이블 행 |
| 9 | L506 | 검토 이력 "Deep Analysis" 행 업데이트 | 텍스트 수정 |
| 10 | -- | Item 5에 통합, 별도 불필요 | 없음 |
| 11 | L447 직후 | `--session-id` 체크박스 추가 | 체크박스 |

**총 편집 작업: 8건** (3건은 확인 완료로 수정 불필요)
