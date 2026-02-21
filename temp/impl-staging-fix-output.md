# Implementation Report: Staging Path Fix

## Summary
Fixed `commands/memory-save.md` to use `.claude/memory/.staging/` path instead of `/tmp/`.

## Changes Made

### File: `commands/memory-save.md` (lines 39-40)

**Before:**
```
5. Write the JSON to `/tmp/.memory-write-pending.json`
6. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action create --category <cat> --target <memory_root>/<folder>/<slug>.json --input /tmp/.memory-write-pending.json`
```

**After:**
```
5. Write the JSON to `.claude/memory/.staging/.memory-write-pending.json`
6. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action create --category <cat> --target <memory_root>/<folder>/<slug>.json --input .claude/memory/.staging/.memory-write-pending.json`
```

## Why This Is Correct

1. **Direct conflict resolved:** `memory_write.py`'s `_read_input()` (line 1181) enforces `"/.claude/memory/.staging/" in resolved`. Any input file outside `.staging/` is rejected with a `SECURITY_ERROR`. The old `/tmp/` path would always fail validation, making the `/memory:save` command non-functional.
2. **Consistent with SKILL.md:** The SKILL.md (line 99) already uses `.claude/memory/.staging/draft-<category>-<pid>.json` for draft files. This fix aligns the `/memory:save` command with the established pattern.
3. **Security alignment:** The `.staging/` enforcement exists as defense-in-depth against subagent manipulation. Using `/tmp/` would bypass workspace isolation.
4. **Backward-compatible:** The old path was always rejected, so this fix makes a broken feature work rather than changing working behavior.

## Cross-Model Validation Results (pal clink)

### Codex
- **Status:** Unavailable (usage limit exceeded). Could not validate.

### Gemini (gemini-3.1-pro-preview)
- **Verdict:** "Exactly the correct approach"
- **Key points:**
  1. Explicit security validation in `_read_input()` was designed to prevent path traversal attacks
  2. Cross-platform compatibility -- `/tmp/` assumes Unix-like environment
  3. Workspace isolation -- project-local `.staging/` prevents cross-project artifacts
- **Additional suggestion:** Add `.claude/memory/.staging/` to `.gitignore` (note: likely already handled by existing `.claude/` gitignore patterns)

## Vibe Check Results

### Quick Assessment
Plan is on track -- minimal, targeted fix for a clear path mismatch.

### Key Questions Raised
1. Does `.staging/` directory get created automatically? Yes -- the triage hook and SKILL.md flow create it; the Write tool also creates intermediate directories.
2. Is the relative path resolved correctly? Yes -- `os.path.realpath()` in `_read_input()` resolves relative paths against the CWD, which is the project root during Claude Code sessions.
3. Is this backward-compatible? Yes -- the old path always failed, so this makes a broken feature work.

### Recommendation
Proceed. Fix is correct and minimal.

## MEMORY-CONSOLIDATION-PROPOSAL.md Assessment

The proposal has many `/tmp/` references (Sections 4.4.1, Appendix B, etc.) but is already marked with a large warning banner: "HISTORICAL DOCUMENT -- DO NOT IMPLEMENT FROM THIS SPEC". These references are archival context for the v4.2 design and do not affect runtime behavior. No changes needed.

## Additional Findings: Other Stale `/tmp/` References

The following files also contain `/tmp/.memory-write-pending` references that are out of scope for this fix but should be noted:

1. **`hooks/scripts/memory_write.py` (lines 11, 15)** -- Docstring usage examples. Informational only.
2. **`hooks/scripts/memory_write_guard.py` (lines 42-51)** -- Legacy `/tmp/` allowlist alongside `.staging/` allowlist. Dead code since `_read_input()` rejects `/tmp/` paths.
3. **`TEST-PLAN.md` (line 140)** -- References `/tmp/.memory-write-pending.json` as "explicitly allowed."
4. **`tests/test_memory_write_guard.py` (lines 58-61)** -- Test asserting `/tmp/` writes are allowed (validates dead code).

### Recommendation for Follow-Up
The dead `/tmp/` allowlist in `memory_write_guard.py` (lines 42-51) and its corresponding test should be cleaned up in a separate task.

## Deployment
ops project loads this plugin via `.claude/plugin-dirs` pointing to `~/projects/claude-memory`. Fixing the source here automatically fixes ops.
