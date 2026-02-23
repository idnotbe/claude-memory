# V1 UX/Usability Review: Guardian-Memory Conflict Fix Design

**Reviewer:** v1-ux-reviewer
**Date:** 2026-02-22
**Inputs:** guardian-conflict-memory-side.md, guardian-conflict-fix-design.md
**External sources:** Gemini (via pal clink) on security dialog UX best practices

---

## Checklist Assessment

### 1. Problem Severity: 7 Popups in 20 Hours

**Rating: HIGH severity**

Seven interruptive confirmation popups across a 20-hour period translates to roughly 1 popup every 2.9 hours. UX research on developer security tools (confirmed by Gemini analysis) indicates that **1-2 false positive interruptions per day** is the threshold where "confirmation fatigue" or "habituation" sets in -- developers begin blindly approving all dialogs without reading them.

At 7 popups / 20 hours, this system is operating right at the danger zone. The critical risk: once a developer habituates to dismissing these popups, they will also approve **genuine** security threats. The guardian tool's entire value proposition depends on users trusting that popups are meaningful. Each false positive erodes that trust.

Additional UX factors:
- These popups are **blocking** -- they halt the entire Claude Code session until the user responds
- They occur during background memory consolidation (the Stop hook), so they appear to interrupt unpredictably rather than as a response to explicit user action
- The user has no easy way to distinguish "false positive from memory plugin" vs "real guardian alert" without reading the full command

**Verdict: This is a real usability problem that demands a fix. Left unaddressed, it will undermine the guardian's effectiveness system-wide.**

---

### 2. Fix C1 Effectiveness: Will Strengthening SKILL.md Wording Reduce Non-Compliance?

**Assessment: PARTIALLY EFFECTIVE -- necessary but insufficient alone**

Evidence supporting the change:
- The proposed switch from positive framing ("MUST use Write tool") to negative framing ("FORBIDDEN from using Bash tool") aligns with prompt engineering findings. LLMs -- especially smaller models like Haiku -- treat positive instructions as preferences they may override, but treat explicit prohibitions ("FORBIDDEN", "NEVER", "PROHIBITED") as hard constraints.
- The addition of a concrete anti-pattern example ("DO NOT DO THIS" code block) provides pattern-matching that smaller models can use to detect when they are about to violate the rule.

Evidence limiting effectiveness:
- The current mandate already exists and is clear to a human reader. The problem is not ambiguity but **model capability** -- Haiku-tier models have limited instruction-following fidelity, especially in multi-step task contexts.
- No instruction wording change can guarantee 100% compliance from an LLM. The compliance rate may improve from, say, 70% to 85%, but there will always be residual violations.
- The 7 incidents suggest a systematic tendency, not an occasional lapse.

**Recommendation: Implement C1 (low cost, some benefit), but do not rely on it as the primary fix. It shifts the baseline but does not eliminate the problem class.**

---

### 3. Fix C2 UX: Deny Message Quality and Subagent Behavior

**Assessment: GOOD deny message design, with one concern**

The proposed deny message from `memory_staging_guard.py`:

> "Bash writes to .claude/memory/.staging/ are blocked. Use the Write tool instead: Write(file_path='.claude/memory/.staging/<filename>', content='<json>')"

This message satisfies the three-component standard for actionable denials:
1. **What was blocked:** "Bash writes to .claude/memory/.staging/"
2. **Why:** "are blocked" (policy enforcement -- though a brief reason like "to avoid guardian false positives" would be better)
3. **How to fix it:** "Use the Write tool instead: Write(file_path=..., content=...)"

The concrete `Write(file_path=..., content=...)` example is particularly good because it gives the subagent an executable pattern to follow in the retry.

**Concern: Subagent retry behavior.** When a PreToolUse hook returns `deny`, Claude Code prevents the tool call from executing and shows the deny reason to the agent. The subagent should then retry with the Write tool. However:
- Will Haiku-tier subagents reliably parse the deny message and switch to the Write tool?
- If the subagent retries with the same Bash approach, the deny fires again, creating a retry loop.
- There is no documented maximum retry limit behavior for PreToolUse denials in Claude Code.

**Recommendation: The deny message is well-designed. Add a brief "why" clause. Monitor whether subagents actually recover correctly from the denial or enter retry loops. If retry loops occur, this is a signal to move toward Option E (stdout extraction).**

---

### 4. Fix A/B Transparency: Behavioral Changes After Guardian Fix

**Assessment: NO negative UX impact expected**

After implementing Option A (heredoc-aware `split_commands`) and Option B (quote-aware `is_write_command`):
- **What changes for the user:** Fewer false confirmation popups. This is purely beneficial.
- **What stays the same:** Genuine dangerous commands (actual file writes via redirection, actual `.env` access) continue to trigger popups because the command line itself (the line containing `> file`) is still analyzed.
- **Risk of false negatives:** Could a genuine dangerous heredoc now be silently allowed? No -- the design correctly still analyzes the command line. Only the heredoc **body** (which is stdin data, not executable commands) is excluded from sub-command splitting. A heredoc body containing `rm -rf /` is literally just text being piped to stdin -- it is not dangerous in that context.

One edge case worth noting: if someone constructs `bash << 'EOF'\nrm -rf /\nEOF`, the body IS executed. However, this is correctly handled because:
- The command itself (`bash << 'EOF'`) is still analyzed
- A `bash` command being piped arbitrary content via heredoc should already be flagged by other guardian heuristics (execution of stdin)

**Verdict: The behavioral change is entirely positive. No transparency concerns.**

---

### 5. Implementation Priority: Is C1 -> C2 -> A -> B Optimal?

**Assessment: YES, this is the correct priority order for fastest UX improvement**

Rationale:

| Step | Impact on user | Time to deploy | Dependency |
|------|---------------|---------------|------------|
| C1 (SKILL.md wording) | Reduces popup frequency by improving compliance | 15 min | None |
| C2 (Memory staging guard) | Eliminates remaining non-compliant attempts with actionable deny | 30 min | None |
| A (Heredoc parser) | Fixes root cause for all heredoc users | 2-3 hours | Different repo |
| B (Quote awareness) | Fixes separate class of false positives | 30 min | Depends on A being in progress |

The ordering follows the "shift-left" security UX principle: fix at the source of generation first (C1), add enforcement at the plugin boundary second (C2), then fix the global parser (A/B). Steps C1 and C2 can be deployed immediately within the memory plugin repo without any changes to the guardian, giving the user immediate relief.

**One optimization:** C1 and C2 are independent and could be implemented simultaneously rather than sequentially.

---

### 6. Hook Ordering: Could the User See TWO Popups for One Command?

**Assessment: YES, this is a real risk -- but the impact is manageable**

The fix design document acknowledges this (Option C, "Hook Ordering Caveat"): Claude Code does not guarantee inter-plugin hook execution order. Two scenarios:

**Scenario A: Guardian fires first, memory guard fires second**
- Guardian shows an ASK popup ("could not resolve target paths")
- If user approves, memory guard then denies
- User sees: one popup (guardian) + one deny message (memory guard) = two interruptions
- This is confusing -- the user approved a command that then gets denied anyway

**Scenario B: Memory guard fires first, Guardian never sees it**
- Memory guard denies the command before execution
- Guardian hook may or may not fire (depends on whether Claude Code short-circuits after a deny)
- User sees: one deny message = good UX

**Scenario C: Both return deny**
- Both hooks deny for different reasons
- User sees either one or two deny messages depending on Claude Code's hook aggregation behavior

The fix design correctly notes the memory guard is "best-effort secondary defense." In practice, once the guardian is fixed (Option A), the memory guard becomes the sole enforcement layer for this specific case, eliminating the dual-popup concern.

**Recommendation: Accept the short-term risk of occasional dual popups. Document this as a known transitional artifact. The memory guard's deny is still preferable to the guardian's ASK popup because a deny is silent to the user (no manual approval needed) -- it just redirects the subagent. Verify whether Claude Code stops hook chain execution after a deny.**

---

### 7. Long-Term UX: Would Option E (Stdout Extraction) Be Better?

**Assessment: YES for UX, but NOT justified right now**

Option E's UX advantages:
- **Zero tool calls for staging writes** -- subagents return JSON inline, the orchestrator writes
- **No Bash involvement** -- eliminates the entire class of guardian/memory conflicts
- **Fewer tool calls visible in the UI** -- each memory save currently shows Write + Bash calls; Option E reduces this to just the orchestrator's Write call
- **Higher reliability** -- LLMs are better at producing text output than correctly choosing between tools

Option E's UX risks:
- **Fragile XML parsing** -- if the subagent doesn't close XML tags correctly, the entire draft is lost
- **Orchestration complexity** -- the main agent needs to parse subagent responses, adding a failure mode
- **Behavior change** -- the current pipeline is well-understood; Option E changes the flow

**Recommendation: Option E is the architecturally correct long-term solution. However, implementing C1 + C2 now and A + B in the guardian resolves the immediate problem. Revisit Option E when the memory consolidation pipeline is next refactored, or if C2 reveals persistent subagent retry-loop issues.**

---

## UX Recommendations Summary

1. **Implement C1 + C2 immediately** -- they are independent, low-risk, and address the user-facing symptom within the memory plugin's control.

2. **Enhance the C2 deny message** -- add a brief "why" clause:
   > "Bash writes to .claude/memory/.staging/ are blocked to prevent guardian false positives. Use the Write tool instead: ..."

3. **Monitor subagent recovery** after C2 deployment. If Haiku-tier subagents enter retry loops instead of switching to the Write tool, escalate to Option E.

4. **Verify Claude Code deny short-circuiting** -- does a `deny` from one PreToolUse hook prevent subsequent hooks from firing? If yes, the dual-popup concern in item 6 is mitigated. If no, consider adding a note in the memory plugin docs about the transitional behavior.

5. **Track popup frequency after each fix layer** to measure actual impact. The guardian.log already provides this data.

6. **Do not implement Option D (allowlists)** -- Gemini's recommendation to whitelist the staging directory is pragmatic but trades security for convenience. The fix design's rejection of Option D is correct.

---

## Overall Verdict

### PASS WITH NOTES

The fix design is well-structured and addresses the UX problem effectively through layered defense. The priority ordering is correct. The primary concerns are:

- **C1 alone is insufficient** -- the negative framing will help but cannot guarantee Haiku-tier compliance. C2 (hard enforcement) is essential.
- **Dual-hook popup risk** exists during the transitional period between C2 deployment and guardian fix (A). This is acceptable but should be documented.
- **Subagent retry behavior** after C2 deny is unverified. If subagents do not recover gracefully from denials, the deny message effectively becomes another kind of failure mode (silent rather than popup, but still blocking the memory save).
- **The deny message should include "why"** for better developer understanding.

None of these concerns are blockers. The design is sound for immediate deployment.
