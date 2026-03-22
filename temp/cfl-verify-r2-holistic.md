# CFL Research - Verification Round 2: Holistic Quality + Actionability

**Reviewer perspective**: Internal consistency, gap analysis, actionability
**Document**: research/closed-feedback-loop.md

## Findings

1. [OK] **Internal consistency**: The 5 phases build logically -- each phase's outputs are inputs to the next (Evidence Contract -> Runner -> Promotion -> Traceability -> Auto-Fix). No circular dependencies.

2. [OK] **Cross-model synthesis (Sec 3)**: Universal agreements and disagreements are clearly resolved with rationale. The "spike test first" resolution for `claude -p` hook behavior is pragmatic.

3. [OK] **Deterministic oracle priority (Sec 3.1 #4, 4.2, 7)**: Consistently enforced throughout -- LLM judgment is explanation-only, pass/fail is always deterministic. No contradictions on this principle.

4. [OK] **Test infrastructure reuse (Sec 5)**: 1097 existing tests mapped to PRD sections. The plan to add markers without code changes is low-risk and realistic.

5. [MINOR] **Phase 1 acceptance criteria (Sec 4.2)**: The verification gate ("run same scenario twice, get comparable output") is vague. Define "comparable" -- exact JSON match? Same verdict? Tolerance on duration_ms? Without this, Phase 1 "done" is subjective.

6. [MINOR] **Phase 2 runner.sh (Sec 4.3)**: Uses `claude -p` with `--permission-mode dontAsk` but Section 6.1 explicitly flags that `claude -p` hook behavior is unvalidated. The runner script assumes the spike test passes without noting the fallback path inline. A comment or conditional would improve clarity.

7. [MINOR] **Phase 3 acceptance criteria missing**: Section 4.4 describes promotion mechanics but has no verification gate (unlike Phases 1 and 2 which have explicit gates). Add a gate like "promotion generates valid repo A artifact from known ops failure."

8. [MINOR] **Risk matrix gap -- flaky scenarios**: Section 7 mentions the decision point ("flaky -> stay in Shadow Loop") but the risk matrix (Sec 8) does not list scenario flakiness as a risk. It should, given it gates Phase 5.

9. [OK] **Risk: blast radius (Sec 8)**: Correctly identified with `--plugin-dir .` mitigation. Consistent with Gemini's critical insight in Sec 3.3.

10. [OK] **Risk: prd.json mutability**: Correctly resolved as derived artifact (Sec 3.2). Implementation in Phase 4 uses immutable `requirements.json` + derived status from pytest results. Consistent.

11. [ACTION NEEDED] **Phase 1 implementation context insufficient**: Someone starting Phase 1 from this document alone would lack: (a) where to find the actual PRD requirement IDs referenced in scenarios (document says `docs/requirements/prd.md` but those REQ-3.x.x IDs are not defined here), (b) how `setup_workspace` populates test memories (the scenario schema shows `"setup": {"memories": [...]}` but no explanation of resolution), (c) what `--plugin-dir .` actually does with hooks.json resolution. A "Prerequisites" subsection in Phase 1 would close this gap.

12. [OK] **Diagrams/tables accuracy**: The PRD-to-tier mapping table (Sec 4.5) correctly distinguishes what needs live testing vs pytest-only. The file structure (Sec 9) matches all referenced paths in the phases.

13. [MINOR] **runner.sh vs runner.py duplication (Sec 9)**: The appendix lists both `runner.sh` (Bash) and `runner.py` (Python) without explaining the split. Section 4.3 only shows `runner.sh`. Clarify whether runner.py replaces or wraps runner.sh.

14. [OK] **Shadow Loop safety (Sec 4.6)**: Branch isolation + hard quality gates + single-failure-per-iteration + no-merge policy is well-designed. Properly inherits patterns from both autoresearch (keep/discard) and ralph (fresh context).

## Summary

The document is well-structured, internally consistent, and the phased approach is sound. Two items need attention: (1) Phase 1 needs enough standalone context for someone to begin implementation without hunting through other documents, and (2) a few acceptance criteria are missing or underspecified. The rest are minor polish items that won't block progress.
