---
status: done
progress: "전체 완료. Phase 1-6 구현 + 품질 감사 11개 전부 실행 (A-01~A-11). 916 tests. 3-tier audit: Phase A (data contract), Phase B (behavioral), Phase C (operational). 각 phase V1+V2 독립 검증. Gemini 3.1 Pro 외부 리뷰 포함."
---

# Plan #2: 로깅 인프라스트럭처 (Logging Infrastructure)

**날짜:** 2026-02-22
**범위:** 구조화된 JSONL 로깅 인프라 구축 (검색 품질 측정, PoC 지원)
**검증 소스:** Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check
**의존 대상:** Plan #1 (Actions #1-#4), Plan #3 (PoC #4-#7)

---

## 배경 (Background)

### 왜 로깅이 필요한가

현재 claude-memory 플러그인은 검색 품질에 대한 관측 가능성(observability)이 거의 없다. `memory_retrieve.py`는 BM25 검색 결과를 stdout으로 주입하지만, 어떤 쿼리가 들어오고, 어떤 결과가 반환되며, 어떤 결과가 실제로 유용했는지에 대한 데이터가 축적되지 않는다.

**현재 상태:**
- `memory_triage.py`에 임시 스코어 로깅 존재 (`.staging/.triage-scores.log`, `os.open` + `O_APPEND` 패턴, lines 997-1015)
- `memory_judge.py`에 stderr `[DEBUG]` 출력 존재 (lines 347, 360) -- 세션 종료 시 소실
- `memory_retrieve.py`에 stderr `[WARN]`/`[INFO]` 출력 존재 (lines 362, 388, 466) -- 세션 종료 시 소실
- 통합된 로깅 시스템 없음, 사후 분석 불가능

**필요한 이유 (자기개선 피드백 루프):**
1. **PoC #5 (BM25 정밀도 측정)** -- 모든 검색 후보의 점수를 기록해야 수동 라벨링으로 정밀도 계산 가능
2. **PoC #6 (Nudge 준수율)** -- 축약 주입(compact injection) 발생 횟수와 후속 `/memory:search` 호출 비율 측정 필요
3. **PoC #7 (OR-query 정밀도)** -- 단일 토큰 vs 다중 토큰 매칭의 false positive 비율 측정 필요
4. **PoC #4 (Agent Hook)** -- agent hook 레이턴시 측정 필요
5. **Action #1-#2 사전/사후 비교** -- confidence 교정 및 축약 주입 도입 효과 측정

---

## 목적 (Purpose)

구조화된 로깅 인프라를 구축하여:

1. **검색 품질 측정 가능** -- 매 검색마다 쿼리, 후보, 점수, 필터링 단계, 최종 주입 결과를 기록
2. **레이턴시 프로파일링** -- FTS5 검색, body bonus 계산, judge API 호출의 각 단계별 소요 시간 기록
3. **자기개선 피드백 루프** -- 축적된 데이터로 임계치 튜닝, 정밀도 개선, 의사결정 근거 확보
4. **PoC 실험 지원** -- Plan #3의 모든 PoC가 이 로깅 인프라에 의존

---

## 관련 정보 (Related Info)

### 아키텍처 결정 사항

#### 1. 디렉토리 구조

```
<project>/.claude/memory/logs/
├── retrieval/
│   ├── 2026-02-22.jsonl
│   └── 2026-02-23.jsonl
├── judge/
│   ├── 2026-02-22.jsonl
│   └── 2026-02-23.jsonl
└── triage/
    └── 2026-02-22.jsonl
```

**결정:** 이벤트 타입별 → 일자별 JSONL 파일 (`logs/{event_type}/{YYYY-MM-DD}.jsonl`)

**근거 (Codex + Gemini 합의):**
- 분석 워크플로우에 최적: `cat logs/retrieval/*.jsonl | jq '.duration_ms'` 로 시계열 분석
- 일자별 자동 로테이션 (파일명에 날짜 내장)
- 이벤트 타입별 분리로 jq/pandas 분석 시 불필요한 필터링 불필요
- **기각된 대안:** 날짜 먼저 (`logs/2026-02-22/retrieval.jsonl`) -- 크로스 데이 분석 시 불편; 단일 파일 로테이션 -- 시간 슬라이싱 약화

#### 2. 로거 구현 방식

**결정:** 커스텀 경량 모듈 (`hooks/scripts/memory_logger.py`)

**근거:**
- Python `logging` stdlib은 핸들러/포매터 설정 오버헤드가 있음 -- 단수명 서브프로세스에 부적합
- 기존 `memory_triage.py` 패턴 개선: `os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` + **`os.write(fd, line_bytes)`** + `os.close(fd)` (리뷰 반영: `os.fdopen()` 대신 직접 `os.write()` 사용으로 단일 write syscall 보장)
- 단일 `emit_event()` 함수로 모든 스크립트가 동일 인터페이스 사용
- 모든 로깅 오류는 fail-open (hook 실행을 절대 차단하지 않음)
- **Lazy import 패턴 (V2-adversarial + Deep Analysis 반영):** `memory_logger`는 top-level import가 아닌 lazy import with fallback. **`e.name` 스코핑으로 전이적 종속성 실패 구분** (Deep Analysis NEW-5):
  ```python
  try:
      from memory_logger import emit_event
  except ImportError as e:
      if getattr(e, 'name', None) != 'memory_logger':
          raise  # 전이적 종속성 실패 -- fail-fast (올바른 동작)
      def emit_event(*args, **kwargs): pass
  ```
  근거: 부분 배포/업데이트 시 `memory_logger.py` 미존재 가능. top-level `ImportError`는 hook 전체 실패 유발 → fail-open 원칙 위반. `e.name` 체크는 "모듈 미존재"(폴백)와 "전이적 종속성 실패"(crash, 배포 오류 진단 필요)를 구분. Gemini 3.1 Pro + Codex 5.3 독립 확인.

**핵심 요구사항:**
- p95 로깅 호출 < 5ms (hook 15s 타임아웃 예산에서 무시 가능)
- Atomic append (단일 write syscall로 전체 JSONL 라인 기록)
- 파일 핸들 lazy initialization (로깅 비활성 시 파일 I/O 0)
- stdlib only (외부 의존성 없음)

#### 3. 로그 엔트리 스키마

```json
{
  "schema_version": 1,
  "timestamp": "2026-02-22T10:30:00.123Z",
  "event_type": "retrieval.search",
  "level": "info",
  "hook": "UserPromptSubmit",
  "script": "memory_retrieve.py",
  "session_id": "transcript-abc123",
  "duration_ms": 87.4,
  "data": {
    "query_tokens": ["authentication", "oauth"],
    "engine": "fts5_bm25",
    "candidates_found": 8,
    "candidates_post_threshold": 5,
    "candidates_post_judge": 3,
    "injected_count": 3,
    "results": [
      {"path": ".claude/memory/decisions/use-oauth.json", "score": -4.23, "raw_bm25": -1.23, "body_bonus": 3, "confidence": "high"},
      {"path": ".claude/memory/constraints/api-limits.json", "score": -2.11, "raw_bm25": -0.61, "body_bonus": 1.5, "confidence": "medium"}
    ]
  },
  "error": null
}
```

> **Note (리뷰 반영):** `results[]`에 제목(title) 미포함 (info 레벨). 경로(path)와 점수(score/raw_bm25)만 기록. `level: "debug"` 시 제목 추가됨.
>
> **V2-adversarial + Deep Analysis 반영:** `results[]`에 3개 점수 필드 기록 (triple-field logging): `raw_bm25` (순수 BM25 점수), `score` (body_bonus 반영 복합 점수), `body_bonus` (body 키워드 매칭 보너스). PoC #5는 두 점수 도메인에서 각각 precision 계산: `raw_bm25` 기반 (BM25 자체 품질)과 `score` 기반 (end-to-end 품질). `body_bonus`는 점수 분해(decomposition) 분석에 사용.

**스키마 설계 원칙:**
- **`schema_version` 필드 (리뷰 반영):** `"schema_version": 1` -- 모든 이벤트에 포함. 향후 스키마 변경 시 호환성 보장. 비용: 1 LOC/event.
- **안정적 최상위 필드:** `schema_version`, `timestamp`, `event_type`, `level`, `hook`, `script`, `session_id`, `duration_ms` -- 모든 이벤트에 공통
- **이벤트별 `data` 객체:** 이벤트 타입에 따라 다른 구조 -- 확장성 확보
- **선택적 `error` 필드:** `{type, message}` 구조, 정상 시 `null`
- **프라이버시 (리뷰 반영 강화):**
  - `level: "info"` -- 메모리 ID/경로만 기록, 제목(title) 미포함. 이유: 삭제/retire된 메모리의 제목이 로그에 잔류하는 "secret residue" 위험 방지.
  - `level: "debug"` -- 제목(title) + 원본 프롬프트(raw prompt) 포함. 개발/디버깅용.
  - 쿼리 토큰(`query_tokens`)은 info 레벨에서 기록됨 -- 사용자 의도 노출 가능하므로 `.gitignore` 가이드 필수.
- **session_id:** `hook_input.transcript_path`에서 파일명 추출 (세션 간 상관관계 분석용)
  - **제한 사항 (리뷰 반영):** CLI 모드(`memory_search_engine.py --mode search`)에서는 hook_input이 없으므로 session_id가 직접 제공되지 않는다. `search.query` 이벤트는 기본적으로 session_id가 빈 문자열.
  - **해결 방안 (Deep Analysis 설계 완료):** `--session-id` CLI 파라미터 + `CLAUDE_SESSION_ID` 환경변수 폴백을 통해 CLI 모드에서도 session_id를 전달할 수 있다. 우선순위: `--session-id CLI 인자 > CLAUDE_SESSION_ID 환경변수 > 빈 문자열`. `memory_search_engine.py`에 ~12 LOC 추가로 구현 (argparse 파라미터 추가 + `os.environ.get()` 폴백 + `emit_event()` 전달). SKILL.md 변경 불필요 -- 현재 `CLAUDE_SESSION_ID` 환경변수가 없으므로 skill 측 전파는 불가하나, 향후 Claude Code가 해당 환경변수를 노출하면 코드 변경 없이 자동 적용된다.
- **엔트리 크기 제한 (리뷰 반영):** `data.results` 배열을 최대 20개로 제한 (이후 truncated). 4KB 미만으로 엔트리 유지하여 POSIX atomic write 보장.

#### 4. 이벤트 타입 체계 (Event Type Taxonomy)

| event_type | 발생 스크립트 | 설명 |
|------------|-------------|------|
| `retrieval.search` | memory_retrieve.py | FTS5/legacy 검색 실행 + 결과 |
| `retrieval.inject` | memory_retrieve.py | 최종 주입 결과 (high/medium/low 분류) |
| `retrieval.skip` | memory_retrieve.py | 검색 건너뜀 (짧은 프롬프트, 비활성 등) |
| `judge.evaluate` | memory_judge.py | Judge 후보 평가 (accepted/rejected + 사유) |
| `judge.error` | memory_judge.py | Judge API 오류 + 폴백 |
| `search.query` | memory_search_engine.py | CLI 검색 쿼리 (on-demand) |
| `triage.score` | memory_triage.py | 트리아지 카테고리별 점수 (기존 .triage-scores.log 대체) |

#### 5. 설정 키 (Config Keys)

`memory-config.json`의 기존 패턴(`dict.get()` 안전 기본값)을 따름:

```json
{
  "logging": {
    "enabled": false,
    "level": "info",
    "retention_days": 14
  }
}
```

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| `logging.enabled` | bool | `false` | 로깅 활성화 여부. `false`면 파일 I/O 0 |
| `logging.level` | string | `"info"` | 최소 로그 레벨: `"debug"`, `"info"`, `"warning"`, `"error"` |
| `logging.retention_days` | int | `14` | 자동 정리 기준 일수 (0 = 자동 정리 안 함) |

**설계 결정:**
- `logging.enabled`는 기본 `false` **(리뷰 반영 변경)**:
  - **변경 근거 (engineering + adversarial 리뷰 합의):** 기본 `true`는 "principle of least astonishment" 위반. 모든 프로젝트에 자동으로 `logs/` 디렉토리가 생성되어 repo 위생 문제 및 `.gitignore` 미설정 시 민감 데이터 커밋 위험.
  - **완화:** 설치 문서에 "로깅 활성화 권장" 안내 추가. PoC 실행 시 자동 활성화 가이드 제공.
  - **기존 Vibe-check 의견 (기각됨):** "데이터 수집이 핵심 목적이므로 기본 활성" -- 데이터 수집 필요성은 인정하나 사용자 동의 없는 자동 파일 생성은 부적절.
- 최소 설정 표면: v1에서는 3개 키만. 향후 필요 시 `logging.events.{type}` 개별 토글, `logging.max_file_mb` 등 추가 가능.
- `logging.path` 오버라이드 키는 v1에서 미포함 -- 로그 경로는 `<memory_root>/logs/`로 고정. 커스텀 경로가 필요한 유스케이스가 확인되면 추가.
- **`.gitignore` 가이드 (리뷰 반영):** 플러그인 설치 시 또는 로깅 활성화 시 `.gitignore`에 `.claude/memory/logs/` 추가 안내. 로그에 쿼리 토큰이 포함되어 사용자 의도/프로젝트 정보 노출 가능.

#### 6. 정리(Cleanup) 전략

**결정:** `.last_cleanup` 타임스탬프 파일 기반 1일 1회 정리

**근거 (Vibe-check 반영):**
- 확률적 정리(1-in-10)는 비결정적 동작 도입 -- 불필요한 복잡성
- 대신 `logs/.last_cleanup` 파일에 마지막 정리 시각 기록
- 로거 초기화 시 `.last_cleanup` 확인 → 24시간 이상 경과 시 `retention_days` 초과 파일 삭제
- 정리 실패 시 무시 (fail-open)
- 14일간 JSONL은 단일 사용자 기준 < 1MB로 추정 -- 공격적 정리 불필요

### 스크립트별 로깅 포인트

#### memory_retrieve.py (가장 상세한 로깅)

```python
# 로깅 포인트 1: 검색 시작 (debug)
# - query_tokens, fts_query 구성, engine 선택

# 로깅 포인트 2: 검색 결과 (info) -- PoC #5, #7 핵심
# - 전체 후보 리스트 (score, path, category)
# - threshold 적용 전/후 건수
# - body bonus 적용 결과
# - 단일 토큰 매칭 vs 다중 토큰 매칭 표시 (PoC #7)

# 로깅 포인트 3: Judge 결과 (info) -- Judge 활성 시
# - judge 전/후 후보 건수
# - judge 레이턴시

# 로깅 포인트 4: 최종 주입 (info) -- PoC #6 핵심
# - 주입된 결과별 confidence (high/medium/low)
# - 주입 모드 (full/compact/silent)
# - 전체 파이프라인 소요 시간

# 로깅 포인트 5: 0-result / all-low-confidence (info)
# - hint 발생 여부
```

#### memory_judge.py

```python
# 로깅 포인트 1: Judge 호출 (info)
# - 후보 수, 모델, 배치 분할 여부

# 로깅 포인트 2: Judge 응답 (info)
# - accepted/rejected 인덱스
# - API 레이턴시
# - 파싱 성공/실패

# 로깅 포인트 3: Judge 오류 (warning)
# - 에러 타입, 폴백 전략
```

#### memory_search_engine.py (CLI 검색)

```python
# 로깅 포인트 1: 검색 쿼리 (info)
# - FTS5 쿼리 구성, 토큰 수
# - 결과 수, top 점수
```

### 기존 로깅 마이그레이션

| 현재 | 변경 후 |
|------|---------|
| `.staging/.triage-scores.log` (memory_triage.py:997) | `logs/triage/{YYYY-MM-DD}.jsonl` |
| `[DEBUG] judge call: ...` stderr (memory_judge.py:360) | `logs/judge/{YYYY-MM-DD}.jsonl` |
| `[WARN] FTS5 unavailable` stderr (memory_retrieve.py:466) | `logs/retrieval/{YYYY-MM-DD}.jsonl` |

마이그레이션은 점진적: 새 로깅 시스템 도입 후 기존 stderr/로그를 하나씩 전환. 기존 `.triage-scores.log`는 듀얼 라이트(old + new) 기간을 둔 후 제거.

### 파일 목록

| 파일 | 역할 | 변경 유형 |
|------|------|-----------|
| `hooks/scripts/memory_logger.py` | **신규** -- 공유 로깅 모듈 | 생성 (~80-120 LOC) |
| `hooks/scripts/memory_retrieve.py` | 검색 파이프라인 계측 | 수정 (~30-50 LOC 추가) |
| `hooks/scripts/memory_judge.py` | Judge 호출 계측 | 수정 (~15-25 LOC 추가) |
| `hooks/scripts/memory_search_engine.py` | CLI 검색 계측 | 수정 (~10-15 LOC 추가) |
| `hooks/scripts/memory_triage.py` | 기존 스코어 로그 마이그레이션 | 수정 (~10-15 LOC 변경) |
| `assets/memory-config.default.json` | `logging` 설정 키 추가 | 수정 (~5 LOC 추가) |
| `tests/test_memory_logger.py` | **신규** -- 로거 테스트 | 생성 (~150-250 LOC) |
| `CLAUDE.md` | Key Files 테이블 업데이트 | 수정 |

### `memory_logger.py` 핵심 인터페이스 (예상)

```python
"""Shared structured logging for claude-memory plugin.

Lightweight JSONL logger with fail-open semantics.
All errors are silently swallowed to never block hook execution.

No external dependencies (stdlib only).
"""

# 핵심 함수:
def emit_event(
    event_type: str,       # e.g. "retrieval.search"
    data: dict,            # 이벤트별 페이로드
    *,
    level: str = "info",   # debug/info/warning/error
    hook: str = "",        # UserPromptSubmit/Stop
    script: str = "",      # 호출 스크립트명
    session_id: str = "",  # transcript_path 기반
    duration_ms: float | None = None,
    error: dict | None = None,
    memory_root: str | Path = "",  # .claude/memory 경로
    config: dict | None = None,    # logging config (캐시용)
) -> None:
    """Append a single JSONL event to the appropriate log file.

    File path: {memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl
    where event_category = event_type.split('.')[0]

    Fail-open: any exception is silently caught.
    """

# 보조 함수:
def get_session_id(transcript_path: str) -> str:
    """Extract session identifier from transcript path."""

def cleanup_old_logs(log_root: Path, retention_days: int) -> None:
    """Delete log files older than retention_days. Called at most once per 24h."""

def parse_logging_config(config: dict) -> dict:
    """Parse logging config with safe defaults."""
```

### PoC 의존성 매핑

| PoC | 필요한 로그 데이터 | 해당 event_type |
|-----|-------------------|-----------------|
| #4 Agent Hook | hook 레이턴시 | `retrieval.search` (duration_ms) |
| #5 BM25 정밀도 | 전체 후보 + 점수 | `retrieval.search` (data.results) |
| #6 Nudge 준수율 | compact injection 발생 수 | `retrieval.inject` (data.output_mode per result) |
| #7 OR-query 정밀도 | 토큰별 매칭 정보 | `retrieval.search` (data.query_tokens + `data.results[].matched_tokens`) |

> **Cross-plan 의존성 (리뷰 반영):** PoC #7은 `data.results[].matched_tokens` 필드를 필요로 함. FTS5 `rank`는 전체 점수만 반환하므로, 로깅 시 제목+태그 토큰 교차 비교로 `matched_tokens` 근사 계산 필요. 구현 복잡도: ~10-15 LOC 추가.

---

## 구현 순서 (Implementation Order)

### Phase 의존성 다이어그램

```
Phase 1 (계약 정의) ──→ Phase 2 (로거 구현) ──→ Phase 3 (파이프라인 계측) ──→ Phase 5 (테스트)  ──→ Phase 6 (문서)
                                               ↘ Phase 4 (마이그레이션)     ↗
```

**주의:** Phase 3과 Phase 4는 Phase 2 완료 후 **병렬 실행 가능**. 두 Phase가 수정하는 코드 영역이 다름 (Phase 3: 신규 `emit_event()` 계측 삽입 / Phase 4: 기존 `print(..., file=sys.stderr)` 라인 교체). 단, `memory_judge.py`와 `memory_retrieve.py`는 양쪽 Phase에서 모두 수정하므로 git 브랜치 병렬 작업 시 머지 충돌 주의. 단일 브랜치 순차 작업이면 문제없음. Phase 5 (테스트)는 Phase 3+4 완료 후 최종 벤치마크 실행하되, Phase 2/3/4 진행 중에도 TDD 방식으로 단위 테스트 점진적 작성 가능. Phase 6 (문서)은 Phase 5와 부분 병행 가능.

### 순서 근거

1. **Phase 1이 먼저 (Contract-first):** JSONL 스키마는 로깅 시스템의 API 경계. 계약을 먼저 확정해야 Phase 2의 `emit_event()` 구현이 정확하고, Plan #3의 PoC 분석 스크립트도 스키마에 맞춰 선행 개발 가능
2. **Phase 2가 다음 (Core primitive):** 공유 로거 모듈이 존재해야 Phase 3/4에서 계측 코드 작성 가능
3. **Phase 3+4 병렬 (Edge integration):** Phase 3 (신규 계측)과 Phase 4 (기존 로그 마이그레이션)는 서로 다른 코드 영역을 수정하므로 개념적으로 독립적. 단, `memory_judge.py`와 `memory_retrieve.py`는 양쪽에서 수정하므로 병렬 브랜치 작업 시 충돌 가능. Phase 4에서 스키마 누락 필드 발견 시 Phase 1 계약 수정 필요할 수 있음
4. **Phase 5 후반 (Validation gate):** 최종 p95 < 5ms 벤치마크와 회귀 테스트는 모든 계측 완료 후 실행
5. **Phase 6 마지막 (Documentation):** 구현 확정 후 CLAUDE.md, config 문서 업데이트

### Cross-Plan 의존성

| Plan | 관계 | 설명 |
|------|------|------|
| Plan #1 (Actions #1-#4) | **독립** (병렬 실행 가능) | Plan #1은 `memory_retrieve.py`의 confidence/output 로직 수정. Plan #2의 로깅 인프라와 무관하게 진행 가능. 단, 최종 계측(Phase 3)은 Plan #1 수정 반영 후가 이상적 |
| Plan #3 (PoC #4-#7) | **Plan #2에 의존** | 모든 PoC가 로깅 인프라를 전제. 최소한 Phase 1-2 완료 후 PoC #5 baseline 수집 시작 가능 |

> **참고:** Cross-Plan 상세 구현 순서는 Plan #3 부록 "Cross-Plan 구현 순서" 참조.

---

## 진행 상황 (Progress)

### Phase 1: 로깅 계약 정의 (Logging Contract) -- COMPLETE ✓
- [x] JSONL 스키마 확정 (최상위 필드 + 이벤트별 data 구조) → `temp/p2-logger-schema.md`
- [x] event_type 체계 확정 (7 event types)
- [x] `assets/memory-config.default.json`에 `logging` 섹션 추가
- [x] 샘플 JSONL 라인으로 jq/python 파싱 검증

### Phase 2: 공유 로거 모듈 구현 -- COMPLETE ✓
- [x] `hooks/scripts/memory_logger.py` 생성 (~324 LOC, security-hardened)
- [x] `emit_event()` 구현 -- atomic append + symlink containment + NaN sanitization
- [x] `get_session_id()` 구현 -- transcript_path에서 세션 ID 추출
- [x] `cleanup_old_logs()` 구현 -- `.last_cleanup` 타임스탬프 기반 + symlink bypass 방지
- [x] `parse_logging_config()` 구현 -- dict.get() 안전 기본값 + string boolean 처리
- [x] 레벨 필터링 구현 (debug < info < warning < error)
- [x] fail-open 보장: 모든 예외 잡아서 무시

### Phase 3: 검색 파이프라인 계측 -- COMPLETE ✓
- [x] `memory_retrieve.py` -- FTS5 경로에 타이밍 계측 추가 (`time.perf_counter()`)
- [x] `memory_retrieve.py` -- 전체 후보 파이프라인 로깅 (pre/post threshold, pre/post judge)
- [x] `memory_retrieve.py` -- 최종 주입 결과 로깅 (confidence별 분류)
- [x] `memory_retrieve.py` -- 0-result / skip 이벤트 로깅
- [x] `memory_judge.py` -- Judge 호출/응답/오류 로깅
- [x] `memory_search_engine.py` -- CLI 검색 쿼리 로깅 + `--session-id` CLI 파라미터

### Phase 4: 기존 로그 마이그레이션 -- PARTIAL (1/3 deferred)
- [x] `memory_triage.py` -- `.triage-scores.log`와 새 로거 듀얼 라이트
- [x] 기존 stderr 출력 보존 (듀얼 라이트 기간)
- [ ] 듀얼 라이트 기간 후 `.triage-scores.log` 경로 제거 (향후 세션)

### Phase 5: 테스트 및 성능 검증 -- COMPLETE ✓
- [x] `tests/test_memory_logger.py` 작성 (52 tests)
  - [x] 정상 append + JSONL 유효성 + 스키마 필드
  - [x] 디렉토리 자동 생성 + 권한 오류 fail-open
  - [x] 비활성/잘못된 config 안전 기본값 (5 tests)
  - [x] 레벨 필터링 (3 tests)
  - [x] cleanup 동작 (4 tests) + symlink bypass 방지
  - [x] session_id 추출 (3 tests)
  - [x] 동시 append 안전성 (8 threads x 50 writes)
  - [x] V1+V2 보안 테스트 (NaN, symlink containment, bool string, category length, midnight consistency)
- [x] 성능 벤치마크: p95 < 5ms 확인
- [x] 기존 테스트 회귀 없음: 852/852 통과

### Phase 6: 문서 및 설정 업데이트 -- COMPLETE ✓
- [x] `CLAUDE.md` Key Files 테이블에 `memory_logger.py` 추가
- [x] `CLAUDE.md` Config 키 목록에 `logging.*` 추가
- [x] `assets/memory-config.default.json` 업데이트 완료

### V1+V2 검증 -- COMPLETE ✓
- [x] V1 (Correctness + Security): CONDITIONAL PASS → 이슈 수정 후 PASS
- [x] V2 (Adversarial + Fresh-eyes): CONDITIONAL PASS → 이슈 수정 후 PASS
- [x] 10개 이슈 수정, 3개 LOW 이슈 DEFERRED
- [x] 14개 보안 테스트 추가
- [x] 스키마 계약 문서 실제 코드와 동기화

---

## 위험 및 완화 (Risks & Mitigations)

| 위험 | 심각도 | 완화 |
|------|--------|------|
| 로깅이 hook 타임아웃을 유발 | 중간 | fail-open + p95 < 5ms 예산. 로깅 실패 시 hook은 정상 진행 |
| 동시 write 시 JSONL 손상 | 낮음 | 단일 write syscall + `O_APPEND` 플래그. Claude Code는 동일 hook을 동시 실행하지 않음 |
| 로그 파일 무한 증가 | 낮음 | 14일 retention + 24시간 1회 자동 정리. 14일 로그 ≈ < 1MB. 향후 `logging.max_file_mb` 크기 기반 로테이션 추가 가능 |
| Write guard가 로그 쓰기 차단 | **비해당** | PreToolUse:Write guard(`memory_write_guard.py`)는 Claude의 Write 도구만 가로챔. 훅 스크립트의 Python `os.open()`/`os.write()`는 영향 없음 (리뷰 반영 확인) |
| 삭제된 메모리 제목이 로그에 잔류 (secret residue) | 중간 | info 레벨에서 제목 미기록 (경로/ID만). debug 레벨에서만 제목 포함. `.gitignore` 가이드 제공 (리뷰 반영) |
| 기존 stderr 출력 제거로 디버깅 어려움 | 낮음 | 마이그레이션 기간 동안 듀얼 라이트. `level: "debug"` 로 상세 로그 활성화 가능 |
| session_id 불일치 (hook 간) | 중간 | 구현 전 UserPromptSubmit/Stop hook의 `hook_input` 스키마에서 `transcript_path` 필드 존재 확인 필요 |

### 롤백 전략

| 단계 | 롤백 방법 | 영향 범위 |
|------|----------|----------|
| Phase 2 (로거 모듈) | `memory_logger.py` 삭제 → fail-open noop 폴백 자동 활성 | 로깅만 비활성, 핵심 기능 무영향 |
| Phase 3 (파이프라인 계측) | `logging.enabled: false` 설정 → 파일 I/O 0 | emit_event() 호출은 남지만 즉시 반환 |
| Phase 4 (마이그레이션) | 듀얼 라이트 기간 중 새 로깅 제거, 기존 stderr 복원 | 기존 동작으로 완전 복귀 |
| 전체 | `logging` 설정 키 제거 → 기본값 `false`로 폴백 | 제로 설정으로 완전 비활성. **주의:** Phase 4 완료 후에는 기존 stderr도 제거된 상태이므로 설정만 비활성하면 관측성 제로 상태. 완전 복구 시 Phase 4 코드 변경도 revert 필요 |
| Phase 1 (스키마 계약) | 롤백 불필요 | `assets/memory-config.default.json`의 `logging` 키가 남지만 기본값 `false`로 런타임 영향 없음 (zombie config) |

- 모든 롤백은 핵심 검색 기능에 영향 없음 (fail-open 원칙)
- lazy import 패턴으로 memory_logger.py 미존재 시 자동 noop 폴백

---

## 외부 모델 합의 (External Model Consensus)

### Codex 5.3 (planner 모드)
- **디렉토리 구조:** Option 1 (event_type/date) 추천 -- 파이프라인별 시계열 분석에 최적
- **로거:** 커스텀 경량 -- 기존 triage `os.open(O_APPEND)` 패턴 재활용
- **스키마:** 확장형 (안정적 최상위 + event-specific data) 추천
- **프라이버시:** 원본 프롬프트/트랜스크립트 기본 미기록
- **정리:** 일 1회 시간 게이트, `.last_cleanup` 파일 기반
- **추가 제안:** `schema_version` 필드로 스키마 드리프트 방지

### Gemini 3 Pro (planner 모드)
- **디렉토리 구조:** Option 1 (event_type/date) 추천 -- `cat logs/retrieval/*.jsonl | jq` 워크플로우에 최적
- **로거:** `MemoryLogger` 클래스 with lazy file handle 추천
- **session_id:** `transcript_path` 활용 추천 (파일명 해시/추출)
- **정리:** 수동 cleanup 스크립트 또는 수동 사용자 실행 대안 제시
- **추가 제안:** 후보 감소 지표(attrition metrics) 기록 중요 -- `candidates_found`, `candidates_post_threshold`, `candidates_post_judge`

### Vibe-check 피드백 반영
- ~~`logging.enabled` 기본값 `true`로 변경~~ → **리뷰 후 `false`로 재변경** (사용자 동의 원칙 우선)
- 확률적 정리 → `.last_cleanup` 시간 게이트로 단순화
- v1 설정 키를 3개로 최소화 (enabled, level, retention_days)
- PoC 지원을 위해 전체 후보 파이프라인 로깅 강조

### 리뷰 피드백 반영 요약
- `logging.enabled` default: `true` → `false` (engineering + adversarial 합의)
- Write 패턴: `os.fdopen().write()` → `os.write(fd, line_bytes)` (atomic append 보장)
- 프라이버시: info 레벨에서 제목 미기록, debug에서만 기록 (secret residue 방지)
- 스키마: `schema_version: 1` 필드 추가 (forward compatibility)
- session_id: CLI 모드 미제공 제한 사항 문서화
- Write guard: 로그 쓰기 비간섭 확인 문서화
- `.gitignore`: `logs/` 디렉토리 추가 가이드

---

## Plan #3 의존성 (Dependencies for PoC Plan)

Plan #3 (PoC 실험)은 이 로깅 인프라에 다음을 요구한다:

1. **`retrieval.search` 이벤트에 전체 후보 리스트 포함** -- PoC #5 (BM25 정밀도)에서 수동 라벨링 대상
2. **`retrieval.inject` 이벤트에 per-result confidence + output_mode 포함** -- PoC #6 (Nudge 준수율) 측정
3. **`retrieval.search` 이벤트에 토큰 매칭 상세 포함** -- PoC #7 (OR-query 정밀도) 분석
4. **`duration_ms` 필드의 신뢰성** -- PoC #4 (Agent Hook) 레이턴시 비교
5. **`session_id` 필드의 일관성** -- 세션 내 여러 이벤트 상관관계 분석

이 요구사항들이 위 스키마와 로깅 포인트 설계에 반영되어 있다.

---

## DEFERRED 항목 (구현 세션에서 연기된 사항)

### D-01: `retrieval.inject`에 `output_mode` 필드 추가 [V1 F-04, LOW]
- [ ] `output_mode` 필드 추가 구현
- **내용:** `retrieval.inject` 이벤트에 `output_mode` (`"full"`, `"compact"`, `"silent"`) 필드가 누락됨
- **영향:** PoC #6 (Nudge 준수율)에서 compact injection 발생 횟수 측정 불가
- **수정 위치:** `hooks/scripts/memory_retrieve.py` -- FTS5 경로(~line 533)와 legacy 경로(~line 678)의 `retrieval.inject` emit 호출
- **예상 공수:** ~5 LOC, 30분

### D-02: `candidates_found` vs `candidates_post_threshold` 분리 [V1 F-05, LOW]
- [ ] raw 후보 수와 threshold 후 후보 수 분리 구현
- **내용:** `retrieval.search` 이벤트에서 두 필드가 동일한 값(`len(results)`) -- threshold 적용 전 raw 후보 수가 누락됨
- **영향:** 파이프라인 후보 감소(attrition) 분석 불가. `candidates_found`가 threshold 전 수치여야 의미 있음
- **수정 위치:** `hooks/scripts/memory_retrieve.py` -- `score_with_body()` 호출 전후로 카운트 분리 필요. `score_with_body()`가 내부에서 `apply_threshold()` 호출하므로 반환값에 raw count 추가하거나 별도 query로 raw count 획득
- **예상 공수:** ~15-20 LOC, 1-2시간 (score_with_body 반환 구조 변경 필요)

### D-03: 글로벌 payload 크기 제한 [V2 Finding #8, LOW]
- [ ] `emit_event()` 내 payload 크기 제한 추가
- **내용:** `data.results[]`는 20개로 제한하지만, 다른 data 필드(`query_tokens` 등)에는 크기 제한 없음
- **영향:** 소비자 스크립트 버그로 인한 대량 로그 엔트리 가능 (이론적). fail-open이 MemoryError를 잡음
- **수정 위치:** `hooks/scripts/memory_logger.py` `emit_event()` -- `json.dumps()` 후 `len(line_bytes) > 32768` 체크 추가
- **예상 공수:** ~3 LOC, 15분

### D-04: 듀얼 라이트 종료 -- `.triage-scores.log` 제거 [Phase 4 잔여]
- [ ] 레거시 `.triage-scores.log` 듀얼 라이트 코드 제거
- **내용:** `memory_triage.py`에서 레거시 `.triage-scores.log` 듀얼 라이트 코드 제거
- **전제 조건:** 새 로깅 시스템으로 충분한 데이터 축적 확인 후 (2-4주 운영)
- **수정 위치:** `hooks/scripts/memory_triage.py` lines ~1012-1046 (`# LEGACY: remove after migration validation`)
- **예상 공수:** ~30 LOC 삭제, 30분

### D-05: `retrieval.search`에 `matched_tokens` 필드 추가 [PoC #7 의존성]
- [ ] `matched_tokens` 근사 계산 로직 구현
- **내용:** PoC #7 (OR-query 정밀도)은 `data.results[].matched_tokens` 필드를 요구함. FTS5 `rank`는 전체 점수만 반환하므로 로깅 시 제목+태그 토큰 교차 비교로 근사 계산 필요
- **영향:** Plan #3 PoC #7 분석 불가
- **수정 위치:** `hooks/scripts/memory_retrieve.py` -- `retrieval.search` emit 직전에 query_tokens과 entry title/tag tokens의 교집합 계산
- **예상 공수:** ~10-15 LOC, 1시간

---

## 품질 감사 계획 (Quality Audit Plan)

**날짜:** 2026-02-25
**범위:** Plan #2 구현 전체 (memory_logger.py + 4개 소비자 스크립트 계측 + 테스트)
**전략 근거:** V1+V2 정적 리뷰는 코드 *구조*를 검증했으나, 런타임 *데이터 흐름*과 *통합 동작*은 검증하지 못함. 이 감사는 정적 리뷰가 구조적으로 놓치는 영역에 집중.

### 전략 선택 근거

| 접근법 | 장점 | 단점 | 채택 여부 |
|--------|------|------|-----------|
| User scenario walkthrough | 사용자 관점의 실제 문제 발견 | 내부 데이터 흐름 미검증 | 부분 채택 (Tier 3) |
| 모듈별 분리 리뷰 | 체계적, 누락 방지 | V1+V2와 중복, 비효율 | 미채택 |
| 보안/정확성 관점 리뷰 | 깊은 분석 가능 | V1+V2에서 이미 수행 | 미채택 |
| **통합 데이터 계약 검증** | V1+V2가 놓치는 핵심 영역 | call-site별 수작업 필요 | **주 전략** |
| **행동 검증 (behavioral)** | 런타임 버그 발견 | 테스트 작성 비용 | **보조 전략** |
| **운영 시나리오 검증** | 사용자 체감 문제 발견 | 범위 제한적 | **보조 전략** |

**최종 전략: 3단계 우선순위 감사 (Three-Tier Prioritized Audit)**
- **Tier 1 (통합 데이터 계약):** emit_event() call-site별 실제 data dict 키를 스키마와 대조. 런타임 데이터 흐름 추적.
- **Tier 2 (행동 검증):** 파이프라인 end-to-end 실행 후 디스크에 기록된 실제 바이트 검증. lazy import 폴백 검증.
- **Tier 3 (운영 검증):** 사용자 워크플로우 (활성화/비활성화/분석) 동작 확인. 설계 개선 제안.

### Tier 1: 통합 데이터 계약 검증 (HIGH priority, ~1.5시간)

#### A-01: Config 로딩 순서 버그 [est. 20분]
- [x] config 로드 전 emit_event 호출 경로 추적 및 검증
- **가설:** `memory_retrieve.py`의 초기 `retrieval.skip` 이벤트(~line 333, ~361)가 `config=None`으로 emit → `parse_logging_config(None)`이 `enabled: False` 반환 → 로깅 활성 상태에서도 이 이벤트들이 영구 미기록
- **검증:** 실행 경로 추적: config 로드 시점(~line 370) 이전의 모든 emit_event 호출 식별
- **영향:** 짧은 프롬프트/빈 인덱스에 대한 skip 이벤트가 로그에 누락 → 관측 가능성 갭
- **분류:** 데이터 완전성 버그

#### A-02: Call-Site 스키마 감사 [est. 45분]
- [x] 4개 소비자 스크립트의 ~12개 emit_event() 호출 대조 완료
- **방법:** 4개 소비자 스크립트의 ~12개 `emit_event()` 호출 지점에서 실제 `data` dict 키를 추출하여 스키마 계약(`temp/p2-logger-schema.md`)과 대조
- **목표:** DEFERRED D-01~D-05 외의 미알려진 스키마 불일치 발견
- **산출물:** call-site별 대조표 (expected vs actual vs gap)

#### A-03: results[] 필드 정확성 검증 [est. 30분]
- [x] score_with_body() 데이터 흐름 추적 및 정확성 확인
- **가설:** `score_with_body()` 내에서 `top_k_paths` 범위 밖 엔트리의 `body_bonus`가 "0" (분석 미수행)과 "0" (매칭 없음)을 구분할 수 없음
- **검증:** `score_with_body()` 데이터 흐름 추적 -- `raw_bm25`, `score`, `body_bonus` 값이 로깅 시점에 정확한지 확인
- **영향:** PoC #5 (BM25 정밀도) 데이터 품질

### Tier 2: 행동 검증 (MEDIUM priority, ~1.5시간)

#### A-04: End-to-End 데이터 흐름 추적 [est. 40분]
- [x] 최소 코퍼스로 E2E 파이프라인 실행 및 JSONL 출력 검증
- **방법:** 최소 메모리 코퍼스(2-3개 JSON) 생성 → `logging.enabled: true` 설정 → `memory_retrieve.py`에 hook_input 파이프 → `logs/` 디렉토리의 JSONL 파일 파싱 검증
- **검증:** 유효한 JSON, schema_version=1, timestamp/filename 일치, data 키 존재, duration_ms 양수 유한
- **의의:** 기존 52개 테스트는 `emit_event()`를 합성 데이터로 직접 호출. 소비자 스크립트가 구성하는 실제 data dict를 검증하는 테스트 없음

#### A-05: Lazy Import 폴백 검증 [est. 15분]
- [x] 4개 소비자 스크립트에서 3가지 import 실패 시나리오 테스트
- **방법:** `memory_logger.py` 미존재/SyntaxError/전이적 ImportError 3가지 시나리오를 4개 소비자 스크립트 각각에서 테스트
- **의의:** 폴백 코드가 4개 파일에 복제됨. 어느 하나에 오타가 있으면 기존 테스트로 발견 불가

#### A-06: Cleanup 레이턴시 (축적 상태) [est. 20분]
- [x] 축적된 파일 상태에서 p95 < 5ms 벤치마크 확인
- **방법:** 14개 서브디렉토리 x 14개 .jsonl 파일 생성 → `.last_cleanup` 없이 `emit_event()` 호출 → p95 < 5ms 확인
- **의의:** 벤치마크 테스트는 빈 디렉토리에서 실행. 프로덕션은 파일이 축적된 상태

#### A-07: 큰 페이로드 동시 Append [est. 15분]
- [x] 4096바이트 근처 페이로드로 동시 append 원자성 검증
- **방법:** 4096바이트 근처 페이로드로 동시 append 테스트 → JSONL 라인 손상 여부 확인
- **의의:** POSIX `O_APPEND` 원자성 보장 경계(PIPE_BUF) 근처 동작 검증

### Tier 3: 운영 검증 및 설계 개선 (LOW priority, ~30분)

#### A-08: 운영 워크플로우 스모크 테스트 [est. 10분]
- [x] 로깅 활성화/비활성화 전환 동작 검증
- [x] 레벨 변경 (info→debug→warning) 적용 확인
- [x] jq 파싱 검증 (출력 JSONL의 유효성)
- [x] config 삭제 시 안전 기본값 폴백 확인

#### A-09: 잘림(truncation) 메타데이터 누락 [est. 5분, 설계 개선]
- [x] 잘림 발생 시 `_truncated`/`_original_count` 메타데이터 추가 구현
- `results[]` 잘림 시 원래 개수(`_original_results_count`) 미기록 → 분석 정확도 저하
- 수정 방안: 잘림 발생 시 `data["_truncated"] = True`, `data["_original_count"] = len(results)` 추가

#### A-10: triage.score 이벤트에 비트리거 카테고리 점수 누락 [est. 5분, 설계 개선]
- [x] 전체 6개 카테고리 점수 기록 여부 확인 및 구현
- 현재 threshold 초과 카테고리만 기록 → threshold 튜닝 분석에 전체 6개 카테고리 점수 필요
- PoC #4 의존성 확인 필요

#### A-11: 비결정적 set 직렬화 방어 [est. 5분, 설계 개선]
- [x] `json.dumps()` 호출 전 set→sorted list 변환 방어 코드 추가
- `json.dumps(default=str)`로 `set` → 비결정적 문자열 변환. 현재 call-site에서 set 전달 없으나 방어적 개선 가능

### 우선순위 요약

| 순위 | 액션 | 시간 | 버그 유형 | 발견 확률 |
|------|------|------|-----------|----------|
| 1 | A-01 Config 로딩 순서 | 20분 | 데이터 완전성 | 높음 (실 버그 가설) |
| 2 | A-02 Call-site 스키마 | 45분 | 스키마 불일치 | 중간 (미지 갭) |
| 3 | A-03 results[] 정확성 | 30분 | PoC 데이터 품질 | 중간 |
| 4 | A-04 E2E 데이터 흐름 | 40분 | 통합 검증 | 높음 (최고 가치) |
| 5 | A-05 Import 폴백 | 15분 | 회귀 안전 | 낮음 |
| 6 | A-10 비트리거 점수 | 5분 | 데이터 완전성 | 확정 (설계 갭) |
| 7 | A-09 잘림 메타데이터 | 5분 | 분석 정확도 | 확정 (설계 갭) |
| 8 | A-06 Cleanup 레이턴시 | 20분 | 성능 가정 | 낮음 |
| 9 | A-08 운영 스모크 | 10분 | 사용자 체감 | 중간 |
| 10 | A-07 큰 페이로드 | 15분 | 원자성 가정 | 낮음 |
| 11 | A-11 set 직렬화 | 5분 | 방어적 개선 | 해당 없음 (현재 버그 아님) |

**총 예상 시간:** Tier 1만 ~1.5시간, 전체 ~3.5시간

### 전략 자기비판

1. **강점:** V1+V2 정적 리뷰와 중복 없이 통합 데이터 흐름에 집중. 구체적 파일/라인 수준의 가설 기반.
2. **약점:** Plan 문서 자체의 정확성은 검증하지 않음. 소비자 스크립트 에러 경로의 data dict 구성 미검증.
3. **외부 검증:** Gemini 3.1 Pro (잘림 메타데이터, set 직렬화), Codex 5.3 (config race, call-site audit), vibe-check (우선순위 조정) 의견 반영.

---

## 검토 이력

| 검토 | 결과 | 핵심 발견 |
|------|------|----------|
| Engineering Review | APPROVE WITH CHANGES | logging.enabled default false, os.write pattern, schema_version |
| Adversarial Review | APPROVE WITH CHANGES | Privacy residue at info level, .gitignore guidance |
| V1-Robustness | PASS WITH NOTES | session_id CLI limitation documented |
| V1-Practical | PASS | LOC estimates verified, tools available |
| V2-Fresh Eyes | APPROVE | Slightly over-engineered but sound; add v0 milestone |
| V2-Adversarial | HIGH → fixed | Logger import crash (lazy import), raw_bm25 in schema |
| Deep Analysis (7-agent) | Import hardening refined | e.name scoping for transitive dependency distinction (NEW-5). body_bonus added to logging schema (triple-field). |
| Structure Audit (Session 10) | 3 gaps fixed | Finding #4 session-id 해결책, 구현 순서 섹션, 롤백 전략 섹션 추가. V1 중복 롤백 제거. |
| V2-Holistic (Session 10) | PASS | Gemini 3.1 Pro 교차 검증 통과. 구조, 정확성, 완전성 모두 합격. |
| V2-Adversarial (Session 10) | MEDIUM→fixed | Phase 3/4 파일 겹침 주장 수정, 전체 롤백 관측성 경고 추가, Phase 1 zombie config 명시. |
| Implementation V1 (Phase 1-5) | CONDITIONAL PASS→PASS | 4 MEDIUM, 4 LOW 발견. makedirs mode, schema drift, output_mode 누락 등. |
| Implementation V2 (Phase 1-5) | CONDITIONAL PASS→PASS | 1 HIGH (symlink traversal), 3 MEDIUM (NaN, .last_cleanup, bool parsing), 4 LOW. 10개 수정. |
| Post-Fix Verification | PASS | 852/852 테스트 통과, 14개 보안 테스트 추가, 스키마 문서 동기화 |
| Quality Audit Plan | DESIGNED | 3-tier 감사 전략 수립. Gemini 3.1 Pro + vibe-check 교차 검증. 11개 감사 액션 도출. |
