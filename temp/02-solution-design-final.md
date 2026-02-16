# Final Solution Design: 100% Error-Free Stop Hooks

> **Version:** 1.0 | **Date:** 2026-02-16
> **Reviewed by:** Gemini 3 Pro (via PAL clink), Vibe-Check metacognitive review, Self-critique
> **Status:** APPROVED FOR IMPLEMENTATION

---

## 1. Problem Statement

Six `type: "prompt"` Stop hooks each call an internal LLM that must return `{"ok": boolean, "reason"?: string}`. The LLM frequently fails to produce valid JSON due to empty responses, schema mismatches, markdown wrapping, and conversational preamble. With 6 independent hooks, the combined failure rate is ~17-26% per stop event.

**Root cause:** Prompt-type hooks have an inherent, non-zero failure rate that cannot be eliminated. This is confirmed by Claude Code binary analysis, GitHub issue #11947 (open since Nov 2025), and cross-model validation.

## 2. Solution: Single Command-Type Stop Hook

Replace ALL 6 `type: "prompt"` Stop hooks with 1 `type: "command"` Stop hook running `hooks/scripts/memory_triage.py`.

Command hooks are deterministic: the Python script controls stdout, stderr, and exit codes completely. No LLM touches Claude Code's JSON parser. Error rate drops to 0%.

## 3. Architecture

```
Stop event fires
    |
    v
Claude Code executes: python3 hooks/scripts/memory_triage.py
    |
    v
Script reads stdin JSON (with select.select timeout)
    |
    +-- Extracts: transcript_path, session_id, cwd
    |
    +-- Checks stop_hook_active flag (with TTL)
    |   |-- Flag exists AND fresh (< 5 min) -> delete flag, exit 0
    |   |-- Flag exists AND stale (>= 5 min) -> ignore flag, continue
    |   |-- No flag -> continue
    |
    +-- Reads JSONL transcript file
    |   |-- Defensive: handle missing, empty, corrupt
    |   |-- Extract last N messages (default 50)
    |   |-- Filter out code blocks to reduce false positives
    |
    +-- Heuristic scoring pass (6 categories)
    |   |-- DECISION: co-occurrence regex patterns
    |   |-- RUNBOOK: error + fix pattern pairs
    |   |-- CONSTRAINT: limitation keywords
    |   |-- TECH_DEBT: deferral patterns
    |   |-- PREFERENCE: convention patterns
    |   |-- SESSION_SUMMARY: activity metrics
    |
    +-- Threshold check (per-category, configurable)
    |   |-- Any category passes? -> exit 2 + stderr message
    |   |-- Nothing passes? -> exit 0 (allow stop)
    |
    +-- On exit 2: create stop_hook_active flag with timestamp
    +-- On any exception: exit 0 (fail open)
```

## 4. hooks.json Changes

### Before (6 prompt hooks):
```json
{
  "Stop": [
    { "matcher": "*", "hooks": [{ "type": "prompt", "timeout": 30, "prompt": "...session_summary..." }] },
    { "matcher": "*", "hooks": [{ "type": "prompt", "timeout": 30, "prompt": "...decision..." }] },
    { "matcher": "*", "hooks": [{ "type": "prompt", "timeout": 30, "prompt": "...runbook..." }] },
    { "matcher": "*", "hooks": [{ "type": "prompt", "timeout": 30, "prompt": "...constraint..." }] },
    { "matcher": "*", "hooks": [{ "type": "prompt", "timeout": 30, "prompt": "...tech_debt..." }] },
    { "matcher": "*", "hooks": [{ "type": "prompt", "timeout": 30, "prompt": "...preference..." }] }
  ]
}
```

### After (1 command hook):
```json
{
  "Stop": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py\"",
          "timeout": 30,
          "statusMessage": "Evaluating session for memories..."
        }
      ]
    }
  ]
}
```

PreToolUse, PostToolUse, and UserPromptSubmit hooks remain unchanged.

## 5. Detailed Script Design: memory_triage.py

### 5.1 Input Handling

**stdin JSON** (from Claude Code):
```json
{
  "transcript_path": "/path/to/transcript.jsonl",
  "session_id": "...",
  "cwd": "/path/to/project"
}
```

**stdin reading strategy:** Use `select.select()` with a 2-second timeout. Claude Code does not send EOF after writing to stdin, so `sys.stdin.read()` would block forever. The approach:

```python
import select
import sys

def read_stdin(timeout_seconds: float = 2.0) -> str:
    """Read stdin with timeout (Claude Code doesn't send EOF)."""
    chunks = []
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
        if not ready:
            break
        chunk = sys.stdin.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
        timeout_seconds = 0.1  # After first chunk, use short timeout for remaining data
    return "".join(chunks)
```

### 5.2 Transcript Parsing

**JSONL format:** Each line is a JSON object with at minimum a `type` field. Types include `"human"`, `"assistant"`, `"tool_use"`, `"tool_result"`.

```python
def parse_transcript(transcript_path: str, max_messages: int = 50) -> list[dict]:
    """Parse last N messages from JSONL transcript.

    Returns list of message dicts, most recent last.
    Handles: missing file, empty file, corrupt lines.
    """
    messages = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue  # Skip corrupt lines
    except (OSError, IOError):
        return []
    return messages[-max_messages:]
```

**Text extraction:** Extract text content from human and assistant messages, stripping code blocks:

```python
CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

def extract_text(messages: list[dict]) -> str:
    """Extract human/assistant text content, stripping code blocks."""
    parts = []
    for msg in messages:
        if msg.get("type") not in ("human", "assistant"):
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            # Content can be list of blocks
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
        elif isinstance(content, str):
            parts.append(content)
    text = "\n".join(parts)
    # Strip code blocks to reduce false positives
    text = CODE_FENCE_RE.sub("", text)
    return text
```

### 5.3 Heuristic Scoring

Each category uses **distance-constrained regex patterns** and **co-occurrence within a sliding window** (4 lines). This avoids false positives from isolated keywords.

#### Category Definitions

| Category | Primary Patterns | Co-occurrence Boosters | Score Type |
|----------|-----------------|----------------------|------------|
| DECISION | `\b(decided|chose|selected|went with|picked)\b` | "because", "over", "instead of", "rather than", "rationale" | Binary + co-occurrence |
| RUNBOOK | `\b(error|exception|traceback|stack trace|failed)\b` | "fixed by", "resolved", "root cause", "solution", "workaround" | Pair: error + fix |
| CONSTRAINT | `\b(limitation|API limit|cannot|restricted|not supported|quota)\b` | "discovered", "found that", "turns out" | Keyword density |
| TECH_DEBT | `\b(TODO|deferred|tech debt|workaround|hack|will address later)\b` | "because", "for now", "temporary", "acknowledged" | Binary + co-occurrence |
| PREFERENCE | `\b(always use|prefer|convention|from now on|standard|never use)\b` | "established", "agreed", "going forward" | Binary trigger |
| SESSION_SUMMARY | N/A (uses activity metrics) | N/A | Cumulative |

#### Scoring Algorithm

For text-based categories (DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE):

1. Split extracted text into lines
2. For each line, check against primary pattern regex
3. If primary pattern matches, check co-occurrence within a 4-line sliding window (2 lines before, 1 line after)
4. Score:
   - Primary match alone: +0.3 per occurrence (capped at 3)
   - Primary + co-occurrence in window: +0.5 per occurrence (capped at 2)
   - Final score = sum / category-specific denominator, clamped to [0.0, 1.0]

For SESSION_SUMMARY (activity-based):
1. Count `tool_use` messages (file writes, git operations, etc.)
2. Count distinct tool names used
3. Count human/assistant message exchanges
4. Score: `min(1.0, (tool_uses * 0.05) + (distinct_tools * 0.1) + (exchanges * 0.02))`
5. Threshold is higher for SESSION_SUMMARY (0.6 vs 0.4 for text categories)

#### Per-Category Thresholds (Configurable)

```python
DEFAULT_THRESHOLDS = {
    "DECISION": 0.4,
    "RUNBOOK": 0.4,
    "CONSTRAINT": 0.5,
    "TECH_DEBT": 0.4,
    "PREFERENCE": 0.4,
    "SESSION_SUMMARY": 0.6,
}
```

### 5.4 Stop Hook Active Flag (with TTL)

The flag prevents infinite block/stop loops. Key improvement from Gemini review: **the flag has a TTL** (time-to-live). If the user continues working after a block, the stale flag expires and the script re-evaluates.

```python
FLAG_TTL_SECONDS = 300  # 5 minutes

def check_stop_flag(cwd: str) -> bool:
    """Check and handle the stop_hook_active flag.

    Returns True if the script should exit 0 immediately (flag is fresh).
    Returns False if the script should continue evaluation.
    """
    flag_path = Path(cwd) / ".claude" / ".stop_hook_active"
    if not flag_path.exists():
        return False

    try:
        mtime = flag_path.stat().st_mtime
        age = time.time() - mtime
        if age < FLAG_TTL_SECONDS:
            # Flag is fresh: user is re-stopping after a block. Allow it.
            flag_path.unlink(missing_ok=True)
            return True
        else:
            # Flag is stale: user continued working. Re-evaluate.
            flag_path.unlink(missing_ok=True)
            return False
    except OSError:
        return False

def set_stop_flag(cwd: str) -> None:
    """Create the stop_hook_active flag file with current timestamp."""
    flag_path = Path(cwd) / ".claude" / ".stop_hook_active"
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(str(time.time()))
    except OSError:
        pass  # Non-critical
```

### 5.5 Output Format

**Exit 0** (allow stop): No stdout needed. Script simply exits.

**Exit 2** (block stop): Descriptive message on stderr that Claude can understand and act on:

```
The following items should be saved as memories before stopping:
- [DECISION] Chose command-type hooks over prompt-type for 100% reliability (score: 0.72)
- [TECH_DEBT] Deferred multi-model consensus voting for future implementation (score: 0.55)

Use the memory-management skill to save each item. After saving, you may stop.
```

### 5.6 Error Handling

All exceptions are caught at the top level. The script NEVER crashes in a way that produces non-zero exit codes other than 0 or 2.

```python
def main() -> int:
    try:
        # ... all logic ...
        return exit_code  # 0 or 2
    except Exception:
        return 0  # Fail open: never trap the user

if __name__ == "__main__":
    sys.exit(main())
```

### 5.7 Configuration

The script reads optional configuration from `memory-config.json` (same file used by memory_retrieve.py):

```json
{
  "triage": {
    "enabled": true,
    "max_messages": 50,
    "thresholds": {
      "DECISION": 0.4,
      "RUNBOOK": 0.4,
      "CONSTRAINT": 0.5,
      "TECH_DEBT": 0.4,
      "PREFERENCE": 0.4,
      "SESSION_SUMMARY": 0.6
    }
  }
}
```

Missing or invalid config falls back to defaults.

## 6. Design Decisions & Rationale

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Single command hook replacing 6 prompt hooks | Eliminates 6x failure amplification. Single point of control. 0% error rate. |
| 2 | Python stdlib only | No external dependencies. Matches project convention (all scripts except memory_write.py are stdlib-only). |
| 3 | Fail open (exit 0 on any error) | Missing a memory is better than trapping the user. UX priority. |
| 4 | Heuristics-only (no external LLM in v1) | Keeps complexity low, latency under 200ms, zero API cost. LLM integration deferred to v2 if heuristic recall is insufficient. |
| 5 | Flag TTL of 5 minutes | Prevents stale flags from giving a "free pass" after extended work. Gemini review recommendation. |
| 6 | 4-line sliding window for co-occurrence | Captures cross-sentence reasoning without paragraph-level noise. Gemini review recommendation. |
| 7 | Code block stripping | Prevents matching keywords in code (e.g., `decision_tree`, `TODO` in comments). Reduces false positives. |
| 8 | Per-category threshold normalization | Different categories have different signal characteristics. SESSION_SUMMARY is cumulative; DECISION is binary+co-occurrence. |

## 7. Self-Critique: What Could Go Wrong?

### 7.1 False Positives (Blocking unnecessarily)
**Risk:** Heuristics match keywords in discussion about decisions/preferences without actual decisions being made. E.g., "We discussed whether to use Redis but didn't decide."
**Mitigation:** Co-occurrence requirement. "discussed" alone doesn't trigger. Needs "decided"/"chose" + "because"/"over". Threshold tuning.

### 7.2 False Negatives (Missing memories)
**Risk:** Subtle decisions expressed without trigger keywords. E.g., "Let's go with approach B" (no "decided", "chose", "because").
**Mitigation:** Acceptable in v1. User can always manually save. LLM integration in v2 for ambiguous cases. The key requirement is 0% errors, not 100% recall.

### 7.3 Transcript File Issues
**Risk:** Stale transcript_path (GitHub #8564), missing after /clear (#3046), not yet flushed.
**Mitigation:** Defensive handling: if file missing/empty, exit 0. Don't scan for "most recent .jsonl" (adds complexity, potential security risk of reading wrong session).

### 7.4 stdin Not Available
**Risk:** Claude Code might not provide stdin data in all contexts.
**Mitigation:** Graceful fallback: if stdin is empty or unparseable, exit 0.

### 7.5 Long Transcripts
**Risk:** Very long sessions could have 1000+ messages. Reading entire file is slow.
**Mitigation:** Only process last N messages (default 50). Read file line-by-line (streaming, not load-all).

### 7.6 Flag File Race Condition
**Risk:** Two concurrent stop attempts could race on flag creation/deletion.
**Mitigation:** Minimal risk in practice (user initiates stop sequentially). `unlink(missing_ok=True)` handles TOCTOU.

### 7.7 Non-English Content
**Risk:** Keywords are English-only. Non-English conversations won't trigger heuristics.
**Mitigation:** Acceptable for v1. Most Claude Code interactions are English-dominant. The worst case is a false negative (missed memory), not a false positive or error.

## 8. Comparison: Before vs After

| Aspect | Before (6 prompt hooks) | After (1 command hook) |
|--------|------------------------|----------------------|
| Error rate | ~17-26% per stop | **0%** |
| Hook type | prompt (LLM-dependent) | command (deterministic) |
| Hook count | 6 parallel | 1 |
| Intelligence | High (LLM semantic) | Medium (keyword heuristic) |
| Latency | 2-5s (6 parallel LLM calls) | <200ms (local heuristic) |
| Cost | 6x Haiku API calls | $0 |
| UX | 6 error messages | Clean, no errors |
| Dependencies | Claude Code internal LLM | Python stdlib |
| Failure mode | JSON validation error | Silent pass (exit 0) |

## 9. Implementation Plan

1. Create `hooks/scripts/memory_triage.py` (~400 LOC)
2. Update `hooks/hooks.json` (replace 6 Stop entries with 1)
3. Compile check: `python3 -m py_compile hooks/scripts/memory_triage.py`
4. Smoke test: echo test JSON to stdin
5. Log implementation to `temp/03-implementation-log.md`

## 10. Future Enhancements (v2, not in scope)

- Optional external LLM for ambiguous cases (Gemini Flash / Haiku API)
- SessionEnd hook for session summary processing
- Multi-language keyword sets
- Feedback loop: track which blocked stops actually led to memory saves
