# Round 1 Functional Verification Report

**Verifier:** verifier-r1-functional
**Date:** 2026-02-20
**Scope:** Functional correctness of the `/tmp/` -> `.staging/` path fix in `commands/memory-save.md`

---

## 1. Verify Lines 39-40 Contain the Correct New Path

**PASS**

`commands/memory-save.md` lines 39-40 now read:

```
5. Write the JSON to `.claude/memory/.staging/.memory-write-pending.json`
6. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action create --category <cat> --target <memory_root>/<folder>/<slug>.json --input .claude/memory/.staging/.memory-write-pending.json`
```

Both the Write target (step 5) and the `--input` argument (step 6) use the same relative path: `.claude/memory/.staging/.memory-write-pending.json`. These are consistent with each other.

---

## 2. Trace the Validation Path: `_read_input()` (memory_write.py:1165-1205)

**PASS -- The new path will pass all validation checks.**

### Validation Step 1: `..` component check (line 1173)
```python
if ".." in input_path:
```
The path `.claude/memory/.staging/.memory-write-pending.json` contains no `..` components. **PASS.**

### Validation Step 2: `.staging/` substring check (line 1181)
```python
resolved = os.path.realpath(input_path)
in_staging = "/.claude/memory/.staging/" in resolved
```

When Claude Code runs from the project root (e.g., `/home/user/projects/ops/`), `os.path.realpath(".claude/memory/.staging/.memory-write-pending.json")` resolves to:
```
/home/user/projects/ops/.claude/memory/.staging/.memory-write-pending.json
```

The substring `/.claude/memory/.staging/` is present in the resolved path. **PASS.**

### Validation Step 3: File read (lines 1190-1205)
The file was written by the Write tool in step 5 before `memory_write.py` is invoked in step 6, so `open(resolved, "r")` will find the file. **PASS.**

### Cross-Model Verification (pal clink -- Gemini)
Gemini confirmed: **Yes**, `os.path.realpath()` on the relative path will contain `/.claude/memory/.staging/` as long as no intermediate directories are symlinks. In a normal Claude Code session where `.claude/memory/.staging/` is created as standard directories (either by the triage hook or the Write tool), this holds.

**Edge case noted:** If any component (`.claude`, `memory`, `.staging`) were a symlink, `os.path.realpath()` would resolve through the symlink and the substring check could fail. However, this is a pre-existing limitation of the security validation, not introduced by this fix. The security review (task #2) already assessed symlink risk as LOW, and it applies equally to the auto-capture flow's `draft-<category>-<pid>.json` paths.

---

## 3. `.staging/` Directory Handling

**PASS -- No directory creation gap.**

### Who creates `.staging/`?

1. **The triage hook (`memory_triage.py`)** creates `.staging/` at line 705-707:
   ```python
   staging_dir = os.path.join(cwd, ".claude", "memory", ".staging")
   os.makedirs(staging_dir, exist_ok=True)
   ```
   This runs on every Stop hook invocation where triage triggers.

2. **The SKILL.md auto-capture flow** -- subagents write draft files to `.staging/`, implying it exists.

3. **Claude Code's Write tool** -- when writing to a path like `.claude/memory/.staging/.memory-write-pending.json`, the Write tool creates all intermediate directories automatically (equivalent to `mkdir -p`).

### What if `.staging/` does not exist when `/memory:save` is used?

This is handled correctly. The `/memory:save` command (step 5) uses the Write tool to create the JSON file at `.claude/memory/.staging/.memory-write-pending.json`. The Write tool creates `.claude/memory/.staging/` as needed. There is **no dependency on the triage hook having run first**.

Even in a fresh project where no triage has ever fired, the Write tool will create the full directory tree on its own.

---

## 4. End-to-End Flow Check

**PASS -- Complete flow verified.**

Tracing the full `/memory:save decision "some content"` flow:

| Step | Action | Verified |
|------|--------|----------|
| 1 | User runs `/memory:save decision "We chose Vitest over Jest"` | Triggers `commands/memory-save.md` |
| 2 | Claude reads `.claude/memory/memory-config.json` | Validates `decision` is a valid category |
| 3 | Claude generates kebab-case slug (e.g., `chose-vitest-over-jest`) | Standard text processing |
| 4 | Claude generates JSON with full schema fields | Per memory-save.md steps 3-4 |
| 5 | Claude uses Write tool to create `.claude/memory/.staging/.memory-write-pending.json` | Write tool creates directories and file |
| 5a | `memory_write_guard.py` PreToolUse fires | Checks if path targets memory dir |
| 5b | Guard sees `/.claude/memory/.staging/` in path | Lines 56-58: `sys.exit(0)` -- ALLOWED |
| 6 | Claude calls: `python3 $PLUGIN_ROOT/.../memory_write.py --action create --category decision --target .claude/memory/decisions/chose-vitest-over-jest.json --input .claude/memory/.staging/.memory-write-pending.json` | Bash tool execution |
| 6a | `_read_input()` resolves path with `os.path.realpath()` | Gets `/abs/path/.claude/memory/.staging/.memory-write-pending.json` |
| 6b | `..` check | No `..` in path -- PASS |
| 6c | `.staging/` substring check | `/.claude/memory/.staging/` found in resolved -- PASS |
| 6d | JSON read and parse | File exists (written in step 5), valid JSON -- PASS |
| 6e | Pydantic schema validation | Claude generated valid schema in step 4 |
| 6f | Atomic write to target | File written to `decisions/chose-vitest-over-jest.json` |
| 6g | `_cleanup_input()` | Deletes `.memory-write-pending.json` from staging |
| 6h | Index update | `index.md` entry added |
| 7 | Claude confirms creation | Shows filename and summary to user |

**All steps verified. The flow is functionally correct.**

---

## 5. Write Guard Verification

**PASS -- The write guard allows the staging file.**

`memory_write_guard.py` lines 53-58:
```python
normalized = resolved.replace(os.sep, "/")
staging_segment = "/.claude/memory/.staging/"
if staging_segment in normalized:
    sys.exit(0)
```

When the Write tool creates `.claude/memory/.staging/.memory-write-pending.json`:
1. The guard resolves the path to an absolute path via `os.path.realpath()`
2. Normalizes path separators
3. Checks if `/.claude/memory/.staging/` is in the normalized path
4. It is -- `sys.exit(0)` allows the write

**The guard will NOT block the Write tool from creating the staging file.**

### Test Coverage Gap

There is **no test** in `test_memory_write_guard.py` that verifies the `.staging/` allowlist (lines 53-58). The existing test at line 57 (`test_allows_temp_staging_file`) only tests the old `/tmp/` path:
```python
def test_allows_temp_staging_file(self):
    """Writes to /tmp/.memory-write-pending.json are allowed."""
    hook_input = {"tool_input": {"file_path": "/tmp/.memory-write-pending.json"}}
```

**Recommendation:** A follow-up test should be added that verifies a path like `/some/project/.claude/memory/.staging/.memory-write-pending.json` passes the guard.

---

## 6. Test Coverage for `/memory:save` Flow

**NO EXISTING TESTS**

Grep of `tests/` for `memory.save`, `memory:save`, and `memory-save` returned zero matches. There are no automated tests covering the `/memory:save` command flow.

This is expected -- `/memory:save` is a command file (instructions for the LLM), not executable code. Testing the command flow end-to-end would require integration tests that simulate LLM behavior. However, the individual components that the command invokes (write guard, `_read_input()`, `memory_write.py` create action) are tested separately.

---

## 7. Summary

| Check | Result | Notes |
|-------|--------|-------|
| Lines 39-40 correct | PASS | Both path references use `.claude/memory/.staging/.memory-write-pending.json` |
| `_read_input()` validation | PASS | No `..`, substring `/.claude/memory/.staging/` present in resolved path |
| `.staging/` directory creation | PASS | Write tool creates directories; no dependency on triage hook |
| End-to-end flow | PASS | All 7 steps verified, including guard and validation |
| Write guard allows staging | PASS | `staging_segment` check at line 57 allows the path |
| Cross-model verification | PASS | Gemini confirms `os.path.realpath()` produces expected substring (no-symlink case) |

### Gaps Identified (Outside Fix Scope)

| ID | Severity | Issue |
|----|----------|-------|
| F1 | LOW | No test for `.staging/` allowlist in `test_memory_write_guard.py` (only `/tmp/` allowlist tested) |
| F2 | INFO | No integration tests for the `/memory:save` command flow |
| F3 | INFO | Symlink edge case in `_read_input()` -- pre-existing, not introduced by this fix |

### Verdict

**APPROVED -- The fix is functionally correct.** The relative path `.claude/memory/.staging/.memory-write-pending.json` passes all validation gates (`_read_input()` security checks and `memory_write_guard.py` staging allowlist), the Write tool handles directory creation, and the end-to-end flow from user command to memory file creation works correctly.
