# Cross-Model Validation Round 1

## Gemini 3.1 Pro Analysis (via PAL clink)

### Key Agreement with Opus Analysis
- Hybrid A+C is the most practical approach
- Template-based drafting is viable only for simple/rigid categories
- External process (D) is fragile and complex

### New Ideas NOT in Opus Initial Analysis
1. **Continuous Inline Memory**: Save memories asynchronously DURING the session, use Stop hook only for final silent verification
   - Pro: Distributes workload and noise throughout session
   - Con: May interrupt conversation flow; requires major SKILL.md rewrite

2. **Piggyback on PreCompact**: Hook into PreCompact event to extract memories when context is already being summarized
   - Pro: Natural trigger point; context is being processed anyway
   - Con: Only fires when context gets large; not guaranteed to fire

3. **Next-Session Queue**: SessionEnd hook writes session ID to queue file, next session's UserPromptSubmit processes it
   - Pro: Completely invisible in current session; deferred processing
   - Con: Memory is delayed by one session; may never process if no next session

### Critical Risks Identified
1. **Background agent termination on exit**: Claude Code may kill background tasks when session formally exits — this could mean Approach A's background save gets killed before completing
2. **Context passing bloat**: Passing raw context to background agent via the spawn prompt re-creates the UI noise. MUST use file paths only.
3. **Template brittleness**: For complex categories (decisions, constraints), template-based generation is "profoundly brittle"

### Gemini's Priority Action Items
1. Test if background task survives session exit after stop-block is lifted
2. Verify if Stop hook receives full transcript path (yes — it does, via hook_input.transcript_path)
3. Explore Continuous Inline Memory pattern

## Codex (unavailable — rate limited)

## Synthesis: Updated Ranking

| Rank | Approach | Rationale |
|------|----------|-----------|
| 1 | **A+C Hybrid** | Pre-compute simple drafts in Python, delegate complex to single background agent |
| 2 | **E: Next-Session Queue** (NEW) | Deferred processing is elegant but delayed |
| 3 | **F: Continuous Inline** (NEW) | Good long-term but major architectural change |
| 4 | **G: PreCompact piggyback** (NEW) | Interesting but unreliable trigger |
| 5 | **B: SessionEnd** | Limited by no LLM access |
| 6 | **D: External process** | Too complex |

## Open Questions
- Does background agent survive after stop-block is lifted?
- Can we combine Next-Session Queue with A+C for robustness?
- Is PreCompact hook reliable enough to use as a secondary trigger?
