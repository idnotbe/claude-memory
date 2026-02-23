# Plan #1: Actions #1-#4 구현 계획

**날짜:** 2026-02-22
**범위:** 메모리 검색 신뢰도 교정, 계층적 출력, 힌트 개선, Agent Hook PoC
**대상 파일:** `hooks/scripts/memory_retrieve.py` (주 변경), `assets/memory-config.default.json` (설정 추가)
**총 변경량:** ~60-80 LOC (코드) + ~100-200 LOC (테스트)

---

## 배경 (Background)

현재 메모리 검색 시스템(`memory_retrieve.py`)은 BM25 FTS5 기반으로 매 프롬프트마다 관련 메모리를 자동 주입한다. 이 아키텍처는 결정론적이며 안정적이지만, 신뢰도 분류에 세 가지 알려진 결함이 있다:

1. **단일 결과 항상 "high"**: `confidence_label()` (line 161-174)는 상대 비율만 사용. 단일 약한 매칭도 ratio=1.0으로 "high" 분류됨
2. **클러스터링된 점수 전부 "high"**: 유사 점수 결과 3-5개가 모두 ratio > 0.90으로 "high" 됨 (V1-robustness 발견)
3. **모든 결과 동일 형식 주입**: 신뢰도와 무관하게 `<result>` 형식으로 주입되어 정보 위계 부재

추가로:
- 0-result hint가 HTML 주석(`<!-- -->`)으로 Claude에게 무시될 가능성
- `type: "agent"` hook의 존재가 확인되었으나 컨텍스트 주입 메커니즘 미검증 (V2-adversarial 발견)

**분석 문서 참조:**
- `temp/final-recommendation.md` -- 최종 권고 전체
- `temp/v1-practical.md` -- 구현 가능성 검증
- `temp/v1-robustness.md` -- 보안/견고성 검증 (클러스터 감지 제안 출처)
- `temp/v2-adversarial.md` -- Agent hook 발견
- `temp/agent-hook-verification.md` -- Agent hook 독립 검증

---

## Action #1: `confidence_label()` 절대 하한선 + 클러스터 감지

### 목적 (Purpose)

신뢰도 분류의 정확도를 개선하여 Action #2 (계층적 출력)의 기반을 마련한다. 현재 상대 비율만 사용하는 `confidence_label()`에 두 가지 보완 메커니즘을 추가:

(A) **절대 하한선**: BM25 점수의 절대값이 임계치 미만이면 최대 "medium"으로 캡
(B) **클러스터 감지**: 3개 이상 결과가 ratio > 0.90이면 "medium"으로 캡

### 관련 정보 (Related Info)

**현재 코드** (`hooks/scripts/memory_retrieve.py:161-174`):
```python
def confidence_label(score: float, best_score: float) -> str:
    if best_score == 0:
        return "low"
    ratio = abs(score) / abs(best_score)
    if ratio >= 0.75:
        return "high"
    elif ratio >= 0.40:
        return "medium"
    return "low"
```

**결함 상세:**
- 단일 결과: `ratio = abs(score) / abs(score) = 1.0` -> 항상 "high" (test line 535 확인)
- 클러스터: "api payload" 같은 쿼리로 scores `-4.10, -4.05, -4.02, -4.00, -3.98` 반환 시 모두 ratio > 0.95 -> 모두 "high"
- `apply_threshold()` (`memory_search_engine.py:283-288`)의 25% noise floor는 선택 단계에서 작동하며, `confidence_label()`은 분류 단계에서 작동 -- 이 두 임계치는 독립적이며 서로 다른 차원(선택 vs 표시)에서 동작

**설정 키:**
- `retrieval.confidence_abs_floor` (float, default: `0.0`)
- 기본값 `0.0`은 현행 동작 보존 (하한선 비활성)
- 권장 시작값: BM25 모드에서 `1.0`-`2.0` (로깅 인프라 구축 후 데이터 기반 조정)
- **주의 (리뷰 반영)**: `abs_floor`는 코퍼스 의존적 임시 조치. BM25 점수는 비정규화 값으로, 인덱스 문서 수, 평균 문서 길이, 쿼리 토큰 수에 따라 스케일 변동. 메모리 인덱스 크기가 크게 변하면 재교정 필요. PoC #5의 실증 데이터를 기반으로 향후 백분위 기반 접근(예: "관찰 점수의 하위 25%") 도입 검토.

**클러스터 감지:**
- **설정 토글**: `retrieval.cluster_detection_enabled` (bool, default: **`false`**)
- 조건: `cluster_count > max_inject`인 경우에만 발동 (원안의 `>= 3` 임계치 수정)
- **V2-adversarial CRITICAL 반영 -- Cluster Tautology 수정:**
  - 원안 임계치(`>= 3`)는 `max_inject=3`(기본값)에서 **모든 성공적인 쿼리**에 발동하는 논리 오류. 잘린 후 결과가 최대 3개이므로, 3개 모두 ratio > 0.90이면 항상 발동 → 정당한 high 결과가 불가능해지는 tautology.
  - **수정 1 -- 임계치:** `cluster_count > max_inject` (잘린 후 집합에서 유사 결과가 예산을 초과할 때만 발동)
  - **수정 2 -- 기본값:** `cluster_detection_enabled: false` (V2-fresh + V2-adversarial 합의: 데이터 없이 활성화는 위험)
  - **수정 3 -- 점수 도메인:** `raw_bm25` 기반 ratio로 계산 (body_bonus 변이 배제)
- **로깅 인프라 연계**: 클러스터 감지 발동 시 logging 이벤트 기록 (Plan #2) -> false demotion 데이터 수집 -> 데이터 기반 활성화/임계치 결정

**핵심 수정 (V2-adversarial CRITICAL 반영): `raw_bm25` 기반 신뢰도 분류**

> **V2-adversarial 발견 -- Score Domain Paradox:** 현재 `_output_results()`에서 `confidence_label()`에 전달되는 `score`는 `BM25 - body_bonus` 변이값이며 순수 BM25 점수가 아님. `score_with_body()` (line 257)에서 `r["score"] = r["score"] - body_bonus`로 in-place 변이됨. `raw_bm25` 필드가 line 256에서 이미 계산/보존되지만 하류에서 소비되지 않음.
>
> **영향:** `body_bonus`가 점수 비율을 1.0 방향으로 압축하여, 클러스터 감지의 false trigger 빈도 증가 + `abs_floor` 교정이 복합 점수 도메인에서 무효화됨. PoC #5 정밀도 측정도 잘못된 점수 도메인에서 수행됨.
>
> **수정:** `confidence_label()`과 `cluster_count` 계산에 `raw_bm25` 사용. `_output_results()`에서 `entry.get("raw_bm25", entry.get("score", 0))`로 호출.

**함수 시그니처 변경:**
```python
def confidence_label(score: float, best_score: float,
                     abs_floor: float = 0.0,
                     cluster_count: int = 0) -> str:
```
- `score`, `best_score`: **`raw_bm25` 값 사용** (변이된 `score` 아님)
- `abs_floor`: 절대 하한선. `abs(best_score) < abs_floor`이면 "high" 불가
- `cluster_count`: ratio > 0.90인 결과 수 (**`raw_bm25` 기반 ratio**). 주의: `max_inject`에 의해 결과가 잘린 후의 집합에서 계산.

**호출 지점 변경:**
- `_output_results()` (line 299): `confidence_label()` 호출 전에 cluster_count 계산 필요
- 설정 파싱: `main()` (line 353-384 영역)에서 `abs_floor` 읽기 추가

**`apply_threshold()`와의 상호작용 (개발자 참고):**
`apply_threshold()` (selection)과 `confidence_label()` (labeling)은 독립적 임계치. `apply_threshold()`는 25% noise floor로 결과를 필터링한 후, `confidence_label()`은 남은 결과에 대해 분류한다. 두 임계치가 조율되지 않으므로 `apply_threshold()`를 통과한 클러스터 결과가 `confidence_label()`에서 모두 "high"가 되는 것이 현재 문제이며, 이번 변경으로 해결된다.

**테스트 영향:**
- `TestConfidenceLabel` (`tests/test_memory_retrieve.py:493-562`): 17개 테스트
  - `abs_floor=0.0` 기본값 시: **기존 테스트 전부 통과** (함수 시그니처에 기본값 사용)
  - `test_single_result_always_high` (line 535): `abs_floor > 0` 사용 시에만 변경됨
  - `test_all_same_score_all_high` (line 539): `cluster_count >= 3` 전달 시에만 변경됨
- **신규 테스트 필요**: ~15-25개
  - abs_floor 경계값 (0.0, 양수, BM25 음수 점수)
  - 클러스터 감지 (2개=미적용, 3개=적용, ratio 경계값)
  - abs_floor + 클러스터 조합
  - `_output_results()`에서 cluster_count 계산 정확성

**설정 변경:**
- `assets/memory-config.default.json`에 추가:
```json
"retrieval": {
    ...
    "confidence_abs_floor": 0.0,
    "cluster_detection_enabled": false
}
```

**롤백:**
- 절대 하한선: `confidence_abs_floor: 0.0` 설정으로 비활성화
- 클러스터 감지: `cluster_detection_enabled: false` 설정으로 비활성화 (구성 기반 롤백)

### 진행 상황 (Progress)

- [ ] `confidence_label()` 시그니처 확장 (`abs_floor`, `cluster_count` 파라미터 추가)
- [ ] 절대 하한선 로직 구현: `abs(best_score) < abs_floor`이면 최대 "medium"
- [ ] 클러스터 감지 로직 구현: `cluster_count >= 3`이면 최대 "medium"
- [ ] `_output_results()`에서 `raw_bm25` 기반으로 cluster_count 계산 + `abs_floor` 전달 (V2 수정: `entry.get("raw_bm25", entry.get("score", 0))` 사용)
- [ ] `confidence_label()` 호출 시 `raw_bm25` 값 전달 (변이된 `score` 아님)
- [ ] `main()`에서 `retrieval.confidence_abs_floor` 설정 파싱 추가
- [ ] `assets/memory-config.default.json`에 `confidence_abs_floor`, `cluster_detection_enabled` 추가
- [ ] `main()`에서 `retrieval.cluster_detection_enabled` 설정 파싱 추가
- [ ] 단위 테스트: 절대 하한선 경계값 (~8개)
- [ ] 단위 테스트: 클러스터 감지 (~5개)
- [ ] 단위 테스트: 조합 시나리오 (~3개)
- [ ] 기존 `TestConfidenceLabel` 17개 회귀 테스트 통과 확인
- [ ] `python3 -m py_compile hooks/scripts/memory_retrieve.py` 통과
- [ ] `pytest tests/test_memory_retrieve.py -v` 전체 통과

---

## Action #2: 축약 주입 (Tiered Output)

### 목적 (Purpose)

신뢰도 수준에 따라 주입 형식을 차별화하여 정보 위계를 구현한다:
- **HIGH**: 현행 `<result>` 형식 유지 (전체 주입)
- **MEDIUM**: 새로운 `<memory-compact>` 형식 (제목+경로+태그 + 검색 유도 문구)
- **LOW**: 침묵 (주입 없음, 배너 맹시 방지)

### 관련 정보 (Related Info)

**현재 코드** (`hooks/scripts/memory_retrieve.py:262-301`):
```python
def _output_results(top: list[dict], category_descriptions: dict[str, str]) -> None:
    # ... (설명 속성 구성)
    best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)
    print(f"<memory-context source=\".claude/memory/\"{desc_attr}>")
    for entry in top:
        # ... (sanitize, tags, path)
        conf = confidence_label(entry.get("score", 0), best_score)
        print(f'<result category="{cat}" confidence="{conf}">{safe_title} -> {safe_path}{tags_str}</result>')
    print("</memory-context>")
```

**토큰 절약에 대한 정직한 평가:**
현재 출력 형식은 이미 상대적으로 간결하다 (제목+경로+태그만 포함, 본문 미포함). "축약"이라는 표현은 기존의 `<result>` 형식과 새로운 `<memory-compact>` 형식 간의 차이를 의미하는 것이 아니라, **정보 위계 도입**이 핵심 가치:
1. LOW 결과 침묵 -> 노이즈 제거 (가장 큰 실질적 절약)
2. MEDIUM 결과에 검색 유도 -> 불확실한 매칭에 대한 행동 경로 제공
3. HIGH 결과만 "신뢰할 수 있는 컨텍스트"로 명확히 구분

**설정 키:**
- `retrieval.output_mode` = `"legacy"` (기본값) / `"tiered"`
- **기본값을 `"legacy"`로 설정하는 이유**: "tiered" 모드는 LOW 결과를 침묵시키므로, 현재 모든 결과를 보는 데 의존하는 사용자에게 예기치 않은 동작 변경. `"legacy"` 기본값으로 하위 호환성 보장, 로깅 인프라 구축 후 데이터 기반으로 기본값 전환 검토.
- **외부 모델 합의**: Codex, Gemini 모두 `"legacy"` 기본값 권장

**보안 요구사항 (V1-robustness):**
- `<memory-compact>` 형식에도 XML 구조 wrapper 필수 유지 (`category`, `confidence` 속성은 시스템 제어)
- 모든 사용자 컨텐츠(제목, 경로, 태그)에 기존 `_sanitize_title()` + XML 이스케이프 적용
- 태그는 compact 모드에서도 보존 (V2-fresh: 태그 없으면 Claude가 관련성 판단 어려움)

**출력 형식 설계:**

```xml
<!-- legacy 모드: 현행과 동일 -->
<result category="DECISION" confidence="high">JWT Auth -> .claude/memory/decisions/jwt.json #tags:auth,jwt</result>

<!-- tiered 모드: HIGH -->
<result category="DECISION" confidence="high">JWT Auth -> .claude/memory/decisions/jwt.json #tags:auth,jwt</result>

<!-- tiered 모드: MEDIUM -->
<memory-compact category="DECISION" confidence="medium">JWT Auth -> .claude/memory/decisions/jwt.json #tags:auth,jwt</memory-compact>

<!-- tiered 모드: LOW -- 출력 없음 (침묵) -->
```

MEDIUM 결과 그룹 뒤에 검색 유도 문구:
```xml
<memory-note>Some results had medium confidence. Use /memory:search &lt;topic&gt; for detailed lookup.</memory-note>
```

**"모든 결과가 LOW"인 경우:**
Action #3의 all-low-confidence hint가 이 경로를 처리.

**테스트 영향:**
- `test_confidence_label_in_output` (line 618): `confidence="low"` 가 `<result>` 내에 존재하는지 assert -> tiered 모드에서 LOW 결과 침묵되므로 수정 필요
- `test_no_score_defaults_low` (line 649): LOW confidence 결과 존재 assert -> tiered 모드 분기 필요
- `test_result_element_format` (line 658): `<result ...>` 패턴 assert -> 여전히 유효 (HIGH에만 적용)
- `test_output_results_captures_all_paths` (`test_v2_adversarial_fts5.py:1063`): `<result>` 형식 assert -> tiered 모드 분기 필요
- `test_output_results_description_injection` (`test_v2_adversarial_fts5.py:1079`): output 형식 assert -> tiered 모드 분기 필요
- **기존 테스트는 legacy 모드에서 모두 통과해야 함** (output_mode 미지정 = legacy)
- **신규 테스트 필요**: ~15-30개
  - tiered 모드: HIGH/MEDIUM/LOW 각각의 출력 확인
  - tiered 모드: mixed confidence (HIGH+MEDIUM+LOW) 출력
  - tiered 모드: all-MEDIUM 출력 + 검색 유도 문구
  - tiered 모드: all-LOW 출력 (hint만 발생)
  - legacy 모드: 현행과 동일 출력 (회귀 테스트)
  - compact 형식의 XML 구조 wrapper 보안 테스트
  - compact 형식의 태그 보존 확인
  - XML 이스케이프 정확성 (compact 형식)

**설정 변경:**
```json
"retrieval": {
    ...
    "output_mode": "legacy"
}
```

**함수 시그니처 변경:**
```python
def _output_results(top: list[dict], category_descriptions: dict[str, str],
                    output_mode: str = "legacy",
                    abs_floor: float = 0.0) -> None:
```

**롤백:** `output_mode: "legacy"` 설정으로 현행 동작 복원.

### 진행 상황 (Progress)

- [ ] `_output_results()` 시그니처에 `output_mode`, `abs_floor` 파라미터 추가
- [ ] `_output_results()` 내부에서 cluster_count 계산 로직 구현
- [ ] legacy 모드: 현행 코드 그대로 실행 (output_mode guard)
- [ ] tiered 모드: HIGH 결과 -> `<result>` 형식 (현행)
- [ ] tiered 모드: MEDIUM 결과 -> `<memory-compact>` 형식 (제목+경로+태그)
- [ ] tiered 모드: LOW 결과 -> 침묵 (출력 없음)
- [ ] tiered 모드: MEDIUM 결과 존재 시 검색 유도 `<memory-note>` 추가
- [ ] `main()`에서 `retrieval.output_mode` 설정 파싱 + `_output_results()` 호출 시 전달
- [ ] `assets/memory-config.default.json`에 `output_mode` 추가
- [ ] 기존 테스트: legacy 모드 회귀 테스트 전체 통과 확인
- [ ] 신규 테스트: tiered 모드 HIGH/MEDIUM/LOW 출력 (~6개)
- [ ] 신규 테스트: compact 형식 보안 (XML wrapper, 이스케이프) (~4개)
- [ ] 신규 테스트: compact 형식 태그 보존 (~2개)
- [ ] 신규 테스트: 검색 유도 문구 발생 조건 (~3개)
- [ ] `python3 -m py_compile hooks/scripts/memory_retrieve.py` 통과
- [ ] `pytest tests/ -v` 전체 통과

---

## Action #3: Hint 개선

### 목적 (Purpose)

0-result hint 형식을 HTML 주석에서 XML 태그로 변경하여 Claude의 인식률을 높이고, all-low-confidence 상황에 대한 새로운 hint를 추가한다.

### 관련 정보 (Related Info)

**현재 hint 위치 3곳** (종합 보고서에서는 2곳으로 잘못 기재, V1-practical이 3곳 확인):

1. **Line 458** -- FTS5 경로, 유효 쿼리이나 결과 없음:
```python
print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
```

2. **Line 495** -- Legacy 경로, 점수 매긴 엔트리 없음:
```python
print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
```

3. **Line 560** -- Legacy 경로, deep check 후 결과 없음:
```python
print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
```

**변경 내용:**

1. `<!-- ... -->` -> `<memory-note>...</memory-note>` (3곳 모두)
2. **신규**: all-low-confidence hint -- 결과가 존재하지만 tiered 모드에서 전부 LOW로 침묵된 경우:
```xml
<memory-note>Memories exist but confidence was low. Use /memory:search <topic> for detailed lookup.</memory-note>
```
3. **헬퍼 함수 추출**: hint 발생 로직을 함수로 통합 (DRY, Action #2에서도 사용)
```python
def _emit_search_hint(reason: str = "no_match") -> None:
    """Emit a search hint as XML note."""
    if reason == "all_low":
        print("<memory-note>Memories exist but confidence was low. "
              "Use /memory:search &lt;topic&gt; for detailed lookup.</memory-note>")
    else:
        print("<memory-note>No matching memories found. "
              "If project context is needed, use /memory:search &lt;topic&gt;</memory-note>")
```

**보안 확인 (V1-robustness):**
- hint 텍스트는 하드코딩됨 -- 사용자 제어 데이터 미포함
- `<memory-note>` 태그 이름이 사용자 프롬프트의 `</memory-note>`와 충돌 시: 서로 다른 컨텍스트 세그먼트에서 처리되므로 구조적 간섭 없음
- V1-robustness의 네임스페이스 제안 (`<claude-memory-note>`)은 nice-to-have이나 보안상 불필요

**테스트 영향:**
- 기존 테스트 중 HTML 주석 문자열을 assert하는 테스트 없음 -> **기존 테스트 파손 0건**
- **신규 테스트 필요**: ~5-8개
  - `_emit_search_hint("no_match")` 출력 확인
  - `_emit_search_hint("all_low")` 출력 확인
  - 3곳의 hint 발생 경로에서 `<memory-note>` 형식 확인 (통합 테스트)
  - tiered 모드 all-LOW 시 hint 발생 확인
  - hint 내용에 사용자 데이터 미포함 확인

### 진행 상황 (Progress)

- [ ] `_emit_search_hint()` 헬퍼 함수 구현
- [ ] Line 458 hint를 `_emit_search_hint()` 호출로 교체
- [ ] Line 495 hint를 `_emit_search_hint()` 호출로 교체
- [ ] Line 560 hint를 `_emit_search_hint()` 호출로 교체
- [ ] tiered 모드 `_output_results()`에서 all-LOW 결과 시 `_emit_search_hint("all_low")` 호출
- [ ] 단위 테스트: `_emit_search_hint()` 출력 형식 (~3개)
- [ ] 통합 테스트: 3개 경로의 hint 발생 확인 (~3개)
- [ ] `python3 -m py_compile hooks/scripts/memory_retrieve.py` 통과
- [ ] `pytest tests/ -v` 전체 통과

---

## Action #4: Agent Hook PoC

### 목적 (Purpose)

`type: "agent"` hook이 UserPromptSubmit에서 실제로 어떻게 동작하는지 실험하여, 향후 아키텍처 결정을 위한 데이터를 수집한다.

### 관련 정보 (Related Info)

**배경 (V2-adversarial 발견):**
Claude Code는 3가지 hook type을 지원:
| Type | 기능 | 기본 타임아웃 |
|------|------|--------------|
| `command` | Shell 서브프로세스, stdin/stdout JSON | 600s |
| `prompt` | 단일 턴 LLM 평가, yes/no 결정 | 30s |
| `agent` | **다중 턴 서브에이전트, Read/Grep/Glob/Bash 사용 가능, 최대 50턴** | 60s |

**결정적 차이 -- 출력 메커니즘:**
- `command` hook: stdout 텍스트 -> Claude 컨텍스트에 자동 주입. **현재 메모리 검색 방식.**
- `agent` hook: `{ "ok": true/false, "reason": "..." }` 반환 -> 허용/차단 결정. **컨텍스트 주입이 아닌 게이트키핑.**

**핵심 질문 (PoC로 답해야 할 것):**
1. Agent hook의 실제 레이턴시는? (60s 기본 타임아웃이지만 실행 시간은?)
2. Agent hook이 `{ "ok": true }` 반환 외에 컨텍스트를 주입할 수 있는 메커니즘이 있는가?
3. Plugin의 `hooks/hooks.json`에서 `type: "agent"` hook이 정상 동작하는가?
4. 하이브리드 접근 가능성: command hook (주입) + agent hook (판단)을 연쇄 실행할 수 있는가?

**참조:** `temp/agent-hook-verification.md` -- 독립 검증 결과

**중요: 별도 브랜치 필수** (`feat/agent-hook-poc`)
- 실험 코드가 메인 프로덕션 경로에 유입되지 않도록 격리
- PoC 결과에 따라 아키텍처 재평가 (메인 브랜치에 반영 결정은 별도)

**Agent hook이 "작동"한다고 해도:**
메모리 검색 결과의 컨텍스트 주입에는 여전히 command hook의 stdout 메커니즘이 필요. Agent hook은 보완적 역할(판단/필터링)로 활용 가능하되, command hook을 대체하지는 않음.

### 진행 상황 (Progress)

- [ ] `feat/agent-hook-poc` 브랜치 생성
- [ ] 최소 agent hook 구성: `hooks/hooks.json`에 agent 타입 UserPromptSubmit hook 추가
- [ ] Agent hook 프롬프트 작성: BM25 검색 실행 -> JSON 파일 읽기 -> ok/false 반환
- [ ] 레이턴시 측정: 5-10회 실행의 평균/p95 시간 기록
- [ ] 출력 메커니즘 테스트: ok=true 시 Claude 컨텍스트에 무엇이 전달되는지 확인
- [ ] ok=false + reason 시 Claude에게 어떤 메시지가 보이는지 확인
- [ ] Plugin 호환성 테스트: `hooks/hooks.json`에서 agent 타입이 정상 로드되는지 확인
- [ ] 결과 문서화: `temp/agent-hook-poc-results.md`에 실험 결과 기록
- [ ] 브랜치 머지 여부 결정 (PoC 결과에 따라 -- 이 단계는 별도 의사결정)

---

## 횡단 관심사 (Cross-Cutting Concerns)

### 구현 순서

```
Action #1 ──→ Action #2 ──→ Action #3
(confidence)   (tiered)     (hints)
                                        Action #4 (별도 브랜치, 독립)
```

**순서의 근거:**
1. Action #1이 먼저 -- confidence 의미론을 정의해야 Action #2의 tiering 로직이 정확하게 동작
2. Action #2가 다음 -- 새로운 출력 경로(compact, silence)가 추가되면 hint 발생 지점도 변경됨
3. Action #3이 마지막 -- #2에서 추가된 all-LOW 경로의 hint도 함께 처리
4. Action #4는 독립 -- 별도 브랜치에서 메인 개발과 병행 가능

### 롤백 전략

| Action | 롤백 방법 | 설정 키 |
|--------|----------|---------|
| #1 절대 하한선 | `confidence_abs_floor: 0.0` | `retrieval.confidence_abs_floor` |
| #1 클러스터 감지 | `cluster_detection_enabled: false` | `retrieval.cluster_detection_enabled` |
| #2 계층적 출력 | `output_mode: "legacy"` | `retrieval.output_mode` |
| #3 hint 형식 | 코드 리버트 (매우 저위험이므로 설정 불필요) | N/A |
| #4 Agent Hook PoC | 브랜치 삭제 | N/A |

**롤백 총 3건의 설정 변경** (`confidence_abs_floor` + `cluster_detection_enabled` + `output_mode`). 종합 보고서의 "1건" 주장은 수정됨 (V1-practical 지적). 리뷰 반영으로 클러스터 감지도 설정 기반 롤백 가능.

### 영향받는 파일 요약

| 파일 | 변경 내용 | Actions |
|------|----------|---------|
| `hooks/scripts/memory_retrieve.py` | confidence_label 확장, _output_results 분기, hint 헬퍼 | #1, #2, #3 |
| `assets/memory-config.default.json` | `confidence_abs_floor`, `output_mode` 추가 | #1, #2 |
| `tests/test_memory_retrieve.py` | 기존 테스트 수정 + 신규 테스트 | #1, #2, #3 |
| `tests/test_v2_adversarial_fts5.py` | tiered 모드 분기 추가 (2개 테스트) | #2 |
| `hooks/hooks.json` | agent hook 추가 (PoC 브랜치에서만) | #4 |

### 변경하지 않는 파일

| 파일 | 이유 |
|------|------|
| `hooks/scripts/memory_search_engine.py` | `apply_threshold()`는 수정 불필요 -- 독립적 선택 임계치 |
| `hooks/scripts/memory_judge.py` | judge 로직 변경 없음 |
| `skills/memory-search/SKILL.md` | CLI 검색 출력 형식 미변경 -- auto-inject 출력만 변경 |
| `CLAUDE.md` | 구조적 변경 아님 -- 구현 완료 후 Key Files 테이블 업데이트만 |

### 검증 게이트

각 Action 완료 후 다음 Action 시작 전 확인:

1. **Gate A** (Action #1 후): confidence 테스트 전체 통과, 기존 XML 출력 테스트 회귀 없음
2. **Gate B** (Action #2 후): tiered 모드 smoke test (HIGH/MEDIUM/LOW 매트릭스) + legacy 호환성 테스트
3. **Gate C** (Action #3 후): End-to-end UserPromptSubmit 실행으로 wrapper 무결성 + hint 동작 확인
4. **Gate D** (기본값 전환 전): 20-30개 대표 프롬프트에 대한 수동 검토 (로깅 인프라 구축 후)

### 총 변경량 추정

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

## 외부 검토 의견 요약

| 주제 | Codex (Planner) | Gemini (Planner) |
|------|-----------------|------------------|
| 클러스터 감지 | Always-on 권장, 설정 복잡도 줄임 | Config toggle 권장 (`cluster_cap_enabled`) |
| output_mode 기본값 | `"legacy"` 권장 (첫 릴리스 안전) | `"legacy"` 권장 (하위 호환성) |
| 계획 구조 | 건전, 검증 게이트 추가 권장 | 건전, XML 무결성 테스트 강조 |
| 주요 위험 | BM25 floor 오보정, 출력 형식 회귀 | 밀접 관련 메모리의 오탈락, 컨텍스트 기아 |

**합의 사항:** output_mode 기본값 "legacy", 순차 구현 순서, Action #4 격리
**리뷰 반영 합의 (2차):** 클러스터 감지 설정 토글 추가 (`cluster_detection_enabled`, default: `true`). abs_floor 코퍼스 의존성 경고 추가. cluster_count 의미론 문서화.
