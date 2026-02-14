---
name: memory
description: Show memory status, manage lifecycle (retire, archive, restore, GC)
arguments:
  - name: action
    description: "Subcommand: --retire <slug>, --archive <slug>, --unarchive <slug>, --restore <slug>, --gc, --list-archived. Omit for status."
    required: false
---

Parse the argument to determine which subcommand to run. If no argument is given (or argument is empty), run the **status** display. Otherwise, match the first flag:

## Status (no arguments)

Read the memory config at `.claude/memory/memory-config.json` (or note if it doesn't exist).
Then scan `.claude/memory/` subdirectories and report:

1. **Status**: Whether memory system is active for this project
2. **Categories**: For each category, show:
   - Name and description
   - Number of **active** memories (record_status = "active" or field absent)
   - Number of **retired** memories (record_status = "retired", pending GC)
   - Number of **archived** memories (record_status = "archived")
   - Hook enabled/disabled
   - Most recent file (if any)
3. **Index**: Number of entries in index.md vs actual active file count
4. **Storage**: Total number of memory files (all statuses)
5. **Health indicators**:
   - Heavily updated memories (times_updated > 5) -- list them
   - Index sync status (run `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_index.py --validate --root <memory_root>`)

Format as a clean table with a summary section.

If `.claude/memory/` doesn't exist, report that no memories have been captured yet and suggest using /memory:save to create one manually.

## --retire <slug>

User-initiated soft delete. This is the ONLY way to delete decisions and preferences.

1. Find the memory file matching `<slug>` by scanning all category folders for `<slug>.json`
2. If not found, report error and list similar slugs
3. Show the memory title and category, ask for confirmation
4. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action delete --target <path> --reason "User-initiated retirement via /memory --retire"`
5. Report result

## --archive <slug>

Shelve a memory permanently. Archived memories are excluded from retrieval but NOT eligible for garbage collection (preserved indefinitely).

1. Find the memory file matching `<slug>` by scanning all category folders for `<slug>.json`
2. If not found, report error
3. Show the memory title, ask for confirmation
4. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action archive --target <path> --reason "User-initiated archive via /memory --archive"`
5. Report result

## --unarchive <slug>

Restore an archived memory to active status.

1. Find the memory file matching `<slug>` by scanning all category folders for `<slug>.json`
2. If not found, report error
3. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action unarchive --target <path>`
4. Report result

## --restore <slug>

Restore a retired memory within the 30-day grace period.

1. Find the memory file matching `<slug>` by scanning all category folders for `<slug>.json`
2. If not found, report error
3. Read the file. If record_status is not "retired", report error (can only restore retired memories)
4. Check `retired_at` timestamp:
   - If more than 30 days ago, report error: "Grace period expired. Memory is eligible for GC and cannot be restored."
   - If more than 7 days ago, show staleness warning: "This memory was retired N days ago. Content may be outdated. Proceed?"
5. Modify the JSON:
   - Set `record_status` to `"active"`
   - Remove `retired_at` and `retired_reason` fields
   - Append to `changes[]`: `{ "date": "<now>", "summary": "Restored from retired by user" }`
   - Increment `times_updated`
6. Write the modified JSON to `/tmp/.memory-write-pending.json`
7. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action update --category <cat> --target <path> --input /tmp/.memory-write-pending.json --hash <md5_of_original>`
8. Rebuild index to include the restored entry: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_index.py --rebuild --root <memory_root>`
9. Report result

## --gc

Garbage collect retired memories past the 30-day grace period.

1. Read `.claude/memory/memory-config.json` to get `delete.grace_period_days` (default: 30)
2. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_index.py --gc --root <memory_root>`
3. If `--gc` is not yet supported by memory_index.py, perform manually:
   - Scan all category folders for `.json` files
   - For each file with `record_status == "retired"`, check `retired_at`
   - If `retired_at` is older than grace_period_days, delete the file
   - Report how many files were purged
4. Report result: number of memories purged, remaining retired count

## --list-archived

List all archived memories across all categories.

1. Scan all category folders for `.json` files
2. For each file with `record_status == "archived"`, collect:
   - Category
   - Title
   - Slug (id)
   - archived_at date
   - archived_reason
3. Format as a table sorted by archived_at (most recent first)
4. If none found, report "No archived memories found."
