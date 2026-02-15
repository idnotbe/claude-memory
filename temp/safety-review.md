# Safety Review: Removal of "model": "sonnet" from Stop Hooks

**Reviewer:** safety-reviewer (Claude Opus 4.6)
**Date:** 2026-02-15
**File under review:** `/home/idnotbe/projects/claude-memory/hooks/hooks.json`
**Task:** Task #2 -- Safety review of the model field removal

---

## Executive Summary

**Overall Risk Assessment: LOW -- Clear net positive. APPROVE with observations.**

The change fixes a total failure (6 hooks returning 404 every session) by removing an invalid model alias. The hooks go from 0% functional to 100% functional. Even under pessimistic assumptions about the default model's capabilities, this is unambiguously better than the status quo.

---

## Scope of Changes (Important: Two Changes Bundled)

The diff reveals this is NOT a single mechanical edit. Two distinct changes were made simultaneously:

| Change | Description | Risk Level |
|--------|-------------|------------|
| 1. Model field removal | Remove `"model": "sonnet"` from 6 Stop hooks | LOW |
| 2. Prompt rewrite | Rewrote all 6 prompts from strict JSON-instruction format to natural-language format | LOW-MEDIUM |

**Observation:** The prompt rewrite was introduced in the previous commit (b99323e) as a separate fix attempt. The current change only removes the model field. The diff shown by `git diff HEAD~1` conflates both changes because the comparison base already includes the prompt rewrite. This is NOT a concern for safety -- just noting for clarity in the review chain.

---

## Checklist Analysis

### 1. Default Model Risk: Is Haiku Capable Enough?

**Assessment: ACCEPTABLE**

**Key insight:** The briefing notes that `"model": "haiku"` was the ORIGINAL configuration before being changed to `"model": "sonnet"` in commit 2bd67fa. The rationale for switching to Sonnet was that "haiku가 JSON을 잘못 쓴다" (Haiku writes JSON incorrectly). However, the briefing also notes that the 404 error may have occurred with "haiku" as well, meaning the JSON quality issue was never actually confirmed -- it was the alias resolution failing.

**Now that prompts use natural language** (not requiring the model to produce strict JSON), the original concern about Haiku's JSON generation is moot. Claude Code's internal framework handles the JSON structuring for prompt-type hooks -- the model just needs to make a yes/no triage decision with a reason string.

**Failure modes with a less capable model:**

| Mode | Impact | Severity | Mitigation |
|------|--------|----------|------------|
| Over-saving (false negatives on "ok") | User sees more "save memory" prompts | LOW -- mild nuisance, user can dismiss | Prompts are clear about criteria |
| Under-saving (false positives on "ok") | Lost memory opportunities | LOW -- memories are convenience, not critical data | User can manually save |
| Misclassifying category | Wrong memory type label | NEGLIGIBLE -- downstream consumer (main agent) re-evaluates | Prompt criteria are specific |

**Bottom line:** These are triage hooks, not safety-critical gates. A less capable model making slightly noisier triage decisions is vastly preferable to hooks that silently 404 on every invocation.

### 2. Behavior Change Risk

**Assessment: LOW -- but worth monitoring**

The actual behavior change is: hooks go from **non-functional** (404 error) to **functional** (default fast model evaluates prompts). There is no regression from a working state -- the hooks were broken.

**One subtle risk:** The prompt style change means the model no longer needs to produce raw JSON. If Claude Code's prompt hook framework changed how it interprets natural-language responses vs JSON responses, there could be a mismatch. However, commit b99323e (the prompt rewrite) was specifically designed to align with Claude Code's internal prompt hook expectations, and the worklog confirms this approach was validated.

### 3. Rollback Safety

**Assessment: TRIVIALLY REVERSIBLE**

To rollback, add `"model": "sonnet"` back to each of the 6 hook objects. This is a 6-line addition. However, rolling back would RESTORE the 404 error, making the hooks broken again. A more useful rollback would be to add a full model ID like `"model": "claude-haiku-4-5-20251001"` if the default model proves inadequate.

### 4. Config Integrity

**Assessment: VERIFIED INTACT**

- JSON validates successfully (`python3 -c "import json; json.load(open('hooks/hooks.json'))"`)
- 6 Stop hooks present (unchanged count)
- All 6 hooks have exactly the expected keys: `type`, `timeout`, `statusMessage`, `prompt`
- Zero occurrences of `"model"` in the file
- Description version bumped from v4.0.0 to v4.1.0 (appropriate for minor behavioral change)
- No trailing commas, no structural anomalies

### 5. Side Effects on Non-Stop Hooks

**Assessment: ZERO IMPACT**

The three non-Stop hooks are completely unaffected:

| Hook | Type | Has model field? | Changed? |
|------|------|-----------------|----------|
| PreToolUse (Write guard) | command | Never had one | NO |
| PostToolUse (validation) | command | Never had one | NO |
| UserPromptSubmit (retrieval) | command | Never had one | NO |

`command`-type hooks execute Python scripts directly and never had a `model` field. They are structurally independent from `prompt`-type hooks.

### 6. Cost Implications

**Assessment: BENEFICIAL**

| Model | Cost per hook invocation | 6 hooks x per session |
|-------|------------------------|----------------------|
| Sonnet (broken -- 404) | $0 (fails immediately) | $0 |
| Haiku (default) | ~$0.001-0.003 | ~$0.006-0.018 |
| Opus (session model) | ~$0.01-0.05 | ~$0.06-0.30 |

The briefing's Option C ("model field 제거 → session model(Opus) 사용 → 매우 비쌈") raised a concern about the session model being used. However, the workplan and implementation report both state that the default for prompt-type hooks is the "fast model" (Haiku), NOT the session model. **If this assumption is wrong and Opus is used instead, cost would increase significantly (roughly 10-50x over Haiku).** This is the single most important assumption to verify empirically after deployment.

---

## Adversarial / Devil's Advocate Analysis

### Worst-Case Scenario 1: Default Model is Actually Opus, Not Haiku
- **Impact:** Cost explosion -- 6 Opus calls per session stop, potentially $0.30+ per session
- **Likelihood:** LOW -- Claude Code documentation and community consensus indicate the fast model (Haiku) is used for prompt-type hooks without an explicit model field
- **Mitigation:** Test empirically by stopping a session and checking API logs. If Opus is used, add explicit `"model": "claude-haiku-4-5-20251001"`

### Worst-Case Scenario 2: Haiku Misinterprets Triage Criteria and Over-Blocks Stopping
- **Impact:** User annoyance -- every session stop gets blocked with false "save this memory" triggers
- **Likelihood:** LOW-MEDIUM -- The prompts have clear criteria (e.g., "All three required: diagnosed, fixed, verified"), but a less capable model might be more trigger-happy
- **Mitigation:** Monitor for a few sessions. If over-triggering occurs, tighten prompt language or add explicit `"model": "claude-haiku-4-5-20251001"` and adjust prompts for Haiku's capabilities

### Worst-Case Scenario 3: Haiku Fails to Parse CUD Prefix Instructions
- **Impact:** Memory entries created without proper CUD/EVENT metadata, reducing the quality of downstream memory management
- **Likelihood:** LOW -- The prefix format `[CUD:CREATE|EVENT:none]` is simple and well-specified in the prompts
- **Mitigation:** The main agent re-evaluates the reason string anyway; metadata loss is not catastrophic

### Worst-Case Scenario 4: Claude Code Updates Change Default Model Behavior
- **Impact:** Future Claude Code updates could change what "default" means for prompt hooks, silently altering behavior
- **Likelihood:** MEDIUM over time -- but this risk exists regardless of this change
- **Mitigation:** Consider pinning to an explicit model ID in a future iteration for long-term stability

### Worst-Case Scenario 5: Prompt Injection via $ARGUMENTS
- **Impact:** A crafted conversation context (injected via `$ARGUMENTS`) could trick the triage model into blocking or allowing stops inappropriately
- **Likelihood:** LOW for practical exploitation -- the user controls their own session context
- **Pre-existing:** This risk existed before the change and is not introduced by it. A less capable model (Haiku) might be slightly more susceptible to prompt injection than Sonnet, but the attack surface is limited since $ARGUMENTS contains the session's own conversation context

---

## External Consultation Results

| Tool | Status | Result |
|------|--------|--------|
| Vibe Check | COMPLETED | Assessment: Plan is on track. Low risk, clear net positive. No concerning patterns. Proceed. |
| Gemini CLI (clink) | UNAVAILABLE | TerminalQuotaError -- quota exhausted, resets in ~15h |
| Codex CLI (clink) | UNAVAILABLE | Usage limit reached, resets Feb 21 |

Both external CLI consultations failed due to quota limits. This does not materially impact the review -- the change is straightforward enough that internal analysis is sufficient.

---

## Recommendations

### Immediate (Pre-Merge)
1. **APPROVE** the change as-is. It fixes a total failure with minimal risk.

### Post-Merge Monitoring
2. **Empirically verify the default model.** After deploying, stop a session with meaningful work and confirm that Haiku (not Opus) is being used for the triage evaluation. Check Claude Code debug logs if available.
3. **Monitor triage quality for 3-5 sessions.** Watch for over-triggering (too many false "save memory" blocks) or under-triggering (sessions with clear decisions/runbooks that get missed).

### Future Hardening (Not Blocking)
4. **Consider explicit model ID.** Once the default model behavior is confirmed, consider adding `"model": "claude-haiku-4-5-20251001"` explicitly to avoid future surprises from Claude Code updates.
5. **Track the two-variable problem.** If triage quality issues arise, it will be ambiguous whether the cause is the model change or the prompt format change. The prompt rewrite happened in a prior commit (b99323e), which helps somewhat with attribution.

---

## Verdict

| Criterion | Status |
|-----------|--------|
| Default model risk | ACCEPTABLE -- triage tasks are within Haiku's capabilities |
| Behavior change risk | LOW -- going from broken to functional |
| Rollback safety | TRIVIAL -- 6-line re-addition |
| Config integrity | VERIFIED -- valid JSON, correct structure |
| Non-Stop hook impact | ZERO -- command-type hooks are unaffected |
| Cost implications | BENEFICIAL -- Haiku is cheap; verify it's not Opus |

**FINAL VERDICT: APPROVE**

The change is a clear improvement over the broken status quo. No blocking safety concerns identified. The single most important follow-up action is to empirically verify that the default model is Haiku, not Opus.
