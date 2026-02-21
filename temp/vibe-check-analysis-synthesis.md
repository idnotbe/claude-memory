# Vibe-Check Stall Analysis - Synthesis

## Sources Analyzed
1. **Track A** (agent behavioral analysis subagent): Root cause taxonomy with % attribution
2. **Track B** (skill design analysis subagent): Comparison with other skills, structural gaps
3. **Gemini 3 Pro** (via pal clink): XML framing recommendation
4. **Codex** (via pal clink): Rate limited, no response

---

## Root Cause Consensus (All 3 Sources Agree)

### Primary Cause: Answer-Shaped Output Format
- Track A: 40% attribution. Output has "Recommendation" section = terminal signal
- Track B: "Only skill in ecosystem that produces terminal output with no continuation contract"
- Gemini: "premature conversation turn completion" due to Markdown-as-final-answer

### Secondary Cause: No Continuation Contract
- Track A: 15% attribution. No structural cue to keep going after tool result
- Track B: Every other skill has multi-phase pipeline, explicit handoff, or interaction loops. Vibe-check has NONE.
- Gemini: "agent needs a push to synthesize and continue"

### Tertiary Cause: Authority Gradient from "Meta-Mentor" Persona
- Track A: 20% attribution. Agent defers to hierarchically-superior output
- Track B: "mentors give advice and then wait... role identity says your job is done"
- Gemini: DISAGREES - says persona is responsible for OUTPUT QUALITY, keep it but change structure

### Contributing: Recency Bias + Single-Source Workflow
- Track A: Original instruction buried thousands of tokens back; vibe-check output is immediate and salient
- Track A: When vibe-check is the ONLY external input, no other tracks force synthesis (vs multi-track pattern)

---

## Fix Recommendations Comparison

| Fix | Track A | Track B | Gemini | My Assessment |
|-----|---------|---------|--------|---------------|
| XML wrapping instead of Markdown | Mentioned (JSON variant) | Not mentioned | **PRIMARY recommendation** | High impact, elegant |
| Continuation directive at end | Priority 2 | Fix A (Post-Output section) | **PRIMARY recommendation** | High impact, simple |
| Change persona from "meta-mentor" | Priority 3 | Fix D | **DISAGREES - keep persona** | Keep persona, agree with Gemini |
| Return JSON data | Priority 4 | Not mentioned | Rejected (degrades quality) | Agree, too extreme |
| Add "Next Action" to template | Not mentioned | Fix B | Not mentioned | Good supplementary |
| Add "Caller Context Awareness" | Not mentioned | Fix C | Not mentioned | Good supplementary |
| Reframe output as "Input for Synthesis" | Priority 1 | Not mentioned | Aligned (via XML framing) | Core principle |

---

## Key Insight: The Completeness Paradox (Track A)
"The more complete and useful a tool's output is for humans, the more likely it is to cause agent stalls."

This is an important design principle for ALL skills, not just vibe-check.

## Key Insight: XML as Sweet Spot (Gemini)
- JSON: too machine-like, degrades reasoning quality
- Markdown: too answer-like, causes stalls
- XML: Claude treats as intermediate data, not final response. Best of both worlds.

## Key Insight: Dual-Path Problem (Track A)
Vibe-check can be invoked as:
1. **Skill** (SKILL.md loaded, agent follows instructions) - agent IS the output generator
2. **MCP tool** (external LLM generates) - agent RECEIVES external output

The stall mechanism differs slightly between paths but the fix is the same: output structure must signal "intermediate, not final."

---

## Recommended Minimal Fix (Synthesized)

### Fix 1: XML framing in output (HIGH IMPACT)
Change SKILL.md output template from Markdown headers to XML-wrapped:

```xml
<vibe_check_analysis>
  <status_signal>[ON-TRACK / CAUTION / OFF-TRACK]</status_signal>
  <assessment>[one sentence]</assessment>
  <questions>
    1. [question]
    2. [question]
  </questions>
  <patterns>[detected patterns]</patterns>
  <recommendation>[guidance]</recommendation>
  <adjustments>[if any]</adjustments>
</vibe_check_analysis>
```

### Fix 2: Continuation directive at end of template (HIGH IMPACT)
Add to SKILL.md after the output template:

```markdown
## CRITICAL: Post-Output Behavior

After generating the vibe check analysis above:
1. This analysis is an INTERMEDIATE checkpoint, not your final response
2. You MUST synthesize the findings into your own conclusions
3. Resume your original task immediately, applying any adjustments
4. Do NOT present the vibe check output as your complete response

The vibe check is a pause for reflection. After reflection, continue working.
```

### Fix 3: Reframe identity as pause, not role switch (MEDIUM IMPACT)
Change from:
> "You are now acting as a meta-mentor"

To:
> "Pause your current task to perform a meta-mentor analysis. After the analysis, you will resume your original task."

---

## What NOT to change
- Keep the "meta-mentor" persona concept (Gemini's point: it drives quality)
- Don't switch to pure JSON (degrades reasoning quality)
- Don't remove the Recommendation section entirely (useful guidance)

---

## Verification Questions
1. Would XML framing actually prevent the stall? (testable prediction)
2. Would the continuation directive alone be sufficient? (probably yes for most cases)
3. Is there a risk that XML makes the output less readable for users who see it? (minimal - it's intermediate data)
4. Does this fix also work for the MCP tool path? (yes, same structural signal)
