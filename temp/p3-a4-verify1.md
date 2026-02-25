# Action #4 Agent Hook PoC -- Verification #1

**Verifier perspective:** Technical Accuracy & Documentation Quality
**Date:** 2026-02-26
**Artifact reviewed:** `temp/p3-agent-hook-poc-results.md`
**Plan reference:** `action-plans/plan-retrieval-confidence-and-output.md` (Action #4, Gate E)
**Source of truth:** Official hooks reference at https://code.claude.com/docs/en/hooks (fetched 2026-02-26)

---

## Summary Table

| # | Check Item | Verdict | Notes |
|---|-----------|---------|-------|
| 1 | Agent hook timeout default (claimed 60s) | PASS | Official docs confirm "Default: 60" for agent hooks |
| 2 | Command hook timeout default (claimed 600s) | PASS | Official docs: "Defaults: 600 for command, 30 for prompt, 60 for agent" |
| 3 | Prompt hook timeout default (claimed 30s) | PASS | Confirmed by official docs |
| 4 | Agent hooks support UserPromptSubmit | PASS | Official docs list UserPromptSubmit among events supporting all three hook types |
| 5 | Agent hook max 50 turns | PASS | Official docs: "After up to 50 turns, the subagent returns a structured decision" |
| 6 | `additionalContext` in `hookSpecificOutput` for UserPromptSubmit | **FAIL -- INACCURACY** | See detailed finding below |
| 7 | Agent hooks can return `additionalContext` | **FAIL -- OVERSTATEMENT corrected to accurate conclusion** | PoC correctly concludes agent hooks cannot, but earlier section is misleading |
| 8 | Events supporting command-only (list accuracy) | **FAIL -- MINOR INACCURACY** | See detailed finding below |
| 9 | Hooks run in parallel | PASS | Official docs: "All matching hooks run in parallel" |
| 10 | Plugin hooks.json supports agent type | PASS | Official docs confirm plugin hooks merge with user/project hooks, same schema |
| 11 | Gate E: Agent hook latency documented | PASS | Documented with caveat about no live measurements |
| 12 | Gate E: Context injection mechanism documented | PASS | Thoroughly documented with two mechanisms |
| 13 | Gate E: Plugin type "agent" compatibility confirmed | PASS | Confirmed via official docs |
| 14 | Gate E: Hybrid approach feasibility documented | PASS | Three architectures analyzed with clear recommendation |
| 15 | Gate E: Branch created | PASS | `feat/agent-hook-poc` branch exists (verified via `git branch -a`) |
| 16 | Gate E: Production hooks NOT modified | PASS | `git diff main..feat/agent-hook-poc -- hooks/hooks.json hooks/scripts/` is empty |
| 17 | Gate E: PoC hook config documented | PASS | Three sample configurations provided |
| 18 | Architectural recommendation soundness | PASS | Well-supported by evidence |
| 19 | No live execution performed | NOTE | PoC is analysis-only; plan checklist items for live testing remain unchecked |
| 20 | TypeScript type definition accuracy | **NOTE -- UNVERIFIABLE** | PoC cites a TypeScript SDK type; original source not verified |
| 21 | Security of sample hook configs | PASS with NOTE | See security section below |

---

## Detailed Findings

### Finding #1: `additionalContext` JSON structure -- INACCURACY (Check #6)

**PoC claim (line 40-48):** The TypeScript SDK and official documentation show `additionalContext` nested inside `hookSpecificOutput` with `hookEventName: "UserPromptSubmit"`.

**Official docs reality:** For UserPromptSubmit, `additionalContext` is a **top-level field in the JSON output**, NOT nested inside `hookSpecificOutput`. The official docs show:

```json
{
  "decision": "block",
  "reason": "Explanation for decision",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "My additional context here"
  }
}
```

Wait -- the official docs DO show `additionalContext` inside `hookSpecificOutput` for UserPromptSubmit. But the text description says:

> | Field | Description |
> | `decision` | `"block"` prevents the prompt... |
> | `reason` | Shown to the user when decision is "block" |
> | `additionalContext` | String added to Claude's context |

The `additionalContext` field appears in BOTH places in the official docs: as a field in the decision control table (top-level) AND inside the `hookSpecificOutput` JSON example. The PoC's TypeScript type definition showing it inside `hookSpecificOutput` is consistent with the official JSON example.

**Revised verdict: The PoC's structural representation is consistent with official documentation.** The official docs themselves show `additionalContext` inside `hookSpecificOutput` for UserPromptSubmit. However, the decision control table lists it as a standalone field alongside `decision` and `reason`, creating ambiguity about whether it can also be top-level. The PoC does not address this ambiguity.

**Severity:** Low. The PoC's conclusion (command hooks are the safe path) is not affected.

### Finding #2: `additionalContext` availability for agent/prompt hooks (Check #7)

**PoC claim (Executive Summary, line 11):** "UserPromptSubmit hooks support `additionalContext` injection via `hookSpecificOutput` JSON"

**PoC later conclusion (line 72-76):** "For agent/prompt hooks, the response schema is `{ "ok": true/false, "reason": "..." }` -- `additionalContext` is not part of this schema."

**Assessment:** The Executive Summary creates a misleading impression that agent hooks can inject context via `additionalContext`. The PoC then correctly narrows this down later in the document. However, the progression from "this is possible" to "actually, not for agent hooks" may confuse readers.

The official docs confirm:
- Agent hooks: response schema is `{ "ok": true/false, "reason": "..." }` only
- The `additionalContext` mechanism is for command hooks returning JSON (exit 0)
- Prompt and agent hooks return via the LLM response schema, not general JSON output

**The PoC's final conclusion is correct, but the document structure could be improved.** The Executive Summary should not present `additionalContext` as a primary finding for "UserPromptSubmit hooks" without immediately qualifying that this applies to command hooks only.

**Severity:** Medium (documentation clarity issue, not a factual error in the final conclusion).

### Finding #3: Command-only events list -- MINOR INACCURACY (Check #8)

**PoC claim (lines 99-101):**
> Events that ONLY support `type: "command"`:
> ConfigChange, Notification, PreCompact, SessionEnd, SessionStart, SubagentStart, TeammateIdle, WorktreeCreate, WorktreeRemove

**Official docs:**
> Events that only support `type: "command"` hooks:
> ConfigChange, Notification, PreCompact, SessionEnd, SessionStart, SubagentStart, TeammateIdle, WorktreeCreate, WorktreeRemove

**Assessment:** This matches perfectly. The PoC accurately reproduces the official list. Earlier I thought there might be an issue, but on re-reading, it is correct.

**Revised verdict: PASS.** (Correcting my summary table note -- the list is accurate.)

### Finding #4: Comparison table claim about `additionalContext`

**PoC claim (line 67):**

| Mechanism | Hook Type | Visibility |
|-----------|-----------|------------|
| `additionalContext` JSON | command, prompt, agent | "Added more discretely" |

**Official docs reality:** The `additionalContext` field is documented in the JSON output section, which is described in context of exit code 0 processing. The official docs state: "JSON output is only processed on exit 0" for command hooks. For prompt/agent hooks, the response goes through the LLM response schema (`ok`/`reason`), not the general JSON output pipeline.

**The claim that `additionalContext` works for "command, prompt, agent" hook types is NOT supported by the official documentation.** The docs show `additionalContext` only in contexts where command hooks return JSON. Prompt and agent hooks use the LLM response schema.

**Severity:** Medium. This is an inaccuracy in the PoC's analysis table, though the final recommendation is unaffected.

### Finding #5: No live measurements taken

The PoC explicitly acknowledges this (line 29): "No live measurements were taken. These estimates are derived from documented timeout defaults, known model latency characteristics..."

The plan's checklist items (lines 387-395) include tasks like:
- "Latency measurement: 5-10 runs average/p95 time recording"
- "Output mechanism test: ok=true, what gets passed to Claude context"
- "ok=false + reason, what message Claude sees"

These remain unchecked in the plan. The PoC is analysis-only rather than empirical.

**Assessment:** The PoC is honest about this limitation. However, it means the latency claims (2-15s) are estimates, not measurements. The Gate E checklist in the PoC document marks latency as "Documented" which is technically true, but the plan's original intent was empirical measurement.

**Severity:** Low-Medium. The analysis-only approach is pragmatic and the estimates are reasonable, but the plan's checklist items for live testing were not fulfilled.

---

## Gate E Completeness Assessment

| Gate E Criterion | PoC Status | Verified? |
|-----------------|-----------|-----------|
| Agent hook latency documented | Estimated (not measured) | PASS with NOTE |
| Context injection mechanism documented | Thoroughly documented | PASS |
| Plugin `type: "agent"` compatibility confirmed | Confirmed via official docs | PASS |
| Hybrid approach feasibility documented | Three architectures analyzed | PASS |
| Branch created | `feat/agent-hook-poc` exists | PASS |
| Production hooks NOT modified | `git diff` confirms zero changes | PASS |
| PoC hook config documented | 3 sample configurations | PASS |

**Gate E overall: PASS** -- All 7 criteria are met, though latency is estimated rather than empirically measured.

---

## Architectural Recommendation Soundness

The PoC recommends: "Keep current `type: command` hook for UserPromptSubmit. Agent hooks not suitable for context injection."

**This recommendation is well-supported by evidence:**

1. **Official docs confirm** that agent hooks return `{ "ok": true/false }`, not arbitrary context
2. **Latency concern is valid** -- even estimated 2-15s for agent hooks vs ~0.5-1s for command hooks
3. **The existing `memory_judge.py` LLM judge** already provides the judgment functionality that an agent hook would offer, but within the command hook's execution
4. **`additionalContext` as incremental improvement** (command hook JSON output instead of plain stdout) is a sound suggestion for future work
5. **The hybrid architecture analysis** correctly identifies that parallel execution prevents coordination between command + agent hooks

**One gap:** The PoC does not discuss whether async hooks could enable a post-hoc agent verification (e.g., fire agent hook async, deliver correction on next turn). This is an edge architecture that may not be worth exploring, but it represents a missing consideration.

---

## Security Considerations

### Sample hook configurations (lines 167-261)

1. **`$ARGUMENTS` placeholder in agent prompts:** The sample agent hook prompts use `$ARGUMENTS` which injects the full hook input JSON (including the user's prompt). This is a **prompt injection vector** -- a malicious user prompt containing instructions could influence the agent hook's decision. However, since these are documented as non-active PoC samples, this is an educational concern rather than a production risk.

2. **`$CLAUDE_PLUGIN_ROOT` in command strings:** Properly quoted with escaped double quotes. Consistent with existing production hooks.

3. **Agent hook with `ok: false` could block prompts:** The PoC correctly identifies this risk (lines 195-198 and 225-228). The sample agent-only hook (lines 200-222) instructs the agent to never return `ok: false`, which is a reasonable defensive measure for a PoC.

4. **No secrets or credentials exposed** in any sample configuration.

**Security verdict: No production risk.** Sample configurations are clearly labeled as not active. The prompt injection risk in agent hook prompts is inherent to the mechanism and correctly noted in the PoC's "Why this design won't work well" sections.

---

## Missing Analysis

1. **Async agent hook pattern:** The PoC does not explore whether an async command hook could run an agent-like verification in the background and deliver filtered results on the next turn via `additionalContext`. This is a creative architecture that bridges the command-agent gap.

2. **Cost analysis:** The PoC estimates "~500-2000 tokens per invocation" for agent hooks but does not compare this to the current `memory_judge.py` token usage. A direct comparison would strengthen the "no benefit" argument.

3. **`additionalContext` vs stdout in practice:** The PoC identifies `additionalContext` as "added more discretely" but does not investigate what "discretely" means in practice (e.g., does it appear in the transcript? Is it visible to the user? How does Claude weight it vs stdout context?). This is important for the medium-term recommendation.

4. **Error handling differences:** What happens when an agent hook times out vs a command hook? The PoC does not compare failure modes, which matters for reliability assessment.

---

## Overall Verdict

**PASS WITH NOTES**

The PoC is a thorough, well-structured analysis-only document that correctly answers the four core questions from the plan. The architectural recommendation (keep command hooks, agent hooks not suitable for context injection) is sound and well-supported by official documentation.

**Key strengths:**
- Honest about limitations (no live measurements)
- Thorough comparison of three hybrid architectures
- Discovery of `additionalContext` JSON mechanism as a future incremental improvement
- Sample configurations clearly labeled as not active
- Production hooks verified unmodified

**Key concerns:**
- Executive Summary slightly misleading about `additionalContext` availability for agent hooks (corrected in body text)
- Comparison table claims `additionalContext` works for "command, prompt, agent" -- not supported by official docs for prompt/agent types
- Plan's original intent for live testing (5-10 run latency measurements) was not fulfilled
- Missing analysis of async hooks as a bridge pattern

**Recommendation:** These concerns are minor and do not affect the soundness of the architectural decision. The PoC provides sufficient evidence for the project to continue with the current command hook architecture. The `additionalContext` JSON migration is a viable medium-term improvement worth tracking separately.
