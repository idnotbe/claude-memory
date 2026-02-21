# Vibe-Check Stall Fix -- Practical Verification (Round 2)

> Verifier: Independent practical verifier
> Date: 2026-02-21
> Inputs: vibe-check-analysis-synthesis.md, SKILL.md, Track A/B analyses, comparison with prd-creator/deepscan/memory-management skills

---

## A) Would the XML Framing Fix Actually Work in Practice?

### Verdict: PROBABLY NOT WORTH THE COMPLEXITY. Marginal benefit over a simpler alternative.

**Does Claude Code treat XML differently from Markdown in skill output?**

No, not structurally. The Skill tool in Claude Code works by injecting the SKILL.md content as instructions into the current assistant turn. The agent then generates output following those instructions. Whether the agent outputs XML or Markdown, it is still the agent's own generation within the same turn. Claude Code does not parse or intercept skill output -- it is all just text in the assistant message.

The synthesis claims "Claude treats [XML] as intermediate data, not final response." This is a reasonable intuition about Claude's training data -- XML tags do appear more often in intermediate/structured contexts than as final human-facing output. However, the effect is subtle and unreliable as a primary mechanism. It is a soft statistical signal, not a hard architectural boundary.

**Would XML make the output harder for users to read?**

Yes, somewhat. When `/vibe-check` is invoked directly by a user (not mid-task by an agent), they want to read the results. XML tags like `<vibe_check_analysis><status_signal>CAUTION</status_signal>` are significantly less readable than `### Quick Assessment` with Markdown rendering. The synthesis dismisses this ("minimal -- it's intermediate data") but this is incorrect: the skill IS used interactively by users. The CLAUDE.md for vibe-check confirms it is invoked as `/vibe-check` by users directly.

**Is this a well-tested pattern in Claude Code skills?**

No. I examined three other skills in the same ecosystem (memory-management, prd-creator, deepscan). None of them use XML-wrapped output templates. All use Markdown. The pattern is untested in this context.

**Conclusion on XML framing:** It introduces a new untested pattern, degrades user readability, and provides only a soft statistical nudge. The analysis overvalues this fix because it was the primary recommendation from the Gemini external opinion, but Gemini was reasoning about Claude's behavior from the outside without access to how Claude Code skills actually work.

---

## B) Would the Continuation Directive Actually Prevent the Stall?

### Verdict: YES, this is likely the most effective single fix.

**Where in the SKILL.md would it go?**

It would go after the Output Format section (after line 182 in the current SKILL.md), as both Track B (Fix A) and the synthesis (Fix 2) suggest. This is the right placement because the agent generates the output template first, then encounters the continuation directive immediately after.

**Would the agent even see it after generating the output?**

Yes. This is the critical insight that makes this fix work. Unlike the MCP tool path where the output comes from an external LLM and is returned as a tool result, in the Skill path the SKILL.md is loaded as instructions BEFORE the agent begins generating. The entire SKILL.md is in the agent's context. The continuation directive would be visible throughout the generation process, not just after the output is produced.

However, the effectiveness depends on placement and emphasis. If it is buried at the end of a long document, recency bias (Track A, section 3.4) could still cause the agent to lose track of it. The directive should be:
1. Placed immediately after the Output Format section (not at the very end of the file)
2. Formatted with strong visual emphasis (e.g., `## CRITICAL:` header)
3. Short and direct (not a multi-paragraph explanation)

**Is there precedent for this working in other skills?**

Yes, directly. Track B's comparison table shows:
- prd-creator: Rule #10 "Wait for Input: Never proceed without user confirmation" -- explicit behavioral directive
- deepscan: Multi-phase workflow where each phase chains to the next
- memory-management: 4-phase pipeline with clear "what to do next" at each step

The common pattern is: successful skills include explicit instructions about what happens AFTER the output. Vibe-check is the only skill that omits this.

**Conclusion on continuation directive:** This is the highest-impact fix. The agent reads the entire SKILL.md before generating. A clear, prominent directive saying "this is an intermediate checkpoint, resume your original task" directly addresses the root cause (missing continuation contract).

---

## C) Could There Be a Simpler Fix That Was Overlooked?

### Verdict: YES. There is a one-line fix that was partially identified but not prioritized.

The synthesis identifies three fixes. Track B identifies four fixes. Both analyses correctly diagnose the problem but both overengineer the solution. Here is the minimal fix:

**Option 1: One-line addition at the end of the Output Format section**

After line 182 (end of the output template), add:

```
After outputting the analysis above, resume your original task and apply any adjustments.
```

That is it. One sentence. This directly addresses the single missing element that Track B identified: "the skill has no 'return to caller' contract."

**Option 2: Modify the existing "Special Cases" section**

The existing section at the end of SKILL.md already has behavioral directives ("If no goal/plan is provided: Ask the user...", "If the plan looks solid: Don't invent problems..."). Add one more:

```
**After completing the vibe check:**
Resume your previous task. The vibe check is a reflection pause, not a task completion.
```

This is two sentences added to an existing section, requiring zero structural changes.

**Why was this overlooked?**

The analyses were thorough and intellectually stimulating. They correctly identified the root cause taxonomy and the mechanisms involved. But they converged on multi-part fixes (XML + continuation + persona reframing) because each analyst was incentivized to produce comprehensive recommendations. The simplest fix -- "add one sentence saying to continue" -- is less interesting to write about than "change the output format to XML to exploit Claude's intermediate-data parsing heuristics."

This is, ironically, exactly the kind of pattern vibe-check itself is designed to catch: Complex Solution Bias.

---

## D) Are There Unintended Consequences of the Proposed Fixes?

### XML Wrapping (Fix 1)

**Would it break the MCP tool path?**

No, the MCP tool path is a separate codebase (the npm package `@pv-bhat/vibe-check-mcp`). Changes to SKILL.md do not affect MCP tool output. However, the synthesis discusses fixing "both paths" with the same structural signal, which is misleading -- the MCP path would need separate changes to `formatVibeCheckOutput()` in `index.js`.

**Would it degrade vibe-check quality?**

Possibly. The current Markdown output template is well-designed for readable, structured feedback. Forcing output into XML tags could cause the agent to produce shorter, more telegraphic content inside the tags (XML's structural overhead crowds out natural language). The quality of the analysis could suffer.

**Would users complain?**

Yes. If a user invokes `/vibe-check` directly and sees XML tags in the response, it looks broken. This is a real usability regression, not a theoretical concern.

### Continuation Directive (Fix 2)

**Risk of over-compliance:** The agent might produce the vibe-check analysis AND then immediately start executing changes without presenting the analysis to the user first. The directive should say "resume your original task" not "immediately implement the recommendations." The synthesis's wording ("Resume your original task immediately, applying any adjustments") could be interpreted as "skip presenting the analysis and jump straight to changes."

**Risk in standalone use:** When a user invokes `/vibe-check` directly (not mid-task), there is no "original task" to resume. A directive saying "resume your original task" would be confusing. The directive needs to be conditional: "If you were performing another task when this vibe check was invoked, resume that task."

### Persona Reframing (Fix 3)

**Risk of quality degradation:** The synthesis's recommended reframing -- "Pause your current task to perform a meta-mentor analysis. After the analysis, you will resume your original task" -- is reasonable. It preserves the "meta-mentor" concept while adding the pause/resume framing. However, the original line 13 reads "You are now acting as a **meta-mentor** - an experienced feedback provider specializing in understanding intent, recognizing dysfunctional patterns in AI agent behavior, and providing course corrections." Changing this to include "Pause... After the analysis, you will resume" changes the skill from a role assignment to a workflow instruction. This is the right direction but the wording needs care to preserve the quality-driving aspects of the persona.

---

## E) What Is the MINIMAL Change That Would Fix the Problem?

### The Minimal Fix: Add 3 lines to SKILL.md

Add the following after the Output Format section (after line 182), before the "Core Questions" section:

```markdown
## After Output

This vibe check is a reflection pause, not a task completion. After generating the analysis above, resume whatever task prompted this check.
```

That is the entire fix. Three lines (header + two sentences).

**Why this works:**
1. It directly addresses the root cause: no continuation contract (Track B's finding)
2. It is placed at the exact point where the agent finishes generating the output template and needs to decide what to do next
3. It uses language that is unambiguous: "reflection pause" (not a terminal event) and "resume" (explicit instruction to continue)
4. It does not change the output format, the persona, or any other aspect of the skill
5. It handles both the mid-task case ("resume whatever task prompted this check") and the standalone case (the agent has nothing to resume, so it naturally presents the output and stops -- which is correct behavior for standalone use)

**Why NOT the more complex fixes:**

| Fix | Marginal benefit over minimal fix | Cost |
|-----|-----------------------------------|------|
| XML wrapping | Soft statistical nudge toward "intermediate" perception | Untested pattern, readability regression, user complaints |
| Full continuation directive (8-line version from synthesis) | Slightly more explicit than 2-sentence version | Over-specifies behavior, risk of over-compliance, longer SKILL.md |
| Persona reframing | Reduces authority gradient slightly | Changes skill identity, may degrade quality, requires careful wording |
| Output template restructuring | Removes terminal "Recommendation" signal | Degrades the usefulness of the output for users, major structural change |

The minimal fix has the best benefit-to-risk ratio. If it proves insufficient (the stall persists), the next escalation would be adding the persona reframing (Fix 3 from synthesis), not the XML wrapping.

---

## Summary of Verification Findings

| Question | Answer |
|----------|--------|
| Would XML framing work? | Marginal effect, not worth the downsides |
| Would continuation directive work? | Yes, this is the correct fix |
| Is there a simpler fix? | Yes: 3 lines added after the Output Format section |
| Unintended consequences? | XML: readability regression. Continuation: risk of over-compliance if worded poorly. Persona: quality risk. |
| Minimal viable fix | Add `## After Output` section (2 sentences) after the output template |

### Recommended Action

Edit `/home/idnotbe/projects/vibe-check/.claude/skills/vibe-check/SKILL.md` to add 3 lines after line 182. No other changes needed for the initial fix. Monitor for recurrence before escalating to additional fixes.

### Escalation Path (if minimal fix is insufficient)

1. **First escalation:** Reframe line 13 from "You are now acting as" to "Pause your current task and perform a" (persona reframing)
2. **Second escalation:** Add a `### Next Action` section to the output template (forward-looking closer)
3. **Do not escalate to:** XML wrapping or JSON output (wrong tool for the problem)
