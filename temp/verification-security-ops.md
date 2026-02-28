# Security & Operations Risk Verification

**Verifier:** security-ops-verifier (Task #9)
**Date:** 2026-02-28
**Scope:** Proposed solutions in synthesis-draft.md + supporting research files

---

## Executive Summary

The proposed architectures (particularly Alt 3: Detached Process, Alt 4: Inline API Save in Stop Hook, and the Hybrid A+C approaches) introduce **real and non-trivial security and operational risks** that were either understated or not analyzed in the research files. The most critical finding is that **passing ANTHROPIC_API_KEY to hook subprocess environments is a significant security exposure that the research materials treat too casually**. Several failure modes can result in session lock-up (user cannot exit Claude Code), and the removal of the SKILL.md ACE pipeline represents a feature regression that is more severe than acknowledged.

Risk severity: **HIGH for Tier 3 / Alt 4 inline API approach. MEDIUM for Alt 3 detached process. LOW for SKILL.md minimal fix (Tier 1).**

---

## Finding 1: API Key Exposure (CRITICAL)

### Risk
Alt 4 and Alt 3 both require `ANTHROPIC_API_KEY` to be accessible in the hook script environment. The research notes this as a "requirement" but does not analyze the attack surface adequately.

### Threat vectors
1. **Environment variable leakage via hooks**: Hook scripts run as subprocesses of Claude Code. Their environment is inherited from the parent process. On multi-user systems (shared servers, CI environments), `/proc/<pid>/environ` is readable by the process owner, but there are edge cases where suid/setgid processes or container misconfiguration can expose env vars to other users.

2. **Conversation transcript exfiltration**: Hook scripts receive full `transcript_path` as input. A crafted session (via prompt injection or user-induced) could extract the API key from the environment and exfiltrate it through the memory save pipeline — writing it into a memory JSON file or a staging file that gets indexed and later retrieved by the retrieval hook.

3. **Conversation-to-hook injection**: The Stop hook reads the conversation transcript to extract triage data. If a user crafts a conversation turn that looks like a memory draft (`<memory_draft>` XML block), a naive hook parser would process the attacker-controlled content. If the hook also has API key access, this becomes a code execution + key exfiltration vector.

4. **Hook script modification**: If the plugin root (`~/.claude/plugins/claude-memory/`) has loose file permissions, an attacker who gains write access could modify `memory_triage.py` to exfiltrate the API key to an external endpoint during the next Stop event.

### Assessment
The research files acknowledge API key access is required but do not propose a mitigation strategy. The inline-API approach (Alt 4) is architecturally unsafe without:
- Explicit permission scoping (what can the key do? read-only models only?)
- A dedicated restricted API key (not the user's primary key)
- Key isolation from the main hook environment (e.g., read from a separate credential file with restricted permissions)
- Input sanitization of conversation content before it reaches the hook's API call

### Recommendation
**Block Alt 4 / Tier 3 until a key management design is specified.** The research underestimates this risk. At minimum, the config documentation must warn users not to use their primary ANTHROPIC_API_KEY and to create a restricted key.

---

## Finding 2: Race Conditions — Detached Process vs. Session Exit (HIGH)

### Risk
Alt 3 (Detached Process) uses `subprocess.Popen(start_new_session=True)` to spawn a background saver process. The synthesis draft treats this as "highly feasible" and "reliable." The cross-model validation flags the background agent termination risk but dismisses it. This needs harder analysis.

### Scenarios

**Scenario A: User kills Claude Code (SIGKILL or Ctrl+C during stop hook)**
- `start_new_session=True` creates a new process group, so SIGKILL to the parent does NOT propagate to the child process. The detached process survives.
- However: if the triage sentinel file was only partially written when SIGKILL landed, the detached process reads a corrupt sentinel and attempts to save garbage data.
- **Impact**: Corrupt or empty memory saves. No error visible to user.

**Scenario B: Two simultaneous Claude Code instances on the same project**
- Both instances can trigger Stop hooks concurrently.
- Both read `.claude/memory/index.json` and `.claude/memory/.staging/` files simultaneously.
- `memory_write.py` does NOT implement file locking (confirmed by reading the CLAUDE.md architecture section — it uses atomic writes but no cross-process locking).
- Both instances try to write the same category index. Last writer wins. One instance's memories are silently dropped.
- **Impact**: Data loss. No error visible to either user.

**Scenario C: Alt 4 inline API — hook timeout during active API call**
- The Stop hook has a 30-second timeout. An API call for drafting + `memory_write.py` for 3+ categories might exceed this.
- At timeout, the hook process is killed. The `decision` response never arrives. What does Claude Code do?
  - If Claude Code treats a hook timeout as "block failed, allow stop" — session exits, partial memories lost.
  - If Claude Code treats a hook timeout as "blocking forever, wait" — **the user cannot exit the session**.
- The research files do not document what Claude Code's behavior is on hook timeout. This is a critical unknown.
- **Impact (worst case)**: User is locked out of their session. They must kill Claude Code externally.

**Scenario D: Alt 3 detached process — multiple orphans accumulate**
- User opens and closes Claude Code sessions rapidly. Each Stop event spawns a detached saver process.
- No mechanism exists to prevent duplicate saver processes from running simultaneously.
- Each process reads the same staging files and attempts to write the same memories.
- **Impact**: Duplicate memory entries, index corruption, high resource usage.

### Recommendation
Both Alt 3 and Alt 4 require a **process coordination mechanism**:
- A lockfile at `.claude/memory/.staging/save.lock` (with PID and expiry)
- Sentinel file atomicity (write to `.staging/triage-data.json.tmp` then `os.rename()` to final path — `rename()` is atomic on POSIX)
- Documentation of Claude Code hook timeout behavior before Alt 4 is adopted

---

## Finding 3: Data Integrity — Bypassing ACE Candidate Selection (HIGH)

### Risk
The synthesis draft acknowledges that inline API save (Alt 4 / Tier 3) loses ACE candidate selection ("Limited (no existing memory lookup)"). This is understated. The full impact is:

1. **No deduplication**: Without `memory_candidate.py`, the system cannot detect that a memory about "user prefers X" already exists. Every save creates a new entry. The rolling window enforcer (`memory_enforce.py`) will eventually retire valid memories to make room for duplicates.

2. **No update detection**: Existing memories are never updated — only new ones are created. A user's preference that changes over time will have both the old and new version in memory, and retrieval will inject both — potentially contradictory — into future context.

3. **Optimistic concurrency bypassed**: `memory_write.py` supports OCC via `content_hash`. The inline API approach, having no knowledge of existing entries, cannot supply a `content_hash` for update operations. It will always `create`, never `update`. This breaks the integrity model.

4. **Verification phase lost**: The SKILL.md 4-phase flow includes a verification pass where a second LLM call reviews the drafted memory for quality and correctness. Alt 4 drops this entirely. A single rushed API call in a 30-second hook window will produce lower-quality memories.

### Assessment
The research frames this as a "good vs. excellent" quality tradeoff. In practice, for a memory system, deduplication and update detection are **correctness requirements**, not quality enhancements. Without them, the index grows indefinitely with stale and duplicate entries, degrading retrieval quality over time.

### Recommendation
If Alt 4 is adopted, it **must** either:
a) Include a lightweight candidate lookup phase (read `index.json`, compute similarity against draft title), or
b) Be clearly documented as a "degraded mode" with explicit user opt-in, or
c) Always call the existing `memory_candidate.py` script as a synchronous step before drafting

---

## Finding 4: Hook Timeout — User Session Lock-Up (HIGH)

### Risk
(Detailed above in Finding 2, Scenario C — isolated here for emphasis.)

The 30-second Stop hook timeout is the current configured limit for `memory_triage.py`. The research recommends "increasing timeout in hooks.json" for Alt 4. This recommendation is dangerously naive:

- Increasing the hook timeout to 60-90 seconds means the user waits 60-90 seconds when their session wants to end
- During that wait, any network failure (API unavailable) causes the full timeout to be spent waiting on a dead connection before the hook exits
- If the API call hangs indefinitely (e.g., server accepts the connection but doesn't respond), the hook hangs until the configured timeout, then the behavior is undefined (see Finding 2, Scenario C)

**Worst-case scenario**: A user tries to end a session. The Stop hook fires, makes an API call. The API endpoint is down. The hook hangs for the full timeout duration. If Claude Code waits for the hook, the user cannot close their terminal window gracefully for 30-90 seconds. If they force-kill Claude Code, any partial work is lost.

### Recommendation
Any API call from within a Stop hook MUST have:
1. A separate `socket.setdefaulttimeout()` or per-request timeout well below the hook's total timeout (e.g., 10s max for API call, 5s for writing, 5s buffer)
2. A fallback: if API call fails, write triage data to a sentinel file and allow stop — deferring to next session processing
3. Clear user communication: a brief "Memory save failed — will retry next session" message rather than silent failure

---

## Finding 5: Edge Cases — First Run and Missing Prerequisites (MEDIUM)

### Risk
The synthesis draft does not analyze first-run experience or environmental edge cases:

**No API key set:**
- Alt 4 silently fails (hook exits 0 but saves nothing, or raises an unhandled exception)
- No memory is saved, no error is shown to the user
- User doesn't know their memories were lost
- **Required behavior**: explicit check at hook start, write warning to staging file for injection into next session

**Network unavailable:**
- Hook attempts API call, times out, exits silently
- Memory lost for the session
- **Required behavior**: same as above — write deferred sentinel, notify next session

**Memory directory permissions:**
- `.claude/memory/` might have restrictive permissions (umask, or Docker volume mount issues)
- `memory_write.py` fails silently or raises an unhandled exception
- Hook exits non-zero, which may block session termination (see Finding 2)
- **Required behavior**: permission check before attempting write, graceful degradation

**Memory directory full (disk space):**
- `memory_write.py` fails mid-write, potentially leaving a corrupt JSON file
- Corrupt file will fail schema validation but the `memory_validate_hook.py` PostToolUse hook won't fire (it's not a Write tool call in this path)
- **Required behavior**: disk space pre-check, atomic write with rollback on failure

**Plugin venv not set up:**
- `memory_write.py` requires pydantic v2 and re-execs under `.venv/bin/python3`
- If venv doesn't exist (first install, or user deleted it), re-exec fails, memory_write.py fails
- Hook exits non-zero
- **Required behavior**: pre-flight venv check, meaningful error message on first run

---

## Finding 6: Regression Risks — Features Lost by Bypassing SKILL.md (MEDIUM)

### Risk
Several features in the current SKILL.md flow are silently lost when moving to Alt 4:

| Feature | SKILL.md | Alt 4 (Inline API) | Risk Level |
|---------|----------|-------------------|-----------|
| ACE candidate selection | Yes | No | HIGH (duplicates accumulate) |
| Update vs. create detection | Yes | No | HIGH (stale entries preserved) |
| Multi-stage verification pass | Yes | No | MEDIUM (lower draft quality) |
| Content hash OCC | Yes | No | MEDIUM (concurrent write safety lost) |
| Rollback on validation failure | Yes | Partial | LOW (quarantine still works via PostToolUse) |
| User confirmation of saves | Yes | No | LOW (silent saves, no visibility) |
| Manual override / re-save | SKILL.md invocation | SKILL.md still available | LOW |

**Critical note on PostToolUse validation**: `memory_validate_hook.py` is registered as a PostToolUse hook. It fires after Write tool calls. If Alt 4 uses Python imports (calling `memory_write.py` as a module, not via Bash/Write tool calls), the PostToolUse hook **will not fire**. Schema validation is bypassed. Invalid memory JSONs could be written to disk without detection.

### Recommendation
The regression matrix above must be presented to users as a documented trade-off before Alt 4 is made the default. `memory_validate_hook.py` must be refactored to also run as a standalone validation step callable from the Alt 4 pipeline.

---

## Finding 7: Prompt Injection via Crafted Conversation Content (HIGH)

### Risk
Both Option A (background-agent researcher) and Alt 4 involve parsing the conversation transcript from within a hook script. This is an injection vector:

**Attack scenario for Alt 4:**
1. User (or a document they pasted into the conversation) contains text that looks like a valid `<memory_draft>` XML block with a crafted title/content
2. The hook's transcript parser picks this up as a legitimate memory to save
3. The injected content is saved to the memory store
4. On next session, the retrieval hook injects the injected content into the conversation context
5. The injected content could contain further instructions that affect Claude's behavior

**Attack scenario for Option A (hook parses agent text output):**
1. Agent outputs `<memory_draft>` blocks in its stop message
2. A prompt injection earlier in the conversation caused the agent to output a malicious `<memory_draft>` block
3. The hook's parser saves it without validation

### Current mitigations (partial)
- CLAUDE.md mentions sanitization (escape `<`/`>`, strip control chars, remove delimiter patterns)
- `memory_write.py` has schema validation via Pydantic
- These mitigations exist for the SKILL.md path; they may not be ported to the Alt 4 path

### Recommendation
Any hook that parses transcript content MUST:
1. Validate that `<memory_draft>` blocks appear only in specific turns (agent tool results, not user messages)
2. Enforce strict schema validation on all parsed content before calling `memory_write.py`
3. Sanitize titles and content fields against the known injection vectors documented in CLAUDE.md
4. Rate-limit: no more than N memories per session via hook (to prevent injection-driven mass writes)

---

## Finding 8: Detached Process Security (MEDIUM)

### Risk
Alt 3 spawns a detached process (`start_new_session=True`) that runs independently. This process:

1. **Has no audit trail**: It runs outside Claude Code's hook event system. Its actions are not logged in the Claude Code event log.
2. **Cannot be killed by Claude Code**: Once spawned, there is no handle to it. If it hangs, it's an orphan process.
3. **Could interfere with a new session**: User immediately starts a new Claude Code session. The orphan saver process is simultaneously reading/writing `.claude/memory/` while the new session's hooks also read/write the same directory. No coordination exists.
4. **Error visibility**: The process redirects stdout/stderr to `/dev/null`. If it fails (API error, disk error, permission error), the user never knows. Memories are silently lost.

### Recommendation
Alt 3 is better suited as a **last-resort fallback** (for when Alt 4 fails mid-execution), not as the primary save mechanism. If implemented, it must write a completion/error file to `.staging/` that the next session's SessionStart hook reads and reports.

---

## Summary: Risk Matrix

| Risk | Severity | Alt 3 (Detached) | Alt 4 (Inline API) | Tier 1 (SKILL.md fix) | Mitigated? |
|------|----------|-----------------|-------------------|----------------------|-----------|
| API key exposure | CRITICAL | Yes | Yes | No | No design yet |
| Race condition (dual instances) | HIGH | Yes | No | No | No |
| Session lock-up on timeout | HIGH | No | Yes | No | No design yet |
| ACE/dedup regression | HIGH | Yes | Yes | No | Documented only |
| Prompt injection via transcript | HIGH | Yes | Yes | Partial | Existing sanitization |
| PostToolUse validation bypass | MEDIUM | Yes | Yes | No | Must fix |
| Orphan process accumulation | MEDIUM | Yes | No | No | No |
| First-run/missing prerequisites | MEDIUM | Yes | Yes | No | No |
| No error visibility to user | MEDIUM | Yes | Yes | No | No |

---

## Recommendations by Tier

### Tier 1 (SKILL.md Minimal Fix) — LOW RISK, PROCEED
- Externalize triage_data to file (Fix A) is safe and should proceed immediately
- Single consolidated save agent (Fix B) is safe and reduces Bug #18351 risk
- No new security surface introduced

### Tier 2 (Agent Hook Investigation) — MEDIUM RISK, WORTH INVESTIGATING
- If agent hook subagents are truly isolated, this is the best architecture
- Before adopting: verify transcript isolation empirically
- Ensure agent hook subagents cannot be injected via conversation content

### Tier 3 (Inline API / Detached Process) — HIGH RISK, BLOCK UNTIL MITIGATED
**Do not proceed without resolving:**
1. API key management design (separate restricted key, not primary)
2. Hook timeout behavior documentation from Claude Code team
3. Cross-process locking for `.claude/memory/` directory
4. ACE candidate lookup integration into hook pipeline
5. Error handling with user-visible next-session notification
6. Prompt injection mitigations for transcript parsing
7. PostToolUse validation bypass workaround (call memory_validate.py explicitly)

---

## Most Critical Finding

**The API key exposure risk combined with prompt injection creates a chained attack vector unique to Alt 4.** A crafted `<memory_draft>` block injected via a user-pasted document → saves to memory → retrieved in future session → contains `ANTHROPIC_API_KEY` exfiltration instruction → executed by Claude. This chain is possible if the hook script reads the API key from env, calls the Anthropic API using that key, and outputs errors (including the key) to any log file that is later read by Claude.

This specific attack chain is not present in the current SKILL.md architecture because:
1. The API key is never in the hook environment (Claude Code uses its own internal auth)
2. Save operations happen through tool calls that are user-visible (harder to hide malicious writes)
3. The verification phase provides a second LLM check before writes

**Recommendation: Make the API key attack chain analysis an explicit acceptance criterion before Tier 3 is implemented.**
