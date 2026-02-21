# Fix Instructions: claude-memory Plugin

**Context**: Two bugs need to be fixed in the `claude-memory` plugin repo.
**Repo path**: `/home/idnotbe/projects/claude-memory/`

Paste this file into a Claude Code session opened in the `claude-memory` repo and ask it to implement all changes.

---

## Overview of Changes

### Change 1: Rename `--action delete` to `--action retire`

The CLI action `--action delete` is misleading. The operation is a **soft-retire** (sets `record_status` to `"retired"` in the memory index), not a file deletion. Renaming to `--action retire` makes the semantics clear and eliminates a regex collision with the `claude-code-guardian` plugin.

Affects: `hooks/scripts/memory_write.py`, `skills/memory-management/SKILL.md`, `commands/memory.md`, `hooks/scripts/memory_write_guard.py`, `CLAUDE.md`, `tests/test_memory_write.py`, `README.md`

### Change 2: Remove `/tmp/` from `_read_input()`, only allow `.staging/`

The `_read_input()` function in `memory_write.py` currently only accepts input files from `/tmp/`. But the rest of the pipeline (skill instructions, `memory_triage.py`) writes drafts to `.claude/memory/.staging/`. This causes a `SECURITY_ERROR` when agents pass staging paths to `memory_write.py --input`. Fix: accept only `.staging/` paths.

Affects: `hooks/scripts/memory_write.py` (one function)

---

## What NOT to Change

Before starting, read these carefully:

- **CUD internal labels**: In `SKILL.md`, there are references to `UPDATE_OR_DELETE` (in `structural_cud` fields) and `DELETE` as a CUD decision table value. These are **internal state machine labels** from `memory_candidate.py`, NOT CLI arguments. Do NOT change them.
- **`"UPDATE over DELETE"` principle** in `SKILL.md`: This is a conceptual safety default, not a CLI invocation. Do NOT change it.
- **`_cleanup_input()` function**: This function in `memory_write.py` physically deletes a staging draft file after it is processed. It is named "cleanup" and the docstring says "Delete the temp input file." This is NOT the retire operation. Do NOT rename or change it.
- **Config keys** like `delete.grace_period_days` and `delete.archive_retired`: These are configuration YAML/TOML key names, not CLI argument names. Do NOT rename these.
- **Comment at line ~843**: `# Rename flow: write new, update index, delete old` -- this describes physically unlinking an old JSON file during a slug rename, not the retire operation. Do NOT change this comment.
- **`temp/*.md` files**: Historical analysis artifacts. Do NOT update them.
- **`MEMORY-CONSOLIDATION-PROPOSAL.md`**: Historical proposal doc. Low priority -- see end of file for guidance.

---

## Change 1: Rename `--action delete` to `--action retire`

### File 1.1: `hooks/scripts/memory_write.py`

**Location**: Find these by content -- line numbers may shift.

#### 1.1.1 Module docstring (near top of file)

Find:
```
Handles CREATE, UPDATE, DELETE, ARCHIVE, UNARCHIVE, and RESTORE operations
```
Replace `DELETE` with `RETIRE`:
```
Handles CREATE, UPDATE, RETIRE, ARCHIVE, UNARCHIVE, and RESTORE operations
```

#### 1.1.2 Usage example in module docstring

Find (approximate lines 17-19):
```
python3 memory_write.py --action delete \
    --target ...
    --reason "..."
```
Change `--action delete` to `--action retire`.

#### 1.1.3a Comment near record_status immutability (around line 497)

Find:
```python
# record_status immutable via UPDATE (only via delete/archive)
```
Replace with:
```python
# record_status immutable via UPDATE (only via retire/archive)
```

#### 1.1.3b Error message string (inside `do_delete` or validation logic)

Find:
```python
"fix: Use --action delete to retire, or --action archive to archive"
```
Replace with:
```python
"fix: Use --action retire to retire, or --action archive to archive"
```

#### 1.1.4 Function definition

Find:
```python
def do_delete(args, ...):
    """Handle --action delete (retire)."""
```
Replace with:
```python
def do_retire(args, ...):
    """Handle --action retire (soft retire)."""
```

#### 1.1.5 Internal label in `_check_path_containment` call (inside renamed function)

Find (inside the old `do_delete` / new `do_retire` function):
```python
_check_path_containment(target_abs, memory_root, "DELETE")
```
Replace with:
```python
_check_path_containment(target_abs, memory_root, "RETIRE")
```

#### 1.1.6 Error output strings (inside renamed function)

Find all occurrences:
```python
f"DELETE_ERROR\ntarget: ..."
```
Replace `DELETE_ERROR` with `RETIRE_ERROR` in all occurrences within the retire function. There are approximately 2 such strings.

#### 1.1.7 argparse choices

Find:
```python
choices=["create", "update", "delete", "archive", "unarchive", "restore"]
```
Replace with:
```python
choices=["create", "update", "retire", "archive", "unarchive", "restore"]
```

#### 1.1.8 argparse `--reason` help text

Find:
```python
help="Reason for deletion or archival (delete/archive)"
```
Replace with:
```python
help="Reason for retirement or archival (retire/archive)"
```

#### 1.1.9 Dispatch block

Find:
```python
elif args.action == "delete":
    return do_delete(args, memory_root, index_path)
```
Replace with:
```python
elif args.action == "retire":
    return do_retire(args, memory_root, index_path)
```

---

### File 1.2: `skills/memory-management/SKILL.md`

**Important**: Only change the 4 locations listed below. Do NOT change `UPDATE_OR_DELETE`, the CUD table, or `"UPDATE over DELETE"`.

#### 1.2.1 Draft JSON written by LLM (Phase 1 step)

Find (approximately line 100):
```
Write {"action": "delete", "target": ..., "reason": ...}
```
Replace `"action": "delete"` with `"action": "retire"`.

#### 1.2.2 Phase 3 step (CLI invocation)

Find (approximately line 130):
```
--action delete --target <path> --reason "<why>"
```
Replace with:
```
--action retire --target <path> --reason "<why>"
```

#### 1.2.3 Session rolling window example

Find (approximately line 218):
```
memory_write.py --action delete --target <path> --reason "Session rolling window..."
```
Replace `--action delete` with `--action retire`.

#### 1.2.4 User intent mapping

Find (approximately line 244):
```
"Forget..." -> ... retire via memory_write.py --action delete
```
Replace `--action delete` with `--action retire`.

#### 1.2.5 Subagent report instruction (line ~102)

Find:
```
Report: action (CREATE/UPDATE/DELETE/NOOP)
```
Replace `DELETE` with `RETIRE`:
```
Report: action (CREATE/UPDATE/RETIRE/NOOP)
```

#### 1.2.6 Write protections note (line ~143)

Find:
```
record_status cannot be changed via UPDATE (use delete/archive actions)
```
Update to:
```
record_status cannot be changed via UPDATE (use retire/archive actions)
```

---

### File 1.3: `commands/memory.md`

#### 1.3.1 `--retire` subcommand definition

Find (approximately line 52):
```
--action delete --target <path> --reason "User-initiated retirement via /memory --retire"
```
Replace with:
```
--action retire --target <path> --reason "User-initiated retirement via /memory --retire"
```

---

### File 1.4: `hooks/scripts/memory_write_guard.py`

#### 1.4.1 Error message string

Find (approximately line 78):
```
"--action <create|update|delete> ..."
```
Replace with:
```
"--action <create|update|retire|archive|unarchive|restore> ..."
```
(Add the full list for completeness.)

---

### File 1.5: `CLAUDE.md`

#### 1.5.1 Architecture description

Find (approximately line 24):
```
6 actions: create, update, delete (soft retire), archive, unarchive, and restore
```
Replace with:
```
6 actions: create, update, retire (soft retire), archive, unarchive, and restore
```

#### 1.5.2 Key Files table

Find (approximately line 76):
```
memory_write.py -- create/update/delete operations...
```
Replace `delete` with `retire`.

---

### File 1.6: `tests/test_memory_write.py`

**Note**: Class and method names are non-functional -- rename them for clarity but this is optional. The functional changes (action strings and assertions) are required.

#### 1.6.1 All `run_write("delete", ...)` calls

Find all occurrences:
```python
run_write("delete", ...
```
Replace with:
```python
run_write("retire", ...
```
There are approximately 8 such calls (lines ~493, 512, 515, 524, 645, 797, 816, 847).

#### 1.6.2 `DELETE_ERROR` assertions

Find all occurrences:
```python
assert "DELETE_ERROR" in stdout
```
Replace with:
```python
assert "RETIRE_ERROR" in stdout
```
There are 2 such assertions (lines ~528, 820).

#### 1.6.3 Optional: Class and method name renames

These are non-functional but improve clarity:

| Old Name | New Name |
|----------|----------|
| `class TestDeleteFlow` | `class TestRetireFlow` |
| `def test_delete_retires(...)` | `def test_retire_retires(...)` |
| `def test_delete_idempotent(...)` | `def test_retire_idempotent(...)` |
| `def test_delete_nonexistent(...)` | `def test_retire_nonexistent(...)` |
| `class TestDeleteArchiveInteraction` | `class TestRetireArchiveInteraction` |
| `def test_delete_clears_archived_fields(...)` | `def test_retire_clears_archived_fields(...)` |
| `def test_path_traversal_delete_blocked(...)` | `def test_path_traversal_retire_blocked(...)` |
| `# First delete` comment | `# First retire` |

---

### File 1.7: `README.md`

#### 1.7.1 User-visible description of `/memory --retire`

Find (approximately line 141):
```
Soft-delete a memory
```
Replace with:
```
Soft-retire a memory
```

#### 1.7.2 Usage example comment (approximately line 159)

Find:
```
# Soft-delete, 30-day grace period
```
Replace with:
```
# Soft-retire, 30-day grace period
```

Also find nearby (approximately line 253):
```
memory_write.py --action create/update/delete/archive/unarchive
```
Or similar. Update `delete` to `retire`.

#### 1.7.3 Actions list in README

Find any remaining references to `--action delete` in the actions list section (approximately line 253). Change to `--action retire`.

---

## Change 2: Fix `_read_input()` to Only Allow `.staging/`

### File: `hooks/scripts/memory_write.py`

**Function**: `_read_input()` (approximately lines 1165-1195)

#### Current code (find by content)

```python
def _read_input(input_path: str) -> Optional[dict]:
    """Read JSON from input file in /tmp/.

    Validates that the input path is a /tmp/ path and contains no
    path traversal components (defense-in-depth against subagent
    manipulation).
    """
    resolved = os.path.realpath(input_path)
    if not resolved.startswith("/tmp/") or ".." in input_path:
        print(
            f"SECURITY_ERROR\npath: {input_path}\n"
            f"resolved: {resolved}\n"
            f"fix: Input file must be a /tmp/ path with no '..' components."
        )
        return None
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(
            f"INPUT_ERROR\npath: {input_path}\n"
            f"fix: Input file does not exist. Write JSON to the temp file first."
        )
        return None
    except json.JSONDecodeError as e:
        print(
            f"INPUT_ERROR\npath: {input_path}\n"
            f"error: Invalid JSON: {e}\n"
            f"fix: Ensure the input file contains valid JSON."
        )
        return None
```

#### Replacement code

Replace the entire `_read_input()` function with:

```python
def _read_input(input_path: str) -> Optional[dict]:
    """Read JSON from input file in .claude/memory/.staging/.

    Validates that the input path is within the project's
    .claude/memory/.staging/ directory and contains no path traversal
    components (defense-in-depth against subagent manipulation).
    """
    resolved = os.path.realpath(input_path)
    if ".." in input_path:
        print(
            f"SECURITY_ERROR\npath: {input_path}\n"
            f"resolved: {resolved}\n"
            f"fix: Input path must not contain '..' components."
        )
        return None
    # Only accept input from project-local .staging/ directory
    in_staging = "/.claude/memory/.staging/" in resolved
    if not in_staging:
        print(
            f"SECURITY_ERROR\npath: {input_path}\n"
            f"resolved: {resolved}\n"
            f"fix: Input file must be in .claude/memory/.staging/ "
            f"with no '..' components."
        )
        return None
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(
            f"INPUT_ERROR\npath: {input_path}\n"
            f"fix: Input file does not exist. Write JSON to the staging path first."
        )
        return None
    except json.JSONDecodeError as e:
        print(
            f"INPUT_ERROR\npath: {input_path}\n"
            f"error: Invalid JSON: {e}\n"
            f"fix: Ensure the input file contains valid JSON."
        )
        return None
```

**Key changes**:
- Docstring updated to reference `.staging/` instead of `/tmp/`
- `..` traversal check is now separate (not combined with startswith)
- Replaced `resolved.startswith("/tmp/")` with `"/.claude/memory/.staging/" in resolved`
- Error messages updated to reference `.staging/`

#### Note on `_cleanup_input()`

The `_cleanup_input()` function (defined just after `_read_input()`) physically deletes the input file after processing:

```python
def _cleanup_input(input_path: str) -> None:
    """Delete the temp input file."""
    try:
        os.unlink(input_path)
    except OSError:
        pass
```

**Do NOT change this function.** When input files come from `.staging/`, this will delete staging draft files after they are processed. That is correct behavior -- staging drafts are temporary and should not persist after the memory is saved. The function name and docstring reference "temp input file" which still applies (the staging file is temporary).

---

## Testing

### Run Existing Tests

After making all changes:

```bash
cd /path/to/claude-memory
python -m pytest tests/test_memory_write.py -v
```

All existing tests should pass. If any test fails with an unexpected action string or `DELETE_ERROR` assertion, check that all `run_write("delete", ...)` calls were renamed to `run_write("retire", ...)` and all `assert "DELETE_ERROR"` assertions were renamed to `assert "RETIRE_ERROR"`.

### Manual Smoke Tests for `_read_input()`

Create a test staging file and verify the path check works:

```bash
# Setup
mkdir -p .claude/memory/.staging/
echo '{"test": "data"}' > .claude/memory/.staging/test-input.json

# Should PASS (staging path)
python3 hooks/scripts/memory_write.py --action create \
    --input .claude/memory/.staging/test-input.json \
    --target .claude/memory/sessions/test.json

# Should FAIL with SECURITY_ERROR (no longer accepted)
echo '{"test": "data"}' > /tmp/test-input.json
python3 hooks/scripts/memory_write.py --action create \
    --input /tmp/test-input.json \
    --target .claude/memory/sessions/test.json

# Should FAIL with SECURITY_ERROR (path traversal)
python3 hooks/scripts/memory_write.py --action create \
    --input .claude/memory/../../../etc/passwd \
    --target .claude/memory/sessions/test.json
```

### Manual Smoke Test for `--action retire`

```bash
# Create a memory record first, then retire it
python3 hooks/scripts/memory_write.py --action create \
    --target .claude/memory/sessions/test-retire.json \
    --content '{"key": "test"}' --reason "Test record"

python3 hooks/scripts/memory_write.py --action retire \
    --target .claude/memory/sessions/test-retire.json \
    --reason "Testing retire action"

# Verify record_status is "retired" in the index
grep "test-retire" .claude/memory/.index.json
```

### Verify No Remaining `--action delete` References

After all changes, search for any remaining references that should have been renamed:

```bash
# Should return no results (excluding temp/ and MEMORY-CONSOLIDATION-PROPOSAL.md)
grep -r "\-\-action delete" . \
    --include="*.py" --include="*.md" --include="*.json" \
    --exclude-dir=temp --exclude="MEMORY-CONSOLIDATION-PROPOSAL.md"
```

### Verify Tests Have No `DELETE_ERROR` Assertions

```bash
grep "DELETE_ERROR" tests/test_memory_write.py
# Should return nothing
```

---

## Optional: `MEMORY-CONSOLIDATION-PROPOSAL.md`

This file is a historical proposal document (not runtime). It contains approximately 8 references to `--action delete`. Updating it is low priority but recommended for consistency. The references are at lines: 219, 406, 429, 598, 718, 1263-1264. Update `--action delete` to `--action retire` and `<create|update|delete>` to `<create|update|retire>` in these locations if desired.

---

## Summary Checklist

Use this to track completion:

- [ ] `hooks/scripts/memory_write.py`: Module docstring (DELETE -> RETIRE)
- [ ] `hooks/scripts/memory_write.py`: Usage example (--action delete -> --action retire)
- [ ] `hooks/scripts/memory_write.py`: Comment near record_status immutability (delete -> retire)
- [ ] `hooks/scripts/memory_write.py`: Error fix message string
- [ ] `hooks/scripts/memory_write.py`: `do_delete` renamed to `do_retire`
- [ ] `hooks/scripts/memory_write.py`: Docstring of renamed function
- [ ] `hooks/scripts/memory_write.py`: `_check_path_containment` label ("DELETE" -> "RETIRE")
- [ ] `hooks/scripts/memory_write.py`: `DELETE_ERROR` -> `RETIRE_ERROR` (2 occurrences)
- [ ] `hooks/scripts/memory_write.py`: argparse choices list
- [ ] `hooks/scripts/memory_write.py`: `--reason` help text
- [ ] `hooks/scripts/memory_write.py`: dispatch `elif args.action == "retire"`
- [ ] `hooks/scripts/memory_write.py`: `_read_input()` function replaced (Change 2)
- [ ] `skills/memory-management/SKILL.md`: Draft JSON action field (line ~100)
- [ ] `skills/memory-management/SKILL.md`: Phase 3 CLI invocation (line ~130)
- [ ] `skills/memory-management/SKILL.md`: Session rolling window example (line ~218)
- [ ] `skills/memory-management/SKILL.md`: User intent mapping (line ~244)
- [ ] `skills/memory-management/SKILL.md`: Subagent report instruction (CREATE/UPDATE/DELETE/NOOP -> RETIRE)
- [ ] `skills/memory-management/SKILL.md`: Write protections note (line ~143)
- [ ] `commands/memory.md`: `--retire` subcommand definition (line ~52)
- [ ] `hooks/scripts/memory_write_guard.py`: Error message string (line ~78)
- [ ] `CLAUDE.md`: Architecture description (line ~24)
- [ ] `CLAUDE.md`: Key Files table (line ~76)
- [ ] `tests/test_memory_write.py`: All `run_write("delete", ...)` -> `run_write("retire", ...)`
- [ ] `tests/test_memory_write.py`: `assert "DELETE_ERROR"` -> `assert "RETIRE_ERROR"` (2 occurrences)
- [ ] `README.md`: Soft-delete -> Soft-retire description (line ~141)
- [ ] `README.md`: Soft-delete comment -> Soft-retire (line ~159)
- [ ] `README.md`: Actions list references (line ~253)
- [ ] All tests pass: `python -m pytest tests/test_memory_write.py -v`
