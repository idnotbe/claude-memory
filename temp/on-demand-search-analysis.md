# On-Demand Search 현황 분석

## 질문
1. rd-08-final-plan.md에 on-demand search 계획이 포함되어 있는가?
2. 이미 구현되어 있는가?
3. claude-mem과의 비교 (MCP vs Skill+Script)

## 조사 결과

### 1. 계획 포함 여부: YES
- Phase 2b (Session 3)에서 계획됨 -- rd-08 line 1092-1103
- **이미 COMPLETE** (2026-02-21)
- Session 8 (Phase 3c)에서 Task subagent judge 추가 예정 (NEXT)

### 2. 구현 상태: FULLY IMPLEMENTED
- **Skill**: skills/memory-search/SKILL.md (159 LOC)
- **Command**: commands/memory-search.md (48 LOC)
- **Engine**: hooks/scripts/memory_search_engine.py (499 LOC) -- FTS5 BM25
- **Plugin registration**: plugin.json에 등록 완료

### 3. 아키텍처 결정: Skill + Python Script (not MCP)

**핵심 근거** (rd-08 line 137-138):
> "On-Demand Search: Skill (not MCP) -- Unchanged from consolidated plan. No daemons = no MCP."

**"No daemons = no MCP" 철학:**
- claude-mem은 MCP daemon 기반 → 52GB RAM 누수, 프로세스 증식 문제 경험
- claude-memory는 stdlib-only 제약 → MCP 서버 비현실적
- Skill이 Python 스크립트를 Bash로 호출 → 결정론적, 정형적

### 4. 실행 흐름 (현재 구현)
```
User: /memory:search "authentication"
  → Skill activates (SKILL.md 지시)
  → Agent calls: python3 memory_search_engine.py --query "auth" --root .claude/memory --mode search
  → FTS5 BM25 검색 (title, tags, body)
  → Top-10 JSON 결과 반환
  → Agent가 결과를 사용자에게 정리하여 보여줌
```

### 5. 결정론성 분석
- ✅ FTS5 BM25: SQLite 내장, 완전 결정론적
- ✅ Tokenization: regex 기반 (`[a-z0-9][a-z0-9_.\-]*[a-z0-9]`)
- ✅ Scoring: title(2pts), tag(3pts), prefix(1pt), recency(+1)
- ✅ SQL injection 방지: parameterized queries, whitelist-only tokens
- ⚠️ LLM judge (optional): 비결정론적이지만 기본값 off

### 6. Session 8에서 추가될 것
- Task subagent judge (lenient mode): "Which are RELATED? Be inclusive."
- 전체 대화 컨텍스트 접근 가능
- BM25 결과를 LLM이 한번 더 필터링
- 실패 시 unfiltered BM25 결과 그대로 반환

### 7. Auto-inject vs On-demand 비교

| 측면 | Auto-inject (Hook) | On-demand (Skill) |
|------|-------------------|-------------------|
| 트리거 | 매 프롬프트 자동 | /memory:search 명시적 |
| 실행 모델 | Python subprocess | Agent 대화 내 |
| 검색 범위 | title + tags only | title + tags + body |
| 결과 수 | top 3 (max_inject) | top 10 |
| Judge | urllib API 직접호출 (strict) | Task subagent (lenient) [S8 예정] |
| 레이턴시 | <15초 | ~30초 허용 |

## 출처
- rd-08-final-plan.md: lines 14, 135, 137-138, 469-490, 1092-1103, 1309
- temp/lj-04-consolidated.md: lines 13-17, 52-73, 75-84
- research/retrieval-improvement/02-research-claude-mem-rationale.md: lines 186-225
- research/claude-mem-comparison/final-analysis-report.md: RAM leak 관련
