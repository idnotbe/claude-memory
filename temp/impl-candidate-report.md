# impl-candidate Report: --new-info-file for memory_candidate.py

## Summary

Added `--new-info-file` optional argument to `hooks/scripts/memory_candidate.py` per Change 2 of the spec. This allows passing new-info text via file instead of inline bash argument, which prevents Guardian from scanning memory content that may contain protected path references like `.env`.

## Changes Made

**File:** `hooks/scripts/memory_candidate.py`

### 1. Argparse block (lines 201-208)
- Changed `--new-info` from `required=True` to optional
- Added `--new-info-file` as a new optional argument

### 2. Post-parse validation (lines 221-233)
- If `--new-info-file` is provided: reads file content, assigns to `args.new_info`
- If both provided: `--new-info-file` takes precedence (file content overwrites inline)
- If neither provided: `parser.error()` with clear message
- Error handling for: `FileNotFoundError`, `PermissionError`, generic `OSError`

### 3. Zero changes to downstream logic
- The rest of the script uses `args.new_info` / `new_info` unchanged (line 255)
- Scoring, matching, output format all identical

## Design Decisions

**Why not `mutually_exclusive_group`?**
- The spec says "If both are provided, --new-info-file takes precedence (or error -- your choice)"
- Allowing both with file precedence is more forgiving and avoids user confusion
- A mutually exclusive group doesn't enforce "at least one" without additional code anyway
- Manual validation after `parse_args()` is cleaner and more explicit

**Why `parser.error()` instead of `sys.exit()`?**
- `parser.error()` prints usage + error message and exits with code 2, consistent with argparse conventions
- Existing error paths in the script use `sys.exit(1)` for runtime errors, while argparse errors use exit code 2

## Testing Results

| Test | Input | Expected | Result |
|------|-------|----------|--------|
| File-based (valid file) | `--new-info-file /tmp/mem-test/new-info.txt` | Proceeds to index lookup | PASS |
| Inline (original behavior) | `--new-info "test info"` | Same as before | PASS |
| Neither provided | no `--new-info` flags | Error: "one of --new-info or --new-info-file is required" | PASS |
| Non-existent file | `--new-info-file /tmp/nonexistent.txt` | Error: "--new-info-file not found" | PASS |
| Precedence (both provided) | `--new-info "unrelated" --new-info-file file-with-match.txt` | File content used (score=12) | PASS |
| Full regression suite | `pytest tests/ -v` | All tests pass | PASS (435 passed, 10 xpassed) |

## Backwards Compatibility

- Existing callers using `--new-info "..."` continue to work unchanged
- The only behavioral change is that `--new-info` is no longer marked `required=True` in argparse, but the manual validation enforces the same constraint (at least one source required)

## Usage Example

```bash
# Old (inline -- may trigger Guardian if content contains .env):
python3 memory_candidate.py --category session_summary --new-info "Session discussed .env configuration..."

# New (file-based -- bypasses Guardian):
python3 memory_candidate.py --category session_summary --new-info-file /tmp/.memory-new-info-12345.txt
```
