---
name: memory-management
description: Manages structured project memories. Provides format instructions for writing and updating memory files in .claude/memory/.
globs:
  - ".claude/memory/**"
  - ".claude/memory/memory-config.json"
triggers:
  - "remember"
  - "forget"
  - "memory"
  - "memories"
  - "previous session"
---

# Memory Management System

Structured memory stored in `.claude/memory/`. When instructed to save a memory, follow the steps below.

## Categories

| Category | Folder | What It Captures |
|----------|--------|-----------------|
| session_summary | sessions/ | Work resume snapshot |
| decision | decisions/ | Choice + rationale (why X over Y) |
| runbook | runbooks/ | Error fix procedure (diagnose, fix, verify) |
| constraint | constraints/ | Known limitations (enduring walls) |
| tech_debt | tech-debt/ | Deferred work (what was skipped and why) |
| preference | preferences/ | Conventions (how things should be done) |

## Writing Memory Files

### Step 0: Bootstrap

Create `.claude/memory/` and `index.md` if they don't exist. If `memory-config.json` doesn't exist, treat all categories as enabled with `auto_capture: true`.

### Step 1: Check Config

If `.claude/memory/memory-config.json` exists, check `categories.<category>.enabled` (skip if false) and `categories.<category>.auto_capture` (skip if false and this is auto-capture).

### Step 2: Check for Duplicates

Read `.claude/memory/index.md`. Look for existing entries of the same category with the same specific subject.

**Match criteria**: Same category AND same primary subject. Example: both about "JWT auth" = update; "JWT auth" vs "OAuth flow" = create new.

- **Match found**: Read existing JSON file, merge new info, update `updated_at`. If the referenced file is missing, treat as new.
- **No match**: Create a new file.

### Step 3: Generate File

**Path**: `.claude/memory/<folder>/<slug>.json` (create folder if needed)

**Common fields** (all categories):
```
{ schema_version: "1.0", category, id (=slug), title (max 120 chars),
  created_at (ISO 8601 UTC), updated_at, tags[] (min 1),
  related_files[], confidence (0.0-1.0), content: {...} }
```

**Content by category**:

- **session_summary**: `{ goal, outcome: "success|partial|blocked|abandoned", completed[], in_progress[], blockers[], next_actions[], key_changes[] }`
- **decision**: `{ status: "proposed|accepted|deprecated|superseded", context, decision, alternatives: [{option, rejected_reason}], rationale[], consequences[] }`
- **runbook**: `{ trigger, symptoms[], steps[], verification, root_cause, environment }`
- **constraint**: `{ kind: "limitation|gap|policy|technical", rule, impact[], workarounds[], severity: "high|medium|low", active: true, expires: "condition or 'none'" }`
- **tech_debt**: `{ status: "open|in_progress|resolved|wont_fix", priority: "critical|high|medium|low", description, reason_deferred, impact[], suggested_fix[], acceptance_criteria[] }`
- **preference**: `{ topic, value, reason, strength: "strong|default|soft", examples: { prefer[], avoid[] } }`

**Session summary special procedure**: Find the existing SESSION_SUMMARY entry in index.md. Delete that JSON file. Write the new session file. Replace the index line. Only the latest session summary is kept.

Full JSON Schema definitions are in the plugin's `assets/schemas/` directory.

### Step 4: Update Index

Add or update the entry in `.claude/memory/index.md`:
```
- [CATEGORY] summary -> .claude/memory/<folder>/<slug>.json
```

Index rules: one line per file, sorted by category then alphabetically, max 150 lines (remove oldest session_summary first if over).

## When the User Asks About Memories

- "What do you remember?" -> Read index.md and summarize
- "Remember that..." -> Create a memory in the appropriate category
- "Forget..." -> Read the memory, confirm with user, delete file and remove from index
- "What did we decide about X?" -> Search decisions/ folder
- /memory, /memory:config, /memory:search, /memory:save -> See slash commands

## Rules

1. **Never delete** memory files unless the user asks to "forget" -- except session_summary, where only the latest is kept
2. **Silent operation**: Do NOT mention memory operations in visible output during auto-capture
3. **Check before creating**: Always read index.md first to avoid duplicates
4. **Update over create**: If a memory with the same specific subject exists, update it
5. **Confidence scores**: 0.7-0.9 for most; 0.9+ only for explicitly confirmed facts

## Config

`.claude/memory/memory-config.json` (all defaults apply if absent):
- `categories.<name>.enabled` -- enable/disable category (default: true)
- `categories.<name>.auto_capture` -- enable/disable auto-capture (default: true)
- `categories.<name>.retention_days` -- auto-expire after N days (0 = permanent; 90 for sessions)
- `retrieval.max_inject` -- max memories injected per prompt (default: 5)
- `max_memories_per_category` -- max files per folder (default: 100)
