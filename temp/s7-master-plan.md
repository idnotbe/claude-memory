# Session 7 Master Plan -- LLM Judge Implementation

**Date:** 2026-02-21
**Status:** COMPLETE
**Source:** rd-08-final-plan.md, lines 1134-1139

---

## Objectives (from rd-08)

1. Create `hooks/scripts/memory_judge.py` (~140 LOC)
2. Integrate into `memory_retrieve.py` (~30 LOC)
3. Add judge config to `assets/memory-config.default.json`
4. Update `hooks/hooks.json` timeout 10->15s
5. Update CLAUDE.md

## Team Structure

### Phase 1: Implementation (Parallel where possible)

| Teammate | Role | Tasks | Subagents |
|----------|------|-------|-----------|
| architect | Creates memory_judge.py from pseudocode in rd-08 | T1 | Code writer, security reviewer, test compiler |
| integrator | Integrates judge into memory_retrieve.py + updates config files | T2, T3, T4 | Integration writer, config updater |
| docs-updater | Updates CLAUDE.md Key Files table + architecture | T5 | Doc reviewer |

### Phase 2: Verification Round 1 (3 diverse reviewers)

| Teammate | Perspective | Focus |
|----------|-------------|-------|
| v1-correctness | Correctness & logic | Code logic, edge cases, pseudocode fidelity |
| v1-security | Security & hardening | Prompt injection, API key handling, data boundaries |
| v1-integration | Integration & consistency | Config consistency, hook timeout, cross-file coherence |

### Phase 3: Verification Round 2 (2 diverse reviewers)

| Teammate | Perspective | Focus |
|----------|-------------|-------|
| v2-adversarial | Adversarial tester | Break it: malicious inputs, failure modes, race conditions |
| v2-independent | Independent auditor | Fresh eyes: does it match the plan? Any gaps? |

## File-Based Communication

All inter-teammate communication uses files in `temp/s7-*.md`:
- `temp/s7-master-plan.md` -- this file (shared context)
- `temp/s7-architect-output.md` -- architect's work output
- `temp/s7-integrator-output.md` -- integrator's work output
- `temp/s7-docs-output.md` -- docs updater's output
- `temp/s7-v1-report.md` -- verification round 1 combined report
- `temp/s7-v2-report.md` -- verification round 2 combined report

## Dependencies

```
T1 (memory_judge.py) ──┐
                        ├── T2 (integrate into memory_retrieve.py)
T3 (config files) ──────┤
T4 (hooks.json) ────────┘
T5 (CLAUDE.md) ── depends on T1-T4 being done

V1 (round 1) ── depends on T1-T5
V2 (round 2) ── depends on V1 fixes applied
```

## Key Constraints

- memory_judge.py uses stdlib only (urllib.request, no pip deps)
- Judge is opt-in: `judge.enabled: false` by default
- Requires ANTHROPIC_API_KEY env var
- Pseudocode in rd-08 lines 573-809 is the reference implementation
- Anti-position-bias: deterministic shuffle via sha256
- Anti-injection: `<memory_data>` XML boundary tags
- Fallback: on judge failure, reduce to Top-2 BM25 results

## Progress Tracking

- [x] T1: memory_judge.py created (253 LOC, architect)
- [x] T2: memory_retrieve.py integrated (75 LOC added, architect)
- [x] T3: memory-config.default.json updated (config-specialist)
- [x] T4: hooks.json timeout 10->15s (config-specialist)
- [x] T5: CLAUDE.md updated (architect)
- [x] V1: CONDITIONAL PASS -> 3 MEDIUM fixes applied (v1-correctness, v1-security, v1-integration)
- [x] V2: PASS, grade A- (v2-adversarial, v2-independent)

## V1 Fixes Applied

| Fix | Issue | Resolution |
|-----|-------|------------|
| M1 | FTS5 pool capped at max_inject (3) not candidate_pool_size (15) | Pass effective_inject to score_with_body when judge enabled |
| M2 | No title sanitization in format_judge_input | Added html.escape() for title, category, tags |
| M3 | Transcript path traversal (no validation) | Added path validation matching memory_triage.py |

## Final Stats

- **Total LOC:** ~328 (253 judge + 75 integration) vs 170 estimated (1.9x)
- **Tests:** 683/683 pass, no regressions
- **Team:** 7 teammates total (2 implementers + 5 reviewers)
- **Grade:** A-

## Working Files

- `temp/s7-architect-output.md` -- implementation details
- `temp/s7-integrator-output.md` -- integration details
- `temp/s7-docs-output.md` -- documentation details
- `temp/s7-v1-report.md` -- V1 combined report
- `temp/s7-v1-correctness.md` -- V1 correctness review
- `temp/s7-v1-security.md` -- V1 security review
- `temp/s7-v1-integration.md` -- V1 integration review
- `temp/s7-v2-report.md` -- V2 combined report
- `temp/s7-v2-adversarial.md` -- V2 adversarial review
- `temp/s7-v2-independent.md` -- V2 independent audit
