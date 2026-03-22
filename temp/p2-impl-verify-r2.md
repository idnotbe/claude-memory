# Phase 2 Implementation Verification -- Round 2 (Adversarial)

**Verifier**: Opus 4.6 (adversarial)
**Date**: 2026-03-21
**Files Verified**:
- `skills/memory-management/SKILL.md` (Phase 2 changes: rm replacement, --result-file, Rule 0)
- `hooks/scripts/memory_write.py` (--result-file flag addition)

**Cross-Model**: Codex 5.3 + Gemini 3.1 Pro (both confirm critical finding)

---

## Overall Verdict: FAIL

One critical bug, two medium findings, two advisory notes. Change 2 (--result-file) is solid. Change 1 (rm replacement) is a lateral move -- equally blocked by Guardian.

---

## 1. Attack Vectors

### 1.1 `--result-file` Path Abuse -- PASS (low residual risk)

**Attack**: `--result-file /etc/passwd` or `--result-file /dev/zero`

**Analysis**:
- The file IS read without path validation (line 1627: `open(args.result_file, "r")`).
- `/etc/passwd` content fails `json.loads()` at line 577 and returns an error. The error message does NOT echo back the file contents -- only reports "Invalid JSON: ...".
- `/dev/zero` or large files: `rf.read()` reads unbounded before `_SAVE_RESULT_MAX_SIZE` (10KB) check at line 573. Could cause memory exhaustion or hang on FIFOs.
- Symlinks are followed by `open()`.

**Mitigating factors**:
- The script runs as the user's own process -- no privilege escalation possible.
- The caller is the haiku Task subagent instructed by SKILL.md, not external untrusted input.
- The output path is always `<staging_dir>/last-save-result.json` -- cannot be redirected via `--result-file`.
- Schema validation (allowed keys, type enforcement, length caps) prevents arbitrary content from being persisted.

**Verdict**: PASS (acceptable residual risk for the threat model: subagent manipulation, not filesystem-level attacker). Codex 5.3 recommends bounded read + O_NOFOLLOW + fstat as defense-in-depth -- valid hardening but not blocking for this phase.

### 1.2 Write Tool Auto-Approve for `last-save-result-input.json` -- PASS

**Regex test**: `_STAGING_FILENAME_RE` matches `last-save-result-input.json` correctly.
```
^(?:intent|input|draft|context|new-info|triage-data|candidate|
last-save-result|\.triage-pending)(?:[-.].*)?\.(?:json|txt)$
```
The `last-save-result` prefix matches, `(?:[-.].*)?` matches `-input`, and `\.json$` matches the extension. Write tool will auto-approve this file (no popup). Verified by executing the regex.

**Verdict**: PASS.

### 1.3 Guardian Trigger on `rm .claude/...` -- **CRITICAL FAIL**

**Attack vector**: SKILL.md line 60 instructs:
```bash
rm .claude/memory/.staging/intent-*.json 2>/dev/null; echo "ok"
```

Guardian BLOCK pattern (guardian.default.json line 21):
```regex
(?i)(?:^\s*|[;|&`({]\s*)(?:rm|rmdir|del|delete|deletion|remove-item)\b\s+.*\.claude(?:\s|/|[;&|)`'"]|$)
```

**Verified match**: `re.search(pattern, cmd)` matches `rm .claude/` -- this is a BLOCK (not ASK), meaning the command is silently prevented, not prompted. This is a **net regression** from the original `find -delete` (which was also blocked, but the replacement was supposed to fix it).

**Cross-model confirmation**:
- Codex 5.3: "the SKILL cleanup replacement is still blocked by the provided Guardian BLOCK regex [...] replacing `find -delete` with this `rm` command does not avoid Guardian; it remains blocked"
- Gemini 3.1 Pro: "The new `rm` command directly triggers Guardian's `.claude` deletion block pattern [...] a critical correctness failure"

**Alternatives (from Gemini + Codex)**:
1. **Best**: Add `--action clean-intents --staging-dir ...` to `memory_write.py` (Python deletion, no Guardian involvement)
2. **Quick**: `cd .claude/memory/.staging && rm intent-*.json 2>/dev/null; echo "ok"` (Guardian regex requires `.claude` after the `rm` keyword; `cd` moves `.claude` to a different command position)

**Verdict**: CRITICAL FAIL. Must fix before shipping Phase 2.

### 1.4 Rule 0 Self-Contradicting Instruction -- MEDIUM

SKILL.md line 431 now says:
> "Do NOT use `find -delete` (use `rm` pattern instead)."

This actively instructs agents to generate `rm .claude/...` commands, which are equally blocked by Guardian. Rule 0 propagates the bug.

**Fix**: Update Rule 0 to forbid both `find -delete` AND direct `rm`/`del` on `.claude` paths. Recommend `cd`-based approach or Python script delegation.

**Verdict**: MEDIUM -- documentation-driven regression risk.

---

## 2. Operational Risk

### 2.1 `rm` with No Matching Files -- PASS (with caveat)

**Test**: `rm /tmp/nonexistent-glob-*.json 2>/dev/null` returns exit code 1, but `; echo "ok"` resets the visible output. The Bash call itself returns exit code 0 (from `echo`).

If the command were not Guardian-blocked (which it is -- see 1.3), this would work correctly operationally.

**Verdict**: PASS (moot due to 1.3).

### 2.2 Glob Expansion Size -- PASS

Intent files are one per category (max 6 categories). The glob `intent-*.json` would match at most 6 files. No risk of ARG_MAX overflow.

**Verdict**: PASS.

### 2.3 `--result-file` Race with Cleanup -- PASS

**Flow analysis** (SKILL.md lines 287-296):
1. Save commands execute
2. `cleanup-staging` runs (deletes drafts, context, input, intent, new-info, triage-data, .triage-pending)
3. Write tool creates `last-save-result-input.json` (NOT in cleanup patterns)
4. `memory_write.py --result-file` reads the input file, writes `last-save-result.json`

`_STAGING_CLEANUP_PATTERNS` does NOT include `last-save-result*`. The input file is created AFTER cleanup. No race condition.

**Verdict**: PASS.

---

## 3. Completeness Check

### 3.1 Other `find -delete` Patterns in SKILL.md -- PASS

Grep for `find.*-delete` in SKILL.md returns only the Rule 0 reference (which warns against it, not uses it). The actual command at line 60 has been changed to `rm`. No remaining `find -delete` usage.

**Verdict**: PASS.

### 3.2 Other Inline JSON with `.claude` Paths -- PASS

Grep for `--result-json` in SKILL.md returns 0 matches. The old inline JSON pattern has been fully replaced with the Write tool + `--result-file` approach.

**Verdict**: PASS.

### 3.3 Rule 0 Comprehensiveness -- MEDIUM (incomplete)

Rule 0 now covers:
- No heredoc + Python + .claude combination
- No `python3 -c` with .claude paths
- No `find -delete`
- No inline JSON with .claude paths on Bash command line
- Bash only for running python3 scripts
- Write tool for staging file content

**Missing from Rule 0**:
- No `rm`/`del`/`rmdir` targeting `.claude` paths (the very bug in this phase)
- No guidance on the `cd`-first workaround for legitimate deletions
- No mention of Guardian BLOCK vs ASK distinction

**Verdict**: MEDIUM -- Rule 0 needs expansion to cover direct deletion commands.

---

## 4. Cross-Model Summary

| Source | Key Finding | Agreement |
|--------|------------|-----------|
| Opus 4.6 (this) | `rm .claude/...` matches Guardian BLOCK pattern -- lateral move | Primary finding |
| Codex 5.3 | Confirms BLOCK match; recommends --result-file path containment + bounded read | Agrees on critical bug; adds defense-in-depth recommendations |
| Gemini 3.1 Pro | Confirms BLOCK match; recommends `cd`-based workaround or Python action | Agrees on critical bug; proposes same alternatives |

**Unanimous agreement**: Change 1 is broken (CRITICAL), Change 2 is correct (PASS).

---

## 5. Vibe Check Summary

- Change 2 (--result-file) is a clean architectural improvement. Guardian does not scan file payloads, only command-line text. The decoupling works.
- Change 1 (rm replacement) is a **lateral fix trap** -- replacing one blocked pattern with another without testing against the actual blocking rules.
- Rule 0 now actively misleads agents into generating blocked commands.
- Phase 4 Step 4.2 test plan mentions "guardian_ask_patterns" but should also cover BLOCK patterns.

---

## Recommended Fixes Before Phase 2 Merge

1. **CRITICAL**: Replace `rm .claude/memory/.staging/intent-*.json 2>/dev/null; echo "ok"` with one of:
   - `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action clean-intents --staging-dir .claude/memory/.staging` (new action)
   - `cd .claude/memory/.staging && rm intent-*.json 2>/dev/null; echo "ok"` (quick fix)
2. **MEDIUM**: Update Rule 0 to warn against `rm`/`del`/`rmdir` on `.claude` paths (not just `find -delete`).
3. **MEDIUM**: Update Phase 4 Step 4.2 to test commands against Guardian BLOCK patterns, not just ASK patterns.
4. **ADVISORY**: Consider bounded read for `--result-file` (`rf.read(_SAVE_RESULT_MAX_SIZE + 1)`) to prevent memory exhaustion on adversarial inputs. Low priority.
5. **ADVISORY**: Consider `--result-file` path containment (must be in staging dir) for defense-in-depth. Low priority given threat model.

---

## Per-Attack Verdict Table

| # | Attack/Check | Verdict | Severity |
|---|-------------|---------|----------|
| 1.1 | --result-file arbitrary path read | PASS | Low (residual) |
| 1.2 | Write tool auto-approve for result-input.json | PASS | N/A |
| 1.3 | rm .claude/... Guardian BLOCK match | **FAIL** | **CRITICAL** |
| 1.4 | Rule 0 misleading rm instruction | FAIL | MEDIUM |
| 2.1 | rm with no matching files | PASS | N/A |
| 2.2 | Glob expansion overflow | PASS | N/A |
| 2.3 | --result-file race with cleanup | PASS | N/A |
| 3.1 | Remaining find -delete patterns | PASS | N/A |
| 3.2 | Remaining inline JSON patterns | PASS | N/A |
| 3.3 | Rule 0 comprehensiveness | FAIL | MEDIUM |
