---
name: memory:config
description: Configure memory categories and settings using natural language
arguments:
  - name: instruction
    description: What to change (e.g., "disable runbook auto-capture", "add category api_notes")
    required: true
---

Read .claude/memory/memory-config.json (create from defaults if missing).
Apply the user's instruction by modifying the config JSON.
Supported operations:
- Enable/disable a category: set enabled or auto_capture
- Add a custom category: append to categories object with a new folder
- Remove a custom category: set enabled: false (don't delete files)
- Change retrieval settings: max_inject, match_strategy
- Change storage root (advanced)

After modifying, write the updated config and confirm what changed.
If the instruction is ambiguous, ask for clarification.
Do NOT delete existing memory files when disabling a category.
