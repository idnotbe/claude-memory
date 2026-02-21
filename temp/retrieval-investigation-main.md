# Memory Retrieval System Investigation
## Working Memory - Main Thread

### Status: IN PROGRESS
### Date: 2026-02-19

---

## Files Read So Far
- [x] hooks/scripts/memory_retrieve.py (362 lines) - Core retrieval logic
- [x] hooks/hooks.json - Hook configuration
- [x] assets/memory-config.default.json - Default config
- [x] hooks/scripts/memory_index.py (449 lines) - Index management
- [x] hooks/scripts/memory_candidate.py (383 lines) - ACE candidate selection
- [x] hooks/scripts/memory_triage.py (1062 lines) - Triage/save system
- [x] skills/memory-management/SKILL.md - Orchestration skill

## Key Architectural Understanding

### Retrieval = UserPromptSubmit Hook
- Event: UserPromptSubmit (user types a prompt)
- Script: memory_retrieve.py
- Type: command
- Timeout: 10s
- Output: stdout -> injected into Claude's context (exit 0)

### High-Level Flow
1. User types prompt -> Claude Code fires UserPromptSubmit hook
2. memory_retrieve.py receives hook input JSON via stdin
3. Reads .claude/memory/index.md (lightweight index)
4. Tokenizes user prompt -> keyword matching against index entries
5. Scores entries (title + tags + category description matching)
6. Deep-checks top 20 for recency/retired status
7. Outputs top N results as <memory-context> XML block
8. Claude sees this in its context automatically

### Subagent Tasks Launched
- [ ] Flow Analysis (end-to-end pipeline)
- [ ] Scoring Algorithm Deep Dive
- [ ] Security & Edge Cases
- [ ] Architecture Critique

---

## Preliminary Observations
1. This is a KEYWORD-BASED retrieval, not semantic/embedding-based
2. Index is a markdown file (index.md), not a database
3. Two-pass scoring: text matching first, then JSON deep-check for recency
4. Category priority ordering affects tie-breaking
5. Defense-in-depth: title sanitization on both write and read sides
6. Auto-rebuild: if index.md missing, rebuilds from JSON files on demand
