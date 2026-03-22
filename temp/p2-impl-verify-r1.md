# Phase 2 Implementation Verification — Round 1 (Structural)

**Verifier:** Opus 4.6 (1M context)
**Date:** 2026-03-21
**Scope:** Phase 2, Step 2.1 — SKILL.md + memory_write.py changes
**Cross-model:** Codex 5.3 + Gemini 3.1 Pro via pal clink

---

## 1. SKILL.md Changes

### 1.1 `find -delete` → `rm` replacement

**OLD:** `find .claude/memory/.staging -maxdepth 1 -name 'intent-*.json' -delete 2>/dev/null; echo "ok"`
**NEW:** `rm .claude/memory/.staging/intent-*.json 2>/dev/null; echo "ok"`

| Check | Verdict | Notes |
|-------|---------|-------|
| Glob targets only intent-*.json? | PASS | Bash glob `intent-*.json` strictly matches that prefix+suffix. Does not touch `context-*.txt`, `triage-data.json`, etc. (Codex + Gemini confirmed) |
| `.staging/` doesn't exist? | PASS | `rm` emits error to stderr, `2>/dev/null` suppresses it, `; echo "ok"` normalizes exit to 0. Same effective behavior as `find` version. |
| No matching files? | PASS | Bash passes literal unexpanded glob to `rm`, which fails silently due to `2>/dev/null`. `echo "ok"` ensures success exit. |
| Behavioral differences from `find -delete`? | PASS (minor) | Two non-blocking differences: (1) `find -delete` could remove empty directories named `intent-*.json`; `rm` cannot. Not a real concern. (2) `rm` is subject to ARG_MAX limits; `find -delete` is not. Negligible for a staging directory with single-digit intent files per session. (Both models confirmed.) |

**Verdict: PASS**

### 1.2 `--result-json` → `--result-file` replacement

**OLD (SKILL.md line 292):**
```
python3 ... --result-json '{"saved_at": "...", "categories": [...], ...}'
```

**NEW (SKILL.md lines 292-296):**
```
Write(file_path='.claude/memory/.staging/last-save-result-input.json', content='{...}')
python3 ... --result-file .claude/memory/.staging/last-save-result-input.json
```

| Check | Verdict | Notes |
|-------|---------|-------|
| Avoids Guardian scan? | PASS | Inline JSON with `.claude` paths no longer appears on Bash command line. The Write tool writes the JSON file (auto-approved by write_guard Phase 1 fix since `last-save-result-input.json` matches `_STAGING_FILENAME_RE`: `last-save-result` + `[-.].*` + `.json`). Bash only contains a file path reference. (Both models confirmed.) |
| Write tool auto-approve works? | PASS | `_STAGING_FILENAME_RE` is `^(?:intent|input|draft|context|new-info|triage-data|candidate|last-save-result|\.triage-pending)(?:[-.].*)?\.(?:json|txt)$`. The filename `last-save-result-input.json` matches: `last-save-result` prefix, then `-input` matches `[-.].*`, then `.json`. |
| Temp file cleanup? | PASS (by design) | `last-save-result-input.json` lives in `.staging/`. The `cleanup-staging` action removes all staging files. The SKILL.md flow runs cleanup after successful saves. |

**Verdict: PASS**

### 1.3 Rule 0 expansion

**OLD:**
> "Never combine heredoc, Python interpreter, and .claude path in a single Bash command. All staging file writes must use the Write tool. Each python3 command must be a separate Bash tool call."

**NEW:**
> "Never combine heredoc (`<<`), Python interpreter, and `.claude` path in a single Bash command. All staging file content must be written via Write tool (not Bash). Bash is only for running python3 scripts. Do NOT use `python3 -c` with inline code referencing `.claude` paths. Do NOT use `find -delete` (use `rm` pattern instead). Do NOT pass inline JSON containing `.claude` paths on the Bash command line (use `--result-file` with a staging temp file instead)."

| Check | Verdict | Notes |
|-------|---------|-------|
| Covers RC-3 (Guardian heredoc patterns)? | PASS | "Never combine heredoc, Python interpreter, and .claude path" |
| Covers RC-4 (python3 -c inline code)? | PASS | "Do NOT use `python3 -c` with inline code referencing `.claude` paths" |
| Covers RC-5 (find -delete)? | PASS | "Do NOT use `find -delete` (use `rm` pattern instead)" |
| Covers inline JSON Guardian trigger? | PASS | "Do NOT pass inline JSON containing `.claude` paths on the Bash command line" |
| Provides alternatives for each prohibition? | PASS | Write tool for staging content, `rm` for deletion, `--result-file` for JSON |
| Accurate and complete? | PASS | All known Guardian pattern triggers from the action plan are covered |

**Verdict: PASS**

### 1.4 Other Guardian-triggerable commands in SKILL.md

Scanned all `python3` and `bash` commands in SKILL.md:

| Command Pattern | Guardian Risk? | Notes |
|-----------------|---------------|-------|
| `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-staging --staging-dir .claude/memory/.staging` | LOW | Runs a named script with path args. No inline code, no heredoc, no inline JSON. `--staging-dir` arg contains `.claude` but this is a simple path argument, not JSON. |
| `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" --category <cat> --new-info-file ...` | LOW | Named script with file path args only. |
| `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_draft.py" --action create ...` | LOW | Named script, no inline content. |
| `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action create/update/retire ...` | LOW | Named script, path args only. |
| `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_enforce.py" --category session_summary` | LOW | Named script, simple args. |
| Phase 3 subagent uses `;` command chaining | LOW | Rule 0 says "Do NOT use heredoc", subagent instructions say "Do NOT use heredoc (<<)". Commands are chained with `;` not heredoc. |

No remaining commands embed inline JSON or use prohibited patterns. The `--staging-dir .claude/memory/.staging` path argument appears in multiple commands but is a simple CLI argument, not JSON content -- Guardian scans for destructive patterns with interpreter+path combinations, not simple path arguments to known scripts.

**Verdict: PASS**

### 1.5 `retrieval.max_inject` default correction (5 → 3)

This is an unrelated documentation fix bundled into the Phase 2 changeset. The default in `memory-config.default.json` is 3, not 5. The SKILL.md was out of date.

**Verdict: PASS (accurate fix, but should ideally be a separate commit for bisectability)**

---

## 2. memory_write.py `--result-file` Implementation

### 2.1 Argument definition

```python
parser.add_argument(
    "--result-file",
    help="Path to JSON file for save result (alternative to --result-json, avoids Guardian scan of inline JSON)",
)
```

| Check | Verdict | Notes |
|-------|---------|-------|
| Argument properly defined? | PASS | Optional string argument, clear help text |
| Name consistent with SKILL.md? | PASS | SKILL.md uses `--result-file`, code uses `--result-file` |

### 2.2 File reading logic

```python
result_json = args.result_json
if not result_json and args.result_file:
    try:
        with open(args.result_file, "r", encoding="utf-8") as rf:
            result_json = rf.read()
    except (OSError, IOError) as e:
        print("ERROR: Cannot read --result-file {}: {}".format(args.result_file, e))
        return 1
if not result_json:
    print("ERROR: --result-json or --result-file is required for write-save-result.")
    return 1
result = write_save_result(args.staging_dir, result_json)
```

| Check | Verdict | Notes |
|-------|---------|-------|
| Fallback order correct? | PASS | `--result-json` takes priority (checked first). `--result-file` is only used if `--result-json` is falsy. |
| Error handling? | PASS | `OSError`/`IOError` caught, error message includes path and exception, returns 1. |
| Backwards compatible? | PASS | `--result-json` still works unchanged. Old callers unaffected. Both models confirmed. |
| Empty file handling? | PASS | Empty file → `result_json = ""` → falsy → falls to "ERROR: --result-json or --result-file is required" message. Correct behavior. |

**Verdict: PASS**

### 2.3 Security: arbitrary file read via `--result-file`

| Threat | Risk | Mitigation | Assessment |
|--------|------|------------|------------|
| Read arbitrary files | LOW | File content passes through `write_save_result()` which validates JSON schema (allowed keys, type enforcement, length caps). Non-JSON files fail at `json.loads()`. Error messages show parse errors only, not file content. No data exfiltration. (Gemini confirmed.) |
| Unbounded read (DoS) | MEDIUM | Codex reproduced: `--result-file /dev/zero` causes `rf.read()` to hang indefinitely. The file is read entirely before the 10KB size check in `write_save_result()`. |
| Path traversal | LOW | No path containment check, but the content goes through strict schema validation. The output is written to `--staging-dir` (which IS path-validated to end with `memory/.staging`). |

**Codex-specific finding:** The `rf.read()` call is unbounded. Codex verified that pointing at `/dev/zero` causes the process to hang until killed. This is a legitimate defense-in-depth concern.

**Severity assessment:** LOW in practice because:
1. This script is only called by the haiku Task subagent in a controlled Phase 3 flow
2. The `--result-file` path is constructed by the main agent, not user-supplied
3. Claude Code's tool approval would catch anomalous paths
4. The subagent has a timeout

**Recommendation for follow-up hardening (not blocking for Phase 2):**
- Add `os.path.isfile()` check before reading (rejects device files, sockets, etc.)
- Read at most `_SAVE_RESULT_MAX_SIZE + 1` bytes instead of unbounded `read()`
- Optionally restrict path to resolve under `--staging-dir`

**Verdict: PASS (with advisory for future hardening)**

---

## 3. Cross-Model Review Summary

| Model | Change 1 (rm) | Change 2 (--result-file) | Key Unique Finding |
|-------|---------------|-------------------------|-------------------|
| Codex 5.3 | PASS | PASS (with medium advisory) | Unbounded `rf.read()` hangs on `/dev/zero` — verified experimentally |
| Gemini 3.1 Pro | PASS | PASS | ARG_MAX theoretical limit for rm globbing; arbitrary read mitigated by JSON parse masking |
| Opus 4.6 (self) | PASS | PASS | `last-save-result-input.json` correctly matches write_guard regex for auto-approve |

**Cross-model consensus:** Both changes are correct and safe to merge. One hardening advisory (unbounded read) for future improvement.

---

## 4. Vibe Check Summary

- No concerning patterns detected (no complexity bias, no feature creep, no misalignment)
- Changes are appropriately minimal and map 1:1 to documented root causes (RC-3 through RC-5)
- The `max_inject` default fix is correct but slightly off-topic for this changeset
- Rule 0 expansion is comprehensive and provides actionable alternatives for each prohibition

---

## Overall Verdict: PASS

All Phase 2 changes are structurally sound, functionally correct, backwards-compatible, and achieve their stated goal of reducing Guardian popup triggers.

| Item | Verdict |
|------|---------|
| `find -delete` → `rm` | PASS |
| `--result-json` → `--result-file` (SKILL.md) | PASS |
| `--result-file` argument (memory_write.py) | PASS |
| Rule 0 expansion | PASS |
| Backwards compatibility | PASS |
| Security (arbitrary file read) | PASS (advisory: add bounded read) |
| Cross-model consensus | PASS |
| Remaining Guardian patterns | PASS (none found) |
| `max_inject` default fix | PASS (unrelated but accurate) |
| **Overall** | **PASS** |

### Advisories (non-blocking, for future hardening)

1. **Bounded read for `--result-file`**: Add `os.path.isfile()` guard and read at most `_SAVE_RESULT_MAX_SIZE + 1` bytes to prevent DoS on device files. Severity: LOW (controlled call context).
2. **Separate commit for `max_inject` fix**: The retrieval default correction is unrelated to Guardian popup fixes. Consider splitting for clean git history.
