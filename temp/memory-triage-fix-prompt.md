# Fix Critical Bugs in memory_triage.py

## Context

The Stop hook (`hooks/scripts/memory_triage.py`) fires on every session end but **never captures any memories**. Root cause investigation revealed **3 bugs** in the transcript parsing and exit protocol. All 3 must be fixed.

The hook has been running across 76 sessions in the ops project with zero automated captures. The bugs were confirmed by analyzing real session transcript JSONL files.

## Real Transcript JSONL Format (VERIFIED)

Real Claude Code session transcripts (`.jsonl` files) have this structure:

```jsonl
{"type": "user", "message": {"role": "user", "content": "actual user text as a STRING"}}
{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "actual response..."}, {"type": "tool_use", "name": "Read", "input": {...}}]}}
{"type": "file-history-snapshot", ...}
{"type": "progress", ...}
```

Key facts:
- **User messages**: `type: "user"` (NOT `"human"`), content at `msg["message"]["content"]` -- can be either a **string** (plain text) OR a **list of blocks** (containing `tool_result` and `text` types). In real transcripts, ~66% of user messages have list content.
- **Assistant messages**: `type: "assistant"`, content at `msg["message"]["content"]` as a **list of blocks** containing `text`, `tool_use`, and `thinking` types
- **Tool use blocks**: Nested INSIDE assistant message content arrays as `{"type": "tool_use", "name": "...", ...}`
- **Thinking blocks**: Nested inside assistant content as `{"type": "thinking", "thinking": "..."}`. Do NOT extract text from these -- they contain internal reasoning that would inflate false positives.
- **There is NO top-level `"content"` key** on any message -- `msg.get("content")` returns `None`/empty
- **There is NO `type: "human"`** in real transcripts
- **Use defensive access**: Always use `msg.get("message", {}).get("content", "")` NOT `msg["message"]["content"]` (which would KeyError on malformed messages)

## Bug 1: `extract_text_content()` -- Transcript Format Mismatch

**Current code** (around line 239):
```python
def extract_text_content(messages: list[dict]) -> str:
    parts: list[str] = []
    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type not in ("human", "assistant"):  # BUG: "human" should be "user"
            continue
        content = msg.get("content", "")  # BUG: content is at msg["message"]["content"]
        if isinstance(content, list):
            ...
```

**Two bugs**:
1. Filters for `"human"` but real transcripts use `"user"` -- all user messages are skipped
2. Reads `msg.get("content")` but content is at `msg["message"]["content"]` -- returns empty string

**Impact**: Extracts 0 non-whitespace characters from real transcripts. All keyword scores = 0.0.

**Fix requirements**:
- Accept `"user"` in addition to `"human"` and `"assistant"` (keep `"human"` for backwards compatibility with test fixtures)
- Read content from `msg.get("message", {}).get("content", "")` first, fall back to `msg.get("content", "")` if nested path doesn't exist (use defensive `.get()` chaining, NOT direct key access)
- Content can be a `str` OR a `list` of blocks for BOTH user and assistant messages -- handle both (the list handling code already exists for the flat case)
- Do NOT extract text from `thinking` blocks (`{"type": "thinking", ...}`) -- only extract from `text` blocks

## Bug 2: `extract_activity_metrics()` -- Same Format Mismatch

**Current code** (around line 267):
```python
def extract_activity_metrics(messages: list[dict]) -> dict[str, int]:
    tool_uses = 0
    tool_names: set[str] = set()
    exchanges = 0
    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type == "tool_use":       # BUG: tool_use is not a top-level type
            tool_uses += 1
            name = msg.get("name", "")
            ...
        elif msg_type in ("human", "assistant"):  # BUG: "human" should be "user"
            exchanges += 1
```

**Three bugs**:
1. Looks for `type: "tool_use"` at top level but tool_use blocks are nested inside assistant message content arrays
2. Counts `"human"` for exchanges but should count `"user"`
3. Doesn't look inside `msg["message"]["content"]` for nested tool_use blocks

**Fix requirements**:
- Accept `"user"` in addition to `"human"` and `"assistant"` for exchange counting
- For assistant messages, iterate through `msg.get("message", {}).get("content", [])` blocks and count `type: "tool_use"` blocks (use defensive `.get()` chaining)
- Extract tool names from nested tool_use blocks
- Keep existing top-level tool_use counting as fallback
- Do NOT extract tool_result blocks from user content for tool counting (tool_use only appears in assistant content)

## Bug 3: Exit Protocol -- Plugin Hook Compatibility

**Current code** (around line 958 in `_run_triage()`):
```python
print(message, file=sys.stderr)
return 2
```

**The bug**: For plugin hooks loaded via `--plugin-dir`, `exit code 2 + stderr` does not work correctly. Claude Code issue #10875 documents this: plugin hook stderr output from exit-2 hooks is not captured/acted on. The Anthropic collaborator recommended switching to the advanced JSON hook API.

**Fix requirements**:
- Change the blocking response to use **stdout JSON + exit 0**:
  ```python
  import json
  response = {"decision": "block", "reason": message}
  print(json.dumps(response))  # stdout ONLY
  return 0
  ```
- **CRITICAL: stdout must contain ONLY the final JSON payload.** Audit the ENTIRE script for any other `print()` calls that write to stdout. ALL diagnostic/debug prints must use `sys.stderr`. If ANY non-JSON text appears on stdout, Claude Code will fail to parse the hook response.
- For the "allow stop" case (no results), output nothing and return 0 (current behavior is correct -- it returns 0 with no output)
- **Update docstrings**: The module-level docstring (lines 9-12), `main()` docstring, and `format_block_message()` docstring all reference "exit 2" and "stderr". Update them to reflect the new exit 0 + stdout JSON protocol.

## Bug 4 (MEDIUM): `parse_transcript()` Deque Dilution

**Current code** (around line 214):
```python
maxlen = max_messages if max_messages > 0 else None
messages: collections.deque[dict] = collections.deque(maxlen=maxlen)
```

The deque stores ALL message types (progress, system, file-history-snapshot, queue-operation, etc.) but has a max of 50 entries. Real transcripts have many non-content messages (e.g., 883 `progress` messages vs 245 `user` messages in a sample of 10 sessions). These non-content messages push out actual user/assistant messages from the deque.

**Fix**: Filter the deque to only store messages with `type` in `("user", "human", "assistant")`. Other message types should be skipped before appending.

## Additional Improvement: Score Logging (Observability)

Currently there is ZERO logging of triage scores, making debugging impossible after the fact.

**Add**: After running `run_triage()` and before the decision output, append a one-line JSON log entry to `/tmp/.memory-triage-scores.log` with the timestamp, per-category scores, which categories triggered, and the cwd. Use the actual variable names from the codebase (check what `run_triage()` returns and adapt accordingly). Wrap in try/except OSError to fail silently -- this is non-critical observability.

Write this to **stderr** or to the file only -- never to stdout (see Bug 3 warning).

## Process Requirements

1. **Run `pytest` BEFORE making any changes** to establish a green baseline. If any tests fail before your changes, note them.
2. **Make the fixes** to `hooks/scripts/memory_triage.py`
3. **Update existing tests** in `tests/test_memory_triage.py` to cover the new transcript format:
   - Add test cases with `type: "user"` messages where content is a **string**
   - Add test cases with `type: "user"` messages where content is a **list** (containing `tool_result` and `text` blocks)
   - Add test cases with `type: "assistant"` messages (nested content as list of blocks)
   - Add test cases with nested `tool_use` blocks inside assistant content
   - Add test case verifying `thinking` blocks in assistant content are NOT extracted
   - Add test case verifying the JSON stdout output format for blocking (capture stdout, assert valid JSON, assert `decision` and `reason` keys)
   - Add at least one **end-to-end integration test**: create a realistic JSONL transcript file, feed it through the full `_run_triage()` pipeline, verify correct behavior
   - Add test case for `parse_transcript` deque filtering (verify non-content messages don't push out user/assistant messages)
   - Keep existing tests passing (backwards compat with `type: "human"` format)
4. **Run `pytest` AFTER changes** to verify everything passes
5. **Do NOT change** any other files besides `memory_triage.py` and `test_memory_triage.py` unless absolutely necessary
6. **Do NOT add external dependencies** -- the script must remain stdlib-only

## Verification Checklist

After all changes, verify:
- [ ] `pytest` passes with no failures
- [ ] `extract_text_content()` returns non-empty text from messages with `type: "user"` and nested content
- [ ] `extract_text_content()` returns non-empty text from messages with `type: "assistant"` and nested content
- [ ] `extract_text_content()` still works with old-format messages (`type: "human"`, flat `content`)
- [ ] `extract_activity_metrics()` counts exchanges for `type: "user"` messages
- [ ] `extract_activity_metrics()` counts tool_use from nested assistant content blocks
- [ ] Blocking output goes to stdout as JSON `{"decision": "block", "reason": "..."}`
- [ ] No non-JSON output appears on stdout (capture and verify)
- [ ] Allow-stop case returns 0 with no stdout output
- [ ] Score logging writes to `/tmp/.memory-triage-scores.log`
- [ ] `thinking` blocks in assistant content are NOT extracted as text
- [ ] `tool_result` blocks in user content list are NOT extracted as text (only `text` blocks are)
- [ ] `parse_transcript()` filters out non-content message types (progress, system, etc.)
- [ ] Module, `main()`, and `format_block_message()` docstrings updated to reflect new exit protocol
