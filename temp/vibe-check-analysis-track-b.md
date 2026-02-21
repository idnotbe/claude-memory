# Vibe-Check Skill: Why Agents Stop After Receiving Its Output

## Summary of Finding

The vibe-check skill's SKILL.md creates a strong "conversation terminus" pattern. Its output format is a self-contained report with a final `### Recommendation` section that reads like a closing statement. There is **zero guidance** telling the calling agent what to do after receiving the results. Combined with the skill's identity as a "meta-mentor" (advisory, not operational), the output signals "I have spoken, now the ball is in your court" -- but the agent interprets that as "task complete, stop."

---

## 1. The Output Format Creates an Implicit "Done" Signal

The prescribed output template (SKILL.md lines 160-182):

```
## Vibe Check Results

### Quick Assessment
[One sentence]

### Key Questions to Consider
1-4 questions

### Pattern Watch
[pitfall analysis]

### Recommendation
[Clear guidance: proceed, adjust, or reconsider]

### If Adjusting
[Optional: suggestions]
```

**Problems:**

- **`### Recommendation` is psychologically terminal.** A recommendation is a conclusion. It wraps up an analysis. When the agent generates this section, it has produced a coherent, closed-form response. The LLM's next-token prediction strongly favors stopping after a recommendation because that is how advisory documents end.

- **No "Next Steps for You" section.** The output template ends at `### If Adjusting` with optional suggestions. There is no section like "Now apply these findings to your plan" or "Return to your original task with these adjustments." The agent has no explicit instruction to resume its pre-skill work.

- **Headers create structural completeness.** The 5-section format (Assessment, Questions, Pattern Watch, Recommendation, If Adjusting) mirrors a complete report structure. The agent perceives it as a finished deliverable, not an intermediate checkpoint.

## 2. The Skill Has No "Return to Caller" Contract

Compare the vibe-check SKILL.md to other skills in the ecosystem:

| Skill | Has Post-Output Instructions | Mechanism |
|-------|------------------------------|-----------|
| **vibe-check** | **No** | Ends at output template. Nothing says "after producing this, continue with X." |
| **memory-management** | Yes (implicit) | Phase 0-3 pipeline means the skill is always mid-workflow. The agent knows it must proceed to the next phase. |
| **scaffold** (fractal-wave) | Yes (explicit) | "Step 3: Execute -- Follow the loaded Phase Brief instructions." Clear handoff to next action. |
| **prd-creator** | Yes (explicit) | A/P/R/C menu system forces continued interaction. Rule #10: "Wait for Input: Never proceed without user confirmation." |
| **guardian config-guide** | Yes (implicit) | Every operation ends with a confirmation step or an offer ("Want it as an ask-confirm instead?"). |
| **deepscan** | Yes (explicit) | Multi-phase workflow (init -> scout -> chunk -> MAP -> REDUCE -> export). Each phase chains to the next. |

The vibe-check skill is the **only** skill in the ecosystem that produces a terminal output with no continuation contract.

## 3. The "Meta-Mentor" Role Reinforces Stopping

SKILL.md line 13 sets the identity:

> "You are now acting as a **meta-mentor** - an experienced feedback provider..."

This is a fundamentally advisory role. Mentors give advice and then wait. They do not execute. The skill explicitly frames itself as someone who provides feedback, not someone who acts on it. When the agent finishes producing the vibe-check output, its role identity says "you are a feedback provider" -- which means "your job is done once you have provided feedback."

Compare this with prd-creator which says "You are a professional Product Manager **collaborating** with users" -- the collaborative framing implies ongoing work.

## 4. The "Special Cases" Section Reinforces Early Termination

SKILL.md lines 209-220:

```
**If the plan looks solid:**
Don't invent problems. Acknowledge it's well-thought-out and give approval to proceed.
```

This tells the agent that in the positive case, the correct action is to **give approval and stop**. "Give approval to proceed" is a terminal action -- the agent has approved, its job is done. There is no "...and then resume execution of the plan."

## 5. No Explicit "Integration Point" With the Calling Context

The skill is invoked via `/vibe-check` with arguments. But the SKILL.md never acknowledges that:
- The caller may have been mid-task when invoking the skill
- The caller should return to whatever it was doing before
- The vibe-check output is an intermediate artifact, not the final deliverable

The skill treats itself as a standalone interaction, not as a subroutine within a larger workflow. There is no concept of "the thing the agent was doing before it invoked vibe-check."

## 6. Structural Comparison: What Other Skills Do Differently

### memory-management (multi-phase pipeline)
The skill is structured as Phase 0 -> Phase 1 -> Phase 2 -> Phase 3. The agent is always inside a pipeline with a clear next step. It cannot "stop" because it has not reached Phase 3 yet.

### scaffold (explicit handoff)
After detecting state and loading context, the skill says: "Step 3: Execute -- Follow the loaded Phase Brief instructions." This is a clear handoff that prevents stopping.

### prd-creator (menu system)
Every step ends with an A/P/R/C menu that requires user input. The agent cannot stop because it is always waiting for a menu choice.

### guardian config-guide (action-response pairs)
Every operation (block, protect, unblock, troubleshoot) ends with a confirmation or follow-up offer. The agent always has one more thing to say.

**The common pattern:** Successful skills either (a) have a multi-phase pipeline that keeps the agent moving, (b) have explicit handoff instructions, or (c) have interaction loops that prevent premature termination.

Vibe-check has none of these.

## 7. The Root Cause

The vibe-check skill was designed as a **document template** (produce a structured report), not as a **workflow step** (produce output, then do something with it). The SKILL.md tells the agent *what to output* but not *what to do after outputting it*. Since the output is a complete, well-structured advisory report, the agent's natural behavior is to present it and stop.

## 8. Recommended Fixes

### Fix A: Add a "Post-Output" section to SKILL.md

After the Output Format section (after line 182), add:

```markdown
## After Producing Output

After generating the Vibe Check Results:
1. Present the results to the user/caller
2. If this was invoked mid-task, explicitly state: "Returning to [original task]"
3. Apply any "proceed" or "adjust" recommendations to the current plan
4. Resume the interrupted workflow

Do NOT treat the vibe check output as a final response. The vibe check is an intermediate checkpoint, not a deliverable.
```

### Fix B: Modify the output template to include a continuation signal

Change the output template to end with:

```markdown
### Next Action
[Based on the recommendation above: what the caller should do now.
 If "proceed" -- state "Continue with the current plan."
 If "adjust" -- state "Revise the plan as follows before continuing: ..."
 If "reconsider" -- state "Pause implementation and reconsider: ..."]
```

This makes the output format itself forward-looking rather than terminal.

### Fix C: Add a "Caller Context" section

Before the Evaluation Framework, add:

```markdown
## Caller Context Awareness

This skill is typically invoked mid-task. After producing your feedback:
- You are still the same agent working on the same task
- The vibe check is a pause for reflection, not a task completion
- After outputting results, immediately return to the task that prompted the check
```

### Fix D: Change the identity framing

Instead of:
> "You are now acting as a **meta-mentor**"

Use:
> "Pause your current task and perform a **meta-mentor analysis**. After the analysis, resume your task."

This frames vibe-check as an interruption/pause pattern rather than a role switch.

---

## Relevant Files

- **Skill definition:** `/home/idnotbe/projects/vibe-check/.claude/skills/vibe-check/SKILL.md` (220 lines)
- **Plugin manifest:** `/home/idnotbe/projects/vibe-check/.claude-plugin/plugin.json`
- **Architecture doc:** `/home/idnotbe/projects/vibe-check/ARCHITECTURE.md`
- **Project instructions:** `/home/idnotbe/projects/vibe-check/CLAUDE.md`

## Key Lines in SKILL.md

| Line(s) | Content | Issue |
|---------|---------|-------|
| 13 | "You are now acting as a **meta-mentor**" | Role identity implies advisory-only, reinforces stopping |
| 160-182 | Output Format template | Terminal structure with `### Recommendation` as closing section |
| 178-179 | "### Recommendation / [Clear guidance: proceed, adjust, or reconsider]" | Recommendation = conclusion = stop signal |
| 181-182 | "### If Adjusting / [Optional: Specific suggestions]" | Optional section means the agent may skip it, making Recommendation the last thing it outputs |
| 215-216 | "Don't invent problems. Acknowledge it's well-thought-out and give approval to proceed." | Positive case = approve + stop |
| (absent) | No post-output instructions | No mechanism to resume caller's workflow |
