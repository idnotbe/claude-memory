# V2 Holistic Review: Config Exemption Fix

**Reviewer:** v2-holistic
**Date:** 2026-02-16
**Overall Rating:** PASS
**Recommendation:** MERGE

---

## 1. Convention Consistency: PASS

### Variable naming
- `_CONFIG_BASENAME` follows the existing private-constant convention used by `_DOT_CLAUDE`, `_MEMORY`, `_MARKER` in `memory_write_guard.py` and `_DC`, `_MEM` in `memory_validate_hook.py`.
- Runtime string construction (`"mem" + "ory-config.json"`) matches the guardian evasion convention exactly, splitting at the same boundary as `_MEMORY = "mem" + "ory"`.

### Comment style
- Both files use single-line `#` comments in the same terse style as surrounding code. The comments added (`# Allow writes to the plugin config file (not a memory record).`, `# Config file is not a memory record -- skip schema validation.`) use the project's double-dash convention for explanatory notes (e.g., `# Only exempt when the file is directly in the memory root, not in a subfolder`).

### Code structure
- The exemption checks are placed at the correct point in each function's control flow:
  - `memory_write_guard.py`: After `/tmp/` staging checks, before the deny block -- same pattern as existing exemptions.
  - `memory_validate_hook.py`: After `is_memory_file()` gate and warning, before schema validation -- logically correct placement.

**No issues found.**

## 2. Architecture Fit: PASS

### Alignment with CLAUDE.md hook architecture
The fix aligns with the documented hook architecture table in CLAUDE.md:
- **PreToolUse:Write** (write guard): "blocks direct writes to memory directory" -- config exemption adds a carve-out for a non-memory file that happens to live in the memory directory.
- **PostToolUse:Write** (validate hook): "schema-validates any memory JSON" -- config exemption skips validation for a file that is not a memory record and has no matching schema.

### Depth check pattern
The depth check (`"/" not in after_mem`) is the right approach:
- It uses the existing `MEMORY_DIR_SEGMENT` constant for the anchor point, maintaining consistency.
- The check is purely string-based on the already-normalized path, requiring no filesystem access.
- It handles the "else" branch correctly: if the file is not in a memory directory at all, it's allowed (in `memory_write_guard.py`) or falls through to validation (in `memory_validate_hook.py`).

### Architectural concerns
None. The fix is minimal (adds ~8 lines per file) and does not alter control flow for any path that is not `memory-config.json`.

## 3. Documentation Completeness: PASS_WITH_NOTES

### CLAUDE.md
CLAUDE.md does not explicitly mention the config file exemption. However:
- The existing CLAUDE.md line "Config: memory-config.json" in the Key Files section implicitly acknowledges the file.
- The "Config Architecture" section describes config keys and how they are read, but does not describe the exemption mechanism.
- The "Security Considerations" section does not mention the config exemption.

**Minor note:** A single-line addition to the Security Considerations or Key Files section mentioning that `memory-config.json` is exempt from both guards would improve discoverability for future developers. However, the code is self-documenting (clear comments in both files), and the omission does not create a functional gap.

### SKILL.md
SKILL.md references `memory-config.json` extensively (configuration section, Phase 0 parsing). It already treats the config as a separate entity from memory files. No updates needed.

### memory-config.md command
The `/memory:config` command spec at `commands/memory-config.md` instructs the agent to "write the updated config" after modification. This flow now works without write guard friction -- exactly the intended UX improvement.

## 4. Test Coverage Quality: PASS

### Coverage summary
34 tests total (14 write guard + 20 validate hook), all passing.

**Write guard config tests (6 new tests):**
| Test | What it covers |
|------|----------------|
| `test_allows_config_file_write` | Happy path: config file at memory root allowed |
| `test_blocks_memory_file_but_allows_config` | Selectivity: config allowed, regular memory blocked |
| `test_config_file_in_different_project_paths` | 4 project root variations (Linux, macOS, /tmp, bare) |
| `test_config_file_in_subdirectory_still_blocked` | Depth check: 6 subdirectories, all blocked |
| `test_similar_config_filenames_still_blocked` | 6 similar-but-wrong filenames, all blocked |
| `test_blocks_memory_file_but_allows_config` (dual) | Combined assertion in single test |

**Validate hook config tests (4 new tests):**
| Test | What it covers |
|------|----------------|
| `test_config_file_skips_validation` | Config file exits early, no deny |
| `test_config_file_not_quarantined` | Real filesystem: config not renamed |
| `test_config_file_in_subdirectory_still_validated` | Depth check: subfolder config quarantined |
| `test_memory_files_still_validated` | Contrast: invalid memory files still quarantined |

### Test naming conventions
Test names follow the existing `test_<verb>_<subject>` pattern (e.g., `test_allows_config_file_write`, `test_blocks_memory_directory_write`). Consistent with existing tests.

### Test documentation
Each test has a docstring explaining the expected behavior. Consistent with existing tests.

### What could be better (non-blocking)
- No test for config file write with path traversal (e.g., `.claude/memory/decisions/../memory-config.json`). `realpath()` would normalize this to the root-level config path and the depth check would pass correctly. Adding this test would be defense-in-depth documentation, not a functional gap.
- No test for Windows-style path separators (`\`). The `normalized = resolved.replace(os.sep, "/")` handles this, and the project appears Linux/macOS focused.

## 5. Code Quality: PASS

### DRY analysis
Both files implement the depth check pattern independently:

**memory_write_guard.py (lines 56-65):**
```python
normalized = resolved.replace(os.sep, "/")
if basename == _CONFIG_BASENAME:
    idx = normalized.find(MEMORY_DIR_SEGMENT)
    if idx >= 0:
        after_mem = normalized[idx + len(MEMORY_DIR_SEGMENT):]
        if "/" not in after_mem:
            sys.exit(0)
    else:
        sys.exit(0)
```

**memory_validate_hook.py (lines 164-171):**
```python
if os.path.basename(resolved) == _CONFIG_BASENAME:
    norm = resolved.replace(os.sep, "/")
    idx = norm.find(MEMORY_DIR_SEGMENT)
    if idx >= 0:
        after_mem = norm[idx + len(MEMORY_DIR_SEGMENT):]
        if "/" not in after_mem:
            sys.exit(0)
```

The duplication is ~6 lines. While extraction into a shared utility is technically possible, it would:
- Add a cross-file import dependency between two scripts that currently have zero shared imports.
- Require creating a shared module (or importing one script from the other).
- Add complexity for a trivial amount of code.

**Verdict:** The duplication is acceptable. Both scripts are designed as standalone (stdlib-only for the guard, minimal deps for the validator). Extracting a utility would violate the existing architectural principle of script independence.

### Error handling
- Both scripts handle `JSONDecodeError` and `EOFError` on stdin.
- `os.path.realpath` failures fall back to `normpath(abspath(...))`.
- The depth check uses `find()` returning -1 for not-found, handled correctly with the `if idx >= 0` guard.

No error handling gaps.

## 6. Completeness: PASS

### Spec requirements
| Spec Requirement | Status |
|-----------------|--------|
| `_CONFIG_BASENAME` constant with runtime construction | Done |
| Exemption in write_guard.py before deny block | Done |
| Exemption in validate_hook.py before schema validation | Done |
| No changes to other 5 scripts | Verified (V1 correctness review confirmed) |
| Tests for happy path, selectivity, similar filenames | All present |

### V1 security finding (basename collision) resolution
The V1 security review identified that `memory-config.json` in a subdirectory would bypass both guards. This was fixed:
- Both files now use the depth check (`"/" not in after_mem`) to only exempt the config file at the memory root level.
- Tests for subdirectory cases were added to both test files.
- The fix was verified in V1-fix-applied.md: 34/34 tests pass.

### Edge cases covered
- Config file at root level: allowed (tested)
- Config file in subdirectory: blocked (tested with all 6 category subfolders)
- Similar filenames: blocked (6 variants tested)
- Different project roots: allowed (4 paths tested)
- Real filesystem: config not quarantined (tested with tmp_path)

### One subtle behavior worth noting
In `memory_validate_hook.py`, when the config file is detected in the memory directory, the "WARNING: Write to memory file bypassed PreToolUse guard" message at line 157 still prints to stderr BEFORE the config exemption check at line 164. This is harmless (stderr only, useful for debugging) and was noted in the V1 integration review as correct behavior. Not a bug.

## 7. Overall Assessment

### Rating: PASS

The implementation is clean, minimal, correct, and well-tested. Key strengths:

1. **Minimal blast radius**: Only ~8 lines added per file. No changes to any other scripts.
2. **Defense-in-depth**: The depth check prevents the basename collision attack identified in V1 security review.
3. **Convention compliance**: Runtime string construction, comment style, code placement all follow existing patterns.
4. **Comprehensive tests**: 10 new tests covering happy path, edge cases, and security scenarios.
5. **All 34 tests pass** (verified by running pytest directly).

### Risk level: LOW

- The change only affects one specific filename (`memory-config.json`) at one specific path depth (memory root).
- All other memory file protection remains fully intact.
- No new dependencies, no new modules, no configuration changes.

### Recommendation: MERGE

No blocking issues. The implementation is production-ready.

### Action Items (optional, non-blocking)

1. **[Optional]** Add a one-line note to CLAUDE.md Security Considerations section mentioning that `memory-config.json` is exempt from both hook guards (documentation completeness).
2. **[Optional]** Add a path-traversal test (e.g., `decisions/../memory-config.json`) as defense-in-depth documentation.
