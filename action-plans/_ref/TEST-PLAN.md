# Test Plan: claude-memory Plugin

Prioritized test plan derived from infrastructure audit and security review.
All tests should use **pytest** and live in `tests/`.

## Prerequisites

```bash
pip install pytest pydantic>=2.0
```

## P0 -- Security-Critical (Must Test First)

### P0.1: Prompt Injection via Memory Titles
**Files:** memory_retrieve.py, memory_index.py, memory_write.py

Memory titles from index.md are injected into Claude's context on every
conversation turn. Titles are sanitized on write (`memory_write.py` auto-fix)
and re-sanitized on read (`memory_retrieve.py` `_sanitize_title`). Tests should
verify the full sanitization chain and that bypass attempts fail.

**Tests to write:**
- Title containing instruction-like content (e.g., "SYSTEM: Ignore all previous instructions") is sanitized or clearly labeled
- Title with newlines is rejected or stripped at write time
- Title with index delimiters is rejected or escaped
- Very long titles (>500 chars) are truncated
- Output includes untrusted-content warning label

### P0.2: max_inject Clamping
**File:** memory_retrieve.py

The `retrieval.max_inject` config value is clamped to [0, 20] with fallback
to default 5 on parse failure. Tests should verify this clamping holds.

**Tests to write:**
- max_inject = 0: no memories injected
- max_inject = 5 (default): normal behavior
- max_inject = -1: should not inject all entries (Python slice behavior)
- max_inject = 999999: should be clamped to a safe upper bound (e.g., 20)
- max_inject = non-integer string: should fall back to default
- max_inject missing from config: should use default 5

### P0.3: Config Integrity
**File:** memory_retrieve.py

Config file is read with no schema validation or integrity check.

**Tests to write:**
- Malformed JSON config: graceful fallback to defaults
- Config with retrieval.enabled = false: no injection
- Config with unknown fields: ignored without crash
- Missing config file: default behavior
- Config with retrieval section missing: default behavior

---

## P1 -- Core Functional Tests

### P1.1: Keyword Matching (memory_retrieve.py)

**Tests to write:**
- Empty prompt (<10 chars): exits silently, no output
- Prompt with all stop words: no matches
- Exact word match scores higher than prefix match
- Prefix matching works for 4+ char tokens (e.g., "auth" matches "authentication")
- Prefix matching does NOT work for 3-char tokens
- Category priority ordering (DECISION > CONSTRAINT > ... > SESSION_SUMMARY)
- Multiple entries: correct top-N selection
- Entries with no matching words: score = 0, not returned
- Punctuation stripping works correctly

### P1.2: Index Operations (memory_index.py)

**Tests to write:**
- Rebuild with fixture data: produces valid index.md
- Rebuild with empty directory: no crash, informative message
- Rebuild with malformed JSON files: warns on stderr, skips bad files
- Validate with matching index: returns True
- Validate with stale entry (file deleted): reports mismatch
- Validate with missing entry (new file): reports mismatch
- Query with matching keyword: returns correct entries
- Query with no matches: informative message
- Non-existent root directory: exits with error

### P1.3: Candidate Selection (memory_candidate.py)

**Tests to write:**
- Exact word match on title: 2 points
- Tag match: 3 points
- Prefix match on title (4+ chars): 1 point
- Score >= 3 threshold for candidate selection
- Score < 3: no candidate, falls back to CREATE
- Lifecycle event with no candidate: NOOP
- DELETE disallowed for decision/preference/session_summary categories
- Path safety: candidate path must resolve under memory root
- Index line parsing regex: valid lines, edge cases, malformed lines
- Tokenizer: stop words filtered, short words filtered, punctuation handled

### P1.4: Write Operations (memory_write.py)

**Tests to write:**
- CREATE: produces valid JSON file + updates index.md
- UPDATE: modifies existing file, preserves history, bumps updated_at
- DELETE (soft retire): sets record_status to "retired", removes from index, preserves file for grace period
- OCC hash check: update with wrong hash is rejected
- Atomic write: partial failure does not corrupt existing file
- Title sanitization: control chars, delimiters stripped/rejected
- Pydantic validation: invalid data is rejected with clear error
- File locking: concurrent writes do not corrupt

### P1.5: Triage Hook (memory_triage.py)

**Tests to write:**
- stdin JSON parsing: valid JSON with transcript_path processed correctly
- Empty/invalid/missing stdin: exits 0 (fail-open)
- Transcript parsing: JSONL lines read correctly, corrupt lines skipped
- Text preprocessing: fenced code blocks and inline code stripped
- Keyword scoring: primary patterns match correctly per category
- Co-occurrence boosting: boosters within 4-line window amplify score
- SESSION_SUMMARY scoring: activity-based (tool uses, exchanges)
- Threshold comparison: categories above threshold trigger, below do not
- Stop flag: flag file created on exit 2, allows through on next stop within 5 minutes
- Stop flag TTL: stale flag (>5 min) is ignored, evaluation continues
- Context file generation: per-category files written with correct format
- Context file truncation: files capped at 50KB
- Config reading: triage.enabled=false exits immediately, thresholds applied
- Snippet sanitization: control chars, zero-width Unicode, XML escaping
- Transcript path validation: paths outside /tmp/ and $HOME/ rejected
- Output format: human-readable message + `<triage_data>` JSON block on stderr

---

## P2 -- Guard and Validation Tests

### P2.1: Write Guard (memory_write_guard.py)

**Tests to write:**
- Path inside memory directory: blocked with denial reason
- Path outside memory directory: allowed (exit 0)
- Staging file (/tmp/.memory-write-pending.json): explicitly allowed
- Draft file (/tmp/.memory-draft-*.json): explicitly allowed
- Context file (/tmp/.memory-triage-context-*.txt): explicitly allowed
- Path traversal attempts (../ sequences): correctly detected
- Symlink to memory directory: correctly detected via realpath
- Empty/missing file_path in hook input: passes through
- Malformed JSON on stdin: exits cleanly

### P2.2: Validate Hook (memory_validate_hook.py)

**Tests to write:**
- Valid memory JSON: passes, warns about guard bypass
- Invalid JSON (parse error): quarantined
- Valid JSON but wrong schema (missing fields): quarantined
- Category mismatch (file in decisions/ but category=runbook): quarantined
- Non-memory JSON write: ignored (exit 0)
- Quarantine file naming: correct timestamp suffix
- Fallback validation (no pydantic): basic field checks work

---

## P3 -- Nice to Have

### P3.1: Schema Validation
- All 7 JSON Schema files in assets/schemas/ are valid JSON Schema
- Fixture memory files conform to their category schema
- Pydantic models match JSON Schema definitions (no drift)

### P3.2: Command Hook Integration Tests
- Stop hook (memory_triage.py): stdin JSON parsed, exit codes correct (0=allow, 2=block)
- Stop flag file (.claude/.stop_hook_active): created on block, allows through within 5-min TTL, auto-expires
- Triage output format: human-readable message + `<triage_data>` JSON block on stderr

### P3.3: CI/CD
- GitHub Actions workflow: lint (ruff) + test (pytest) on push/PR
- Pre-commit config for linting

### P3.4: Project Scaffolding
- pyproject.toml with [project.optional-dependencies] for pytest + pydantic
- .gitignore updates for __pycache__/, *.pyc, *.bak

---

## Test Fixture Strategy

Tests should use `tmp_path` (pytest fixture) to create isolated memory
directories with known fixture data. Suggested fixtures:

- `sample_index_md`: index.md with 5-10 entries across categories
- `sample_memory_files`: JSON files matching each category schema
- `sample_config`: memory-config.json with default settings
- `malicious_index_md`: index with injection-style titles
- `corrupt_config`: malformed JSON, missing fields, extreme values

## References

- Security considerations: see CLAUDE.md "Security Considerations" section
- Full test plan context: see CLAUDE.md "Testing" section
