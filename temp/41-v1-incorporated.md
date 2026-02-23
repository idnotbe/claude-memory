# V1 Feedback Incorporation

**Date:** 2026-02-22
**Sources:** `temp/41-v1-code-correctness.md`, `temp/41-v1-design-security.md`

---

## V1 Verdicts

- **v1-code-verifier:** PASS WITH NOTES (1 line number correction, 1 new minor finding)
- **v1-design-verifier:** PASS WITH NOTES (3 actionable items)

No FAIL or NEEDS WORK from either verifier. All 5 fixes confirmed code-correct and security-safe.

---

## Corrections Applied

### 1. emit_event Placement (from v1-code-verifier)

**Issue:** Solution synthesis said "after line 482" for the emit_event() call in memory_search_engine.py. Line 482 is inside the JSON output branch only.

**Correction:** emit_event() must be placed after the entire if/else output block (after L495, after the text output for-loop ends), to cover both JSON and text output paths.

**Updated Finding #4 code change:**
```python
# In memory_search_engine.py main(), AFTER the entire output block (after L495):
emit_event(
    event_type="search.query",
    data={
        "query": args.query,
        "mode": args.mode,
        "total_results": len(results),
    },
    session_id=session_id,
    script="memory_search_engine.py",
    memory_root=str(memory_root),
)
```

### 2. Judge Fallback stderr Warning (from v1-design-verifier)

**Issue:** Both Gemini instances independently flagged that silent judge fallback masks deployment errors. When `judge_enabled=True` but `memory_judge.py` is missing, the hook silently degrades with no diagnostic signal.

**Correction:** Add stderr warning at both judge fallback sites.

**Updated Finding #5 judge hardening:**
```python
# FTS5 path (line ~429):
if judge_enabled and results:
    try:
        from memory_judge import judge_candidates
    except ImportError:
        judge_candidates = None

    if judge_candidates is not None:
        # ... existing judge logic unchanged ...
    else:
        print("[WARN] Judge enabled but memory_judge module not found; "
              "falling back to top-k", file=sys.stderr)
        fallback_k = judge_cfg.get("fallback_top_k", 2)
        results = results[:fallback_k]

# Legacy path (line ~503): Same pattern with stderr warning.
```

### 3. label_precision Annotation Methodology (from v1-design-verifier)

**Issue:** The label_precision metric needs explicit annotation methodology in PoC #5 plan.

**Correction:** Add to plan-poc-retrieval-experiments.md PoC #5 section:
```
Relevance ground truth: Human annotation on curated query set.
Annotator reviews each result and marks relevant/irrelevant using rubric:
"Would this memory help Claude provide a better answer to the query?"
```

---

## New Items to Track

### NEW-3: Empty XML After Judge Rejection (LOW)

**Discovered by:** Gemini 3 Pro (via v1-code-verifier)

If judge filters out ALL candidates in FTS5 path, `top = results[:max_inject]` becomes `[]`, and `_output_results([], ...)` outputs empty `<memory-context>...</memory-context>`. This wastes tokens.

**Proposed fix:** Add `if not top:` guard before `_output_results()` in FTS5 path.

**Status:** Track separately. LOW severity, not part of current fix scope.

### NEW-2 Test Case Requirement

**From v1-design-verifier:** Judge import vulnerability (NEW-2) needs a dedicated regression test:
```python
def test_judge_enabled_missing_module():
    """Judge enabled but module missing should fallback gracefully, not crash."""
```

**Status:** Required as part of Finding #5 implementation.

---

## Updated Solution Summary (Post-V1)

All fixes remain the same, with these refinements:

| Finding | Original Solution | V1 Refinement |
|---------|------------------|---------------|
| #1 (Score Domain) | 2-line raw_bm25 fallback | No change -- confirmed correct |
| #2 (Cluster Tautology) | Keep disabled, document | No change -- proof verified |
| #3 (PoC #5 Measurement) | Triple logging + label_precision | Add annotation methodology |
| #4 (Dead Correlation) | --session-id CLI param | Fix emit_event placement (after L495) |
| #5 (Import Crash) | try/except + judge hardening | Add stderr warning to judge fallback |

### Verification Questions for V2 Round

1. **Adversarial:** Can an attacker construct inputs that make the raw_bm25 fallback produce worse results than the current mutated-score behavior?
2. **Adversarial:** What if body_bonus is negative? (Currently capped at 0-3 by `min(3, len(body_matches))`, but what if the formula changes?)
3. **Fresh eyes:** Do the 5 fixes as a coherent whole change the system's behavior in unexpected ways?
4. **Fresh eyes:** Are there emergent issues when ALL fixes are applied simultaneously vs. individually?
5. **Fresh eyes:** Is the overall analysis proportional to the actual risk, or have we over-analyzed?
