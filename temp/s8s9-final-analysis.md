# Session 8 & Session 9 최종 분석

## 분석 프로세스
- 소스: rd-08-final-plan.md, memory_judge.py, memory_retrieve.py, memory_search_engine.py, SKILL.md
- 분석자: Opus (코드 직접 분석), Explore subagent x2 (S8/S9 심층), General subagent (ThreadPoolExecutor 실험적 검증)
- 외부 의견: Codex 5.3 (planner), Gemini 3 Pro (planner)
- 메타인지: vibe-check 스킬
- 검증: 독립 Explore agent (12개 claim 중 11 VERIFIED, 1 PARTIALLY CORRECT)

---

## Session 8 (Phase 3b-3c) 분석

### 무엇을 하자는 건가?

두 가지 작업으로 구성:

**Phase 3b: memory_judge.py 테스트 작성 (~200 LOC, 15개 테스트)**
- S7에서 만든 LLM 판정기(memory_judge.py, 253 LOC)에 대한 자동화 테스트 스위트 구축

**Phase 3c: /memory:search 스킬에 Task subagent 판정기 추가**
- 온디맨드 검색 시 더 풍부한 컨텍스트로 판정하는 메커니즘 도입

### 테스트를 어떻게 하자는 건가?

**테스트 파일:** `tests/test_memory_judge.py` (신규 생성)

**15개 테스트 케이스 (rd-08 lines 942-957):**

| # | 테스트명 | 대상 함수 | 유형 | 검증 내용 |
|---|---------|----------|------|----------|
| 1 | test_call_api_success | call_api() | Unit | urllib 응답 모킹 → 텍스트 추출 성공 |
| 2 | test_call_api_no_key | call_api() | Unit | ANTHROPIC_API_KEY 없을 때 None 반환 |
| 3 | test_call_api_timeout | call_api() | Unit | 타임아웃 → None 반환 |
| 4 | test_call_api_http_error | call_api() | Unit | HTTP 에러 → None 반환 |
| 5 | test_format_judge_input_shuffles | format_judge_input() | Unit | sha256 기반 결정적 셔플, 프로세스 간 안정성 |
| 6 | test_format_judge_input_with_context | format_judge_input() | Unit | 대화 컨텍스트 포함 여부 |
| 7 | test_parse_response_valid_json | parse_response() | Unit | 정상 JSON → 올바른 인덱스 |
| 8 | test_parse_response_with_preamble | parse_response() | Unit | 마크다운 래핑된 JSON 파싱 |
| 9 | test_parse_response_string_indices | parse_response() | Unit | 문자열 인덱스 "2" → int 2 변환 |
| 10 | test_parse_response_nested_braces | parse_response() | Unit | 중첩 중괄호에서 최외곽 JSON 추출 |
| 11 | test_parse_response_invalid | parse_response() | Unit | 유효하지 않은 JSON → None |
| 12 | test_judge_candidates_integration | judge_candidates() | Integration | 전체 파이프라인 (컨텍스트→포맷→API→파싱→필터링) |
| 13 | test_judge_candidates_api_failure | judge_candidates() | Integration | API 실패 시 None 반환 (폴백 트리거) |
| 14 | test_extract_recent_context | extract_recent_context() | Unit | JSONL 트랜스크립트 파싱, 마지막 N턴 추출 |
| 15 | test_extract_recent_context_empty | extract_recent_context() | Unit | 파일 없음/빈 파일 → 빈 문자열 |

**API 모킹 전략:** stdlib의 `unittest.mock`으로 `urllib.request.urlopen`을 패치. 외부 라이브러리 불필요.

```python
# 예시: 성공 케이스 모킹
@patch('urllib.request.urlopen')
def test_call_api_success(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "content": [{"type": "text", "text": '{"keep": [0, 2]}'}]
    }).encode()
    mock_response.__enter__ = lambda s: s
    mock_urlopen.return_value = mock_response
    result = call_api("system", "user")
    assert result == '{"keep": [0, 2]}'
```

**수동 정밀도 비교 (line 958):** 자동화 테스트와 별개로, 20개 쿼리에 대해 BM25-only vs BM25+judge 결과를 사람이 직접 비교. 이는 코드 검증이 아닌 judge 실효성 확인용 smoke test.

### "Task subagent judge"란?

이것이 S8의 핵심 아키텍처 결정이다.

**문제의 근본:** Claude Code의 아키텍처적 경계 (rd-08 lines 28-29)
```
Hook scripts (type: "command") run as standalone Python subprocesses.
They CANNOT access Claude Code's Task tool. This is a fundamental boundary.
```

즉, 두 개의 서로 다른 실행 환경이 존재:

| | Hook (UserPromptSubmit) | Skill (/memory:search) |
|-|------------------------|----------------------|
| 실행 모델 | 독립 Python 서브프로세스 | 에이전트 대화 내에서 실행 |
| 사용 가능 도구 | 없음 (stdlib만) | Task, Read, Bash 등 전부 |
| 대화 컨텍스트 | user_prompt + 최근 5턴 (transcript_path) | 전체 대화 히스토리 |
| 레이턴시 | <15초 (hook timeout) | ~30초 허용 (사용자가 명시적으로 검색) |

**따라서 두 가지 다른 판정 메커니즘이 필요:**

1. **Auto-inject 판정기 (hook 경로):** `memory_judge.py`가 `urllib.request`로 Anthropic API를 직접 호출. ANTHROPIC_API_KEY 환경변수 필요. **strict 모드** -- "DIRECTLY RELEVANT하고 ACTIVELY HELP하는 것만 keep"

2. **Task subagent 판정기 (skill 경로):** `/memory:search` 스킬이 Claude Code의 Task 도구로 haiku 모델 서브에이전트를 스폰. 서브에이전트는 전체 대화 컨텍스트를 가짐. **lenient 모드** -- "RELATED to the user's query? Be inclusive." (rd-08 line 964)

**Task subagent의 장점:**
- API 키 불필요 (에이전트 자체 인증 사용 → OAuth 사용자도 동작)
- 전체 대화 컨텍스트 접근 → "fix that function" 같은 맥락의존 쿼리에서 훨씬 정확
- 관대한 레이턴시 예산 (~30초)

**Task subagent의 단점 (Gemini의 비판):**
- hook과 skill에서 서로 다른 판정 로직 → 테스트/유지보수 부담 증가
- 서브에이전트 출력 형식이 비결정적 (LLM 응답 변동성)
- memory_judge.py를 --lenient 플래그로 재사용하는 것이 더 DRY

---

## Session 9 (Phase 4) 분석

### "Dual judge prompt"이란?

현재 S7에서 구현된 단일 판정기는 하나의 프롬프트로 "이 메모리가 관련있고 유용한가?"를 한번에 판단. Session 9는 이를 **두 개의 독립적인 평가 차원**으로 분리하자는 제안 (rd-08 lines 910-912):

- **Judge 1 (관련성/Relevance):** "이 메모리가 같은 주제인가?"
- **Judge 2 (유용성/Usefulness):** "이 메모리가 현재 작업에 도움이 되는가?"

**왜 분리하는가?** 관련성과 유용성은 독립적 속성이기 때문:
- 관련있지만 유용하지 않은 예: "OAuth 2.0 토큰 포맷" 메모리가 있는데 지금 JWT를 구현 중
- 유용하지만 간접적인 예: "시크릿 하드코딩 금지" 제약이 있는데 지금 API 최적화 중

**설정 게이트:** `judge.dual_verification: true` (기본값 false). 단일 판정기의 정밀도가 85% 미만일 때만 켜는 선택적 업그레이드 경로.

### Intersection/Union logic이란?

두 판정기의 결과를 합치는 방식이 모드에 따라 다름 (rd-08 lines 913-917):

**Intersection (교집합) -- Auto-inject (strict 모드):**
- 두 판정기가 **모두** 동의해야 keep → 정밀도 최우선
- 수학: 각 판정기 정확도 70%면 → 0.7 × 0.7 = **0.49 recall** (둘 다 맞을 확률)
- 각 90%면 → 0.9 × 0.9 = 0.81 recall (여전히 19% 손실)

**Union (합집합) -- On-demand search (lenient 모드):**
- **어느 하나라도** 동의하면 keep → 재현율 최우선
- 수학: 각 70%면 → 1 - (0.3 × 0.3) = **0.91 recall**
- 각 90%면 → 1 - (0.1 × 0.1) = 0.99 recall

**왜 모드별로 다른 로직인가?**
- Auto-inject: 매 프롬프트마다 자동 실행. 거짓양성 = 컨텍스트 창에 쓸모없는 토큰 ($0.004/개). 정밀도가 중요.
- Search: 사용자가 명시적으로 검색. 거짓음성 = 필요한 정보 누락. 재현율이 중요.

**Skeptic의 핵심 우려 (rd-08 line 508):**
> "AND-gate of two imperfect classifiers drops recall to ~49%."

이것이 S9의 가장 큰 위험. 각 판정기가 독립적으로 70% 정확하면, 교집합 취할 때 관련 메모리의 **절반 이상**을 잃는다. 메모리 시스템에서 recall 손실은 특히 치명적 -- 놓친 메모리 때문에 디버깅 시간이 늘어나거나 잘못된 결정을 내릴 수 있다.

### ThreadPoolExecutor 메모리 누수 위험은?

**결론: 실질적 위험 없음 (LOW)**

서브에이전트가 실제 실험으로 검증한 결과:

1. **프로세스가 단명(短命):** hook 스크립트는 시작→실행→종료. OS가 모든 메모리 회수. 장기 누수 구조적 불가능.
2. **GIL 문제 없음:** I/O 중 GIL 해제. 2개 병렬 urllib 호출이 1초에 완료 (순차 2초 아닌).
3. **urllib.request는 thread-safe:** 각 호출이 독립 HTTP 연결 생성. 공유 커넥션 풀 없음.
4. **FD 누수 없음:** 타임아웃 발생 시에도 소켓 정상 정리 (실험적 확인: FD 0개 누수).
5. **ThreadPoolExecutor 스레드는 non-daemon:** Python이 종료 시 join()으로 대기. urllib timeout(3초)이 상한선.
6. **최악의 경우:** DNS 행 → hook 15초 timeout → SIGKILL → 모든 스레드 즉시 파괴.

**권장 구현 패턴:**
```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=2) as executor:
    f1 = executor.submit(call_api, RELEVANCE_PROMPT, formatted, model, timeout)
    f2 = executor.submit(call_api, USEFULNESS_PROMPT, formatted, model, timeout)
    try:
        r1 = f1.result(timeout=4.0)  # belt-and-suspenders
        r2 = f2.result(timeout=4.0)
    except TimeoutError:
        return None  # fallback to BM25
```

3중 타임아웃 방어: urllib(3s) → future.result(4s) → hook SIGKILL(15s).

### Precision improvement 측정 방법은?

**정의:** `precision = 관련_있는_주입_메모리 / 전체_주입_메모리`

**방법론 (rd-08 lines 413-425):**
1. 40-50개 대표 쿼리 준비 (맥락의존, 구체적, 멀티토픽, 모호한 쿼리 혼합)
2. 각 쿼리에 대해 주입된 메모리를 사람이 관련/비관련으로 레이블링
3. 파이프라인별 비교: BM25-only → BM25+단일판정기 → BM25+이중판정기
4. 95% CI가 ~13-15pp (n=50에서) → 방향성 확인용이지 정밀 통계가 아님

**실용적 어려움:**
- 단일 레이블러 편향 (한 사람이 판단)
- "관련성"의 주관성
- 500개 메모리 규모에서 통계적 검정력 제한적

---

## 외부 모델 비교 분석

### Task subagent judge에 대한 시각 차이

| 시각 | 의견 | 근거 |
|------|------|------|
| **Codex 5.3** | Sound with guardrails | 아키텍처 제약에 맞음, OAuth 사용자에게 유리 |
| **Gemini 3 Pro** | Abandon -- over-engineering | 로직 분기 → 테스트 중복, memory_judge.py 재사용이 DRY |
| **내 분석** | 양쪽 모두 유효한 점 있음 | 아래 종합 참조 |

**종합:** Codex의 포인트(OAuth 사용자, 전체 컨텍스트 접근)가 기술적으로 맞다. 하지만 Gemini의 포인트(DRY 원칙, 유지보수 부담)도 실무적으로 중요하다. 실질적으로 두 접근은 상호배타적이 아닌데 -- Task subagent 내에서 memory_judge.py를 Bash로 호출하되 lenient 파라미터를 추가하면 양쪽 장점을 모두 취할 수 있다.

### Dual judge에 대한 합의

| 시각 | 의견 |
|------|------|
| **Codex** | "Not worth default complexity; gated experiment only" |
| **Gemini** | "Scrap entirely. Fatal flaw for contextual memory system" |
| **Plan 자체의 skeptic** | "AND-gate drops recall to ~49%... structurally net-negative" |
| **내 분석** | 현재 단일 판정기 JUDGE_SYSTEM이 이미 관련성+유용성 기준을 통합. 분리의 이론적 이득(~3%p 정밀도)이 실용적 비용(2x API, recall 손실, 복잡성)을 정당화하지 못함 |

---

## 검증 결과

독립 검증 에이전트가 12개 핵심 주장을 rd-08 원문 대비 검증:
- **11개 VERIFIED** (정확한 라인 번호 확인)
- **1개 PARTIALLY CORRECT** (정밀도 측정의 비교 대상 범위: 40-50 쿼리는 맞지만 "BM25 vs single vs dual" 비교는 S9가 아닌 Phase 2f 측정 게이트에서 수행)
- **0개 INCORRECT**
