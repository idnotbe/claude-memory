# Consolidated Answers to User Questions

**Date:** 2026-02-20
**Sources:** 3 research files + code analysis + vibe check

---

## Q1: cwd가 뭔가?

**cwd = Current Working Directory** (현재 작업 디렉토리)

터미널에서 `/home/user/projects/backend/auth/` 에서 Claude Code를 실행하면, 그 경로가 cwd입니다.

retrieval hook (`memory_retrieve.py:219`)은 hook input에서 `cwd`를 받습니다:
```python
cwd = hook_input.get("cwd", os.getcwd())
```

현재는 memory root를 찾는 데만 사용하고, **scoring에는 사용하지 않습니다.**

Final report에서 제안한 것: 사용자가 `backend/auth/` 에서 작업 중이면 "authentication" 관련 메모리에 가산점을 주자는 것.

---

## Q2: Document Suite Issues가 해결된 것인가?

**아니요, "해결"된 것이 아닙니다.** Final report는 문제점을 **문서화하고 영향을 평가**한 것입니다.

| Issue | Status | 설명 |
|-------|--------|------|
| Cross-Document Inconsistency | **수용 (미수정)** | reviews가 다른 alternative 세트를 분석한 문제. Alt 3, Alt 7은 둘 다 REJECT이므로 추가 리뷰 불필요 |
| Optimistic Bias | **완화 (미해결)** | adversarial/comparative review가 보정 역할. 근본적 해결은 아님 |

더 고칠 필요가 있나? **실질적으로 없습니다.** 누락된 리뷰 대상은 모두 reject 판정이라, 추가 분석의 ROI가 없습니다.

---

## Q3: MCP 대신 agentic skill로 처리 가능하지 않나?

**가능합니다.** 그리고 실제로 skill이 더 적합한 경우가 있습니다.

### 방식 비교

| 방식 | 자동성 | 양방향 | 의존성 | 적합한 용도 |
|------|--------|--------|--------|-------------|
| **Hook** (현재) | 매 턴 자동 | 단방향 (inject만) | 없음 | 확실히 관련있는 정보 자동 주입 |
| **MCP Tool** | Claude가 호출 | 양방향 대화 | 별도 서버 프로세스 | Progressive disclosure, 복잡한 검색 |
| **Agentic Skill** | Claude가 호출 | 양방향 | 없음 (기존 도구 사용) | Interactive 검색, 사용자 명령 |

### claude-mem의 접근: Hook + MCP 하이브리드

claude-mem은 **두 가지를 모두 사용합니다:**
- `SessionStart` hook: 최근 context를 자동 주입 (recency 기반, 벡터 검색 아님)
- MCP tools (`search`, `timeline`, `get_observations`): Claude가 필요할 때 능동적으로 검색

### 추천: Hook + Skill 하이브리드

MCP 서버 없이도 **skill**로 동일한 interactive 검색이 가능합니다:

```
Hook (자동):     높은 확신의 메모리만 주입 (precision 우선)
Skill (수동):    `/memory-search query` — 사용자/Claude가 필요할 때 검색
```

Skill의 장점:
- MCP와 달리 별도 서버 프로세스 불필요
- Claude Code의 기존 tool (Read, Grep 등) 활용 가능
- Claude 자체가 LLM이므로, 검색 결과를 보고 relevance를 직접 판단

---

## Q4: keyword matching의 irrelevant info 삽입 리스크 (CRITICAL)

### 사용자의 우려는 타당합니다

현재 시스템의 false positive 예시:

Prompt: "how to fix the authentication bug"

| Memory | Score | 관련있나? |
|--------|-------|-----------|
| "JWT authentication token refresh" (tags: auth, jwt) | 3점 (authentication=title+2, auth prefix+1) | Maybe |
| "Login page CSS grid layout" | 4점 (login=title+2, page=title+2) | **NO** |
| "Fix database connection pool bug" | 4점 (fix=title+2, bug=title+2) | **NO** |

**현재 precision: ~40% (추정, 미측정).** inject된 메모리 중 상당수가 무관한 정보.

### 왜 이것이 위험한가

1. **Context window 낭비**: 무관한 메모리 × 200-500 tokens = 쓸데없는 소비
2. **Claude 혼란**: 무관한 정보가 Claude의 추론을 방해
3. **신뢰 하락**: 사용자가 무관한 injection을 보면 retrieval을 끔
4. **No injection > Wrong injection**: 잘못된 context는 없는 것보다 나쁨

### 핵심 발견: transcript_path로 대화 context 접근 가능!

**Final report에서 "#1 architectural constraint"으로 꼽은 한계가 실제로는 해결 가능합니다.**

모든 hook은 `transcript_path` 필드를 받습니다. 이를 통해 전체 대화 이력을 읽을 수 있습니다:

```python
# UserPromptSubmit hook에서 대화 context 접근 가능
transcript_path = hook_input["transcript_path"]
with open(transcript_path, 'r') as f:
    messages = [json.loads(line) for line in f if line.strip()]
```

이것은 retrieval 품질을 극적으로 개선할 수 있습니다:
- 단일 prompt가 아닌 대화 전체의 topic을 파악
- "auth bug 수정 중" 이라는 context를 알면 CSS layout 메모리를 제외 가능
- memory_triage.py (Stop hook)는 이미 이 방식으로 transcript를 읽고 있음

### 제안: Precision-First Hybrid Architecture

```
┌─────────────────────────────────────────────┐
│  Tier 1: Conservative Auto-Inject (Hook)    │
│  - 높은 threshold (score >= 4, 현재 1)       │
│  - max_inject = 3 (현재 5 → 줄임)            │
│  - 확실히 관련있는 것만 inject                 │
│  - (향후) transcript_path 대화 context 분석   │
│  → Precision 향상 (구체적 수치는 측정 필요)      │
├─────────────────────────────────────────────┤
│  Tier 2: On-Demand Search (Skill, proposed)  │
│  - /memory-search query                     │
│  - 낮은 threshold (더 많은 결과 제공)          │
│  - Claude가 직접 relevance 판단 (LLM-as-Judge)│
│  - Progressive disclosure 가능               │
│  → Recall 향상 예상 (검증 필요, 미구현)         │
├─────────────────────────────────────────────┤
│  Tier 3: Configuration (on/off)             │
│  - auto_inject.enabled: true/false          │
│  - auto_inject.min_score: 6 (조정 가능)      │
│  - manual_search.enabled: true/false        │
│  → 사용자가 완전히 제어 가능                    │
└─────────────────────────────────────────────┘
```

### 왜 이것이 vector/LLM 없이도 효과적인가

1. **transcript context** → 대화 주제를 알면 keyword matching도 훨씬 정확해짐
2. **높은 threshold** → false positive를 극적으로 줄임 (recall 감소는 Tier 2로 보상)
3. **Tier 2에서 Claude 자체가 LLM-as-Judge** → 외부 API 없이 LLM 판단력 활용
4. **Configuration** → 사용자가 precision/recall 균형을 직접 조정

### Final report 수정 사항

Final report는 다음을 과소평가/누락했습니다:
- `transcript_path`를 통한 대화 context 접근 가능성
- Hook + Skill 하이브리드 아키텍처
- 사용자 입장에서의 false positive 비용

---

## Q5: conversation context 접근 방법

### 방법 1: transcript_path (실용적, 즉시 사용 가능)

모든 hook은 `transcript_path` 필드를 받습니다:

```json
{
  "session_id": "abc123",
  "transcript_path": "/home/user/.claude/projects/.../<session-id>.jsonl",
  "cwd": "/home/user/my-project",
  "prompt": "fix the auth bug"
}
```

> **Note:** The official Claude Code hooks API uses `prompt` as the field name for UserPromptSubmit hooks. The current `memory_retrieve.py` code reads `user_prompt` (line 218), which is a discrepancy -- this may be a pre-existing bug or an undocumented compatibility alias. The `01-research-claude-code-context.md` file correctly identifies the official field as `prompt`.

JSONL 파일에서 대화 이력을 읽을 수 있습니다. 이미 `memory_triage.py`가 이 방식을 사용합니다.

**주의사항:**
- UserPromptSubmit hook의 timeout은 10초 — 큰 transcript 파싱에 주의
- JSONL format은 공식 API가 아님 (내부 형식, 변경 가능)
- 최근 N개 메시지만 읽는 것이 실용적 (전체 파싱 대신)

### 방법 2: OpenTelemetry (모니터링용, 확인됨)

Claude Code는 **네이티브 OpenTelemetry 지원**이 확인되었습니다:

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
```

**8개 metrics + 5개 event types** 지원. 그러나 OTel은 모니터링/분석용이지, retrieval 로직을 구동하기에는 부적합합니다.

### 방법 3: PreCompact hook (보존용)

PreCompact hook은 context compaction 전에 실행되어, 중요한 정보를 보존할 수 있습니다. 현재 claude-memory에서 활용하지 않는 gap입니다.

### 추천: 방법 1 (transcript_path) + 최적화

```python
# 최근 10개 메시지만 읽어서 topic keywords 추출
# 전체 transcript 파싱 대신 tail 접근
import json
from collections import Counter

def extract_recent_topics(transcript_path, n=10):
    """최근 n개 메시지에서 topic keywords 추출."""
    messages = []
    with open(transcript_path) as f:
        for line in f:
            if line.strip():
                messages.append(json.loads(line))

    # 최근 n개만
    recent = messages[-n:]
    text = " ".join(msg.get("content", "") for msg in recent if isinstance(msg.get("content"), str))
    # tokenize and return top keywords
    ...
```

이 approach의 latency: ~5-20ms (파일 크기에 따라). 10초 timeout 내 충분.

---

## Q6: claude-mem의 retrieval 방법

### 한 줄 요약

claude-mem은 **SessionStart hook (자동, recency 기반) + MCP tools (수동, vector 기반)** 의 dual-path 시스템.

### Path A: Passive (Hook, 자동)

- `SessionStart` hook이 세션 시작 시 자동 실행
- SQLite에서 **최근** observations + session summaries를 가져옴
- **벡터 검색 없음** — 순수 recency 기반
- Token economics 계산 (discovery cost vs read cost)
- Progressive context 생성: header + timeline + summary + footer

### Path B: Active (MCP Tools, 수동)

Claude가 필요할 때 MCP tool을 호출:

| Layer | Tool | 내용 | Token |
|-------|------|------|-------|
| 1 | `search(query)` | Compact index (ID, title, date) | ~50-100/결과 |
| 2 | `timeline(anchor)` | 특정 ID 주변 시간순 context | 중간 |
| 3 | `get_observations(ids)` | 선택한 ID의 전체 상세 | ~500-1000/결과 |

검색 엔진: **ChromaDB vector embeddings** (cosine distance)
- 별도 Python subprocess (`uvx chroma-mcp`)
- 로컬 embedding 모델 (all-MiniLM-L6-v2 추정)
- 90일 recency hard cutoff
- **keyword search 없음** (FTS5는 deprecated dead code)

### claude-mem이 사용하지 않는 것

- BM25 / TF-IDF 없음
- Field-level scoring 없음
- Reranking model 없음
- Score fusion (RRF 등) 없음
- Active retrieval path에 keyword search 전혀 없음

### claude-memory와의 핵심 차이

| | claude-mem | claude-memory |
|---|---|---|
| 자동 retrieval | SessionStart (recency) | UserPromptSubmit (keyword) |
| 수동 retrieval | MCP tools (vector) | 없음 |
| 검색 방식 | Vector distance | Keyword matching |
| Progressive disclosure | 3-layer MCP tools | 없음 (single-shot) |
| Dependencies | Bun, ChromaDB, chroma-mcp | stdlib Python only |

---

## Q7: fingerprint tokens, TF, TF-IDF 설명

### Fingerprint tokens

메모리 본문(body)을 대표하는 핵심 단어 10-15개.

현재 index.md 라인: `- [DECISION] JWT auth setup -> path #tags:auth,jwt`
제안: `- [DECISION] JWT auth setup -> path #tags:auth,jwt #body:refresh,token,expiry,middleware`

"body fingerprint"는 본문 전체를 인덱스에 넣을 수 없으니, 가장 중요한 단어만 "지문"처럼 추출하자는 것.

### TF (Term Frequency)

그 문서에서 단어가 몇 번 나오는지.

예: "database"가 본문에 8번 등장 → TF("database") = 8
문제: "the"가 20번 등장 → TF("the") = 20 → 무의미한 단어가 더 높음

### TF-IDF (Term Frequency × Inverse Document Frequency)

TF에 "전체 문서에서 얼마나 드문가" 가중치를 곱한 것.

- "database"가 50개 메모리 중 40개에 등장 → IDF 낮음 → 변별력 없음
- "pydantic"이 50개 중 2개에만 등장 → IDF 높음 → 이 메모리를 구별하는 핵심 단어

**TF-IDF로 fingerprint를 뽑으면**: "database"(흔한 단어) 대신 "pydantic"(드문 단어)이 선택됨 → 검색 시 더 정확한 매칭.

---

## Revised Recommendation Summary

Final report의 Phase 0-1 권고안을 다음과 같이 수정 제안:

### Phase 0: Evaluation Framework (변경 없음, 2시간)
- 20개 테스트 쿼리 + precision@5 / recall@5 측정

### Phase 0.5 (수정됨): Precision-First Hybrid (~12시간)

1. **injection threshold 상향** — min_score를 현재 1 → 4으로 (threshold 분석: 단일 키워드 최대 5점, 6은 대부분 2개 이상 필요)
2. **body tokens 추가** — index.md에 `#body:token1,...` 추가
3. **`/memory-search` skill 생성** — interactive 검색 (Tier 2, 미구현/미검증)
4. **config 추가** — `auto_inject.enabled`, `auto_inject.min_score`
5. **(향후) transcript_path 활용** — UserPromptSubmit hook에서 최근 대화 topic 추출 (제안 단계, 미구현)

### Phase 1 이후: 필요 시 BM25 (변경 없음)

---

## Open Items

1. transcript_path의 JSONL 형식이 stable API가 아님 — 변경 시 hook이 깨질 수 있음
2. transcript 파싱 latency 측정 필요 (10초 timeout 내 안전한지)
3. `/memory-search` skill의 UI/UX 설계 필요
