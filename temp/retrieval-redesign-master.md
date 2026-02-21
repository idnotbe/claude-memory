# Retrieval Redesign -- Master Working Memory

**Created:** 2026-02-20
**Purpose:** Central coordination file for retrieval improvement planning

---

## Context Summary

### Problem
- Current keyword matching has ~40% precision (estimated, not measured)
- Auto-injection at min_score=1, max_inject=5 → ~3/5 injected memories are irrelevant noise
- Final analysis report: "현재 auto-injection은 아마 해롭다" (net-negative)

### Constraints
- Keep storage system as-is (JSON files + index.md)
- stdlib-only for core scripts (pydantic only for write/validate)
- No daemons, no ports, no background processes
- WSL2 compatibility required
- Prefer skill over MCP (existing architecture uses skills)

### Key Insights from Research
1. claude-mem dual-path: recency hook (SessionStart) + MCP tools (on-demand vector search)
2. claude-mem abandoned skills for MCP (v5.4 → v6+) — skills had 67% effectiveness
3. claude-mem abandoned FTS5/BM25 for vector search — keyword search was deprecated
4. Progressive disclosure saves tokens: search → timeline → full detail
5. "Structural enforcement over behavioral guidance" — MCP forces workflow, skills suggest it
6. Recommended: Precision-First Hybrid (conservative auto-inject + manual search)
7. transcript_path available in hooks but NOT used by retrieval hook yet

### Decision Points
1. Hook strategy: UserPromptSubmit (current) vs SessionStart (claude-mem) vs both?
2. On-demand search: Skill vs MCP vs both?
3. Progressive disclosure: 3-layer (claude-mem style) vs 2-tier vs something else?
4. Scoring algorithm: current keyword → BM25 → FTS5 → hybrid?
5. Transcript context: use conversation history for better matching?
6. Eval framework: build first or design alongside?

---

## Team Structure

### Phase 1: Research & Design
- **synthesizer**: Consolidates all research into actionable brief
- **architect**: Designs the retrieval architecture from zero-base
- **skeptic**: Adversarial reviewer — attacks the design
- **pragmatist**: Feasibility/simplicity reviewer

### Phase 2: Consolidation
- Lead (me): Merges inputs, resolves conflicts, produces final plan

### Phase 3: Verification Round 1
- **verifier-technical**: Technical correctness check
- **verifier-practical**: Implementation feasibility check

### Phase 4: Verification Round 2
- **verifier-adversarial**: Adversarial challenge
- **verifier-independent**: Independent fresh-eyes review

---

## File Index
| File | Purpose | Author |
|------|---------|--------|
| `temp/retrieval-redesign-master.md` | This coordination file | lead |
| `temp/rd-01-research-synthesis.md` | Research synthesis brief | synthesizer |
| `temp/rd-02-architecture-proposal.md` | Architecture design | architect |
| `temp/rd-03-skeptic-review.md` | Adversarial review | skeptic |
| `temp/rd-04-pragmatist-review.md` | Feasibility review | pragmatist |
| `temp/rd-05-consolidated-plan.md` | Merged plan after Phase 2 | lead |
| `temp/rd-06-verify1-technical.md` | Verification R1 - technical | verifier-technical |
| `temp/rd-06-verify1-practical.md` | Verification R1 - practical | verifier-practical |
| `temp/rd-07-verify2-adversarial.md` | Verification R2 - adversarial | verifier-adversarial |
| `temp/rd-07-verify2-independent.md` | Verification R2 - independent | verifier-independent |
| `temp/rd-08-final-plan.md` | Final retrieval improvement plan | lead |
