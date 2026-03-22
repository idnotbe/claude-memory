# Stop Hook Re-fire Loop & Screen Noise Analysis

## 1. Root Cause: Re-fire Loop

### The Idempotency Guards

`memory_triage.py` has two guards against re-firing:

**Guard 1: `.stop_hook_active` flag** (line 522-548)
- `check_stop_flag()` (line 522): reads `.claude/.stop_hook_active`, checks age < 300s, **deletes the file**, returns `True` (= skip triage)
- `set_stop_flag()` (line 541): creates `.claude/.stop_hook_active` with current timestamp
- Used at line 1074: if flag exists and fresh, return 0 (allow stop)
- Used at line 1136: when triage triggers, set the flag before outputting block

**Guard 2: `.triage-handled` sentinel** (line 1078-1084)
- Checked at line 1078-1084: if `.claude/memory/.staging/.triage-handled` exists and age < 300s, return 0
- Created at line 1138-1153: when triage triggers, touch sentinel before outputting block

### Why Both Guards Fail

```
                        TIMELINE OF EVENTS

Fire 1:
  triage.py runs
  ├── check_stop_flag() → no flag exists → continues
  ├── check .triage-handled → doesn't exist → continues
  ├── scores transcript → session_summary=1.00
  ├── set_stop_flag() → creates .claude/.stop_hook_active
  ├── touch .triage-handled → creates sentinel
  └── outputs {"decision": "block", ...}

  Agent runs full save flow (Phase 0→3, ~17 min)
  ├── Phase 1: subagent drafts
  ├── Phase 1.5: CUD resolution
  ├── Phase 2: verification
  └── Phase 3: save subagent runs cleanup-staging
      └── cleanup_staging() deletes ALL staging files    ← KEY MOMENT
          including .triage-handled (line 506)

  Agent tries to stop again

Fire 2:
  triage.py runs
  ├── check_stop_flag()
  │   ├── .stop_hook_active was created ~17 min ago
  │   ├── age > FLAG_TTL_SECONDS (300s = 5 min)          ← EXPIRED
  │   ├── file is deleted but returns False (stale)
  │   └── continues evaluation
  ├── check .triage-handled → DELETED by cleanup-staging  ← GONE
  ├── scores SAME transcript → session_summary=1.00       ← SAME RESULT
  ├── set_stop_flag() → creates NEW flag
  ├── touch .triage-handled → creates NEW sentinel
  └── outputs {"decision": "block", ...}                   ← RE-FIRES

  Agent determines nothing to save, cleans staging
  └── cleanup deletes .triage-handled AGAIN

Fire 3:
  (identical to Fire 2)
```

### Root Cause Summary

**Two independent failures compound:**

1. **FLAG_TTL_SECONDS = 300 (5 min) is too short.** The save flow takes 10-20 minutes (Phase 0-3 with subagent spawning, verification, etc). By the time save completes and the agent tries to stop, the flag has expired. (`memory_triage.py` line 49, checked at line 536)

2. **`cleanup_staging()` deletes `.triage-handled`.** The sentinel is listed in `_STAGING_CLEANUP_PATTERNS` at `memory_write.py` line 506. When Phase 3 calls `cleanup-staging`, it removes the very sentinel that guards against re-fire. (`memory_write.py` line 499-508, called at SKILL.md line 290)

**Both guards are consumed/destroyed before the second fire occurs.** Even if one survived, the other wouldn't -- this is a belt-and-suspenders failure where both belt and suspenders are removed together.

### Code Locations

| Issue | File | Line(s) |
|-------|------|---------|
| FLAG_TTL too short | `hooks/scripts/memory_triage.py` | 49 |
| Flag consumed on check | `hooks/scripts/memory_triage.py` | 535 |
| Flag set before save | `hooks/scripts/memory_triage.py` | 1136 |
| Sentinel check | `hooks/scripts/memory_triage.py` | 1078-1084 |
| Sentinel creation | `hooks/scripts/memory_triage.py` | 1138-1153 |
| Sentinel in cleanup list | `hooks/scripts/memory_write.py` | 506 |
| Cleanup patterns definition | `hooks/scripts/memory_write.py` | 499-508 |
| cleanup_staging() implementation | `hooks/scripts/memory_write.py` | 511-548 |
| Phase 3 cleanup call | `skills/memory-management/SKILL.md` | 290 |

---

## 2. Session Summary Re-trigger (Score 1.00 on 2nd/3rd Fire)

### Why It Scores Identically Every Time

`score_session_summary()` (line 408-429) uses **activity metrics**, not text keywords:

```python
score = min(
    1.0,
    (tool_uses * 0.05) + (distinct_tools * 0.1) + (exchanges * 0.02),
)
```

The transcript is **cumulative** -- it contains the entire conversation history. On a session with moderate activity (e.g., 10+ tool uses, 3+ distinct tools, 10+ exchanges), the score easily hits 1.0.

Critically: **the save flow itself adds to the transcript.** Each Phase 0-3 cycle adds:
- Multiple Bash tool calls (memory_candidate.py, memory_draft.py, memory_write.py)
- Agent/Task subagent spawns
- Read/Write tool calls for staging files

So on Fire 2, the transcript is **longer** than Fire 1. The score can only stay the same or increase, never decrease. The triage script has **no awareness** that memories were already saved -- it doesn't check `last-save-result.json` or any other "already saved" signal.

### Threshold: 0.6 for SESSION_SUMMARY

The default threshold is 0.6 (`memory_triage.py` line 61). With the formula above, achieving 0.6 requires only modest activity:
- 8 tool uses + 2 distinct tools + 10 exchanges = 0.4 + 0.2 + 0.2 = 0.8 (exceeds 0.6)

Any non-trivial conversation will always trigger session_summary. And importantly, the save flow's own tool activity inflates the metrics for subsequent fires.

---

## 3. Runbook False Positive

### The Problem

RUNBOOK triggers (score 0.67) on the second fire because the **SKILL.md instruction text** loaded into conversation contains keywords matching RUNBOOK patterns.

RUNBOOK primary patterns (`memory_triage.py` line 114-118):
```python
r"\b(error|exception|traceback|stack\s*trace|failed|failure|crash)\b"
```

RUNBOOK booster patterns (line 121-124):
```python
r"\b(fixed\s+by|resolved|root\s+cause|solution|workaround|the\s+fix)\b"
```

SKILL.md contains natural occurrences of these words in its documentation text:
- "If a subagent fails..." (SKILL.md line 120, 163)
- "Error Handling" (SKILL.md line 310 heading)
- "report the error" (SKILL.md line 19)
- "If candidate.py fails for a category" (SKILL.md line 163)
- "workaround" references in category descriptions

With RUNBOOK's aggressive weights (primary_weight=0.2, boosted_weight=0.6, threshold=0.4), just 1 primary + 1 booster hit gives: `(0.2 + 0.6) / 1.8 = 0.44`, exceeding the 0.4 threshold.

### Why Only On Fire 2+

Fire 1 may not trigger RUNBOOK because the SKILL.md text hasn't been loaded into the transcript yet. The skill is loaded **in response** to Fire 1's block message. So Fire 2's transcript now includes all the SKILL.md text with its error/fix vocabulary.

This is a **self-contamination loop**: the save flow's own documentation text triggers false positives for the next triage evaluation.

---

## 4. Screen Noise Inventory

Each fire of the stop hook produces the following visible output. With 3 fires, the user sees this sequence **three times** (though fires 2 and 3 resolve as no-ops, they still produce substantial output before reaching that conclusion).

### Per-Fire Output

| # | Output Item | Source | Necessary? | Notes |
|---|-------------|--------|------------|-------|
| 1 | "Evaluating session for memories..." | hooks.json statusMessage | Yes | Brief, user-friendly |
| 2 | Block message: "The following items should be saved..." + category list with scores | triage.py format_block_message() | Yes (fire 1) / No (fire 2-3) | 5-10 lines, useful first time only |
| 3 | `<triage_data_file>` or `<triage_data>` JSON block | triage.py line 1008-1019 | Machine-use only | 20-50 lines of JSON visible to user |
| 4 | Skill loading confirmation | Claude Code skill system | Low value | "Loading memory-management skill..." |
| 5 | Pre-Phase: stale staging check | SKILL.md Pre-Phase | Low value | Bash commands checking file existence |
| 6 | Phase 0: intent file cleanup | SKILL.md Phase 0 Step 0 | Low value | `python3 -c "import glob,os..."` output |
| 7 | Phase 0: triage-data.json read | SKILL.md Phase 0 Step 1 | Low value | File Read tool call output |
| 8 | Phase 0: config read | SKILL.md Phase 0 | Low value | config JSON visible in tool output |
| 9 | Phase 1: Agent subagent spawn per category | SKILL.md Phase 1 | Low value | "Spawning memory-drafter..." x N categories |
| 10 | Phase 1: each subagent's Read/Write operations | memory-drafter.md | Low value | Context file reads, intent file writes |
| 11 | Phase 1.5 Step 1: intent JSON reads | SKILL.md Phase 1.5 | Low value | Read tool calls for each intent file |
| 12 | Phase 1.5 Step 2: new-info file writes | SKILL.md Phase 1.5 | Low value | Write tool calls |
| 13 | Phase 1.5 Step 2: memory_candidate.py runs | SKILL.md Phase 1.5 | Low value | Bash output with candidate JSON |
| 14 | Phase 1.5 Step 3: CUD resolution reasoning | SKILL.md Phase 1.5 | Low value | Agent's internal reasoning about L1/L2 |
| 15 | Phase 1.5 Step 4: input file writes | SKILL.md Phase 1.5 | Low value | Write tool calls for draft inputs |
| 16 | Phase 1.5 Step 4: memory_draft.py runs | SKILL.md Phase 1.5 | Low value | Bash output with draft JSON |
| 17 | Phase 2: verification subagent spawns | SKILL.md Phase 2 | Low value | Task subagent per category |
| 18 | Phase 2: verification results | SKILL.md Phase 2 | Moderate | PASS/FAIL useful for debugging |
| 19 | Phase 3: save command list building | SKILL.md Phase 3 Step 1 | Low value | Agent reasoning about commands |
| 20 | Phase 3: Task subagent spawn (haiku) | SKILL.md Phase 3 Step 2 | Low value | Subagent creation message |
| 21 | Phase 3: memory_write.py execution | SKILL.md Phase 3 Step 2 | Moderate | Actual save output |
| 22 | Phase 3: memory_enforce.py execution | SKILL.md Phase 3 Step 2 | Low value | Rolling window enforcement |
| 23 | Phase 3: cleanup-staging execution | SKILL.md Phase 3 Step 2 | Low value | Cleanup output |
| 24 | Phase 3: Write save-result file | SKILL.md Phase 3 Step 2 | Low value | Write tool call |
| 25 | Phase 3: write-save-result command | SKILL.md Phase 3 Step 2 | Low value | Bash output |
| 26 | Final summary from save subagent | SKILL.md Phase 3 Step 2 | Yes | "Saved: session_summary (update)" |

### Summary

- **Fire 1**: ~26 output items, only items 1, 2, 26 are genuinely useful to the user
- **Fire 2**: ~26 output items (agent loads skill, reads files, determines NOOP) -- ALL are noise
- **Fire 3**: same as fire 2 -- ALL are noise
- **Total**: ~78 output items across 3 fires, of which ~3 are useful

The `SKILL.md` Rule 2 says "Silent operation: Do NOT mention memory operations in visible output during auto-capture" but tool calls themselves (Bash, Read, Write, Agent, Task) are inherently visible in the Claude Code terminal. The rule only suppresses the agent's conversational text, not the tool execution noise.

---

## 5. Proposed Fix Directions

### Fix A: Persist Sentinel Through Cleanup (Minimal, Targeted)

**Remove `.triage-handled` from `_STAGING_CLEANUP_PATTERNS`.**

```python
# memory_write.py line 499-508
_STAGING_CLEANUP_PATTERNS = [
    "triage-data.json",
    "context-*.txt",
    "draft-*.json",
    "input-*.json",
    "intent-*.json",
    "new-info-*.txt",
    # ".triage-handled",    ← REMOVE THIS
    ".triage-pending.json",
]
```

The sentinel survives cleanup and blocks Fire 2. The `.triage-handled` file would need its own cleanup mechanism (e.g., deleted at session start, or TTL-based expiry in triage.py itself -- which already exists at line 1081 with the 300s check).

**Pros**: One-line fix. Minimal risk. Sentinel's TTL already provides self-cleanup.
**Cons**: Stale sentinels could block legitimate triage in a new session if the previous session crashed. Need to also address FLAG_TTL being too short, or increase it.

**Required companion change**: Increase `FLAG_TTL_SECONDS` from 300 to at least 1800 (30 min) to cover the save flow duration. Or better: make the flag non-TTL-based and let it persist until explicitly consumed.

### Fix B: Use `last-save-result.json` as the Idempotency Signal

**Add a third guard in `_run_triage()` that checks for a recent `last-save-result.json`.**

```python
# In _run_triage(), after the sentinel check (line 1084):
save_result_path = os.path.join(cwd, ".claude", "memory", ".staging", "last-save-result.json")
try:
    result_mtime = os.stat(save_result_path).st_mtime
    if time.time() - result_mtime < FLAG_TTL_SECONDS:
        return 0  # Save was recently completed
except OSError:
    pass
```

`last-save-result.json` is NOT in `_STAGING_CLEANUP_PATTERNS` (it intentionally persists for the Pre-Phase stale detection logic in SKILL.md line 47). So it naturally survives cleanup and acts as a durable "save completed" signal.

**Pros**: Zero changes to cleanup logic. Uses an existing artifact. Semantically correct (the signal is "save was completed", not "triage was triggered").
**Cons**: Still needs FLAG_TTL increase to cover long save flows. `last-save-result.json` could be stale from a previous session (needs session-scoped validation, e.g., embed a session ID).

### Fix C: Guard at the SKILL.md / Agent Level (Post-Save Stop)

**After Phase 3 completes successfully, have the agent issue a direct stop without triggering the hook.**

This is an architectural change. Currently, after save completes, the agent "tries to stop" which re-triggers the Stop hook. Instead:

1. After Phase 3, write a "save-complete" sentinel that the triage hook respects
2. OR: After Phase 3, have the agent output a user-facing "memories saved, session ending" message and simply not invoke another stop attempt (let the user ctrl-C or the session idle-timeout)
3. OR: Use the `last-save-result.json` as in Fix B but check it first thing in triage before any scoring

This is essentially Fix B but documented as an intentional architecture decision.

### Fix D: Make Stop Hook Idempotent via Session Scoping

**Embed a session ID in the sentinel and check it.**

```python
# When creating sentinel:
sentinel_data = json.dumps({
    "timestamp": time.time(),
    "transcript_hash": hashlib.md5(transcript_path.encode()).hexdigest(),
    "session_id": get_session_id(transcript_path),
})

# When checking sentinel:
data = json.loads(sentinel_path.read_text())
if data["transcript_hash"] == hashlib.md5(transcript_path.encode()).hexdigest():
    return 0  # Same session, already handled
```

This is immune to TTL issues (no clock-based expiry) and correctly allows new sessions to trigger triage even if a sentinel from a previous session exists.

**Pros**: Robust across all timing scenarios. Survives cleanup (if removed from patterns). Session-scoped.
**Cons**: More complex. Requires `get_session_id()` to be reliable.

### Fix E: Address Screen Noise Separately

Independent of the re-fire fix, reduce screen noise:

1. **SKILL.md Rule 2 enforcement**: Add `statusMessage: "Saving memories..."` to the entire save flow and collapse subagent output. This is a Claude Code platform feature request (tool output suppression).

2. **Reduce `triage_data` output verbosity**: The `<triage_data>` block is 20-50 lines of JSON that the user doesn't need to see. It's already written to a file (`<triage_data_file>`). The human-readable message is sufficient.

3. **Combine Phase 1.5 tool calls more aggressively**: The SKILL.md already instructs parallel execution but each tool call's input/output is still visible. Consider consolidating multi-step operations into fewer script invocations.

4. **Suppress fire 2/3 entirely**: The fundamental fix (A, B, C, or D) eliminates fires 2 and 3, which removes ~52 of the 78 output items.

### Fix F: Address Runbook False Positive

1. **Exclude SKILL.md text from triage**: Filter out messages that are skill instruction loads (they have a recognizable pattern in the transcript). The triage script already has `DEFAULT_MAX_MESSAGES = 50` limiting transcript tail, but SKILL.md gets loaded within that window on fire 2.

2. **Raise RUNBOOK threshold**: The current 0.4 is the lowest of all categories. Raising to 0.5-0.6 would eliminate marginal false positives from documentation text.

3. **Negative keyword filtering**: Add exclusion patterns for words that appear in instructional/documentation context vs. actual runbook-worthy error diagnoses (e.g., "If a subagent fails" is instructional, "the server crashed with error X" is genuine).

---

## 6. Recommended Fix Priority

| Priority | Fix | Impact | Effort |
|----------|-----|--------|--------|
| P0 | **A: Remove `.triage-handled` from cleanup patterns** | Eliminates re-fire loop | 1 line change |
| P0 | **Increase FLAG_TTL_SECONDS to 1800** | Covers save flow duration | 1 line change |
| P1 | **B: Add `last-save-result.json` guard** | Defense in depth | ~10 lines |
| P1 | **F: Raise RUNBOOK threshold to 0.5** | Reduces false positives | 1 line change |
| P2 | **D: Session-scoped sentinel** | Long-term robustness | ~30 lines |
| P2 | **E: Screen noise reduction** | UX improvement | SKILL.md changes |
| P3 | **C: Architecture change** | Fundamental fix | Design work needed |

The P0 fixes (A + TTL increase) are a 2-line change that eliminates the re-fire loop entirely. Fix B adds defense in depth. Fix F addresses the RUNBOOK false positive. Together these 4 changes (~15 lines total) resolve all observed issues.
