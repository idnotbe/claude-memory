---
name: memory:config
description: Configure memory categories and settings using natural language
arguments:
  - name: instruction
    description: What to change (e.g., "disable runbook auto-capture", "add category api_notes")
    required: true
---

**Examples:**
```
/memory:config disable runbook auto-capture
/memory:config set max_inject to 3
/memory:config raise decision threshold to 0.7
/memory:config set all category models to haiku
/memory:config disable triage entirely
```

Read .claude/memory/memory-config.json (create from defaults at `$CLAUDE_PLUGIN_ROOT/assets/memory-config.default.json` if missing).
Apply the user's instruction by modifying the config JSON.

Supported operations:

**Category settings:**
- Enable/disable a category: set `categories.<name>.enabled` or `categories.<name>.auto_capture`
- Change retention: set `categories.<name>.retention_days` (0 = permanent)
- Change session rolling window: set `categories.session_summary.max_retained` (default: 5)

**Retrieval settings:**
- Change max injected memories: set `retrieval.max_inject` (0-20, default: 5)
- Enable/disable retrieval: set `retrieval.enabled` (default: true)

**Triage settings:**
- Enable/disable auto-capture: set `triage.enabled` (default: true)
- Change transcript window: set `triage.max_messages` (10-200, default: 50)
- Tune category thresholds: set `triage.thresholds.<category>` (0.0-1.0). Lower = more captures, higher = fewer but higher-quality. Defaults: decision=0.4, runbook=0.4, constraint=0.5, tech_debt=0.4, preference=0.4, session_summary=0.6

**Parallel processing settings:**
- Change drafting model per category: set `triage.parallel.category_models.<category>` (haiku/sonnet/opus)
- Change verification model: set `triage.parallel.verification_model` (default: sonnet)
- Enable/disable parallel processing: set `triage.parallel.enabled` (default: true)

**Lifecycle settings:**
- Change garbage collection grace period: set `delete.grace_period_days` (default: 30)
- Archive instead of purge on GC: set `delete.archive_retired` (default: true; agent-interpreted hint, not script-enforced)

After modifying, write the updated config and confirm what changed.
If the instruction is ambiguous, ask for clarification.
Do NOT delete existing memory files when disabling a category.

Note: Custom categories are not currently supported by the validation pipeline. The 6 built-in categories (session_summary, decision, runbook, constraint, tech_debt, preference) each have dedicated Pydantic schemas in `memory_write.py`.
