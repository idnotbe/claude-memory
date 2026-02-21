# Implementation Notes: memory_triage.py Bug Fixes

**File modified**: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_triage.py`
**Date**: 2026-02-18
**Baseline**: 14 tests passing, all still passing after changes

---

## Changes Made

### Bug 1: `extract_text_content()` (lines 250-254)
- **Line 251**: Changed type filter from `("human", "assistant")` to `("user", "human", "assistant")`
- **Line 254**: Changed content path from `msg.get("content", "")` to `msg.get("message", {}).get("content", "") or msg.get("content", "")`
- Keeps "human" for backwards compatibility with test fixtures
- The `or` fallback ensures old-format flat `content` still works
- Existing list-block handling already correctly skips thinking/tool_result blocks (only extracts `type: "text"`)

### Bug 2: `extract_activity_metrics()` (lines 280-299)
- **Line 288**: Added `"user"` to exchange counting: `("user", "human", "assistant")`
- **Lines 291-299**: For assistant messages, iterates through `msg.get("message", {}).get("content", [])` and counts `tool_use` blocks, extracting tool names
- Kept existing top-level `tool_use` check as backwards-compat fallback (lines 282-287)
- Only inspects assistant content for tool_use (not user content, which has tool_result)

### Bug 3: Exit Protocol (line 992 + docstrings)
- **Line 992**: Changed `print(message, file=sys.stderr)` + `return 2` to `print(json.dumps({"decision": "block", "reason": message}))` + `return 0`
- **Lines 9-11**: Updated module docstring from exit codes to "Output protocol (advanced JSON hook API)"
- **Lines 894-897**: Updated `main()` docstring to reflect exit code 0 + stdout JSON
- **Line 808**: Updated `format_block_message()` docstring from "stderr message for exit 2" to "stdout JSON response"
- **Line 789**: Updated `_sanitize_snippet()` docstring from "stderr output" to "output"
- **Stdout audit**: Confirmed only 2 print() calls exist -- error handler (line 903) writes to stderr, block output (line 992) now writes JSON to stdout. No stdout contamination.

### Bug 4: `parse_transcript()` Deque Filtering (lines 232-234)
- **Lines 232-234**: Before appending to deque, filters: `if msg_type in ("user", "human", "assistant")`
- Prevents non-content messages (progress, system, file-history-snapshot, etc.) from wasting deque slots
- Safe to combine with Bug 2 fix: tool_use counting now reads from nested assistant content, not top-level messages

### Improvement: Score Logging (lines 956-972)
- Added `import datetime` at module-level imports (line 19)
- After `run_triage()` call (line 954), appends a JSON log entry to `/tmp/.memory-triage-scores.log`
- Log includes: timestamp, cwd, text_len, exchanges, tool_uses, triggered categories with scores
- Wrapped in `try/except OSError` for silent failure
- Writes to FILE ONLY -- never stdout or stderr

## Interaction Safety

- **Bug 2 + Bug 4**: Fixed atomically. Bug 4 filters out top-level `tool_use` messages from deque, but Bug 2's fix reads tool_use from nested assistant content instead. Safe.
- **Bug 3 + Improvement**: Score logging writes to file, not stdout. No interference with JSON response.
- **All bugs**: `"human"` kept in all type filters for backwards compatibility.

## Test Results

- `python3 -m py_compile hooks/scripts/memory_triage.py` -- clean
- `pytest tests/test_memory_triage.py -v` -- 14 passed, 0 failed
