# Team Briefing: Memory Retrieval Architecture Redesign Analysis

## Background

The claude-memory plugin has two memory retrieval paths:
1. **UserPromptSubmit Hook (auto-inject)**: Fires on every user prompt, runs FTS5 BM25 search, optionally filters via LLM judge (direct Anthropic API call, requires ANTHROPIC_API_KEY, disabled by default)
2. **`/memory:search` skill (on-demand)**: User explicitly invokes, runs FTS5 search, optionally filters via Task subagent judge (no API key needed, disabled by default)

There is NO third path where Claude Code autonomously decides to search memories.

## Key Files for Reference

| File | Purpose |
|------|---------|
| `hooks/scripts/memory_retrieve.py` | UserPromptSubmit hook implementation |
| `hooks/scripts/memory_judge.py` | LLM judge module (direct API call) |
| `hooks/scripts/memory_search_engine.py` | FTS5 search engine |
| `skills/memory-search/SKILL.md` | On-demand search skill with subagent judge |
| `research/rd-08-final-plan.md` | Design research document |
| `hooks/hooks.json` | Hook registrations |
| `.claude-plugin/plugin.json` | Plugin manifest |
| `assets/memory-config.default.json` | Default configuration |
| `temp/final-analysis.md` | Previous analysis findings |

## Design Questions to Analyze

### Q1: Can Claude Code be made to autonomously search memories?
- Option A: Add instruction in SKILL.md/CLAUDE.md telling Claude to use `/memory:search` when it needs info
- Option B: Have the hook run the search engine script directly and let Claude decide to use results
- What are the technical constraints? (hooks run as subprocesses, can't access Task tool)

### Q2: Is the on-demand judge intentionally run in a subagent to save main context window?
- SKILL.md instructs spawning a Task subagent (Explore/haiku) for judge
- Is this a deliberate context-window optimization?
- What would be the cost of running the judge in main context?

### Q3: Can the UserPromptSubmit hook use Claude's own LLM instead of separate API?
- Hook scripts run as standalone Python subprocesses — they CANNOT access Claude Code's Task tool
- But the hook OUTPUT is text injected into Claude's context
- Alternative: Hook just reminds Claude of the search skill, doesn't do full retrieval
- Alternative: Hook only injects recency info (recent session summaries), delegates relevance search to Claude's initiative

### Q4: If Claude Code (via subagent) IS the judge, do we need pre-defined judge criteria?
- Currently: Strict system prompt with qualification/disqualification rules
- If Claude is the judge, it already understands relevance and usefulness
- But: Without criteria, judge behavior becomes unpredictable across models/versions
- But: Claude already understands context deeply — pre-set criteria may be restrictive

### Q5: What is the optimal architecture?
Given all the above, what's the best retrieval architecture that:
- Minimizes cost (no separate API calls if possible)
- Maximizes quality (relevance + usefulness + context-awareness)
- Preserves context window (don't pollute main agent context)
- Is simple to implement and maintain
- Handles the "Claude autonomously needs info" case

## Constraints & Context
- Hook scripts (type: "command") run as standalone Python subprocesses
- Hooks CANNOT access Claude Code's Task tool or spawn subagents
- Hook output (stdout) is injected into Claude's context as text
- Skills CAN use Task tool, spawn subagents, and access full conversation
- The plugin targets Claude Code users who may not have ANTHROPIC_API_KEY
- Current architecture was designed through extensive research (rd-08-final-plan.md)
- FTS5 BM25 search is already fast (~100ms) and decent quality (~65-75% precision)

## Output Requirements
Each analyst should write their findings to `temp/<agent-name>-analysis.md` with:
1. Analysis of each question (Q1-Q5)
2. Pros/cons for each option
3. Concrete recommendation
4. Evidence from codebase
5. External model opinions (via pal clink)
6. Vibe-check results at key decision points
