# V2 Fixes Log

**Date**: 2026-02-16
**Agent**: v2-fixer

## Fixes Applied

### CRITICAL Fixes

#### Fix 1: Restore Workflow Bug (commands/memory.md)
- **Issue**: `--restore` flow called `memory_write.py --action update`, but `do_update()` preserves old `record_status` (line 751), making restore silently fail. No `--action restore` exists. `--action unarchive` only works for archived, not retired.
- **Verified against**: `memory_write.py` lines 750-751, 1042-1049, 1250
- **Fix**: Rewrote `--restore` section to document the limitation and provide a create-based workaround that uses `--action create` instead of `--action update`. Added note about 24h anti-resurrection window.
- **File**: `commands/memory.md`

#### Fix 2: README State Transitions (README.md)
- **Issue**: State transition table listed `retired -> active` via `--restore` without noting the limitation.
- **Fix**: Added "(uses create-based workaround -- see Known Limitations)" to the transition line.
- **File**: `README.md`

#### Fix 3: README Known Limitations Section (README.md)
- **Issue**: No documentation of known limitations.
- **Fix**: Added "Known Limitations" section documenting: restore workaround, custom category limitation, and agent-interpreted config keys.
- **File**: `README.md`

#### Fix 4: CONSOLIDATION-PROPOSAL Disclaimer (MEMORY-CONSOLIDATION-PROPOSAL.md)
- **Issue (VULN-2)**: Single-line disclaimer was not prominent enough. Document body still describes 3-layer CUD, 6 Sonnet hooks, lifecycle_event/cud_recommendation fields that no longer exist.
- **Fix**: Replaced single-line note with prominent WARNING block listing specific architectural differences (hooks, CUD layers, triage output format, locking mechanism).
- **File**: `MEMORY-CONSOLIDATION-PROPOSAL.md`

### HIGH Fixes

#### Fix 5: Archive/Unarchive in CLAUDE.md (VULN-4)
- **Issue**: CLAUDE.md architecture section only mentioned create/update/delete, not archive/unarchive.
- **Fix**: Added "Write Actions" subsection to Architecture documenting all 5 actions and the restore limitation.
- **File**: `CLAUDE.md`

#### Fix 6: Context File Failure Handling (VULN-7)
- **Issue**: SKILL.md Phase 1 subagent instructions didn't handle missing `context_file` in triage_data.
- **Fix**: Added instruction to skip category with warning if `context_file` is missing from triage entry.
- **File**: `skills/memory-management/SKILL.md`

#### Fix 7: PostToolUse Deny Semantics (VULN-12)
- **Issue**: PostToolUse deny cannot prevent writes, only inform. This was not documented.
- **Fix**: Added clarification to CLAUDE.md architecture table and README Quarantined files section.
- **Files**: `CLAUDE.md`, `README.md`

#### Fix 8: `delete.archive_retired` in Config Docs
- **Issue**: Key was in default config and SKILL.md but missing from README config table and memory-config.md.
- **Fix**: Added to README config table (noted as agent-interpreted) and memory-config.md lifecycle settings.
- **Files**: `README.md`, `commands/memory-config.md`

#### Fix 9: Stale Line-Number References (VULN-8)
- **Status**: Already resolved in V1 fixes. Current CLAUDE.md has no stale line references (`:141-145`, `:65-76`, `:81` all removed). Security descriptions use function/method names instead.
- **Action**: No change needed.

#### Fix 10: CLAUDE.md Security Claims (VULN-1)
- **Status**: Already corrected in V1 fixes. Security Consideration #1 accurately describes the sanitization chain (write-side auto_fix + read-side _sanitize_title + remaining gap in memory_index.py rebuild).
- **Action**: No change needed.

### MEDIUM Fixes

#### Fix 11: Venv Location Clarification (VULN-15)
- **Issue**: Documentation didn't specify WHERE the .venv must be (plugin root, not project root).
- **Fix**: Updated README Prerequisites, Troubleshooting, and CLAUDE.md Venv Bootstrap sections to specify plugin root path.
- **Files**: `README.md`, `CLAUDE.md`

#### Fix 12: CWD Requirement (VULN-10)
- **Issue**: Script invocations require CWD to be project root but this wasn't documented.
- **Fix**: Added "(CWD must be the project root)" note to memory_candidate.py invocation in SKILL.md.
- **File**: `skills/memory-management/SKILL.md`

#### Fix 13: First-Retrieval Rebuild Latency (VULN-13)
- **Issue**: README said "under 10ms" without noting first-retrieval rebuild can take up to 10 seconds.
- **Fix**: Added "First retrieval after a missing index may be slower (up to 10 seconds) due to automatic index rebuild."
- **File**: `README.md`

#### Fix 14: Data Flow Diagram Actions (README.md)
- **Issue**: Diagram showed only create/update/delete, missing archive/unarchive.
- **Fix**: Updated to `--action create/update/delete/archive/unarchive`.
- **File**: `README.md`

#### Fix 15: Custom Categories Prominence
- **Issue**: Custom categories limitation was buried at bottom of memory-config.md, not prominent in README.
- **Fix**: Added note after category table in README: "These 6 categories are built-in with dedicated Pydantic schemas. Custom categories are not currently supported."
- **File**: `README.md`

#### Fix 16: SKILL.md `delete.archive_retired` Agent-Interpreted Note
- **Issue**: SKILL.md didn't distinguish this key as agent-interpreted.
- **Fix**: Added "(agent-interpreted, not script-enforced)" to the config reference.
- **File**: `skills/memory-management/SKILL.md`

#### Fix 17: SKILL.md Restore Reference
- **Issue**: Manual cleanup section referenced `--restore` without noting the workaround.
- **Fix**: Added "(uses create-based workaround; may be blocked by 24h anti-resurrection window)".
- **File**: `skills/memory-management/SKILL.md`

### LOW Fixes

#### Fix 18: Case-Insensitive Threshold Keys (VULN-17)
- **Issue**: Config uses lowercase keys, code normalizes to uppercase. Behavior not documented.
- **Fix**: Added "Threshold keys are case-insensitive (both `decision` and `DECISION` work)" to README.
- **File**: `README.md`

#### Fix 19: Model Tier Hints (VULN-18)
- **Issue**: `category_models` values described as model names, but they're tier hints for the orchestrator.
- **Fix**: Updated description to "Per-category model tier hint ... (interpreted by orchestrator, not literal model IDs)".
- **File**: `README.md`

#### Fix 20: Upgrade Section Release Notes
- **Issue**: Upgrade section didn't mention checking for breaking changes.
- **Fix**: Added "Check the Version History section for breaking changes between major versions."
- **File**: `README.md`

#### Fix 21: Sensitive Data Immediate Deletion
- **Issue**: GC respects grace period; immediate permanent deletion requires manual rm but wasn't clearly stated.
- **Fix**: Updated to mention manual delete + index rebuild for immediate removal.
- **File**: `README.md`

#### Fix 22: TEST-PLAN.md Write Guard Allowlist
- **Issue**: P2.1 only mentioned staging file, not draft and context file allowlists.
- **Fix**: Added test cases for `/tmp/.memory-draft-*.json` and `/tmp/.memory-triage-context-*.txt`.
- **File**: `TEST-PLAN.md`

## Files Modified

| File | Changes |
|------|---------|
| `commands/memory.md` | Rewrote `--restore` section with known limitation + create workaround |
| `README.md` | 11 fixes: state transitions, known limitations, config table, data flow, venv, latency, upgrade, sensitive data, categories, thresholds, model hints, quarantine, troubleshooting |
| `CLAUDE.md` | 3 fixes: write actions section, PostToolUse deny semantics, venv location |
| `skills/memory-management/SKILL.md` | 4 fixes: context_file failure, CWD note, archive_retired note, restore note |
| `MEMORY-CONSOLIDATION-PROPOSAL.md` | Enhanced disclaimer with specific architectural differences |
| `commands/memory-config.md` | Added delete.archive_retired setting |
| `TEST-PLAN.md` | Added draft/context file allowlist test cases |

## Issues NOT Fixed (Verified Already Resolved)

- **VULN-1** (stale security claims): Already corrected in V1 fixes
- **VULN-3** (max_inject contradiction): Already resolved -- CLAUDE.md correctly describes clamping
- **VULN-8** (stale line numbers): Already removed in V1 fixes
- **VULN-5** (hooks.json format): Investigated, not an issue (plugin format is valid)
- **VULN-6** (state diagram in proposal): Mitigated by enhanced historical disclaimer
- **VULN-11** (stop flag location): Verified consistent, no issue
- **VULN-14** (write guard bypass): Verified sound implementation, no vulnerability
- **VULN-19** (JSON schema maxItems): Not a documentation issue; enforcement is in auto_fix, not validation

## Remaining Known Issues

1. **No `--action restore` in write pipeline**: Documented as known limitation with workaround. Would require code change to properly fix.
2. **24h anti-resurrection window blocks restore**: The create-based workaround may fail if memory was retired recently. Users must wait or use a different slug.
3. **Agent-interpreted config keys**: Behavior depends on LLM interpretation, not code enforcement. Documented but not fixable without code changes.
