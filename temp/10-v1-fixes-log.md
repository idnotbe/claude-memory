# V1 Verification Fixes Log

Applied by: v1-fixer agent
Date: 2026-02-16

## Fixes Applied

### From Correctness Report

| ID | Severity | File | Fix |
|---|---|---|---|
| ISSUE-1 | HIGH | SKILL.md | Fixed `pre_action` vs `structural_cud` field confusion in Phase 1 subagent instructions. Step 3 now correctly lists `pre_action` as "CREATE", "NOOP", or null, and adds `structural_cud` field. Step 4 now uses `structural_cud=UPDATE or UPDATE_OR_DELETE` instead of `pre_action=UPDATE_OR_DELETE`. Candidate object description updated to reference structural_cud. |
| ISSUE-2 | LOW | README.md | Changed "Outputs relevant entries (max 5)" to "Outputs relevant entries (up to `max_inject`, default 5)" in Auto-Retrieval section. |
| ISSUE-3 | LOW | SKILL.md | Changed `category_models` config description from "(default: haiku)" to "(see default config for per-category defaults; fallback: haiku)". |

### From Completeness Report

| ID | Severity | File | Fix |
|---|---|---|---|
| GAP-C4 | CRITICAL | MEMORY-CONSOLIDATION-PROPOSAL.md | Added historical disclaimer banner at top of file noting it describes ACE v4.2 and that v5.0.0 replaced the 6 prompt-type hooks with a single deterministic command-type hook and 2-layer CUD system. |
| NEW-5 | MEDIUM | README.md | Added clarifying paragraph in Configuration section explaining `retention_days` vs `grace_period_days` distinction. |
| GAP-H12 | PARTIAL | README.md | Added "Version History" section with v5.0.0, v4.2, and v3.0 entries. |
| NEW-1 | LOW | README.md | Added note that `retrieval.enabled` defaults to true when absent and is not in the default config file. |
| NEW-2 | LOW | CLAUDE.md | Added `categories.*.folder` (informational mapping) to the agent-interpreted config keys list. |
| NEW-6 | LOW | CLAUDE.md | Updated Key Files table: memory_write.py role changed from "Schema-enforced create/update/delete" to "Schema-enforced CRUD + lifecycle (archive/unarchive)". |

### From Usability Report

| ID | Severity | File | Fix |
|---|---|---|---|
| Scenario 32 (FAIL) | HIGH | README.md | Added "Sensitive Data" section with immediate removal steps, permanent deletion, git history scrubbing, and prevention guidance. |
| Scenario 37 (FAIL) | HIGH | README.md | Added "Upgrading" section with git pull procedure, restart, and verification steps. Noted backward compatibility. |
| Scenario 31 (FAIL) | MEDIUM | README.md | Added cross-project memory sharing guidance in "Notes" section. |
| Scenario 39 (FAIL) | MEDIUM | README.md | Added performance note in "Notes" section explaining retrieval speed and mitigation. |
| Scenario 41 (PARTIAL) | MEDIUM | README.md | Added anti-resurrection troubleshooting entry with workarounds. |
| Scenario 42 (PARTIAL) | MEDIUM | README.md | Added OCC conflict troubleshooting entry with retry guidance. |

## Not Applied (Intentional)

| ID | Reason |
|---|---|
| GAP-M14 | plugin.json is a JSON file, not documentation-only. Task instructions say DO NOT edit .json files. |
| GAP-L4 | Contributor guidelines deferred per original decision. |
| NEW-1 (config fix) | Adding `"enabled": true` to default config requires editing a .json file. |
| NEW-2 (config fix) | Removing `folder` keys from default config requires editing a .json file. |

## Files Modified

1. `skills/memory-management/SKILL.md` - 2 edits (ISSUE-1 field names, ISSUE-3 config description)
2. `README.md` - 6 edits (ISSUE-2 max_inject, NEW-5 retention_days, NEW-1 note, usability sections, version history)
3. `CLAUDE.md` - 2 edits (NEW-6 key files table, NEW-2 config architecture)
4. `MEMORY-CONSOLIDATION-PROPOSAL.md` - 1 edit (GAP-C4 disclaimer banner)
