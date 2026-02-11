---
name: memory-management
description: Manages structured project memories. Auto-captures decisions, runbooks, constraints, tech debt, session summaries, and preferences. Provides format instructions for writing and updating memory files.
globs:
  - ".claude/memory/**"
  - ".claude/memory/memory-config.json"
triggers:
  - "remember"
  - "forget"
  - "memory"
  - "memories"
  - "what do you know about"
  - "what did we decide"
  - "previous session"
---

# Memory Management System

You have access to a structured memory system stored in `.claude/memory/`.

## Categories

| Category | Folder | What It Captures |
|----------|--------|-----------------|
| session_summary | sessions/ | Work resume snapshot |
| decision | decisions/ | Choice + rationale (why X over Y) |
| runbook | runbooks/ | Error fix procedure (diagnose, fix, verify) |
| constraint | constraints/ | Known limitations (enduring walls) |
| tech_debt | tech-debt/ | Deferred work (what was skipped and why) |
| preference | preferences/ | Conventions (how things should be done) |

## How Auto-Capture Works

Six Stop hooks evaluate each conversation turn in parallel. Each hook is a lightweight triage prompt (runs on Haiku). If a hook detects something worth saving, it blocks the stop and provides a reason like:

> "Save a DECISION memory about: We chose X because Y. Check .claude/memory/index.md for existing entries to update."

**You (the main agent) then execute the save.** The hooks only evaluate -- you do the file I/O. Follow the instructions below.

## Writing Memory Files

When instructed to save a memory (either by a hook reason or by user request):

### Step 1: Check Config

Read `.claude/memory/memory-config.json` (if it exists). Check:
- `categories.<category>.enabled` -- if false, skip
- `categories.<category>.auto_capture` -- if false and this is auto-capture, skip

### Step 2: Check for Duplicates

Read `.claude/memory/index.md`. Look for existing entries of the same category covering the same topic.
- **If a matching entry exists**: Read the existing JSON file, merge new information, update `updated_at`
- **If no match**: Create a new file

### Step 3: Generate File

**File path**: `.claude/memory/<folder>/<slug>.json`
- `<folder>`: See categories table above
- `<slug>`: Descriptive kebab-case (e.g., `use-postgres-over-mongo`, `discourse-no-per-agent-rate-limit`)
- Create the folder if it doesn't exist

**Common fields** (all categories):
```json
{
  "schema_version": "1.0",
  "category": "<category_name>",
  "id": "<slug-matching-filename>",
  "title": "<max 120 chars, descriptive>",
  "created_at": "<ISO 8601 UTC>",
  "updated_at": "<ISO 8601 UTC>",
  "tags": ["<min 1 tag>"],
  "related_files": ["<paths to relevant project files>"],
  "confidence": 0.0-1.0,
  "content": { ... }
}
```

**Category-specific `content` fields:**

**session_summary**:
```json
"content": {
  "goal": "what session aimed to accomplish",
  "outcome": "success|partial|blocked|abandoned",
  "completed": ["tasks confirmed done"],
  "in_progress": ["tasks started not finished"],
  "blockers": ["what prevents progress"],
  "next_actions": ["concrete next steps"],
  "key_changes": ["files/modules changed"]
}
```
Special rule: Only keep the LATEST session summary. Overwrite or delete the previous session file.

**decision**:
```json
"content": {
  "status": "proposed|accepted|deprecated|superseded",
  "context": "what prompted this decision",
  "decision": "what was decided",
  "alternatives": [{"option": "alt", "rejected_reason": "why not"}],
  "rationale": ["reasons for choosing this"],
  "consequences": ["known implications"]
}
```

**runbook**:
```json
"content": {
  "trigger": "what symptom/error initiates this runbook",
  "symptoms": ["observable signs"],
  "steps": ["ordered fix steps"],
  "verification": "how to confirm the fix worked",
  "root_cause": "underlying cause",
  "environment": "relevant env details"
}
```

**constraint**:
```json
"content": {
  "kind": "limitation|gap|policy|technical",
  "rule": "the constraint stated clearly",
  "impact": ["what this prevents or limits"],
  "workarounds": ["known workarounds"],
  "severity": "high|medium|low",
  "active": true,
  "expires": "condition/date when constraint may lift, or 'none'"
}
```

**tech_debt**:
```json
"content": {
  "status": "open|in_progress|resolved|wont_fix",
  "priority": "critical|high|medium|low",
  "description": "what was deferred",
  "reason_deferred": "why it was deferred",
  "impact": ["consequences of not addressing"],
  "suggested_fix": ["step 1", "step 2"],
  "acceptance_criteria": ["how to know it is resolved"]
}
```

**preference**:
```json
"content": {
  "topic": "what area this covers",
  "value": "the preferred approach",
  "reason": "why this convention",
  "strength": "strong|default|soft",
  "examples": {
    "prefer": ["do this"],
    "avoid": ["not this"]
  }
}
```

### Step 4: Update Index

Add or update the entry in `.claude/memory/index.md`:
```
- [CATEGORY] summary -> .claude/memory/<folder>/<slug>.json
```

Rules for index:
- One line per memory file
- Sort by category then alphabetically within category
- Max 150 lines (remove oldest session_summary first if over limit)
- For session_summary updates: replace the previous session line

## When the User Asks About Memories

- "What do you remember?" -> Read index.md and summarize
- "Remember that..." -> Create a memory in the appropriate category
- "Forget..." -> Read the memory, confirm with user, then delete file and remove from index
- "What did we decide about X?" -> Search decisions/ folder
- "Show me the runbook for X" -> Search runbooks/ folder
- /memory -> Show memory status and statistics
- /memory:config -> Configure settings
- /memory:search -> Search memories by keyword
- /memory:save -> Manually save a memory

## Rules

1. **Never delete** existing memory files unless the user explicitly asks to "forget"
2. **Silent operation**: Do NOT mention memory operations in visible output during auto-capture
3. **Check before creating**: Always read index.md first to avoid duplicates
4. **Update over create**: If a similar memory exists, update it rather than creating a new one
5. **Confidence scores**: Use 0.7-0.9 for most; 0.9+ only for explicitly confirmed facts
6. **Full JSON schemas**: Available in the plugin's `assets/schemas/` directory for validation reference

## Config

`.claude/memory/memory-config.json` controls behavior:
- `categories.<name>.enabled` -- enable/disable a category (default: true)
- `categories.<name>.auto_capture` -- enable/disable auto-capture (default: true)
- `categories.<name>.retention_days` -- auto-expire after N days (0 = permanent; 90 for sessions)
- `retrieval.max_inject` -- max memories injected per prompt (default: 5)
- `retrieval.match_strategy` -- how to match (default: title_tags)
- `max_memories_per_category` -- max files per folder (default: 100)
