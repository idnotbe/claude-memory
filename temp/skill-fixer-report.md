# SKILL.md Fix Report

## Task #1: Fix SKILL.md: script paths and staging paths (R1, R2-SKILL, R5)

### Changes Made

**File:** `skills/memory-management/SKILL.md`

#### R1: Replace relative script paths with `${CLAUDE_PLUGIN_ROOT}`

| Line (before) | Old | New |
|---|---|---|
| 84 | `python3 hooks/scripts/memory_candidate.py ...` | `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" ...` |
| 125 | `python3 hooks/scripts/memory_write.py --action create ...` | `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action create ...` |
| 127 | `python3 hooks/scripts/memory_write.py --action update ...` | `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action update ...` |
| 128 | `python3 hooks/scripts/memory_write.py --action delete ...` | `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action delete ...` |

Also removed the "(CWD must be the project root)" note from line 84 since the absolute path makes it unnecessary.

#### R2-SKILL: Replace `/tmp/` staging paths with `.claude/memory/.staging/`

| Line (before) | Old | New |
|---|---|---|
| 69 | `/tmp/.memory-triage-context-<category>.txt` | `.claude/memory/.staging/context-<category>.txt` |
| 80 | "can happen on /tmp write failure" | "can happen on staging directory write failure" |
| 97 | `/tmp/.memory-draft-<category>-<pid>.json` | `.claude/memory/.staging/draft-<category>-<pid>.json` |
| 122 | `starts with /tmp/.memory-draft-` | `starts with .claude/memory/.staging/draft-` |

#### R5: Add plugin self-validation

Added blockquote after line 17 (the "Structured memory stored in..." paragraph):

```
> **Plugin self-check:** Before running any memory operations, verify plugin scripts are accessible
> by confirming `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py"` exists. If
> `CLAUDE_PLUGIN_ROOT` is unset or the file is missing, stop and report the error.
```

### Verification

- Grep for `/tmp/` in SKILL.md: **0 matches** (all replaced)
- Grep for `python3 hooks/scripts/` (unqualified): **0 matches** (all prefixed)
- Grep for `CLAUDE_PLUGIN_ROOT` in SKILL.md: **5 matches** (1 self-check + 4 script invocations)
- Grep for `.staging/` in SKILL.md: **3 matches** (context format, draft write, validation rule)

### Notes

- CLAUDE.md line 31 still references `/tmp/.memory-triage-context-<CATEGORY>.txt` -- this is outside scope of Task #1 but should be updated separately for consistency.
- Many temp/ analysis docs and other .md files still reference /tmp paths -- these are historical analysis documents, not operational instructions.
- `commands/memory-save.md` also uses `/tmp/.memory-write-pending.json` -- separate scope.
