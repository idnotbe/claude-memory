# Q&A Working Memory

## Questions from User (2026-02-20)

### Q1: cwd가 뭔가?
**Status:** ANSWERED — Current Working Directory, hook에서 scoring에 사용 제안

### Q2: Document Suite Issues가 해결된 것인가?
**Status:** ANSWERED — 아니오, 문서화/평가만 함. 추가 수정 불필요 (reject 대상이라)

### Q3: MCP 대신 agentic skill로 처리 가능하지 않나?
**Status:** ANSWERED — 가능. Hook + Skill 하이브리드 추천

### Q4: keyword matching의 irrelevant info 삽입 리스크
**Status:** ANSWERED — 사용자 우려 타당. Precision-First Hybrid 아키텍처 제안
**KEY FINDING:** transcript_path로 대화 context 접근 가능 → keyword matching 정밀도 극적 향상 가능

### Q5: conversation context 접근 방법
**Status:** ANSWERED — transcript_path (즉시 가능), OpenTelemetry (확인됨, 모니터링용)

### Q6: claude-mem의 retrieval 방법
**Status:** ANSWERED — Hook (recency) + MCP Tools (vector). Keyword search 없음.

### Q7: fingerprint tokens, TF, TF-IDF
**Status:** ANSWERED — TF-IDF가 fingerprint 선택에 더 적합

---

## Research Tasks Completed
- [x] Claude Code conversation capture / OpenTelemetry → temp/research-claude-code-context.md
- [x] claude-mem retrieval deep dive → temp/research-claude-mem-retrieval.md

## Output Files
- temp/qa-consolidated-answers.md — 전체 답변 종합
- temp/analysis-relevance-precision.md — Q4 심층 분석
- temp/research-claude-code-context.md — Claude Code context 접근 리서치
- temp/research-claude-mem-retrieval.md — claude-mem retrieval 상세 리서치
