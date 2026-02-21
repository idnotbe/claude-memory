# impl-candidate Working Notes

## Task
Add `--new-info-file` to `hooks/scripts/memory_candidate.py`

## Current State
- `--new-info` is `required=True` (line 201-203)
- Used at line 238: `new_info = args.new_info`

## Design Decision: Argparse Approach
- Make `--new-info` optional (remove `required=True`)
- Add `--new-info-file` as optional string argument
- After `parse_args()`, check: at least one must be provided
- Precedence: `--new-info-file` > `--new-info`
- Read file with proper error handling (FileNotFoundError, PermissionError, etc.)

## Why not mutually_exclusive_group?
- `mutually_exclusive_group` makes them mutually exclusive but doesn't enforce "at least one"
- We WANT to allow both (with file taking precedence per spec)
- Manual validation after parse is cleaner and more explicit

## Implementation Plan
1. Change `--new-info` to not required
2. Add `--new-info-file` argument
3. After parse_args, validate at least one provided
4. If --new-info-file, read file content, use as new_info
5. If both, --new-info-file wins (per spec: "your choice, just be consistent")

## Progress
- [x] Read spec and current file
- [x] Implement changes
- [x] Compile check (clean)
- [x] Manual test (6 scenarios, all pass)
- [x] Full test suite (435 passed, 10 xpassed)
- [x] Write report
