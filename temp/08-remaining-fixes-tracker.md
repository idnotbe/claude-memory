# Remaining Issues Fix Tracker

**Date:** 2026-02-16
**Goal:** Fix ALL outstanding issues from 6 verification reports (LOW + INFO)

## Issues to Fix

### LOW Severity (2)

| # | ID | Source | Description | Status |
|---|---|---|---|---|
| 1 | SEC-4 | R1-Security | Draft file path injection - validate paths | DONE |
| 2 | H-1 | R2-Holistic | plugin.json version "4.0.0" vs hooks.json "v5.0.0" mismatch | DONE |

### INFO Severity (10)

| # | ID | Source | Description | Status |
|---|---|---|---|---|
| 3 | Issue #2 | R1-Correctness | Context file paths use UPPERCASE category | DONE |
| 4 | Issue #3 | R1-Correctness | Empty results guard in format_block_message | DONE |
| 5 | INFO-1 | R1-Integration | Write guard allowlist missing `.memory-draft-*` | DONE |
| 6 | INFO-2 | R1-Integration | 6-category simultaneous trigger = 12 subagents (cost docs) | DONE |
| 7 | INFO-3 | R1-Integration | Non-atomic index.md writes (pre-existing) | DONE |
| 8 | ARCH-2 | R2-Architecture | Config key casing inconsistency in thresholds | DONE |
| 9 | ARCH-3 | R2-Architecture | No data flow diagram document | DONE |
| 10 | BONUS-1 | R2-Adversarial | NaN in config thresholds via json.loads() | DONE |
| 11 | ADV-5 | R2-Adversarial | Large context files - no size cap | DONE |
| 12 | H-3 | R2-Holistic | Category casing cognitive overhead (related to #3) | DONE |

## Files Modified

| File | Changes |
|---|---|
| `hooks/scripts/memory_triage.py` | Lowercase context file paths/keys (#3,#12), empty results guard (#4), NaN/Inf threshold guard (#10), context file 50KB cap (#11), case-insensitive config threshold parsing (#8), import math |
| `hooks/scripts/memory_write.py` | Refactored `atomic_write_json` into `atomic_write_text` + `atomic_write_json` (#7), atomic index writes for `add_to_index`/`remove_from_index`/`update_index_entry` (#7), input path validation in `_read_input` (#1) |
| `hooks/scripts/memory_write_guard.py` | Added `.memory-draft-` and `.memory-triage-context-` to temp file allowlist (#5) |
| `skills/memory-management/SKILL.md` | Draft path validation instruction (#1), cost note for 6-category trigger (#6), updated casing documentation (#12) |
| `.claude-plugin/plugin.json` | Version sync 4.0.0 → 5.0.0 (#2) |
| `assets/memory-config.default.json` | Lowercase threshold keys (#8) |
| `README.md` | ASCII data flow diagram (#9), lowercase context file path in docs (#3) |

## External Review

### Gemini 3 Pro (pal clink, codereviewer role)
- All 11 fixes rated **Correct**
- Key improvements adopted:
  1. **SEC-4**: Added code-level enforcement in `memory_write.py`'s `_read_input()` (defense-in-depth)
  2. **INFO-3**: Refactored `atomic_write_json` into generic `atomic_write_text` helper
  3. **ARCH-2**: Used `{k.upper(): v for k, v in ...}` normalization pattern

### Codex CLI
- Usage limit reached. Unavailable.

## Validation

- All 3 modified Python scripts compile: `py_compile` PASS
- All JSON files valid: plugin.json, memory-config.default.json, hooks.json
- **229 tests passed** (9 write_guard + 80 write + 134 others + 16 validate = 239 total, 10 xpassed)
- No regressions from changes

## Progress Log

1. Created tracker document
2. Read all 6 verification reports + current source files
3. Consulted Gemini 3 Pro (codereviewer): all fixes approved, 3 improvements suggested
4. Codex CLI unavailable (usage limit)
5. Applied all 12 fixes across 7 files
6. Compile checks: all PASS
7. Test suite: all PASS (239 tests, 0 failures)
8. Self-review: code consistency verified (lowercase keys in write_context_files match format_block_message lookup)
9. Vibe check: identified truncation breaks closing `</transcript_data>` tag -- FIXED (append closing tag before truncation marker)
10. Spawned 2 verification teammates: r1-reviewer (correctness) + r2-reviewer (security)
