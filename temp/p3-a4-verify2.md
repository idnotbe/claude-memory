# Action #4 Agent Hook PoC -- Verification #2 (Architectural Strategy & Future-Proofing)

**Date:** 2026-02-26
**Reviewer perspective:** Architectural Strategy & Future-Proofing
**Documents reviewed:**
- `action-plans/plan-retrieval-confidence-and-output.md` (Action #4 specification)
- `temp/p3-agent-hook-poc-results.md` (PoC results)
- `hooks/scripts/memory_retrieve.py` (current retrieval implementation)
- `hooks/hooks.json` (current hook configuration)
- `hooks/scripts/memory_write_guard.py` (existing hookSpecificOutput usage)
- `hooks/scripts/memory_staging_guard.py` (existing hookSpecificOutput usage)
- `hooks/scripts/memory_validate_hook.py` (existing hookSpecificOutput usage)
- `assets/memory-config.default.json` (current config)
- `temp/agent-hook-verification.md` (prior independent verification)
- `research/retrieval-improvement/01-research-claude-code-context.md` (original research)

---

## 1. Architecture Decision Quality

### 1.1 Challenging the Three-Phase Recommendation

The PoC recommends:
- **Short-term:** No change (keep command hook)
- **Medium-term:** Migrate to `additionalContext` JSON output
- **Long-term:** Monitor agent hook enhancements

**Verdict: The short-term recommendation is sound. The medium-term recommendation has a subtle but important gap. The long-term recommendation is too passive.**

#### Short-term (No change): AGREE

The reasoning is well-founded. The current architecture (command hook with stdout injection) is:
- Fast (~0.5-1s)
- Deterministic (stdlib only, no API dependency in the base path)
- Well-tested (90/90 tests for memory_retrieve.py, 943/943 total)
- Sufficient for the current feature set

No credible argument exists for premature migration.

#### Medium-term (`additionalContext` JSON output): AGREE WITH CAVEATS

The PoC identifies that `additionalContext` is "added more discretely" than plain stdout, citing the official docs. This is presented as the primary benefit. However, three important gaps exist in the analysis:

**Gap 1 -- "Discrete" semantics are under-specified.** The PoC quotes the docs saying `additionalContext` is "added more discretely" but does not investigate what "discretely" means in practice. Possibilities include:
- (a) Content is injected into the conversation but not shown in the transcript UI
- (b) Content is treated as system-level context with different attention weighting
- (c) Content appears differently in the JSONL transcript file

The PoC should have clarified this. If "discretely" simply means "not visible in the user-facing transcript UI," that may actually be a disadvantage for debugging and user trust -- users who want to see what memories were injected would lose that visibility. The current stdout mechanism, which appears as visible hook output in the transcript, arguably provides better transparency.

**Gap 2 -- Backward compatibility risk.** The PoC estimates ~20 LOC for the migration. This understates the true scope:
- `memory_retrieve.py` currently uses `print()` for all output (lines 306-388, ~80 lines of output logic)
- Migrating to JSON means wrapping ALL output in a `json.dump()` call to stdout
- The `_emit_search_hint()` function (lines 299-313) uses `print()` directly -- these hints would need to be folded into the JSON response or split into a separate mechanism
- The `_output_results()` function (lines 316-388) builds XML incrementally via `print()` -- this would need to be refactored to accumulate a string first, then emit as JSON
- Error/diagnostic output to stderr (lines 474, 514-515, 665) must remain as-is (not captured by hook infrastructure)
- The test suite has extensive stdout-capture tests that assert XML format -- all would need dual-mode testing

True estimate: ~40-60 LOC code change + ~30-50 LOC test changes. Not a trivial migration.

**Gap 3 -- Mixed output model.** The PoC does not address that `memory_retrieve.py` currently outputs to BOTH stdout (context injection) and stderr (diagnostics). With `additionalContext` JSON, the stdout channel becomes exclusively JSON. This is actually cleaner (diagnostic messages stay on stderr, injection goes through structured JSON), but the PoC fails to explicitly acknowledge this as a benefit and migration consideration.

#### Long-term (Monitor agent hook enhancements): TOO PASSIVE

"Monitor the changelog" is not actionable. A better long-term recommendation would be:

1. **Define concrete trigger criteria** for when to re-evaluate agent hooks (e.g., "if agent hooks gain `additionalContext` support in their response schema" or "if agent hook latency drops below 1s via cached model inference")
2. **Identify the feature gap** precisely: agent hooks need the ability to inject arbitrary context, not just binary decisions. The PoC identifies this but does not frame it as a concrete feature request that could be filed against Claude Code.
3. **Consider the convergence scenario**: Claude Code's hook architecture may converge toward a single handler type. If agent hooks eventually subsume command hooks (by gaining stdout injection), the migration path becomes trivial (change `type: "command"` to `type: "agent"` in hooks.json, add a prompt). The PoC should note that this convergence would be the ideal trigger for migration.

### 1.2 What if Hook Architecture Changes?

The PoC does not adequately address this scenario. Three plausible evolution paths:

**Path A: Hook infrastructure adds `additionalContext` to agent/prompt hook responses.**
- Impact: Agent hooks become viable for context injection.
- Migration cost: Low (add prompt to hooks.json, test, remove command hook).
- Risk: Agent hook latency still 2-15s vs 0.5-1s.
- Assessment: Only compelling if agent hooks also gain latency improvements.

**Path B: Hook infrastructure deprecates command hooks in favor of agent hooks.**
- Impact: Forced migration.
- Migration cost: High (rewrite retrieval logic as an agent prompt, lose deterministic BM25 in favor of LLM-mediated search, significant latency regression).
- Risk: Breaking change requiring architectural rethinking.
- Assessment: Unlikely in near term. Command hooks are the simplest, most deterministic option and are used by the majority of documented hook examples.

**Path C: Hook infrastructure adds new output mechanisms (e.g., `contextFiles`, `systemPromptAppend`).**
- Impact: New, potentially superior injection mechanisms.
- Migration cost: Depends on mechanism.
- Assessment: The PoC's `additionalContext` migration would be well-positioned to adopt new mechanisms since the output is already structured JSON.

**Conclusion:** The `additionalContext` migration (medium-term) is architecturally defensive -- it positions the codebase to adopt future output mechanisms with minimal friction. This is a valid strategic argument that the PoC under-emphasizes.

### 1.3 `additionalContext` vs Plain Stdout Tradeoffs

| Dimension | Plain stdout | `additionalContext` JSON |
|-----------|-------------|--------------------------|
| Transparency | Visible in transcript UI | "Discrete" (likely hidden from UI) |
| Debuggability | User can see exactly what was injected | Requires JSONL transcript inspection |
| Structured control | Text only | JSON envelope allows future extensions |
| Error handling | Any non-zero exit = hook failure | JSON can include error fields alongside context |
| Migration cost | N/A (current state) | ~40-60 LOC + test changes |
| Multi-output | Can mix XML elements with hints | Single JSON blob (must consolidate all output) |
| Future-proofing | Tied to stdout convention | Aligned with documented JSON output schema |

**Key insight the PoC misses:** The current codebase already uses `hookSpecificOutput` in THREE other hooks (`memory_write_guard.py`, `memory_staging_guard.py`, `memory_validate_hook.py`). The retrieval hook is the only hook NOT using structured JSON output. This inconsistency is itself an argument for migration -- the codebase convention favors structured JSON for hook responses.

### 1.4 Is the "Hybrid Won't Work" Conclusion Airtight?

The PoC concludes that Architecture A (parallel command + agent hooks) won't work because "hooks run in parallel" and "cannot communicate." This conclusion is **correct but incompletely argued.** Let me strengthen it:

1. **Timing problem:** Even if both hooks could communicate, the agent hook (2-15s) would finish AFTER the command hook (0.5-1s). The command hook's context is already injected before the agent hook renders its verdict.

2. **No cancellation mechanism:** There is no documented way for one hook to cancel or modify another hook's output. The hook infrastructure aggregates all results independently.

3. **`ok: false` side effect:** The PoC correctly identifies that an agent hook returning `ok: false` on UserPromptSubmit would block the entire prompt, not just filter the memory injection. This is a fundamental design mismatch.

4. **The real alternative the PoC should have considered:** What if the agent hook and command hook are registered for DIFFERENT events? For example, the agent hook on `PreToolUse` (to gate specific tool calls based on memory context) rather than `UserPromptSubmit`. This is a different use case but shows agent hooks have value in the system beyond retrieval.

**Verdict:** The "hybrid won't work for retrieval" conclusion is airtight for UserPromptSubmit. But the PoC's framing is too narrow -- it dismisses agent hooks entirely rather than identifying where they could add value in other parts of the memory plugin's lifecycle.

---

## 2. Discovery Validation

### 2.1 `additionalContext` via `hookSpecificOutput` JSON

The PoC presents this as a "critical finding" and "most significant discovery." Let me evaluate the evidence quality:

**Evidence strength: MODERATE**

The PoC cites three sources:
1. TypeScript SDK type definitions (`SyncHookJSONOutput`)
2. Official hooks reference at code.claude.com/docs/en/hooks
3. Quoted documentation text about "discrete" injection

The TypeScript type definition is the strongest evidence -- it explicitly shows `additionalContext` as an optional field on `UserPromptSubmit` output. The documentation quote is helpful but vague ("added more discretely").

**What's missing:** No live validation. The PoC is "analysis-only" (stated on line 5: "no live executions"). This means the `additionalContext` mechanism has NOT been empirically tested with this plugin. It is possible that:
- The mechanism works but has undocumented size limits
- The "discrete" injection has different tokenization or context window treatment
- The mechanism interacts unexpectedly with other hooks' output

**Assessment:** The discovery is credible based on documentation evidence, but the lack of empirical validation is a risk factor for the medium-term migration recommendation. A smoke test (output a simple JSON with `additionalContext` from `memory_retrieve.py`, verify it appears in Claude's context) should be a prerequisite before committing to the migration.

### 2.2 Would Migration Require Changes Beyond `memory_retrieve.py`?

**Yes, but the scope is contained.** Analysis:

| Component | Change needed? | Details |
|-----------|---------------|---------|
| `hooks/scripts/memory_retrieve.py` | YES | Refactor all `print()` output to accumulate strings, wrap in JSON with `hookSpecificOutput` |
| `hooks/hooks.json` | NO | Command hook config stays identical; the output format is internal to the script |
| `assets/memory-config.default.json` | POSSIBLY | Could add `retrieval.output_format: "stdout"/"json"` for backward compatibility |
| `hooks/scripts/memory_search_engine.py` | NO | Search engine is consumed as a library; its output is not hook output |
| `hooks/scripts/memory_judge.py` | NO | Judge is consumed as a library within memory_retrieve.py |
| `tests/test_memory_retrieve.py` | YES | All stdout-capture assertions need updating for JSON format |
| `tests/test_v2_adversarial_fts5.py` | YES | Two tests assert `<result>` format in stdout |
| `CLAUDE.md` | YES (minor) | Update "Stdout is added to Claude's context automatically" description |

### 2.3 hooks.json Implications

**None.** The `additionalContext` mechanism is a change in the SCRIPT's stdout format, not the hook configuration. The hooks.json entry remains:

```json
{
  "type": "command",
  "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py\"",
  "timeout": 15
}
```

The hook infrastructure detects JSON output (vs plain text) automatically by attempting to parse stdout as JSON. This is confirmed by the existing guard hooks (`memory_write_guard.py`, `memory_staging_guard.py`) which output JSON to stdout without any hooks.json changes.

---

## 3. Completeness of Alternatives Analysis

The PoC evaluates three architectures (A: Parallel Independent, B: Command Hook with additionalContext, C: Agent Hook as Sole Handler). Were viable alternatives missed?

### 3.1 Architecture D: Pre-filtering Agent Hook + Command Hook (Flag File)

**Concept:** Agent hook fires first, writes a flag file (e.g., `/tmp/.memory-retrieval-skip`) if memories are irrelevant. Command hook checks for the flag file and skips injection if present.

**Analysis:**
- **Fatal flaw:** Hooks run in parallel, not sequentially. The agent hook cannot finish before the command hook starts. There is no documented mechanism to enforce ordering between hooks in the same event.
- **Verdict:** NOT VIABLE. The PoC's parallel-execution finding eliminates this architecture.

### 3.2 Architecture E: Agent Hook + Bash Tool Writing to Temp File

**Concept:** Agent hook runs BM25 search via Bash tool, writes filtered results to a temp file. Command hook reads the temp file.

**Analysis:**
- **Same fatal flaw:** Parallel execution. The command hook cannot wait for the agent hook to finish writing the temp file.
- **Even if ordering existed:** This adds ~5-15s latency and introduces file-based coordination (race conditions, cleanup, failure modes).
- **Verdict:** NOT VIABLE.

### 3.3 Architecture F: Multiple Command Hooks in Sequence

**Concept:** Two command hooks for UserPromptSubmit -- first does BM25 search and writes candidates to a temp file, second reads the temp file and applies LLM judgment before injecting.

**Analysis:**
- **Same fatal flaw:** Multiple hooks in the same event handler run in parallel, not sequentially. The official docs explicitly state: "All matching hooks run in parallel."
- **Verdict:** NOT VIABLE.

### 3.4 Architecture G: Single Command Hook with Internal Agent Spawning

**Concept:** The command hook (`memory_retrieve.py`) internally spawns a subprocess that acts as a mini-agent (reads files, evaluates relevance) before producing output.

**Analysis:**
- **This is essentially the current architecture with `memory_judge.py`.** The judge makes an API call to Claude for relevance filtering, which is functionally equivalent to what an agent hook would do.
- **Verdict:** ALREADY IMPLEMENTED. The PoC correctly identifies this in Architecture B but could have stated it more explicitly: "we already have the agent hook's judgment capability embedded in our command hook."

### 3.5 Architecture H: SessionStart Hook for Pre-Loading + UserPromptSubmit for Injection

**Concept:** Use a SessionStart command hook to pre-build the FTS5 index and warm caches. UserPromptSubmit hook does fast lookup against pre-warmed state.

**Analysis:**
- **Interesting but limited:** SessionStart fires once per session, not per prompt. The FTS5 index is already rebuilt on-demand per invocation. The bottleneck is not index building (~50ms) but search + file I/O + optional judge (~0.5-1s total).
- **SessionStart supports `additionalContext`** per the TypeScript types. Could inject a "session context preamble" with frequently-accessed memories.
- **Verdict:** PARTIALLY VIABLE as a complement, not a replacement. Worth noting in the long-term section but not a primary architecture. The PoC misses this option.

### 3.6 Alternatives Assessment Summary

The PoC's three architectures (A, B, C) cover the primary design space adequately. Architectures D, E, F are all eliminated by the parallel-execution constraint that the PoC correctly identifies. Architecture G is already implemented. Architecture H is an interesting complement that the PoC misses but is not critical to the core recommendation.

**Verdict: The alternatives analysis is SUFFICIENT.** The parallel-execution constraint is the dominant architectural constraint, and the PoC correctly identifies it.

---

## 4. Impact on Existing Plan Items (Actions #1-#3)

### 4.1 Action #1 (confidence_label): NO IMPACT

The confidence calibration logic is internal to the retrieval pipeline. Whether output goes to stdout as plain text or as JSON with `additionalContext`, the confidence labeling remains identical. The `abs_floor` and `cluster_count` parameters are score-domain concerns, not output-format concerns.

### 4.2 Action #2 (Tiered Output): MINOR IMPACT

The tiered output mode (`legacy` vs `tiered`) determines the XML structure of injected content. If the medium-term `additionalContext` migration happens:
- The XML content (`<memory-context>`, `<result>`, `<memory-compact>`, `<memory-note>`) would be placed inside the `additionalContext` string field
- The tiered logic itself is unchanged
- The `_output_results()` function would need refactoring from `print()` to string accumulation

This is a refactoring concern, not a semantic concern. The PoC recommendation does NOT invalidate any Action #2 decisions.

### 4.3 Action #3 (Hints): MINOR IMPACT

The `_emit_search_hint()` function uses `print()` to emit `<memory-note>` elements. Under `additionalContext` migration:
- Hints would be included in the accumulated `additionalContext` string
- The hint format (XML) remains unchanged
- The "discrete" injection may actually improve hint effectiveness (hints are less likely to be treated as "hook noise" by Claude)

Again, this is a refactoring concern, not a semantic concern.

### 4.4 Cross-cutting: ALL actions' output would be wrapped in JSON

The key impact is that ALL output from Actions #1-#3 would be wrapped in a JSON envelope:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<memory-context ...>...<memory-note>...</memory-note></memory-context>"
  }
}
```

This is a mechanical transformation. The content semantics are preserved.

**Verdict: No Actions #1-#3 decisions need to be revisited based on the PoC findings.** The `additionalContext` migration, if pursued, is an orthogonal output-format change that can be layered on top of the existing implementation.

---

## 5. Risk Assessment

### 5.1 Risk Matrix: Status Quo (No Changes from PoC)

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Stdout injection becomes deprecated | LOW | HIGH | Current mechanism is foundational to Claude Code's hook system; deprecation would break many plugins |
| Agent hooks gain context injection | MEDIUM | LOW | Positive development; would expand options without breaking current approach |
| Transcript visibility of injected memories annoys users | LOW | LOW | Users can already see hook output; this is a feature, not a bug |
| Inconsistency with other hooks using JSON output | LOW | LOW | Cosmetic; does not affect functionality |

**Overall risk of status quo: LOW.** The current architecture is well-aligned with Claude Code's documented hook model.

### 5.2 Risk Matrix: Implementing Medium-Term `additionalContext` Migration

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| `additionalContext` "discrete" injection loses debuggability | MEDIUM | MEDIUM | Add logging; users can check JSONL transcripts; provide config toggle for output format |
| `additionalContext` has undocumented size limits | LOW | HIGH | Smoke test before full migration; fall back to stdout if JSON parsing fails |
| Migration introduces regressions in output format | MEDIUM | MEDIUM | Comprehensive test coverage already exists (90+ tests); dual-mode testing |
| `additionalContext` semantics change in future Claude Code versions | LOW | MEDIUM | Pin to documented behavior; detect via smoke tests in CI |
| Increased complexity of output path (string accumulation vs incremental print) | HIGH | LOW | Well-understood refactoring pattern; contained to single function |

**Overall risk of migration: LOW-MEDIUM.** The primary risk is the unknown "discrete" semantics and potential debuggability loss.

### 5.3 Risk-Benefit Summary

| Path | Risk | Benefit | Recommendation |
|------|------|---------|---------------|
| No change (status quo) | LOW | None (current state preserved) | Acceptable indefinitely |
| `additionalContext` migration | LOW-MEDIUM | Cleaner output model, alignment with codebase convention, future-proofing | Pursue after empirical validation |
| Agent hook adoption | MEDIUM-HIGH | LLM-native judgment (already achieved via judge) | Not justified given current constraints |

---

## 6. Additional Observations

### 6.1 The PoC Correctly Identifies the Redundancy

The PoC states: "The `memory_judge.py` LLM-as-judge already provides the relevance filtering that an agent hook would offer." This is the most important architectural insight in the PoC. The existing judge layer (`memory_judge.py`) effectively embeds an agent hook's capabilities inside a command hook, achieving the best of both worlds:
- Deterministic BM25 for fast candidate retrieval
- LLM judgment for relevance filtering
- Stdout context injection for results delivery

An agent hook would duplicate the judge layer with worse latency and less control.

### 6.2 Missing: Cost Analysis

The PoC mentions token costs (~500-2000 tokens per agent hook invocation) but does not compare this to the existing judge cost. The current `memory_judge.py` makes API calls too -- its token cost should be compared to establish a fair baseline. If the judge already costs ~100-500 tokens per invocation, the agent hook's ~500-2000 tokens represents a 2-20x cost increase for equivalent functionality.

### 6.3 Missing: Failure Mode Comparison

The PoC lists failure modes but does not deeply analyze the fail-open vs fail-closed implications:
- **Command hook failure** (exit non-zero): Hook is skipped, no memory injection. This is fail-open -- the user's prompt proceeds without memory context. Acceptable degradation.
- **Agent hook failure** (timeout, model error): Documented behavior is unclear. If the agent hook times out, does it default to `ok: true` (fail-open) or `ok: false` (fail-closed, blocks the prompt)? The PoC does not investigate this, which is relevant for any future agent hook adoption.

### 6.4 PoC Methodology Concern

The PoC is labeled "Analysis-only PoC -- no production hooks modified, no live executions" (line 5). This is an unusual definition of "PoC" (Proof of Concept). A true PoC would involve at least a minimal live test on the `feat/agent-hook-poc` branch. The Action #4 specification in the plan explicitly calls for:
- "Agent hook latency measurement: 5-10 runs average/p95"
- "Output mechanism test: what is passed to Claude context on ok=true?"
- "Plugin compatibility test: does agent type load normally in hooks.json?"

None of these were empirically executed. The PoC is more accurately described as a "documentation-based analysis" or "desk study." The Gate E checklist at the end of the PoC marks items as "Documented" rather than "Tested," which is honest but does not fully satisfy the original Action #4 specification that called for live experimentation.

However, the analysis quality is high enough that the conclusions are likely correct. The documentation evidence for `additionalContext` is credible, and the parallel-execution constraint is well-established. The risk of incorrect conclusions is low.

---

## Overall Verdict

### PASS WITH NOTES

The PoC delivers a sound architectural analysis with the correct core recommendation: keep the command hook, consider `additionalContext` migration as an incremental improvement, and do not adopt agent hooks for retrieval.

**Strengths:**
1. Correctly identifies the parallel-execution constraint as the dominant architectural barrier to hybrid approaches
2. Discovers the `additionalContext` mechanism with credible documentation evidence
3. Correctly identifies that `memory_judge.py` already provides the functionality an agent hook would offer
4. Provides concrete sample configurations for documentation value
5. Does not modify production code (safe research)

**Weaknesses:**
1. No empirical validation of `additionalContext` behavior (desk study only, despite "PoC" label)
2. Under-estimates the migration cost for `additionalContext` (~20 LOC claimed vs ~40-60 LOC realistic)
3. Does not investigate what "discrete" means for `additionalContext` injection
4. Long-term recommendation is too passive ("monitor changelog" is not actionable)
5. Misses the SessionStart hook as a complementary architecture option
6. Does not compare agent hook failure modes (fail-open vs fail-closed)
7. Does not note the existing codebase convention of using `hookSpecificOutput` in all other hooks

**Recommendations for plan update:**
1. Add a prerequisite smoke test before committing to `additionalContext` migration: output a simple JSON from `memory_retrieve.py`, verify the content appears in Claude's context
2. Revise the migration cost estimate from ~20 LOC to ~40-60 LOC (code) + ~30-50 LOC (tests)
3. Define concrete trigger criteria for long-term re-evaluation (not just "monitor")
4. Note the codebase convention argument: all other hooks already use `hookSpecificOutput`
5. The `feat/agent-hook-poc` branch should be considered for deletion since no experimental code was written on it -- the analysis is purely documentation-based and lives in `temp/`
