# Deep Analysis Report: memory_triage.py Bugs + Improvement

**Analyst**: analyst agent
**Date**: 2026-02-17
**Source file**: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_triage.py` (967 lines)
**Test file**: `/home/idnotbe/projects/claude-memory/tests/test_memory_triage.py` (331 lines)
**Bug spec**: `/home/idnotbe/projects/claude-memory/temp/memory-triage-fix-prompt.md`
**Baseline**: 14 tests pass (all green)

---

## Table of Contents

1. [Bug 1: extract_text_content() -- Transcript Format Mismatch](#bug-1)
2. [Bug 2: extract_activity_metrics() -- Same Format Mismatch](#bug-2)
3. [Bug 3: Exit Protocol -- Plugin Hook Compatibility](#bug-3)
4. [Bug 4: parse_transcript() Deque Dilution](#bug-4)
5. [Improvement: Score Logging](#improvement)
6. [Interaction Effects](#interaction-effects)
7. [Additional Findings](#additional-findings)

---

## Bug 1: `extract_text_content()` -- Transcript Format Mismatch {#bug-1}

### Exact Location

- **File**: `hooks/scripts/memory_triage.py`
- **Function**: `extract_text_content()`, lines 239-264
- **Critical lines**: 248 (type filter), 250 (content path)

### Current Code (lines 245-258)

```python
parts: list[str] = []
for msg in messages:
    msg_type = msg.get("type", "")
    if msg_type not in ("human", "assistant"):       # LINE 248: BUG
        continue
    content = msg.get("content", "")                  # LINE 250: BUG
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
    elif isinstance(content, str):
        parts.append(content)
```

### Root Cause

**Two independent bugs combining to produce zero output:**

1. **Type filter mismatch (line 248)**: The code filters for `"human"` but real Claude Code transcripts use `"user"` as the type for user messages. This means ALL user messages are silently skipped. The original code was likely written against an earlier or different transcript format (or a test fixture that used "human").

2. **Content path mismatch (line 250)**: The code reads `msg.get("content", "")` but in real transcripts, content is nested at `msg["message"]["content"]`. The top-level message dict has `type` and `message` keys -- there is no top-level `content` key. So even for assistant messages (which pass the type filter), `msg.get("content", "")` returns `""`.

**Combined effect**: 0 non-whitespace characters extracted from any real transcript. Since keyword scoring depends entirely on this text, ALL category scores = 0.0, and the hook NEVER triggers.

### Fix Strategy

```python
# BEFORE (lines 245-258):
parts: list[str] = []
for msg in messages:
    msg_type = msg.get("type", "")
    if msg_type not in ("human", "assistant"):
        continue
    content = msg.get("content", "")
    if isinstance(content, list):
        ...

# AFTER:
parts: list[str] = []
for msg in messages:
    msg_type = msg.get("type", "")
    if msg_type not in ("user", "human", "assistant"):  # Accept both "user" and "human"
        continue
    # Try nested path first (real transcripts), fall back to flat (test fixtures)
    content = msg.get("message", {}).get("content", "") or msg.get("content", "")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
    elif isinstance(content, str):
        parts.append(content)
```

Key changes:
- Add `"user"` to the accepted types tuple (keep `"human"` for backwards compat)
- Use `msg.get("message", {}).get("content", "")` as primary path, fall back to `msg.get("content", "")`
- The `or` operator handles the case where the nested path returns an empty string/falsy -- it falls back to the flat path. NOTE: if nested path returns `[]` (empty list), that's falsy so we'd fall back to flat. This is fine since an empty list means no content either way.
- Existing list-block handling already correctly extracts `"text"` type blocks and ignores others (including `"thinking"` blocks since they have `type: "thinking"`, not `type: "text"`)

### Risk Assessment

**Low risk.**

- The `or` fallback ensures old-format messages (flat `content`) still work.
- Adding `"user"` to the tuple is additive -- does not break `"human"` handling.
- The list-block iteration already correctly skips non-text blocks (`tool_use`, `thinking`, `tool_result`).
- **Edge case**: If a real message has BOTH `msg["message"]["content"]` AND `msg["content"]`, the nested path wins. This is correct since real transcripts use the nested path.
- **Edge case**: `thinking` blocks have `type: "thinking"` and the extraction only looks for `type: "text"`, so they are correctly excluded without any additional code.

### Backwards Compatibility

**Full backwards compatibility maintained.** Old-format messages with `type: "human"` and flat `content` key continue to work because:
1. `"human"` is still in the accepted types tuple
2. The `or` fallback reads `msg.get("content", "")` when nested path returns empty/falsy

### Test Implications

**New tests needed:**
- `type: "user"` with string content at `msg["message"]["content"]`
- `type: "user"` with list content (containing `tool_result` and `text` blocks)
- `type: "assistant"` with list content (containing `text`, `tool_use`, `thinking` blocks)
- Verify `thinking` blocks are NOT extracted
- Verify `tool_result` blocks in user content are NOT extracted
- Verify old `type: "human"` with flat `content` still works

**Existing tests to check:**
- No existing tests directly test `extract_text_content()` with message dicts -- the existing tests focus on `load_config`, `write_context_files`, and `format_block_message`. So no existing tests should break.

---

## Bug 2: `extract_activity_metrics()` -- Same Format Mismatch {#bug-2}

### Exact Location

- **File**: `hooks/scripts/memory_triage.py`
- **Function**: `extract_activity_metrics()`, lines 267-290
- **Critical lines**: 278 (tool_use check), 283 (type filter)

### Current Code (lines 272-290)

```python
tool_uses = 0
tool_names: set[str] = set()
exchanges = 0

for msg in messages:
    msg_type = msg.get("type", "")
    if msg_type == "tool_use":           # LINE 278: BUG - no top-level tool_use type
        tool_uses += 1
        name = msg.get("name", "")
        if name:
            tool_names.add(name)
    elif msg_type in ("human", "assistant"):  # LINE 283: BUG - "human" should include "user"
        exchanges += 1

return {
    "tool_uses": tool_uses,
    "distinct_tools": len(tool_names),
    "exchanges": exchanges,
}
```

### Root Cause

**Three bugs:**

1. **Top-level `tool_use` check (line 278)**: The code checks for `msg_type == "tool_use"` at the top level, but in real transcripts, `tool_use` blocks are NESTED inside assistant message content arrays as `{"type": "tool_use", "name": "Read", ...}`. There is no top-level message with `type: "tool_use"` in real transcripts.

2. **Missing "user" in type filter (line 283)**: Same as Bug 1 -- filters for `"human"` but real transcripts use `"user"`. Exchange count for user messages = 0.

3. **No nested content inspection**: Even if we fix the type filter, the function doesn't look inside `msg["message"]["content"]` to find nested tool_use blocks.

**Combined effect**: `tool_uses = 0`, `distinct_tools = 0`, `exchanges` only counts assistant messages (since "human" doesn't match "user"). SESSION_SUMMARY scoring is severely impacted.

### Fix Strategy

```python
# AFTER:
tool_uses = 0
tool_names: set[str] = set()
exchanges = 0

for msg in messages:
    msg_type = msg.get("type", "")
    if msg_type == "tool_use":
        # Fallback: top-level tool_use (backwards compat with flat format)
        tool_uses += 1
        name = msg.get("name", "")
        if name:
            tool_names.add(name)
    elif msg_type in ("user", "human", "assistant"):
        exchanges += 1
        # For assistant messages, inspect nested content for tool_use blocks
        if msg_type == "assistant":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses += 1
                        name = block.get("name", "")
                        if name:
                            tool_names.add(name)

return {
    "tool_uses": tool_uses,
    "distinct_tools": len(tool_names),
    "exchanges": exchanges,
}
```

Key changes:
- Add `"user"` to exchange counting tuple
- For assistant messages, iterate through nested `msg.get("message", {}).get("content", [])` and count `tool_use` blocks
- Keep existing top-level `tool_use` check as fallback for backwards compat
- Only look for tool_use in assistant content (NOT user content -- user content has `tool_result` blocks, which are responses TO tool uses, not tool uses themselves)

### Risk Assessment

**Low risk.**

- Adding `"user"` to exchange counting is additive.
- The nested content inspection only runs for `assistant` messages, which is correct.
- Top-level `tool_use` fallback is kept for backwards compat.
- **Edge case**: If the same assistant message is in both old and new format (impossible in practice, but defensively), tool_uses would be double-counted. This is acceptable since the formats are mutually exclusive.
- **Edge case**: `msg.get("message", {}).get("content", [])` correctly returns `[]` for old-format messages, so no iteration happens.

### Backwards Compatibility

**Full backwards compatibility maintained.** Old-format messages with flat `tool_use` type and `"human"` type still work via the fallback paths.

### Test Implications

**New tests needed:**
- Exchange counting with `type: "user"` messages
- Tool use counting from nested assistant content blocks
- Mix of old-format (`type: "tool_use"` top-level) and new-format (nested)
- Verify `tool_result` blocks in user content are NOT counted as tool_uses
- Verify `thinking` blocks in assistant content are NOT counted

**Existing tests**: No existing tests directly test `extract_activity_metrics()`.

---

## Bug 3: Exit Protocol -- Plugin Hook Compatibility {#bug-3}

### Exact Location

- **File**: `hooks/scripts/memory_triage.py`
- **Function**: `_run_triage()`, lines 958-959
- **Also**: Module docstring lines 9-12, `main()` docstring line 881, `format_block_message()` docstring line 793

### Current Code

**Lines 958-959 (the block output):**
```python
        print(message, file=sys.stderr)
        return 2
```

**Lines 9-12 (module docstring):**
```python
Exit codes:
  0 -- Allow stop (nothing to save, or error/fallback)
  2 -- Block stop (stderr contains items to save)
```

**Line 881 (main docstring):**
```python
    """Main entry point for the memory triage hook.

    Returns exit code: 0 (allow stop) or 2 (block stop).
    """
```

**Line 793 (format_block_message docstring):**
```python
    """Format the stderr message for exit 2 (block stop).
```

### Root Cause

For plugins loaded via `--plugin-dir`, Claude Code's hook system does not capture stderr output from hooks that exit with code 2. This is documented in Claude Code issue #10875. The Anthropic-recommended workaround is to use the advanced JSON hook API: output `{"decision": "block", "reason": "..."}` to **stdout** and exit with code **0**.

The current code writes the message to stderr and returns exit code 2. This means the hook runs, detects categories to save, but its output is silently discarded by Claude Code. The agent never sees the triage results and never saves memories.

### Fix Strategy

**Line 958-959: Change block output to stdout JSON + exit 0:**

```python
# BEFORE:
        print(message, file=sys.stderr)
        return 2

# AFTER:
        response = {"decision": "block", "reason": message}
        print(json.dumps(response))  # stdout ONLY
        return 0
```

**Module docstring (lines 1-14): Update exit protocol description:**

```python
# BEFORE:
"""Memory triage hook for claude-memory plugin (Stop event).

Replaces 6 unreliable type:"prompt" Stop hooks with 1 deterministic
type:"command" hook. Reads the conversation transcript, applies keyword
heuristic scoring for 6 memory categories, and decides whether to block
the stop so the agent can save memories.

Exit codes:
  0 -- Allow stop (nothing to save, or error/fallback)
  2 -- Block stop (stderr contains items to save)

No external dependencies (stdlib only).
"""

# AFTER:
"""Memory triage hook for claude-memory plugin (Stop event).

Replaces 6 unreliable type:"prompt" Stop hooks with 1 deterministic
type:"command" hook. Reads the conversation transcript, applies keyword
heuristic scoring for 6 memory categories, and decides whether to block
the stop so the agent can save memories.

Output protocol (advanced JSON hook API):
  Block stop: exit 0, stdout = {"decision": "block", "reason": "..."}
  Allow stop: exit 0, no stdout output

No external dependencies (stdlib only).
"""
```

**main() docstring (line 881):**

```python
# BEFORE:
    """Main entry point for the memory triage hook.

    Returns exit code: 0 (allow stop) or 2 (block stop).
    """

# AFTER:
    """Main entry point for the memory triage hook.

    Returns exit code 0. Block/allow decision is communicated via
    stdout JSON (advanced hook API), not exit codes.
    """
```

**format_block_message() docstring (line 793):**

```python
# BEFORE:
    """Format the stderr message for exit 2 (block stop).

# AFTER:
    """Format the block message for stdout JSON response (block stop).
```

### Stdout Audit

**CRITICAL**: Stdout must contain ONLY the final JSON payload when blocking. I audited every `print()` call in the script:

| Line | Call | Target | Status |
|------|------|--------|--------|
| 887 | `print(f"[memory_triage] Error (fail-open): {e}", file=sys.stderr)` | stderr | SAFE |
| 958 | `print(message, file=sys.stderr)` | stderr (will change to stdout JSON) | WILL BE CHANGED |

**Result: Only 2 print calls exist, both to stderr. No stdout contamination risk.** No library imports produce stdout output. The script only imports stdlib modules.

**Note on `json` import**: Already imported at line 19. No additional import needed for `json.dumps()`.

### Risk Assessment

**Medium risk.**

- The `format_block_message()` output (which becomes the `reason` field value) contains `<triage_data>` XML tags and nested JSON. This creates a "JSON string containing XML containing JSON" nesting. `json.dumps()` handles the escaping correctly, but the `reason` string will be large.
- If a future code change adds a `print()` to stdout anywhere in the execution path, it would corrupt the JSON output and break the hook silently. **Mitigation**: The existing codebase discipline of using `file=sys.stderr` is well-established.
- The `main()` exception handler (line 887) correctly prints to stderr, so even on error, stdout stays clean.
- **If the `_run_triage()` function raises AFTER a partial stdout write** (hypothetically), the exception handler would not clean up stdout. However, this cannot happen with the proposed fix since `json.dumps()` + `print()` is atomic from the application's perspective -- the JSON is fully serialized before print is called.

### Backwards Compatibility

**Breaking change for the exit protocol**, but this is intentional and necessary. The old protocol (exit 2 + stderr) was non-functional for plugin hooks. No downstream consumer depends on the old protocol since it never worked.

### Test Implications

**New tests needed:**
- Capture stdout from the blocking path, assert valid JSON with `decision` and `reason` keys
- Assert NO non-JSON text on stdout
- Assert allow-stop case produces no stdout output and returns 0
- Assert error handler produces no stdout output

**Existing tests**: No existing tests test `_run_triage()` directly.

---

## Bug 4: `parse_transcript()` Deque Dilution {#bug-4}

### Exact Location

- **File**: `hooks/scripts/memory_triage.py`
- **Function**: `parse_transcript()`, lines 214-236
- **Critical lines**: 230-231 (append without filtering)

### Current Code (lines 220-236)

```python
maxlen = max_messages if max_messages > 0 else None
messages: collections.deque[dict] = collections.deque(maxlen=maxlen)
try:
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict):
                    messages.append(msg)      # LINE 231: appends ALL types
            except json.JSONDecodeError:
                continue
except (OSError, IOError):
    return []
return list(messages)
```

### Root Cause

The deque stores ALL JSONL message types (progress, system, file-history-snapshot, queue-operation, etc.) but has a maximum capacity of 50 entries (DEFAULT_MAX_MESSAGES). In real transcripts, non-content messages vastly outnumber content messages. Sample data from the bug spec: 883 `progress` messages vs 245 `user` messages across 10 sessions.

With `maxlen=50`, the deque acts as a sliding window. When progress messages flood in, they push out the actual user/assistant messages. By the time the file is fully read, the deque may contain mostly progress messages and very few (or zero) actual conversation messages.

Since `extract_text_content()` and `extract_activity_metrics()` both skip non-content types, the downstream functions effectively see an empty or near-empty conversation.

### Fix Strategy

```python
# BEFORE (line 230-231):
                msg = json.loads(line)
                if isinstance(msg, dict):
                    messages.append(msg)

# AFTER:
                msg = json.loads(line)
                if isinstance(msg, dict):
                    msg_type = msg.get("type", "")
                    if msg_type in ("user", "human", "assistant"):
                        messages.append(msg)
```

This filters at the deque-append point so only content-bearing message types consume deque slots.

### Risk Assessment

**Low risk, but requires careful consideration of Bug 2 interaction.**

- The filter uses the same type set (`"user"`, `"human"`, `"assistant"`) that the downstream extraction functions accept.
- **Key interaction with Bug 2**: The current (buggy) `extract_activity_metrics()` also checks for top-level `type: "tool_use"` messages. After Bug 4's fix, those would be filtered out of the deque. However, Bug 2's fix changes the tool_use counting to look inside nested assistant content, making the top-level check a backwards-compat fallback only. Since Bug 2 and Bug 4 are being fixed together, this is safe. **If Bug 4 were fixed WITHOUT fixing Bug 2, tool_use counting via the old path would break.** The bugs MUST be fixed together.
- Other message types (`progress`, `system`, `file-history-snapshot`, etc.) contain no data used by any downstream function.

### Backwards Compatibility

**Full backwards compatibility for content messages.** The change only removes non-content messages from the deque. Old-format messages with `type: "human"` are preserved by the filter.

**Breaking for any hypothetical code that relies on non-content messages being present** -- no such code exists in the current codebase.

### Test Implications

**New tests needed:**
- Create a JSONL with many `progress`/`system` messages interspersed with a few `user`/`assistant` messages, set `max_messages` low, verify only content messages are retained
- Verify deque with `max_messages=5` and 100 progress + 10 user/assistant messages retains the last 5 user/assistant messages
- Verify old-format `type: "human"` messages are not filtered out

**Existing tests**: No existing tests test `parse_transcript()`.

---

## Improvement: Score Logging (Observability) {#improvement}

### Location

- **File**: `hooks/scripts/memory_triage.py`
- **Function**: `_run_triage()`, after line 938 (`results = run_triage(...)`)
- **Log target**: `/tmp/.memory-triage-scores.log`

### Current State

Zero logging of triage scores. When the hook runs across 76 sessions with no captures, there is no way to diagnose why after the fact. No scores, no thresholds, no triggered categories are recorded anywhere.

### Implementation Strategy

**Important design consideration** (identified via Gemini code review): `run_triage()` returns only categories that EXCEED their threshold. To log ALL scores (for observability), we need to either:

1. Call the scoring functions directly before `run_triage()`, OR
2. Add logging INSIDE `_run_triage()` by calling the scoring functions and `run_triage` separately, OR
3. Log only the triggered categories from `results` (less useful but simpler)

**Recommended approach**: Option 3 -- log the triggered categories from `results` plus the overall decision. This gives sufficient observability without modifying `run_triage()` or duplicating scoring work. The key diagnostic question ("did anything trigger?") is answered, and the per-category scores for triggered categories are included.

For completeness/advanced debugging, also log the total text length and exchange count as proxies for "did extraction work?"

```python
# Insert AFTER line 938: results = run_triage(text, metrics, config["thresholds"])

# Score logging (non-critical observability)
try:
    import datetime
    log_entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "cwd": cwd,
        "text_len": len(text),
        "exchanges": metrics.get("exchanges", 0),
        "tool_uses": metrics.get("tool_uses", 0),
        "triggered": [
            {"category": r["category"], "score": round(r["score"], 4)}
            for r in results
        ],
    }
    with open("/tmp/.memory-triage-scores.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")
except OSError:
    pass  # Non-critical: fail silently
```

**Critical**: This writes to a file, NOT to stdout or stderr. Writing to stdout would corrupt the JSON response (Bug 3). Writing to stderr would add noise to the error stream.

### Risk Assessment

**Very low risk.**

- Wrapped in try/except OSError -- fails silently.
- File append writes under ~500 bytes are atomic on Linux (POSIX guarantees for writes under PIPE_BUF = 4096 bytes).
- Concurrent sessions appending to the same file are safe due to atomic append.
- `datetime` is stdlib -- no new dependencies.
- **Important**: The `import datetime` is at function scope to avoid adding a module-level import. Alternatively, move it to the top-level imports (cleaner but slightly changes the file's import section).

### Test Implications

**New tests needed:**
- After running through the triage pipeline, verify `/tmp/.memory-triage-scores.log` was written
- Verify the log line is valid JSON with expected keys
- Verify the log write doesn't interfere with stdout output

---

## Interaction Effects {#interaction-effects}

### Bug 1 + Bug 2: Independent but Same Pattern

Both bugs have the same root cause (transcript format mismatch) applied to different functions. The fix pattern is identical: add `"user"` to type filter, read from nested content path. They should be fixed with the same approach for consistency.

### Bug 1 + Bug 4: Sequential Dependency

Bug 4 (deque filtering) determines WHICH messages reach `extract_text_content()` (Bug 1's function). With Bug 4 fixed, the messages list passed to `extract_text_content()` contains only `user`/`human`/`assistant` messages. Without Bug 4, the list contains all types (but `extract_text_content` filters internally anyway). So Bug 4 is an optimization that prevents deque slot waste, while Bug 1 is a correctness fix. They are logically independent but Bug 4 amplifies Bug 1's effectiveness.

### Bug 2 + Bug 4: MUST Fix Together

**CRITICAL INTERACTION**: Bug 4 filters the deque to only include `user`/`human`/`assistant` messages. The current (buggy) `extract_activity_metrics()` checks for top-level `type: "tool_use"` messages. After Bug 4's filter, top-level `tool_use` messages would be excluded from the deque. This would break the old tool_use counting path.

However, Bug 2's fix changes tool_use counting to look INSIDE nested assistant content blocks. Since assistant messages pass Bug 4's filter, the nested tool_use blocks remain accessible.

**Conclusion**: Bug 2 and Bug 4 MUST be fixed atomically. Fixing Bug 4 without Bug 2 would break tool_use counting (though it was already broken in practice since top-level tool_use messages don't exist in real transcripts).

### Bug 3: Independent

Bug 3 (exit protocol) is purely about output format and is independent of the data extraction bugs.

### Improvement + Bug 3: Stdout Discipline

The score logging improvement MUST NOT write to stdout. Bug 3 establishes that stdout is reserved exclusively for the JSON response payload. The logging implementation writes to a file, which is correct.

---

## Additional Findings {#additional-findings}

### Finding 1: `_sanitize_snippet()` Docstring (Minor)

Line 774: `"""Sanitize a snippet for safe injection into stderr output."""` -- the word "stderr" should be updated to "output" since Bug 3 changes the output target. However, the sanitization is still needed regardless of output target (the snippet ends up in the JSON `reason` field). This is a minor documentation nit, not a bug.

### Finding 2: `run_triage()` Returns Only Above-Threshold Results

`run_triage()` (lines 393-427) only returns categories whose scores exceed their thresholds. This is correct behavior for the triage decision, but it means the score logging improvement cannot log below-threshold scores without additional work. The recommended approach (Option 3 in the Improvement section) accepts this limitation.

### Finding 3: Memory of Transcript Format (Defensive Coding)

The `extract_text_content()` function currently handles `isinstance(block, str)` in the list case (line 255-256). This handles a hypothetical format where content is a list of plain strings. After the fix, this path still works. It's good defensive coding that should be preserved.

### Finding 4: No `tool_result` Extraction Risk

User messages in real transcripts can have list content containing `tool_result` blocks:
```json
{"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "file contents..."}, {"type": "text", "text": "Here's what I found"}]}}
```

The current `extract_text_content()` list handling only extracts `type: "text"` blocks, so `tool_result` content is automatically excluded. This is correct -- tool result content would inflate false positives with code/file contents. **No fix needed**, but tests should verify this behavior.

### Finding 5: Scalability Note

`parse_transcript()` reads the entire JSONL file line by line. For very large transcripts (100MB+), this could be slow. However, this is acceptable for the current use case and not within scope of the bug fixes.

---

## Summary: Fix Priority and Dependency Order

| Fix | Priority | Risk | Dependency |
|-----|----------|------|------------|
| Bug 1 (extract_text_content) | CRITICAL | Low | None |
| Bug 2 (extract_activity_metrics) | CRITICAL | Low | Must fix with Bug 4 |
| Bug 3 (exit protocol) | HIGH | Medium | None |
| Bug 4 (deque dilution) | MEDIUM | Low | Must fix with Bug 2 |
| Improvement (score logging) | LOW | Very Low | Depends on Bug 3 (stdout discipline) |

**Recommended fix order**: Bug 4 -> Bug 1 -> Bug 2 -> Bug 3 -> Improvement (or all at once since they're in the same file).

---

## Test Coverage Plan for Test Writer

### Tests to Add for Bug 1 (`extract_text_content`)

| Test | Description | Existing? |
|------|-------------|-----------|
| test_extract_text_user_string_content | `type: "user"` with string at `msg["message"]["content"]` | No |
| test_extract_text_user_list_content | `type: "user"` with list content (text + tool_result blocks) | No |
| test_extract_text_assistant_list_content | `type: "assistant"` with list content (text + tool_use + thinking blocks) | No |
| test_extract_text_thinking_blocks_excluded | `thinking` blocks NOT extracted | No |
| test_extract_text_tool_result_excluded | `tool_result` blocks in user content NOT extracted | No |
| test_extract_text_human_backwards_compat | Old `type: "human"` with flat `content` still works | No |
| test_extract_text_mixed_formats | Mix of old and new format messages | No |

### Tests to Add for Bug 2 (`extract_activity_metrics`)

| Test | Description | Existing? |
|------|-------------|-----------|
| test_metrics_user_exchange_count | `type: "user"` counted as exchange | No |
| test_metrics_nested_tool_use | tool_use blocks inside assistant content counted | No |
| test_metrics_tool_result_not_counted | tool_result in user content NOT counted as tool_use | No |
| test_metrics_thinking_not_counted | thinking blocks NOT counted | No |
| test_metrics_backwards_compat | Old flat format still works | No |

### Tests to Add for Bug 3 (exit protocol)

| Test | Description | Existing? |
|------|-------------|-----------|
| test_block_output_stdout_json | Blocking path outputs valid JSON to stdout with decision+reason keys | No |
| test_block_output_no_extra_stdout | No non-JSON text on stdout | No |
| test_allow_stop_no_stdout | Allow-stop case: exit 0, no stdout | No |
| test_error_handler_no_stdout | Error path: no stdout, only stderr | No |

### Tests to Add for Bug 4 (deque filtering)

| Test | Description | Existing? |
|------|-------------|-----------|
| test_parse_transcript_filters_non_content | progress/system messages excluded from deque | No |
| test_parse_transcript_deque_capacity | With low max_messages, content messages not pushed out by noise | No |
| test_parse_transcript_human_preserved | Old `type: "human"` messages preserved by filter | No |

### Tests to Add for Improvement (score logging)

| Test | Description | Existing? |
|------|-------------|-----------|
| test_score_log_written | After triage, log file created with valid JSON | No |
| test_score_log_no_stdout_interference | Log write doesn't appear on stdout | No |

### End-to-End Integration Test

| Test | Description | Existing? |
|------|-------------|-----------|
| test_e2e_realistic_transcript | Full pipeline: JSONL file -> parse -> extract -> triage -> output decision | No |
