# Plan #2: 로깅 인프라스트럭처 (Logging Infrastructure)

**날짜:** 2026-02-22
**작성자:** plan2-drafter
**상태:** Draft
**검증 소스:** Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check

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
- **Lazy import 패턴 (V2-adversarial 반영):** `memory_logger`는 top-level import가 아닌 lazy import with fallback:
  ```python
  try:
      from memory_logger import emit_event
  except ImportError:
      def emit_event(*args, **kwargs): pass
  ```
  근거: 부분 배포/업데이트 시 `memory_logger.py` 미존재 가능. top-level `ImportError`는 hook 전체 실패 유발 → fail-open 원칙 위반.

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
      {"path": ".claude/memory/decisions/use-oauth.json", "score": -4.23, "raw_bm25": -1.23, "confidence": "high"},
      {"path": ".claude/memory/constraints/api-limits.json", "score": -2.11, "raw_bm25": -0.61, "confidence": "medium"}
    ]
  },
  "error": null
}
```

> **Note (리뷰 반영):** `results[]`에 제목(title) 미포함 (info 레벨). 경로(path)와 점수(score/raw_bm25)만 기록. `level: "debug"` 시 제목 추가됨.
>
> **V2-adversarial 반영:** `results[]`에 `raw_bm25` (순수 BM25 점수)와 `score` (body_bonus 반영 복합 점수) 모두 기록. PoC #5는 `raw_bm25` 기반 precision 계산, `score`는 end-to-end 품질 평가에 사용.

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
  - **제한 사항 (리뷰 반영):** CLI 모드(`memory_search_engine.py --mode search`)에서는 hook_input이 없으므로 session_id 미제공. `search.query` 이벤트는 session_id가 빈 문자열. PoC #6 크로스 이벤트 상관관계에서 CLI 검색 이벤트는 상관관계 불가. 향후 `os.getppid()` 또는 타임스탬프 기반 그루핑으로 대체 검토.
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

## 진행 상황 (Progress)

### Phase 1: 로깅 계약 정의 (Logging Contract)
- [ ] JSONL 스키마 확정 (최상위 필드 + 이벤트별 data 구조)
- [ ] event_type 체계 확정
- [ ] `assets/memory-config.default.json`에 `logging` 섹션 추가
- [ ] 샘플 JSONL 라인으로 jq/python 파싱 검증

### Phase 2: 공유 로거 모듈 구현
- [ ] `hooks/scripts/memory_logger.py` 생성
- [ ] `emit_event()` 구현 -- `os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` + `os.write(fd, line_bytes)` + `os.close(fd)` 패턴 (단일 syscall 보장)
- [ ] `get_session_id()` 구현 -- transcript_path에서 세션 ID 추출
- [ ] `cleanup_old_logs()` 구현 -- `.last_cleanup` 타임스탬프 기반
- [ ] `parse_logging_config()` 구현 -- dict.get() 안전 기본값
- [ ] 레벨 필터링 구현 (debug < info < warning < error)
- [ ] fail-open 보장: 모든 예외 잡아서 무시

### Phase 3: 검색 파이프라인 계측
- [ ] `memory_retrieve.py` -- FTS5 경로에 타이밍 계측 추가 (`time.perf_counter()`)
- [ ] `memory_retrieve.py` -- 전체 후보 파이프라인 로깅 (pre/post threshold, pre/post judge)
- [ ] `memory_retrieve.py` -- 최종 주입 결과 로깅 (confidence별 분류)
- [ ] `memory_retrieve.py` -- 0-result / skip 이벤트 로깅
- [ ] `memory_judge.py` -- Judge 호출/응답/오류 로깅
- [ ] `memory_search_engine.py` -- CLI 검색 쿼리 로깅

### Phase 4: 기존 로그 마이그레이션
- [ ] `memory_triage.py` -- `.triage-scores.log`를 새 로거로 전환
- [ ] 기존 stderr `[DEBUG]`/`[WARN]`/`[INFO]` 출력을 로거 호출로 대체
- [ ] 듀얼 라이트 기간 후 `.triage-scores.log` 경로 제거

### Phase 5: 테스트 및 성능 검증
- [ ] `tests/test_memory_logger.py` 작성
  - [ ] 정상 append 테스트
  - [ ] 디렉토리 없을 때 자동 생성
  - [ ] 디렉토리 권한 오류 시 fail-open
  - [ ] 잘못된 config 시 안전 기본값
  - [ ] 레벨 필터링
  - [ ] cleanup 동작 (retention_days 초과 파일 삭제)
  - [ ] cleanup 시간 게이트 (.last_cleanup 24시간 미경과 시 건너뜀)
  - [ ] session_id 추출 (다양한 transcript_path 형식)
  - [ ] 동시 append 안전성
- [ ] 성능 벤치마크: `emit_event()` 단일 호출 p95 < 5ms 확인
- [ ] 기존 테스트 회귀 없음 확인 (`pytest tests/ -v`)

### Phase 6: 문서 및 설정 업데이트
- [ ] `CLAUDE.md` Key Files 테이블에 `memory_logger.py` 추가
- [ ] `CLAUDE.md` Config 키 목록에 `logging.*` 추가
- [ ] `assets/memory-config.default.json` 업데이트

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
