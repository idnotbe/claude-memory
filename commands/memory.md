---
name: memory
description: Show memory status and statistics for this project
arguments: []
---

Read the memory config at .claude/memory/memory-config.json (or note if it doesn't exist).
Then scan .claude/memory/ subdirectories and report:

1. **Status**: Whether memory system is active for this project
2. **Categories**: For each category, show:
   - Name and description
   - Number of stored memories
   - Hook enabled/disabled
   - Most recent file (if any)
3. **Index**: Number of entries in index.md
4. **Storage**: Total number of memory files

Format as a clean table. If .claude/memory/ doesn't exist, report that no memories
have been captured yet and suggest using /memory:save to create one manually.
