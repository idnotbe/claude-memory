# Ops Project Impact Investigation - Input Brief

## Your Task
Investigate whether the fixes being applied to the claude-memory plugin require any changes in the ops project.

## Background
- ops project: `/home/idnotbe/projects/ops/`
- ops uses claude-memory as a plugin (via ~/.claude/plugin-dirs)
- ops has its own memory data at: `/home/idnotbe/projects/ops/.claude/memory/`
- ops config: `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`

## Fixes Being Applied (check each for ops impact)

1. **Tag XML escaping** - Tags in output now get XML-escaped. Should be transparent to consumers.
2. **Path containment validation** - Paths outside memory root are skipped. Check if ops has any unusual path structures.
3. **cat_key sanitization** - Category keys in config are sanitized. Check ops config for non-standard keys.
4. **Path field XML-escaping** - Transparent change.
5. **_sanitize_title() truncation order** - Titles now truncated before XML escape. Check if ops has any long titles.
6. **score_description round() vs int()** - Scoring change. Check if this affects ops retrieval quality.
7. **grace_period_days type check** - Check ops config value type.
8. **Index rebuild sanitization** - Check ops index.md for entries with ` -> ` or `#tags:` in titles.
9. **2-char token matching** - Now allows 2-char tokens. Check if ops has 2-char tags.
10. **Description flooding fix** - Description bonus only for entries with existing title/tag match.
11. **Reverse prefix matching** - New matching direction added.

## What to Check
1. Read ops memory-config.json - any affected settings?
2. Read ops index.md - any malformed entries?
3. Sample a few memory JSON files - any long titles, unusual tags, retired entries?
4. Check if ops needs to rebuild its index.md
5. Check if any ops workflow depends on specific retrieval behavior that might change

## Output
Write findings to `/home/idnotbe/projects/claude-memory/temp/task-ops-output.md`
