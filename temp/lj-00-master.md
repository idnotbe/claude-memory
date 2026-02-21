# LLM-as-Judge Design: Master Coordination

**Team:** llm-judge-design
**Goal:** Add LLM-as-judge subagent filtering layer to achieve ~100% precision before memory injection into Claude Code's context window.

## Core Problem

rd-08-final-plan.md's FTS5 BM25 engine achieves ~65-75% auto-inject precision. Anything less than ~100% means irrelevant memories pollute Claude Code's context window, causing:
- Wasted context window tokens
- Claude confusion from irrelevant information
- Worse-than-no-injection outcomes (polluted reasoning)

## User's Key Requirements

1. **LLM-as-judge** via subagent to verify each retrieved memory is truly relevant BEFORE injection
2. **Independent of main conversation** -- subagent runs separately to preserve main context window
3. **Configurable model** -- haiku (default), sonnet, or opus via config
4. **Check twice independently** -- dual independent verification for reliability
5. **Auto-inject: strict** -- only inject if definitely relevant (100% precision goal)
6. **On-demand search: lenient** -- more results, still accurate but not as strict
7. The subagent uses Claude Code's Task tool infrastructure

## Prior Research References

- `research/retrieval-improvement/06-analysis-relevance-precision.md` -- identified LLM-as-judge concept, noted "Claude Code itself IS an LLM"
- `research/claude-mem-comparison/phase1-comparator-output.md` -- parallel subagent orchestration with haiku/sonnet/opus tiers
- `research/retrieval-improvement/01-research-claude-mem-retrieval.md` -- progressive disclosure pattern
- `research/retrieval-improvement/02-research-claude-mem-rationale.md` -- token economics, skill vs MCP
- `research/rd-08-final-plan.md` -- current plan to update (FTS5 BM25 engine)

## Architecture Context

Current retrieval flow (from rd-08):
```
UserPromptSubmit hook -> memory_retrieve.py -> FTS5 BM25 -> Top-K -> <memory-context> output
```

Proposed flow with LLM-as-judge:
```
UserPromptSubmit hook -> memory_retrieve.py -> FTS5 BM25 -> Top-K candidates
  -> Subagent (haiku) verifies each candidate against current context
  -> Only verified-relevant memories -> <memory-context> output
```

## Key Design Questions

1. **How does the subagent access current conversation context?** (transcript_path? user_prompt only?)
2. **What is the subagent's judgment criteria?** (prompt template, structured output)
3. **Latency budget?** UserPromptSubmit hooks have tight timing. Can subagent fit?
4. **Cost per invocation?** haiku API call per prompt submission adds up
5. **Dual verification implementation?** Two independent subagents? Or two passes?
6. **Fallback if subagent fails?** (timeout, API error, etc.)
7. **How does this work for on-demand search?** Different threshold/prompt?
8. **Alternative approaches?** Re-ranking without full LLM call? Lightweight classifier?

## Team Structure

### Phase 1: Design & Analysis
- **architect**: Design the subagent LLM-as-judge system, code architecture, alternatives
- **skeptic**: Challenge approach, find flaws, latency/cost/feasibility concerns
- **pragmatist**: Implementation feasibility, hook constraints, benchmark estimates

### Phase 2: Consolidation (lead)

### Verification R1: 2 verifiers
### Verification R2: 2 verifiers

## File Index

| File | Content | Author |
|------|---------|--------|
| `temp/lj-00-master.md` | This master coordination file | lead |
| `temp/lj-01-architect.md` | Architecture proposal | architect |
| `temp/lj-02-skeptic.md` | Adversarial review | skeptic |
| `temp/lj-03-pragmatist.md` | Feasibility analysis | pragmatist |
| `temp/lj-04-consolidated.md` | Consolidated design | lead |
| `temp/lj-05-verify1-*.md` | Verification R1 | verifiers |
| `temp/lj-06-verify2-*.md` | Verification R2 | verifiers |
