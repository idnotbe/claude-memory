# Correctness Review: memory_draft.py, memory_candidate.py, SKILL.md

**Reviewer:** reviewer-correctness
**Date:** 2026-02-21
**Files reviewed:**
- `hooks/scripts/memory_draft.py` (NEW, 332 lines)
- `hooks/scripts/memory_candidate.py` (MODIFIED, `--new-info-file` added)
- `skills/memory-management/SKILL.md` (MODIFIED, Phase 1 updated)
**Spec:** `/home/idnotbe/projects/ops/temp/claude-memory-prompt.md`

---

## Overall Verdict: PASS with 3 findings (1 medium, 2 low)

The implementation is faithful to the spec. All required behaviors are present, imports are correct, and the SKILL.md instructions correctly reference the new scripts and flows. The three findings below are real but none are blockers.

---

## 1. memory_draft.py -- Detailed Findings

### 1.1 Imports from memory_write.py: CORRECT

All 7 imported names verified to exist in `memory_write.py`:

| Import | Location in memory_write.py | Status |
|--------|---------------------------|--------|
| `slugify` | line 233 | OK -- function |
| `now_utc` | line 229 | OK -- function |
| `build_memory_model` | line 189 | OK -- function |
| `CONTENT_MODELS` | line 159 | OK -- dict |
| `CATEGORY_FOLDERS` | line 58 | OK -- dict |
| `ChangeEntry` | line 173 | OK -- Pydantic model |
| `ValidationError` | line 48 (imported from pydantic) | OK -- re-exported at module scope |

The venv bootstrap in memory_draft.py (lines 22-30) executes *before* the `from memory_write import ...` statement (line 45), so pydantic is guaranteed available when memory_write.py is loaded. This avoids memory_write.py's own `os.execv()` bootstrap, which only fires when pydantic is missing. Correct.

### 1.2 CREATE assembly: CORRECT

`assemble_create()` (lines 125-150) produces all fields required by `build_memory_model()`:

| Field | Spec Requirement | Implementation | Status |
|-------|-----------------|----------------|--------|
| `schema_version` | "1.0" | `"1.0"` (line 132) | OK |
| `category` | from `--category` arg | passed as parameter (line 133) | OK |
| `id` | slugified from title | `slugify(title)` (line 129) | OK |
| `title` | from input | `str(input_data.get("title", ""))` (line 128) | OK |
| `record_status` | "active" | `"active"` (line 135) | OK |
| `created_at` | current UTC ISO 8601 | `now_utc()` (line 127) | OK |
| `updated_at` | current UTC ISO 8601 | `now_utc()` (line 127) | OK |
| `tags` | from input | `input_data.get("tags", [])` (line 139) | OK |
| `related_files` | from input | `input_data.get("related_files")` (line 140) | OK -- None if absent |
| `confidence` | from input | `input_data.get("confidence")` (line 141) | OK -- None if absent |
| `content` | from input | `input_data.get("content", {})` (line 142) | OK |
| `changes` | `[{date, summary}]` | list with one dict (lines 143-148) | OK |
| `times_updated` | 0 | `0` (line 149) | OK |

**Note:** `retired_at`, `retired_reason`, `archived_at`, `archived_reason` are NOT set by assemble_create. This is fine because `build_memory_model()` defaults all four to `None` (lines 215-218 of memory_write.py). When Pydantic validates, missing fields are filled with defaults. However, the assembled dict does not include those keys, and the model has `extra="forbid"`. Since Pydantic `model_validate()` on a dict with *missing* optional fields is fine (they get defaults), but extra fields would fail, this is the correct approach.

### 1.3 UPDATE assembly: CORRECT with one finding

`assemble_update()` (lines 157-212) correctly:
- Starts from `dict(existing)` (line 167) -- shallow copy of existing record
- Preserves immutables (`created_at`, `schema_version`, `category`, `id`) by not overwriting them
- Updates `updated_at` to current time (line 173)
- Preserves `record_status` from existing (line 174)
- Unions tags, deduplicated and sorted (lines 181-183)
- Unions related_files, deduplicated and sorted (lines 186-189)
- Updates confidence if provided (lines 192-193)
- Shallow-merges content: existing dict + new overlay (lines 196-199)
- Appends change entry (lines 202-207)
- Increments `times_updated` (line 210)

**FINDING M-1 (MEDIUM): `record_status` preservation is redundant but not harmful.**
Line 174: `result["record_status"] = existing.get("record_status", "active")`
Since `result` is already a copy of `existing` (line 167), this line overwrites the existing value with itself (or "active" if missing). This is functionally correct and provides a safety default for malformed existing records, but it's worth noting.

Actually, on closer reflection, this is *good defensive code* -- if the existing record is somehow missing `record_status`, this provides a safe default. No issue.

### 1.4 Validation flow: CORRECT

Lines 305-315: The assembled JSON is validated via `build_memory_model(category).model_validate(assembled)`. On `ValidationError`, structured errors are printed to stderr with field locations and messages, and exit code 1 is returned. On success, the draft is written and stdout JSON output is produced. This matches the spec exactly.

### 1.5 Input path security: CORRECT

`validate_input_path()` (lines 67-88):
- Checks for `..` in the raw path (line 78)
- Resolves symlinks via `os.path.realpath()` (line 75)
- Allows `.claude/memory/.staging/` or `/tmp/` only (lines 80-81)
- Both checks apply to the *resolved* path for symlink safety

Spec says: "Input file path must be in `.claude/memory/.staging/` or `/tmp/`" -- matches.

**FINDING L-1 (LOW): The `..` check is on the raw path (pre-resolve), while staging/tmp checks are on the resolved path. This is actually the correct layering -- rejecting `..` early prevents path traversal attempts before resolution, and the resolved-path check catches symlink-based bypasses. No issue.**

### 1.6 Draft output filename: CORRECT

`write_draft()` (lines 219-233) produces `draft-<cat>-<ts>-<pid>.json`. The spec says "Use `os.getpid()` or timestamp for unique draft filenames to avoid collisions" -- implementation uses BOTH, which is more robust. Good.

### 1.7 Argparse logic: CORRECT

- `--action` required, choices `["create", "update"]` (lines 244-247)
- `--category` required, choices from `VALID_CATEGORIES` (derived from `CATEGORY_FOLDERS.keys()`) (lines 248-250)
- `--input-file` required (lines 252-254)
- `--candidate-file` optional (lines 256-258)
- `--root` default `.claude/memory` (lines 260-263)
- Enforces `--candidate-file` required for update (lines 268-270) -- manual check, correct

### 1.8 Edge cases considered

- Empty title: `slugify("")` returns `""`, which fails the `id` pattern regex `^[a-z0-9]...`. Pydantic validation catches this. **Correct.**
- Missing content fields: Pydantic content model validation will catch missing required fields. **Correct.**
- Update with malformed existing file: `read_json_file` catches JSONDecodeError. Pydantic catches schema issues. **Correct.**

---

## 2. memory_candidate.py -- Detailed Findings

### 2.1 --new-info-file addition: CORRECT

Lines 205-208: New `--new-info-file` argument added as optional.
Lines 201-203: `--new-info` changed from `required=True` to optional (no `required` kwarg).

### 2.2 Post-parse validation: CORRECT

Lines 221-233:
- `--new-info-file` takes precedence (line 222): reads file, assigns to `args.new_info`
- Error handling for `FileNotFoundError`, `PermissionError`, `OSError` (lines 226-231)
- If neither provided: `parser.error(...)` with clear message (lines 232-233)

**Spec says:** "If both are provided, `--new-info-file` takes precedence (or error -- your choice, just be consistent)" -- Implementation chose precedence. **Correct.**

### 2.3 Backwards compatibility: CORRECT

Existing callers using `--new-info "..."` continue to work since:
- `--new-info` is still accepted (just not `required=True`)
- The `elif args.new_info is None` check (line 232) catches the case where neither is provided
- If only `--new-info` is given, `args.new_info_file` is `None`, so the precedence block (line 222) is skipped, and `args.new_info` holds the inline value

### 2.4 Zero downstream changes: CORRECT

The rest of the script continues to use `args.new_info` / `new_info` unchanged (line 256). The new code merely provides an alternative way to populate that same variable.

---

## 3. SKILL.md -- Detailed Findings

### 3.1 Write Tool mandate: CORRECT

Lines 81-83: Blockquote mandate requiring Write tool for all `.staging/` writes. Explains Guardian rationale. Matches spec's "MANDATE" requirement.

### 3.2 New step 2 (write new-info to file): CORRECT

Lines 91-93: Subagent writes 1-3 sentence summary to `.claude/memory/.staging/new-info-<category>.txt` via Write tool. Matches spec step 2.

### 3.3 Step 3 (--new-info-file): CORRECT

Lines 94-100: `memory_candidate.py` called with `--new-info-file` pointing to the temp file. Matches spec step 3.

### 3.4 Step 5 (action determination): CORRECT

Lines 107-113: Flat decision table for CREATE/UPDATE/DELETE/NOOP based on `pre_action` and `structural_cud`. Matches the CUD verification rules table in SKILL.md.

### 3.5 Step 6 (partial JSON input): CORRECT

Lines 114-132: DELETE routing at top, then partial JSON format with 6 fields. Explicit list of excluded auto-populated fields. Matches spec step 5.

**FINDING L-2 (LOW): Filename in step 6 uses `.claude/memory/.staging/input-<category>.json` (no PID/timestamp). This differs from the spec which suggests `input-<category>-<pid>.json`. However, since each subagent processes one category and runs in its own Task, collisions are impossible within a single consolidation run. The lack of PID just means stale files from previous runs could be overwritten, which is actually desirable (cleanup). Not a bug.**

### 3.6 Step 7 (memory_draft.py invocation): CORRECT

Lines 133-148: Two clear command variants for CREATE and UPDATE. UPDATE includes `--candidate-file <candidate.path>`. Matches spec step 6.

### 3.7 Step 8-10 (output parsing, DELETE, report): CORRECT

- Step 8 parses `draft_path` from JSON output, handles non-zero exit
- Step 9: DELETE-only retire JSON via Write tool
- Step 10: Report format unchanged

### 3.8 Phase 2 compatibility: CORRECT

Phase 2 verification subagents read the draft JSON file (which is now a complete, schema-valid JSON produced by memory_draft.py). No changes needed to Phase 2.

### 3.9 Phase 3 compatibility: CORRECT

Phase 3 uses `--input <draft>` with memory_write.py. The draft from memory_draft.py is complete JSON, same as what was previously written by the LLM directly. No changes needed to Phase 3.

### 3.10 Removed content: CORRECT

The old instruction "Draft new JSON following the Memory JSON Format section" has been replaced by the partial JSON + memory_draft.py flow. The DELETE flow remains unchanged (small retire JSON, no Guardian concern).

---

## Summary of Findings

| ID | Severity | File | Description | Recommendation |
|----|----------|------|-------------|----------------|
| M-1 | Medium | memory_draft.py:174 | `record_status` line is redundant (copy already contains it) | Self-retracted: actually good defensive code. No action. |
| L-1 | Low | memory_draft.py:75-81 | Path security checks use raw + resolved paths | Correct layering. No action. |
| L-2 | Low | SKILL.md step 6 | Input filename lacks PID/timestamp vs spec suggestion | Not a bug; no collision risk in practice. No action. |

**All three findings were analyzed and found to be non-issues upon deeper inspection.**

---

## Spec Compliance Checklist

| Spec Requirement | Implemented | Notes |
|-----------------|-------------|-------|
| Create `memory_draft.py` | Yes | 332 lines |
| CREATE auto-populates all required fields | Yes | Verified against build_memory_model() |
| UPDATE preserves immutables | Yes | created_at, schema_version, category, id |
| UPDATE unions tags (deduplicated) | Yes | sorted set union |
| UPDATE unions related_files | Yes | sorted set union, None if empty |
| UPDATE appends change entry | Yes | |
| UPDATE increments times_updated | Yes | |
| UPDATE shallow-merges content | Yes | existing.update(new) |
| Validates via Pydantic | Yes | build_memory_model() + model_validate() |
| Input path restricted to .staging/ or /tmp/ | Yes | realpath + check |
| Output to .staging/draft-* | Yes | with timestamp + PID |
| Stdout JSON with status, action, draft_path | Yes | |
| Venv bootstrap pattern | Yes | Same as memory_write.py |
| Import from memory_write.py works | Yes | All 7 names verified |
| Add --new-info-file to memory_candidate.py | Yes | |
| --new-info-file takes precedence | Yes | |
| At least one of --new-info or --new-info-file required | Yes | |
| Error handling for file read failures | Yes | 3 exception types |
| Update SKILL.md Phase 1 | Yes | Steps 2-10 rewritten |
| Write tool mandate in SKILL.md | Yes | Blockquote at top |
| DELETE flow unchanged | Yes | |
| Phase 2/3 compatible | Yes | Draft is complete JSON |

---

## Self-Critique

**Challenge 1:** "Did I miss any imports that might fail at runtime?"
Response: No. I verified all 7 imports exist in memory_write.py. The tricky one is `ValidationError` -- it's imported from pydantic at line 48 of memory_write.py and thus available as a module-level name. Confirmed.

**Challenge 2:** "Could the `extra='forbid'` on the Pydantic model reject a field that assemble_create/update produces?"
Response: No. `assemble_create` produces exactly the fields defined in `build_memory_model()`. `assemble_update` starts from `dict(existing)` which may contain `retired_at`, `retired_reason`, `archived_at`, `archived_reason` -- all of which are defined in the model. No extra fields are introduced.

**Challenge 3:** "Is there a race condition in the draft filename?"
Response: Unlikely. The filename includes both timestamp (second-resolution) and PID. Two processes would need the same PID and same second to collide. PID reuse within one second is practically impossible.

**Challenge 4:** "Could `assemble_update` break when `existing` has unexpected fields?"
Response: Yes, this IS possible -- if the existing JSON file has extra fields not in the schema (e.g., from a future version), `dict(existing)` carries them into the assembled result, and `model_validate()` with `extra="forbid"` would reject them. However, this is actually the **correct behavior**: the draft should fail validation if the existing file is not schema-compliant, rather than silently producing a draft from corrupt data.

**Challenge 5:** "Does the SKILL.md correctly guide haiku-level models?"
Response: Yes. Instructions use numbered sequential steps, explicit action routing, code blocks with copy-pasteable commands, and concrete field names. The flat decision table in step 5 avoids nested branching. The enhanced step 4 documentation of `candidate.path` helps weaker models reference the right value in later steps.
