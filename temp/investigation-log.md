# LLM Judge Implementation Investigation - Consolidated Findings

## Question
Two retrieval paths exist:
1. **UserPromptSubmit hook** - automatic retrieval on user prompt
2. **On-demand search** - Claude Code decides to search for info

## Key Findings (Round 1)

### Path 1: UserPromptSubmit Hook (Auto-Inject)
- **LLM Judge: IMPLEMENTED** (memory_judge.py, called from memory_retrieve.py)
- Judge enabled: `false` by default (opt-in, requires `ANTHROPIC_API_KEY`)
- Model: claude-haiku-4-5-20251001
- Timeout: 3.0 seconds
- Conversation context: Last 5 turns from transcript_path
- Candidate pool: Top 15 from FTS5 BM25 → judge filters → max_inject (default 3)
- Fallback on failure: Conservative top-2 (fallback_top_k)
- Evaluates BOTH relevance AND usefulness (system prompt: "DIRECTLY RELEVANT and would ACTIVELY HELP")

### Path 2: On-Demand Search (/memory:search skill)
- **LLM Judge: IMPLEMENTED** (in SKILL.md orchestration, uses Task subagent)
- Trigger: 2+ results AND judge.enabled == true
- Uses Task subagent (no API key required, unlike Path 1)
- "Lenient" mode - broader recall than auto-inject
- Same judge system prompt (relevance + usefulness)
- Fallback: Show unfiltered results on failure

### Judge Criteria (Shared System Prompt)
Evaluates BOTH:
- **Relevance**: "addresses same topic, technology, or concept"
- **Usefulness**: "would improve response quality", "applies NOW", "specific and direct"

Disqualification:
- Shares keywords but different topic
- Too general or tangential
- Would distract rather than help
- Requires multiple logical leaps

### Key Architectural Differences
| Aspect | Auto-Inject (Path 1) | On-Demand (Path 2) |
|--------|----------------------|---------------------|
| Trigger | Every user prompt | User invokes /memory:search |
| Judge mechanism | Direct API call (urllib) | Task subagent |
| API key required | YES | NO |
| Strictness | Strict | Lenient |
| Max results | 3 (default) | 10 (default) |
| Timeout | 15s hook, 3s judge | ~30s acceptable |
| Failure fallback | Conservative top-K | Show unfiltered |

### Planned But Not Yet Implemented
- S9 was originally "Dual Verification" but CANCELLED (AND-gate recall collapse ~49%)
- S9 revised to: ThreadPoolExecutor utility + qualitative precision evaluation
- Single-judge prompt already handles both relevance + usefulness

## Verification Needed
- [ ] Does SKILL.md actually orchestrate the judge call for on-demand search?
- [ ] Is the on-demand judge using the SAME memory_judge.py or a different prompt?
- [ ] Is there a third path (e.g., Claude Code autonomously searching without user command)?
