# Ops Project Impact Investigation - Output

**Date:** 2026-02-20
**Investigator:** ops-checker
**Scope:** `/home/idnotbe/projects/ops/.claude/memory/`

---

## Summary

The ops project is **mostly unaffected** by the plugin fixes. All config values are valid and standard. Most issues are transparent or no-ops for ops. Two minor findings are worth noting: one absolute path in index.md and one retired entry still in index.md.

---

## Config Analysis (`memory-config.json`)

### Fix 3: cat_key sanitization
- **Status: CLEAN**
- All 6 category keys use valid lowercase snake_case: `session_summary`, `decision`, `runbook`, `constraint`, `tech_debt`, `preference`
- No non-standard characters. Fix has zero impact on ops config.

### Fix 7: grace_period_days type check
- **Status: CLEAN**
- `"grace_period_days": 30` — integer value, not a string.
- B3 fix (int() cast in memory_index.py) is a no-op for ops; this value already works correctly.

### Fix 6: score_description round() vs int()
- **Status: MINOR IMPROVEMENT**
- `"max_inject": 5` — standard value, within clamped range [0, 20].
- The round() vs int() change may very slightly affect scoring for entries near 0.5 boundaries, but with only ~28 total memory entries in ops, this is negligible. Retrieval quality may marginally improve.

### Fix 9: 2-char token matching
- **Status: POTENTIAL IMPROVEMENT**
- Tags like `"ui"`, `"db"`, `"ci"` are NOT present in ops tags. The ops tags are all 3+ characters (e.g., `api`, `wsl`, `mcp-servers`, `rate-limit`, `discourse`).
- No negative impact; 2-char matching simply won't match anything new in ops.

### Fix 11: Reverse prefix matching
- **Status: MINOR IMPROVEMENT**
- Could help match queries like "authentication" to "auth" tags.
- Ops has no short abbreviated tags that would specifically benefit, but no harm.

### Fix 10: Description flooding fix
- **Status: MINOR IMPROVEMENT**
- Ops has 9 session_summary entries. The old description bonus could have inflated session_summary scores.
- After fix, session_summary entries without title/tag match won't score as high. Retrieval results may be slightly more targeted.

---

## Index Analysis (`index.md`)

### Fix 8: Index rebuild sanitization (titles with ` -> ` or `#tags:`)
- **Status: CLEAN**
- No titles in index.md contain the literal string ` -> ` or `#tags:`.
- The ` -> ` characters in index lines are the path delimiter (proper usage), not embedded in titles.
- Example of proper usage: `[CONSTRAINT] Discourse Managed Pro: 60 req/min ... -> .claude/memory/constraints/...`
- All 28 index entries have well-formed titles. No index corruption risk.

### Fix 2: Path containment validation
- **STATUS: ONE FINDING**
- **Line 16 of index.md uses an absolute path:**
  ```
  [SESSION_SUMMARY] Resumed Plugin MCP Isolation Investigation and Executed Migration -> /home/idnotbe/projects/ops/.claude/memory/sessions/plugin-mcp-isolation-resume.json
  ```
- All other entries use relative paths (`.claude/memory/...`).
- With fix A2 (path containment validation via `relative_to()`), when the retrieval script processes this entry it may skip it if the containment check fails.
- **Recommendation:** After plugin fixes are deployed, rebuild the ops index to normalize this path to a relative path. This is not urgent but should be done before the next session to avoid the entry being silently skipped.

### Fix 4: Path field XML-escaping
- **Status: CLEAN**
- No paths in index.md contain XML-special characters (`<`, `>`, `&`, `"`, `'`).
- Transparent no-op.

---

## Memory JSON File Analysis (sampled 8 files)

### Fix 5: _sanitize_title() truncation order
- **Status: CLEAN**
- All sampled titles are well within normal length limits (longest: "Discourse API rate limits fact-check + User API Key alternatives analysis" ~72 chars).
- No titles approach the 200-char truncation threshold. The truncation order fix is a no-op for ops.

### Fix 1: Tag XML escaping
- **Status: CLEAN**
- All tags use lowercase alphanumeric + hyphens only (e.g., `claude-code-guardian`, `rate-limit`, `mcp-servers`).
- No tags contain XML-special characters. The XML escaping fix is a transparent no-op.

### Fix 8 (secondary): Retired entries in index
- **STATUS: ONE FINDING**
- `phase1-launch-strategy-pending-decisions.json` has `record_status` implied to be retired (has `retired_at` and `retired_reason` fields set) but its index entry (line 14) remains in index.md.
- This pre-dates the fixes. After fix B4 (index rebuild sanitization) and any future index rebuild, this entry may be filtered out if `record_status` filtering is applied.
- The JSON itself shows `"record_status": "active"` (the retire operation updated the fields but didn't change status — this appears to be the Guardian regex bug TD listed in tech-debt). The session rolling window failed to fully retire this entry.
- **Not a regression from the fixes** — this is a pre-existing state due to the Guardian blocking --action delete.

---

## Specific Fix-by-Fix Summary Table

| Fix ID | Description | Ops Impact |
|--------|-------------|------------|
| A1 | Tag XML escaping | None - ops tags have no XML-special chars |
| A2 | Path containment validation | **MINOR**: One absolute path in index.md (line 16) may be skipped. Rebuild index after deployment. |
| A3 | cat_key sanitization | None - all category keys are clean |
| A4 | Path field XML-escaping | None - no XML chars in paths |
| B1 | truncation before XML escape | None - no long titles in ops |
| B2 | round() vs int() for score | Negligible - tiny scoring improvement |
| B3 | grace_period_days int() cast | None - value is already integer 30 |
| B4 | Index rebuild sanitization | None - no malformed titles; retroactive rebuild safe |
| C1 | 2-char token matching | None - ops has no 2-char tags |
| C2 | Description flooding fix | Minor improvement - session_summary won't dominate retrieval |
| C3 | Reverse prefix matching | Minor improvement - slightly better query-to-tag matching |

---

## Recommendations

1. **After plugin deployment:** Rebuild ops index to normalize the absolute path on line 16 of index.md to a relative path:
   ```
   python3 ~/.claude/plugins/claude-memory/hooks/scripts/memory_index.py --rebuild --root /home/idnotbe/projects/ops/.claude/memory
   ```

2. **No config changes needed.** The ops `memory-config.json` is clean and fully compatible with all fixes.

3. **No data migration needed.** Existing JSON files are schema-compatible and no titles require sanitization.

4. **Pre-existing state:** The phase1 session entry shows incomplete retirement (Guardian regex blocker - see TD-entry `guardian-regex-blocks-memory-delete`). This is unrelated to the current fixes and should be tracked via the existing tech debt item.
