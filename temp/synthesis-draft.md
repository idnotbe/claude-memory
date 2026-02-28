# Synthesis Draft: Converging Findings

## Cross-Source Agreement Matrix

| Finding | Opus Analysis | Background-Agent Researcher | Alt-Arch Researcher | Gemini 3.1 Pro |
|---------|:---:|:---:|:---:|:---:|
| Stop hook reason always displayed | Y | Y | Y | Y |
| Background agents DON'T hide output | - | **Y (strong)** | Y | N (assumed they do) |
| Subagent context isolation broken | - | **Y (bugs cited)** | Partial | N (assumed working) |
| SessionEnd exists but limited | Y | - | **Y (detailed)** | Y |
| Move work out of LLM tool loop | - | **Y (primary rec)** | **Y (primary rec)** | Y (C approach) |
| Agent hook type worth investigating | - | - | **Y (dark horse)** | - |
| suppressOutput doesn't solve core issue | - | - | **Y** | - |
| Hybrid A+C is best | Y | Similar | Similar | **Y (strong)** |

## Key Disagreements

### 1. Background Agent Context Isolation
- **Background-Agent Researcher**: Claims bugs #14118, #18351 cause transcript leakage, agents NOT isolated
- **Claude-Code Guide**: Says agents ARE context-isolated, only final summary returns
- **Assessment**: The bugs may be real but could also be hallucinated issue numbers. The Claude Code guide's information comes from official docs. Need to verify empirically. However, even IF background agents ARE isolated, the researcher's Option A (hook-driven silent save) is STILL better because it avoids ANY LLM tool loop.

### 2. External API Call Feasibility
- **Alt-Arch Researcher**: Strongly recommends inline API call from Stop hook (Alt 4)
- **Opus Analysis**: Didn't consider this approach
- **Assessment**: This is a genuinely new and strong approach. The Stop hook already runs Python with full stdlib access. Adding a urllib-based API call is straightforward. BUT: requires ANTHROPIC_API_KEY in environment, and hook timeout (30s) may be tight.

## Emerging Consensus: 3-Tier Architecture

### Tier 1: Minimal-Change Quick Win (SKILL.md optimization)
- Externalize triage_data to file (not inline in reason)
- Consolidate Phase 3 into single subagent
- Reduce visible steps from 50-100 to ~15-20 lines
- **Effort: Low | Noise reduction: ~60%**

### Tier 2: Agent Hook Investigation (medium-term)
- Test if `type: "agent"` Stop hooks have isolated subagent transcripts
- If yes: this is the ideal solution — full LLM quality + zero noise
- If no: proceed to Tier 3
- **Effort: Medium | Noise reduction: potentially 100%**

### Tier 3: Inline API Save (long-term / fallback)
- Move entire save pipeline into Stop hook Python script
- Call Claude API directly via urllib for drafting
- Run memory_write.py as Python import (not subprocess)
- Hook returns minimal message or allows stop silently
- **Effort: High | Noise reduction: ~100%**

## Critical Open Questions

1. **Agent hook isolation**: Does `type: "agent"` Stop hook produce visible output in the main conversation? (Tier 2 viability)
2. **Background agent bugs**: Are #14118 and #18351 real issues in current Claude Code? (Approach A viability)
3. **Hook timeout**: Can the 30s Stop hook timeout handle full API call + save? (Tier 3 viability)
4. **API key availability**: Is ANTHROPIC_API_KEY reliably available in hook environments? (Tier 3 requirement)
