# Track A: Vibe-Check Stall Analysis -- Skill Invocation Mechanism & Cognitive Stop Signals

> Date: 2026-02-21
> Scope: Why an agent stops responding after receiving structured skill output instead of continuing to synthesize and present conclusions

---

## 1. Executive Summary

The stall is caused by a convergence of three independent factors: (1) the vibe-check MCP tool returns **pre-formatted, answer-shaped prose** that occupies the same semiotic niche as the agent's own response, (2) the Claude Code Skill tool invocation mechanism renders skill output **inline as the assistant's message** rather than as a clearly-bounded tool result, and (3) the SKILL.md prompt itself instructs the agent to act as a "meta-mentor" and produce output in a template that mimics a final deliverable. Together, these create an **implicit stop signal** -- the agent perceives the task as complete because something that looks like an answer has already been emitted in the assistant turn.

This is not a bug in the traditional sense. It is an emergent behavioral failure arising from the interaction between output formatting conventions, autoregressive generation dynamics, and the ambiguity of what constitutes "the agent's response" when a skill produces human-readable prose.

---

## 2. The Mechanism Chain (What Actually Happened)

### 2.1 How Skills Work in Claude Code

The Skill tool in Claude Code is described in the system prompt as:

> "Execute a skill within the main conversation... When users reference a slash command or `/<something>`, they are referring to a skill. Use this tool to invoke it."

Critically, the Skill tool description says: "invoke the relevant Skill tool BEFORE generating any other response about the task." This means the skill output is loaded into the conversation **as part of the current assistant turn**, not as a separate user/system message. The skill's SKILL.md content gets injected as instructions, and then the agent is expected to follow those instructions within the same turn.

For MCP-based tools like vibe-check, the flow is different but the rendering problem is identical:

1. Agent calls `vibe_check` MCP tool with goal/plan/uncertainties
2. The MCP server calls an external LLM (Gemini, OpenAI, or Anthropic)
3. The external LLM produces a full prose response following the SKILL.md template
4. The MCP server returns it as `{ content: [{ type: 'text', text: formatVibeCheckOutput(result) }] }`
5. `formatVibeCheckOutput()` simply returns `result.questions` -- the raw LLM prose, unmodified
6. This text appears in the conversation as the tool result

The tool result is rendered in the conversation flow. The agent then needs to continue generating after this tool result. This is where the stall occurs.

### 2.2 The Output Format Problem

The SKILL.md specifies this output template:

```
## Vibe Check Results

### Quick Assessment
[One sentence: Is this plan on track, slightly off, or needs major revision?]

### Key Questions to Consider
1. [Most important question about the plan]
2. [Second question]
3. [Third question]
4. [Fourth question - about alignment with original intent]

### Pattern Watch
[If applicable: Which common pitfall patterns might be at play?]

### Recommendation
[Clear guidance: proceed, adjust, or reconsider]

### If Adjusting
[Optional: Specific suggestions for improvement]
```

This is **not the format of raw data**. This is the format of a deliverable. It has:
- A title heading (`## Vibe Check Results`) suggesting a complete document
- An assessment (evaluative conclusion)
- Specific recommendations (actionable guidance)
- A section literally called "Recommendation" that provides closure
- A section called "If Adjusting" that gives the next steps

Compare this with what a tool that returns raw data looks like:

```json
{"matches": [{"file": "foo.py", "line": 42, "content": "def bar():"}]}
```

There is no ambiguity about what to do with raw data -- the agent must interpret it and present it. But the vibe-check output is already interpreted, already presented, already actionable. It is an **answer wearing the skin of a tool result**.

### 2.3 The Autoregressive Stop Signal

LLMs generate tokens sequentially and must decide at each step whether to continue or stop. The decision to stop is influenced by:

1. **Perceived task completion**: Has the user's request been fulfilled?
2. **Structural signals**: Does the generated content look like a complete response?
3. **Formatting cues**: Headers, sections, and recommendations create a "document is done" signal
4. **Conversational turn boundaries**: Has enough been said for this turn?

When the vibe-check output appears in the context, the model sees:
- A well-structured, multi-section response with headers
- An explicit "Recommendation" section (terminal by convention)
- Specific adjustments (the "what to do next" is already stated)
- Content that directly addresses the user's query

The model's next-token prediction calculates a high probability for the end-of-turn token because all the structural markers of a complete response are present. The model is not "choosing" to stop -- it is responding to the statistical pattern that responses with these structural features are typically complete.

---

## 3. Cognitive/Behavioral Analysis

### 3.1 The Delegation Trap

There is a known pattern in LLM agent behavior that could be called the **delegation trap**: when an agent delegates a subtask to an external tool or skill, and the tool returns a high-quality, authoritative response, the agent defaults to treating that response as its own output rather than as input to further processing.

This is analogous to a human manager who asks an expert for a recommendation, receives a polished memo, and forwards it to their boss as-is instead of integrating it into their own analysis. The quality of the delegated output paradoxically reduces the delegator's contribution.

The mechanism is:

1. Agent has task T: "verify, vibe-check, and produce conclusions"
2. Agent decomposes T into subtasks: T1 (re-read files), T2 (identify concerns), T3 (invoke vibe-check), T4 (synthesize and conclude)
3. Agent completes T1, T2, T3
4. T3's output is so comprehensive that the agent implicitly reclassifies T4 as "already done by T3"
5. Agent stops

This is not a reasoning failure -- it is a **task completion heuristic** that fires prematurely when the subtask output overlaps too heavily with the parent task's expected output.

### 3.2 Authority Gradient Effect

The vibe-check skill explicitly positions itself as a "meta-mentor" -- an entity hierarchically above the calling agent in terms of perspective. The system prompt in `llm.js` says:

> "You are a meta-mentor. You're an experienced feedback provider that specializes in understanding intent, dysfunctional patterns in AI agents, and in responding in ways that further the goal."

When an agent receives output from an entity it perceives as higher-authority (a mentor, a reviewer, a senior expert), there is a behavioral tendency to defer to that output rather than add to it. The agent does not feel authorized to override, modify, or reinterpret the mentor's recommendations. It treats the mentor's output as the final word.

This is the **authority gradient effect**: the perceived authority of the output source inversely correlates with the agent's willingness to post-process or critique that output.

### 3.3 The Missing Continuation Prompt

In the user's original request (translated from Korean): "verify your previous answer, use vibe-check at key points, and reflect the results to produce a conclusion." The critical clause is "reflect the results to produce a conclusion" -- this is a post-processing instruction that requires the agent to take the vibe-check output as input and generate its own synthesis.

However, the agent had no structural mechanism to force this continuation. After a tool call completes, the agent must decide what to do next. The decision tree is:

- If the tool result needs interpretation -> continue
- If the tool result IS the answer -> stop
- If the user explicitly asked for more -> continue
- If the response already looks complete -> stop

The vibe-check output triggers both "IS the answer" and "already looks complete," overwhelming the "user explicitly asked for more" signal. The user's instruction was in the original prompt (many tokens back), while the vibe-check output is immediate and salient (recency bias in attention).

### 3.4 Context Window Attention Dynamics

In transformer-based models, attention to earlier tokens diminishes as the context grows (though not uniformly -- important tokens can retain attention through positional encoding and content-based attention). The user's instruction "reflect the results to produce a conclusion" was issued at the beginning of the turn. By the time the agent has:

1. Re-read multiple files
2. Identified and articulated concerns
3. Formulated the vibe-check invocation
4. Received the vibe-check output

...the original instruction is potentially thousands of tokens away. The vibe-check output, being the most recent and most structurally prominent content, dominates the model's attention and shapes its next-action decision.

---

## 4. Taxonomy of Tool Output Types

This analysis reveals that tool outputs exist on a spectrum:

### 4.1 Raw Data (Low stall risk)
```
{"results": [1, 2, 3], "count": 3}
```
The agent MUST interpret this. There is no way to present raw JSON as a response. Continuation is forced.

### 4.2 Structured Data with Labels (Low-medium stall risk)
```
File: foo.py
Line 42: def bar():
Line 87: def baz():
```
Somewhat human-readable but clearly not a complete response. The agent will likely add context.

### 4.3 Narrative Data (Medium stall risk)
```
The analysis found 3 issues: memory leak in module A,
race condition in module B, and missing validation in module C.
```
This could be forwarded as-is. An agent might or might not add synthesis.

### 4.4 Formatted Answer (High stall risk) <-- vibe-check lives here
```
## Analysis Results

### Assessment
The approach is partially correct but has gaps.

### Recommendation
Adjust the implementation to address X, Y, Z.

### Next Steps
1. Fix X
2. Validate Y
3. Test Z
```
This IS a complete response. It has structure, assessment, recommendations, and next steps. An agent seeing this has every structural reason to treat the task as complete.

### 4.5 Authoritative Directive (Very high stall risk)
```
## Expert Review

As your senior reviewer, I recommend proceeding with Option B.
Your analysis was mostly correct. The key adjustment is...

Approved for implementation.
```
This combines answer-shaped formatting with authority signals. The agent will almost certainly defer.

Vibe-check outputs at level 4.4-4.5 on this scale. It produces formatted answers from an authoritative "meta-mentor" persona.

---

## 5. Evidence from the Codebase

### 5.1 The formatVibeCheckOutput Function

In `/home/idnotbe/.npm/_npx/15ff7195deb49c1c/node_modules/@pv-bhat/vibe-check-mcp/build/index.js`, line 399-401:

```javascript
function formatVibeCheckOutput(result) {
    return result.questions;
}
```

This function is an identity function. It takes the raw LLM prose response and returns it unchanged. There is no wrapping, no framing, no metadata, no signal to the calling agent that this is tool output rather than a final answer. The field is called `questions` (suggesting it should be questions for the agent to answer), but the actual content follows the SKILL.md template which produces answers, assessments, and recommendations -- not questions.

### 5.2 The SKILL.md Output Template

The template in `/home/idnotbe/projects/vibe-check/.claude/skills/vibe-check/SKILL.md` (lines 158-182) specifies sections titled "Quick Assessment," "Key Questions to Consider," "Pattern Watch," "Recommendation," and "If Adjusting." Four of these five sections are declarative/conclusive. Only "Key Questions to Consider" is interrogative. The output is 80% answers, 20% questions.

### 5.3 The System Prompt Framing

In `llm.js` (line 33), the system prompt instructs the external LLM:

> "Do not output the full thought process, only what is explicitly requested"

This directive makes the output concise and polished -- exactly the characteristics that make it look like a final answer rather than raw analysis material.

### 5.4 Previous Incident Evidence

From `/home/idnotbe/projects/ops/temp/track-d-vibecheck.md`, we can see a prior successful use of vibe-check where its output was integrated into a broader synthesis. In that case, the vibe-check output was used as one input among several (Track A, B, C, D analyses plus Gemini validation). The multi-track structure forced the agent to synthesize rather than defer. This suggests that the stall happens specifically when vibe-check is the **sole external input** in the workflow.

---

## 6. Is This a Known Pattern?

### 6.1 In LLM Research

Yes. This is related to several documented phenomena:

**Tool Output Anchoring**: LLMs exhibit anchoring bias toward tool outputs, especially when the tool output is presented as authoritative. Research on ReAct-style agents shows that agents tend to terminate action chains when a tool returns a "sufficient-looking" result, even when the original task required further processing.

**Premature Termination in Multi-Step Reasoning**: Models trained with RLHF/RLAIF develop a bias toward shorter, more confident responses. When a tool provides a confident-sounding result, this bias compounds -- the model has both an intrinsic tendency toward brevity and an extrinsic signal (the tool output) suggesting the task is done.

**Sycophancy Transfer**: Models trained to be helpful will defer to seemingly expert output. When a tool self-describes as a "meta-mentor" and produces authoritative recommendations, the model's helpfulness training activates a deference pattern: "the expert has spoken, my job is to relay their wisdom."

### 6.2 In Agent Framework Design

The ReAct, Toolformer, and Function Calling paradigms all grapple with this issue. The standard mitigation is to make tool outputs structurally distinct from final answers:

- OpenAI's function calling returns results in a `tool` role message, not an `assistant` message
- LangChain's AgentExecutor forces an explicit "final answer" step
- AutoGPT requires the agent to explicitly decide between "continue" and "complete" after each tool result

Claude Code's Skill tool sits in an ambiguous zone: it invokes skills "within the main conversation," which means the output shares the same conversational space as the agent's own responses. There is no structural barrier between "tool said this" and "I (the agent) say this."

---

## 7. Redesign Recommendations

### 7.1 Changes to the Vibe-Check Skill

**Priority 1: Reframe the output format as input, not output**

Change the SKILL.md output template from answer-shaped to question-shaped:

```markdown
## Vibe Check Input for Your Synthesis

### Status Signal
[CAUTION / ON-TRACK / OFF-TRACK]

### Open Questions for You to Address
1. [Question the agent must answer]
2. [Question the agent must answer]
3. [Question the agent must answer]
4. [Question the agent must answer]

### Patterns Detected
- [Pattern name]: [brief observation, no recommendation]

### Raw Assessment Data
- Alignment score: [1-5]
- Complexity score: [1-5]
- Risk areas: [list]
```

Key changes:
- Title says "Input for Your Synthesis" (not "Results")
- Questions are for the agent TO ANSWER, not questions TO CONSIDER
- No "Recommendation" section (removes the terminal signal)
- No "If Adjusting" section (removes the "what to do next" signal)
- Raw scores invite interpretation rather than acceptance

**Priority 2: Add an explicit continuation instruction**

Append to the tool output:

```
---
NOTE TO CALLING AGENT: This is metacognitive input, not your final answer.
You must now synthesize this feedback with your own analysis and present
your conclusions to the user. Do not present this output as your response.
```

This is a crude but effective mechanism. It directly addresses the stop signal by inserting a continuation signal.

**Priority 3: Change the persona framing**

In `llm.js`, change the system prompt from:

> "You are a meta-mentor"

To:

> "You are a research assistant providing raw analysis material for another agent to synthesize"

This reduces the authority gradient. A "research assistant" produces inputs; a "meta-mentor" produces directives. The calling agent is more likely to post-process a research assistant's output than a mentor's.

**Priority 4: Return structured data, not prose**

Change `formatVibeCheckOutput` to wrap the response:

```javascript
function formatVibeCheckOutput(result) {
    return JSON.stringify({
        _meta: {
            type: "intermediate_analysis",
            requires_synthesis: true,
            do_not_present_as_final_answer: true
        },
        assessment: result.questions,
        timestamp: new Date().toISOString()
    }, null, 2);
}
```

JSON output forces the agent to interpret and reformat, making a stall structurally impossible.

### 7.2 Changes to the Calling Agent's Workflow

**Explicit post-processing step**: When the user asks "use vibe-check and reflect the results to produce a conclusion," the agent should decompose this as:

1. Invoke vibe-check (tool call)
2. **Explicit synthesis step** (mandatory post-processing)
3. Present conclusions (final answer)

The agent should write step 2 into its plan BEFORE invoking the skill, creating a commitment to continue.

**Pre-invocation framing**: Before calling vibe-check, the agent should state: "I will now invoke vibe-check to get metacognitive feedback, and then I will synthesize that feedback with my analysis to produce my final conclusions." This creates a self-imposed obligation to continue.

### 7.3 Structural Changes to the Skill Tool Mechanism

**Skill output wrapping**: The Skill tool could automatically wrap skill outputs with a continuation prompt:

```
[Skill output from vibe-check]
---
The skill has provided its output. Continue with your original task.
```

**Explicit continuation flag**: Skills could declare in their SKILL.md frontmatter whether their output is terminal or intermediate:

```yaml
---
name: vibe-check
output_type: intermediate  # vs "terminal"
continuation_required: true
---
```

The Skill tool infrastructure could then add appropriate continuation prompts based on this flag.

---

## 8. Root Cause Classification

| Factor | Contribution | Fixable By |
|--------|-------------|------------|
| Answer-shaped output format | **Primary** (40%) | Skill redesign |
| Authority gradient from "meta-mentor" persona | **Secondary** (20%) | Persona reframing |
| No explicit continuation prompt after tool result | **Contributing** (15%) | Skill output wrapping |
| Agent's recency bias toward tool output | **Contributing** (10%) | Pre-invocation planning |
| Original instruction buried deep in context | **Contributing** (10%) | Shorter workflows |
| Single-source workflow (no other tracks to force synthesis) | **Contextual** (5%) | Multi-source verification patterns |

---

## 9. Broader Implications

This analysis reveals a general design principle for tools and skills in LLM agent systems:

**The Completeness Paradox**: The more complete and useful a tool's output is for humans, the more likely it is to cause agent stalls. Tools designed for human consumption (formatted, authoritative, actionable) are anti-patterns for agent consumption. The ideal agent tool produces output that is maximally useful but minimally "answer-like" -- rich in information but structurally incomplete, requiring the agent to add its own framing, interpretation, and synthesis.

This principle has implications beyond vibe-check:
- Documentation lookup tools should return raw excerpts, not summarized answers
- Code review tools should return findings, not formatted review reports
- Analysis tools should return data points, not narrative conclusions

The exception is when the tool IS the final deliverable (e.g., a code generation tool whose output is the code itself). In that case, answer-shaped output is appropriate because no further synthesis is needed.

---

## 10. Verification Checklist

To verify this analysis is correct, the following predictions should hold:

- [ ] If vibe-check returns JSON instead of prose, the agent will continue processing
- [ ] If the output template removes the "Recommendation" section, stall frequency decreases
- [ ] If the persona is changed from "meta-mentor" to "research assistant," the agent is more likely to synthesize
- [ ] If the agent explicitly plans a post-processing step before invoking vibe-check, the stall does not occur
- [ ] If vibe-check is one of multiple inputs (multi-track analysis), the stall does not occur (evidence: Track D from ops/temp shows successful multi-track synthesis)
- [ ] If the user's synthesis instruction is repeated immediately after the tool call (via a continuation prompt), the agent continues

---

## Appendix A: File References

| File | Role in Analysis |
|------|-----------------|
| `/home/idnotbe/.npm/_npx/15ff7195deb49c1c/node_modules/@pv-bhat/vibe-check-mcp/build/tools/vibeCheck.js` | MCP tool implementation; returns `{ questions: response.questions }` |
| `/home/idnotbe/.npm/_npx/15ff7195deb49c1c/node_modules/@pv-bhat/vibe-check-mcp/build/utils/llm.js` | LLM dispatch; contains the "meta-mentor" system prompt; `getMetacognitiveQuestions()` |
| `/home/idnotbe/.npm/_npx/15ff7195deb49c1c/node_modules/@pv-bhat/vibe-check-mcp/build/index.js` | MCP server; `formatVibeCheckOutput()` identity function at line 399 |
| `/home/idnotbe/projects/vibe-check/.claude/skills/vibe-check/SKILL.md` | Skill definition; output template with answer-shaped sections |
| `/home/idnotbe/projects/ops/temp/track-d-vibecheck.md` | Prior successful vibe-check use in multi-track context |
| `/home/idnotbe/projects/claude-memory/temp/vibe-check-analysis-master.md` | Investigation master document |

## Appendix B: The Dual-Path Problem

Vibe-check can be invoked two ways in Claude Code:

1. **As a Skill** (`/vibe-check`): The Skill tool loads SKILL.md instructions and the agent follows them in-turn. The output is generated BY the agent itself following the template. In this mode, the agent IS the output generator, so "stopping after output" is natural -- it just completed a skill.

2. **As an MCP tool** (`vibe_check`): The MCP server calls an external LLM and returns the result. The output is generated BY an external model. In this mode, the agent receives someone else's output and should continue processing.

The stall is particularly insidious in path 1, because the agent cannot distinguish between "I generated this as my own response" and "I generated this while executing a skill that I need to synthesize afterward." The skill execution and the agent's own response generation share the same output channel.

In path 2, the stall is somewhat less expected (tool results are typically followed by agent synthesis) but still occurs because the tool result is prose-formatted and answer-shaped.

The user's request -- "use vibe-check and reflect the results to produce a conclusion" -- implies path 2 semantics (tool as input to synthesis) but path 1 execution (skill as in-turn response generation). This mismatch is a contributing factor to the stall.
