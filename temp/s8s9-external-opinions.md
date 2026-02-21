# External Model Opinions on S8/S9

## Codex (codex 5.3) -- planner role

### Q1: Task subagent judge
- **Verdict: Sound, with guardrails**
- Matches architecture constraints (Task unavailable in hook, available in skill)
- Avoids API-key dependency for OAuth users
- Keeps strict/lenient behavior separated by surface
- Tradeoffs: less deterministic than direct API call, higher orchestration complexity
- Recommendation: use Task judge only in /memory:search, keep inline API judge for hook

### Q2: Dual judge
- **Verdict: Not worth default complexity; gated experiment only**
- AND-gate recall collapse risk is real (independent 0.7 recalls => ~0.49)
- Ship single judge first; dual only if measured precision gain is material
- Recall cannot exceed min(recall1, recall2)

### Q3: ThreadPoolExecutor
- **Verdict: No meaningful memory leak risk**
- Context manager + awaited futures + process exit = clean
- Real risks: latency variance, API rate-limit bursts, more failure branches

### Q4: Precision measurement
- **Verdict: Practical with small labeled benchmark**
- 40-60 real queries, label top-15 candidates
- Compare Precision@3 (auto), Precision@10 (search), Recall@15
- Bootstrap/Wilson confidence intervals
- Set acceptance gates before shipping

---

## Gemini (gemini 3 pro) -- planner role

### Q1: Task subagent judge
- **Verdict: ABANDON the approach -- over-engineering**
- Creates divergent logic paths (API-based for hooks, agent-based for skills)
- Inconsistent filtering, duplicated testing effort
- Alternative: refactor memory_judge.py with --lenient flag, reuse via bash subprocess in skill

### Q2: Dual judge
- **Verdict: SCRAP entirely**
- "Dropping recall to 49% to gain 3% precision is a fatal flaw"
- Existing JUDGE_SYSTEM prompt already combines relevance + usefulness
- 2x API cost for negligible gain

### Q3: ThreadPoolExecutor
- **Verdict: Safe**
- Memory leaks impossible in 3-second script
- urllib.request thread-safe for isolated POST requests
- Only caveat: shared global OpenerDirector (theoretical edge case)

### Q4: Precision measurement
- **Verdict: Abandon formal evaluation -- over-engineering**
- "Qualitative, vibes-based evaluation strategy"
- 10-20 tricky representative queries, manually verify
- Formal precision/recall framework is overkill for 500-item dataset

---

## Key Disagreements Between Models

| Topic | Codex | Gemini |
|-------|-------|--------|
| Task subagent judge | Sound, keep it | Abandon, use unified script |
| Dual judge | Gated experiment | Scrap entirely |
| Evaluation | Formal benchmark (40-60 queries) | Qualitative (10-20 queries) |
| ThreadPoolExecutor | Safe | Safe |

## My (Opus) Initial Assessment
- Both agree: dual judge is questionable, ThreadPoolExecutor is safe
- Codex is more nuanced (keep as experiment), Gemini is more radical (scrap)
- Gemini's point about divergent logic paths is valid
- But Codex's point about OAuth users (no API key) is also valid
- Need to synthesize after seeing subagent analysis results
