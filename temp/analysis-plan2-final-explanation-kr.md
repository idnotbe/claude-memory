# plan-search-quality-logging.md 종합 설명 보고서 (한글)

**작성일:** 2026-02-22
**대상:** action-plans/plan-search-quality-logging.md (Plan #2: 로깅 인프라스트럭처)
**관련 분석:** temp/41-*.md (7-agent, 5-phase Deep Analysis)

---

## 1. Plan 파일 내용 요약

### 1.1 목적
claude-memory 플러그인에 **구조화된 JSONL 로깅 인프라**를 구축하는 계획이다.
현재는 검색 품질에 대한 관측 가능성(observability)이 거의 없어서, 어떤 쿼리가 들어오고 어떤 결과가 반환되며 어떤 결과가 실제로 유용했는지 데이터가 축적되지 않는다.

### 1.2 핵심 구성요소
1. **memory_logger.py** (신규 모듈, ~80-120 LOC): 공유 로깅 모듈. `emit_event()` 함수로 모든 스크립트가 동일 인터페이스 사용.
2. **JSONL 스키마**: 날짜별/이벤트타입별 파일 (`logs/{event_type}/{YYYY-MM-DD}.jsonl`)
3. **7가지 이벤트 타입**: retrieval.search, retrieval.inject, retrieval.skip, judge.evaluate, judge.error, search.query, triage.score
4. **설정 키 3개**: `logging.enabled` (기본 false), `logging.level`, `logging.retention_days`
5. **6-phase 구현 계획**: 계약 정의 → 로거 구현 → 파이프라인 계측 → 마이그레이션 → 테스트 → 문서

### 1.3 기술적 특징
- `os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` + `os.write(fd, line_bytes)` 로 단일 syscall atomic append
- fail-open: 모든 로깅 오류는 무시, hook 실행을 절대 차단하지 않음
- stdlib only (외부 의존성 없음)
- p95 로깅 호출 < 5ms 예산

---

## 2. Deep Analysis와의 연관 분석

### 2.1 Key Course Correction (핵심 방향 전환)과의 관계

**배경:** 원래 분석팀(analysts)은 `memory_retrieve.py`의 라인 283, 299에서 `raw_bm25`를 사용해 confidence label을 계산하자고 제안했다.

**REJECTED된 이유:** V2-adversarial 라운드에서 **ranking-label inversion (순위-라벨 역전)** 이 발견됨:
```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (랭킹 #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (랭킹 #2)

raw_bm25로 confidence 계산 시:
  A → "low", B → "high"
→ 1위 결과가 침묵(silence)되고, 2위 결과가 전체 주입(full injection)됨
```

**plan-search-quality-logging.md에 대한 영향:**
- raw_bm25를 **코드에서 confidence 계산에 사용하지 않는** 대신, **로깅 스키마에는 유지**함
- 로그의 results[] 배열에 triple-field로 기록: `raw_bm25`, `score`, `body_bonus`
- 목적이 "confidence 계산용"에서 "진단/분석 전용"으로 전환됨
- plan 라인 129에 명확히 반영: "PoC #5는 두 점수 도메인에서 각각 precision 계산: raw_bm25 기반 (BM25 자체 품질)과 score 기반 (end-to-end 품질)"

### 2.2 Final Dispositions (5 Findings)과의 관계

#### Finding #5: Logger Import Crash (HIGH → HIGH 유지) -- **가장 직접적 연관**

이것이 plan-search-quality-logging.md에 **가장 직접적으로 영향**을 준 발견이다.

**문제:** memory_logger.py를 top-level import로 추가하면, 부분 배포(partial deploy) 시 파일이 없을 때 `ModuleNotFoundError`로 전체 retrieval hook이 크래시. fail-open 원칙 위반.

**해결 (plan 라인 82-91에 반영됨):**
```python
try:
    from memory_logger import emit_event
except ImportError as e:
    if getattr(e, 'name', None) != 'memory_logger':
        raise  # 전이적 종속성 실패 -- fail-fast
    def emit_event(*args, **kwargs): pass
```

**이 패턴의 의미:**
- memory_logger.py가 없으면 → noop fallback (정상 동작, 로깅만 비활성)
- memory_logger.py는 있지만 내부 import가 실패하면 → `raise`로 crash (배포 오류 진단 필요)
- `e.name` 체크가 이 둘을 구분하는 핵심

**코드 변경량:** ~36 LOC (memory_retrieve.py + memory_search_engine.py 합산)
이것이 Deep Analysis 전체에서 가장 실제 영향력 있는 수정이었다.

#### Finding #3: PoC #5 Measurement Invalidity (HIGH → LOW) -- 스키마 변경 관련

**문제:** PoC #5가 "BM25 정밀도"를 측정한다고 했지만, 실제로는 composite score(BM25 - body_bonus) 정밀도를 측정하게 됨. Action #1 전후 비교 시 precision@k는 동일할 수밖에 없음 (Action #1은 라벨만 변경하고 랭킹은 안 바꿈).

**plan에 대한 영향:**
- 로그 스키마에 `body_bonus` 필드 추가 (plan 라인 119): 기존에는 `score`와 `raw_bm25`만 있었음
- triple-field logging으로 점수 분해(decomposition) 분석 가능하게 됨
- plan 라인 129의 주석이 이를 설명

#### Finding #1: Score Domain Paradox (CRITICAL → HIGH) -- 간접 관련

이 Finding 자체는 `plan-retrieval-confidence-and-output.md`(Plan #1) 대상이다.
그러나 **REJECT 결정**이 plan-search-quality-logging.md의 스키마 설계에 영향을 미쳤다:
- raw_bm25는 confidence 계산에 사용하지 않지만 로그에는 기록 (진단용)
- 이 "진단 전용" 프레이밍이 plan의 스키마 주석에 반영됨

#### Finding #2: Cluster Tautology (CRITICAL → LOW) -- 무관

plan-retrieval-confidence-and-output.md 대상. plan-search-quality-logging.md와 직접적 연관 없음.

#### Finding #4: PoC #6 Dead Correlation Path (HIGH → LOW) -- 부분 관련

**문제:** PoC #6은 `retrieval.inject`와 `search.query` 이벤트를 session_id로 조인하는데, CLI 모드에서는 session_id가 항상 빈 문자열 → 조인 결과 0건.

**plan에 대한 영향:**
- plan 라인 141에 session_id CLI 제한사항이 이미 문서화되어 있음
- 단, Deep Analysis에서 설계한 구체적 해결책(`--session-id` CLI 파라미터 + env var fallback)은 plan에 아직 미반영 (교차 검증에서 발견한 경미한 누락)
- ~12 LOC의 코드 변경이 `memory_search_engine.py`에 필요

### 2.3 Newly Discovered Issues (5개)과의 관계

#### NEW-5: ImportError masks transitive failures (MEDIUM) -- **직접 반영됨**

plan 라인 82에 "(Deep Analysis NEW-5)"로 태그되어 있다.
Finding #5의 단순 `try/except ImportError`에 `e.name` 체크를 추가한 것이 이것.

구체적으로:
- 단순 `except ImportError`만 하면 → memory_logger.py 내부의 `import some_broken_lib`도 잡아서 조용히 무시함
- `e.name` 체크 추가하면 → "memory_logger 모듈 자체가 없는 것"만 fallback, "내부 종속성 깨진 것"은 crash (올바른 동작)
- Gemini 3.1 Pro와 Codex 5.3이 독립적으로 이 패턴을 확인

#### NEW-4: Ranking-label inversion (HIGH) -- 간접 관련

Key Course Correction의 원인. raw_bm25 코드 변경을 REJECT시키면서, plan의 로깅 스키마에서 raw_bm25의 역할을 "진단 전용"으로 재정의.

#### NEW-2: Judge import vulnerability (HIGH) -- Finding #5와 함께 해결

기존 memory_judge import에도 같은 종류의 취약점이 있음이 발견됨. plan의 lazy import 패턴이 judge에도 적용되어야 하지만, 이것은 주로 memory_retrieve.py 구현의 문제이지 plan-search-quality-logging.md 자체의 문제는 아님.

#### NEW-1: apply_threshold noise floor distortion (LOW-MEDIUM) -- 연기됨

plan-search-quality-logging.md와 무관. PoC #5 데이터로 실증적 영향 확인 후 처리.

#### NEW-3: Empty XML after judge rejects all (LOW) -- 별도 추적

plan-search-quality-logging.md와 무관.

### 2.4 Process Assessment와의 관계

7-agent/5-phase 파이프라인은 ~48 LOC 변경에 과한 프로세스였다.
그러나 **Finding #5의 import crash 방지**와 **NEW-4의 ranking-label inversion 발견**에 실질적 가치가 있었다.

plan-search-quality-logging.md에 대해서는:
- Finding #5 (logger import crash)가 **핫패스 crash 방지**로 가장 영향력 있는 수정
- triple-field logging이 미래 PoC 실험의 기반
- 향후 권장: <50 LOC 수정은 2-agent 파이프라인으로 충분

---

## 3. plan의 검토 이력 (Review History) 해석

plan 하단의 검토 이력 테이블 (라인 439-449):

| 단계 | 핵심 내용 |
|------|----------|
| Engineering Review | logging.enabled 기본값 false, os.write 패턴, schema_version 추가 |
| Adversarial Review | info 레벨에서 제목 미기록(secret residue 방지), .gitignore 가이드 |
| V1-Robustness | session_id CLI 제한사항 문서화 |
| V1-Practical | LOC 추정치 검증, 도구 가용성 확인 |
| V2-Fresh Eyes | 약간 과도한 설계지만 건전; v0 마일스톤 추가 권장 |
| **V2-Adversarial** | **Logger import crash (lazy import), raw_bm25 in schema** |
| **Deep Analysis (7-agent)** | **e.name 스코핑(NEW-5), body_bonus 추가(triple-field)** |

마지막 두 행이 Deep Analysis의 직접적 영향:
1. V2-Adversarial에서 lazy import 패턴과 raw_bm25 스키마 추가
2. Deep Analysis에서 이를 정제: e.name 스코핑 + body_bonus 필드 추가

---

## 4. 자가비판 및 보충

### 4.1 발견된 경미한 누락
- plan 라인 141의 session_id 제한사항 설명에 Finding #4의 구체적 해결책(`--session-id` CLI 파라미터)이 미반영
- plan은 "향후 os.getppid() 또는 타임스탬프 기반 그루핑"을 언급하지만, Deep Analysis에서 이미 더 나은 해결책이 설계됨

### 4.2 정확성 검증 완료 항목
- e.name 스코핑 패턴: plan과 Deep Analysis 문서 간 일치 확인
- triple-field logging: plan 스키마와 final report 일치 확인
- raw_bm25 "진단 전용" 프레이밍: REJECT 결정과 plan 설명 일치 확인
- fail-open 원칙: plan의 모든 오류 처리 방식이 이 원칙에 부합
