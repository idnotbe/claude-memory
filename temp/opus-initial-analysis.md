# Opus 4.6 Initial Analysis

## Key Findings from Claude Code Guide

1. **Stop hook "reason" is ALWAYS displayed** — no hidden data channel
2. **SessionEnd hook EXISTS** — with matchers: clear, logout, prompt_input_exit, bypass_permissions_disabled, other
3. **Background agents are context-isolated** — their internal work does NOT consume main context tokens
4. **Subagent results are compact** — only the final summary goes into main context, not the full transcript
5. **Auto-compact triggers at ~83.5% of 200K** (~167K tokens)
6. **Each subagent starts with ~20K token overhead** — expensive but isolated
7. **PreCompact hook exists** — fires before compaction (matcher: manual or auto)

## Preliminary Solution Candidates

### A. Single Background Save Agent
- Stop hook returns minimal reason: "Saving memories (1 category)..."
- Main agent spawns ONE background Task agent with the ENTIRE save pipeline
- Background agent handles all 4 phases internally
- Main agent gets only a short result: "Saved: <title>"
- **Pro**: Minimal main context impact, all noise hidden
- **Con**: Background agent still costs ~20K base tokens + save work; still need to block stop

### B. Minimal Stop + SessionEnd
- Stop hook returns even shorter message
- Save work happens in SessionEnd hook as a command-type hook
- **Pro**: Zero LLM context consumption, truly invisible
- **Con**: SessionEnd can't run LLM operations (no drafting), limited to deterministic saves

### C. Hybrid: Pre-compute in Python + Minimal LLM
- Move MORE work into memory_triage.py (deterministic Python):
  - Auto-run memory_candidate.py
  - Auto-generate draft from templates (no LLM needed for simple cases)
  - Write draft files during stop hook execution
- Stop hook only blocks if LLM judgment is actually needed
- If drafts are pre-computed, save phase is just: verify + write (2 Bash calls)
- **Pro**: Dramatically reduces LLM-driven phases, most saves become near-silent
- **Con**: Lower draft quality for complex categories (decisions, constraints)

### D. External Process Architecture
- Stop hook spawns a detached Python process
- Process calls Anthropic API directly for drafting
- Process writes results to files
- Next session picks up the saved memories
- **Pro**: Completely invisible to user
- **Con**: Requires API key management, external dependency, delayed saves

## My Initial Ranking
1. **A (Background Save Agent)** — most practical, works within existing Claude Code features
2. **C (Hybrid pre-compute)** — best long-term, reduces both noise AND cost
3. **B (SessionEnd)** — good for simple cases but limited
4. **D (External process)** — too complex, fragile

## Questions for Cross-Validation
- Can a background Task agent actually handle the full save pipeline reliably?
- Does blocking stop + spawning background task work correctly together?
- Is the 20K token overhead per subagent acceptable given we're replacing 50-100+ lines of visible output?
- Could approach C handle all 6 categories with acceptable quality?
