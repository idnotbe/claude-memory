# P6 Verification Report: Heredoc False Positives + Interpreter Path Resolution

**Verifier**: Claude Opus 4.6 (structural verification)
**Date**: 2026-03-21
**Documents verified**:
1. `action-plans/heredoc-pattern-false-positives.md` (Step 6.1)
2. `action-plans/interpreter-path-resolution.md` (Step 6.2)
**Cross-model validator**: Gemini 2.5 Pro (via PAL chat)
**Meta-mentor**: Vibe-check

---

## A. Technical Accuracy

### A.1 Line Number Verification

#### heredoc-pattern-false-positives.md

| Claim | Actual | Verdict |
|-------|--------|---------|
| `match_block_patterns` uses `re.DOTALL` at line 872 | Line 872: `match = safe_regex_search(pattern, command, re.IGNORECASE \| re.DOTALL)` | CORRECT |
| `match_ask_patterns` at line 1042 | Definition at line 1013; line 1042 is the `safe_regex_search` call with `re.DOTALL` | MISLEADING -- plan says "line 1042" but this is the regex call line, not the function definition. The re.DOTALL claim itself is correct. |
| `main()` lines 1379-1540 | `main()` starts at line 1379 | CORRECT |
| Layer 0 at line 1423 | Line 1423: `blocked, reason = match_block_patterns(command)` | CORRECT |
| Layer 0b at line 1437 | Line 1437: `needs_ask, ask_reason = match_ask_patterns(command)` | CORRECT |
| `split_commands()` at line 1442 | Line 1442: `sub_commands = split_commands(command)` | CORRECT |
| `scan_text` at line 1450 | Line 1450: `scan_text = ' '.join(...)` | CORRECT |
| `scan_protected_paths` at line 1453 | Line 1453: `scan_verdict, scan_reason = scan_protected_paths(scan_text, config)` | CORRECT |
| `_consume_heredoc_bodies()` at lines 476-506 | Lines 476-506 match exactly | CORRECT |
| `split_commands()` newline handler at lines 420-428 | Lines 420-428 match exactly | CORRECT |
| Short-circuit `sys.exit(0)` on line 1430 | Line 1430: `sys.exit(0)` | CORRECT |
| Layer 1 fix at lines 1444-1453 | Lines 1444-1453: scan_text uses sub_commands | CORRECT |

#### interpreter-path-resolution.md

| Claim | Actual | Verdict |
|-------|--------|---------|
| Block pattern line 69 of `guardian.default.json` | Line 69: Python `os.remove` etc. pattern | CORRECT |
| `split_commands()` at `bash_guardian.py:82` | Line 82: `def split_commands(command: str) -> list[str]:` | CORRECT |
| Layer 3/4 detection at `bash_guardian.py:1462-1463` | Line 1462: `is_write = is_write_command(sub_cmd)`, line 1463: `is_delete = is_delete_command(sub_cmd)` | CORRECT |
| Fallback path at `bash_guardian.py:1056-1061` | Lines 1056-1061: `check_interpreter_payload()` fallback in `is_delete_command()` | CORRECT |
| `check_interpreter_payload()` at `_guardian_utils.py:989-1010` | Lines 989-1010 match exactly | CORRECT |
| `_DESTRUCTIVE_API_PATTERN` at `_guardian_utils.py:907-910` | Lines 907-910 match exactly | CORRECT |
| `extract_interpreter_payload()` at `_guardian_utils.py:913-965` | Lines 913-965 match exactly | CORRECT |
| `shlex.split()` at `bash_guardian.py:913` | Line 913: `parts = shlex.split(command, posix=...)` | CORRECT |
| `_is_path_candidate()` at `bash_guardian.py:1133` | Plan says "line 1133" -- function definition is at line 1120, the `\n` check is at line 1133. Plan references the `_is_path_candidate()` return behavior, not the definition line. | MINOR AMBIGUITY -- the function is at line 1120, but 1133 is the `\n`/`\r` check within it |
| F1 safety net at `bash_guardian.py:1474-1481` | Lines 1474-1481 match exactly | CORRECT |
| `extract_paths()` parts iteration at line 927 | Line 927: `for part in parts[1:]:` | CORRECT |
| `-c` skipping at lines 928-946 | Line 928: `if part.startswith("-"):` through line 946 | CORRECT |
| F1 condition at line 1476 | Line 1476: `if (is_write or is_delete) and not sub_paths:` | CORRECT |

### A.2 Pattern String Verification

| Plan claim | `guardian.default.json` actual | Verdict |
|-----------|-------------------------------|---------|
| `rm\s+-[rRf]+\s+/(?:\s*$\|\*)` | Line 13: `rm\\s+-[rRf]+\\s+/(?:\\s*$\|\\*)` | CORRECT |
| `(?:rm\|rmdir\|...).*\.git` | Line 17: `(?:rm\|rmdir\|del\|delete\|deletion\|remove-item)\\b\\s+.*\\.git` | CORRECT (plan uses `...` as abbreviation) |
| `git\s+push\s.*--force` | Line 29: `git\\s+push\\s[^;\|&\\n]*(?:--force(?!-with-lease)\|-f\\b)` | CORRECT (plan abbreviates) |
| `find\s+.*\s+-delete` | Line 42: `(?i)find\\s+.*\\s+-delete` | CORRECT |
| `shred\s+` | Line 45: `shred\\s+` | CORRECT |
| `(?:curl\|wget).*\|\s*(?:bash\|sh)` | Line 49: `(?:curl\|wget)[^\|]*\\|\\s*(?:bash\|sh\|zsh\|python\|perl\|ruby\|node)` | CORRECT (plan abbreviates interpreter list) |
| `rm\s+-[rRf]+` (ask) | Line 87: `rm\\s+-[rRf]+` | CORRECT |
| `git\s+reset\s+--hard` (ask) | Line 99: `git\\s+reset\\s+--hard` | CORRECT |
| SQL patterns (ask) | Lines 139-149: DROP, TRUNCATE, DELETE FROM patterns | CORRECT |
| Interpreter deletion pattern (block, line 69) | Line 69: `python[23]?\s[^|&\n]*os\.remove` etc. | CORRECT |

### A.3 Execution Flow Verification

**Plan 1 (heredoc-pattern-false-positives.md)** describes the current flow as:
```
Line 1423: match_block_patterns(command)   <-- RAW string
Line 1437: match_ask_patterns(command)      <-- RAW string
Line 1442: sub_commands = split_commands(command)
Line 1450: scan_text = join(sub_commands...)
Line 1453: scan_protected_paths(scan_text)
```

**Verified against actual code**: This matches the actual `main()` flow at lines 1423-1456 exactly. Layer 0 and 0b DO operate on the raw command string before `split_commands()`. This is the root cause of the false positive problem described.

**Plan 2 (interpreter-path-resolution.md)** describes the F1 flow:
1. `is_delete_command()` -> True via `check_interpreter_payload()` fallback
2. `extract_paths()` -> `[]` because payload is code, not paths
3. F1 fires: `(is_write or is_delete) and not sub_paths` -> True

**Verified**: This matches the actual code at lines 1461-1481. The flow description is accurate.

### A.4 Technical Accuracy Summary

**PASS** -- All critical line references, pattern strings, and execution flow descriptions are accurate. Two minor ambiguities noted (match_ask_patterns line reference, _is_path_candidate line reference) but neither affects the correctness of the analysis.

---

## B. Completeness

### B.1 Edge Cases -- Plan 1 (Heredoc False Positives)

The plan covers 6 edge cases (pipe-to-interpreter, heredoc body as file path, database CLIs, custom scripts, multiple heredocs, here-strings). Analysis:

| Edge Case | Coverage | Assessment |
|-----------|----------|------------|
| Pipe-to-interpreter (`cat << EOF \| bash`) | Acknowledged as known limitation | **INCOMPLETE** -- This is a trivially exploitable bypass. See B.3 below. |
| Heredoc body as file path | Covered | ADEQUATE |
| Database CLIs in allowlist | Covered but reasoning flawed | **CONCERN** -- See B.4 below. |
| Custom scripts masquerading as data | Covered | ADEQUATE |
| Multiple heredocs | Covered, correct analysis | ADEQUATE |
| Here-strings (`<<<`) | Covered | ADEQUATE |

**Missing edge case**: `sed` with `/e` flag. The plan lists `sed` in `_DATA_HEREDOC_COMMANDS` (line 168) as a "text processing (read-only)" command. However, `sed`'s `e` flag executes the replacement as a shell command:
```bash
sed -f - << 'EOF'
s/.*/rm -rf .git/e
EOF
```
This would strip the body from scanning, hiding the `rm -rf .git` payload. **This is a security regression.**

**Missing edge case**: `patch` in the allowlist. `patch` is listed as an "editor" data command, but heredoc bodies for `patch` contain diff hunks that modify files. While `patch` itself doesn't execute shell code, its heredoc body can modify arbitrary files including protected ones. Less critical than `sed` but worth noting.

### B.2 Edge Cases -- Plan 2 (Interpreter Path Resolution)

| Edge Case | Coverage | Assessment |
|-----------|----------|------------|
| f-string paths | Covered (fail-closed) | ADEQUATE |
| String concatenation | Covered (fail-closed) | ADEQUATE |
| Triple-quoted strings | Covered (fail-closed) | ADEQUATE |
| Raw strings (`r'...'`) | Covered with note | ADEQUATE |
| Empty payload | Covered (fail-closed) | ADEQUATE |
| Non-path strings | Covered | ADEQUATE |
| Multiple paths with one unsafe | Covered | ADEQUATE |
| Glob with no matches | Covered (fail-closed) | ADEQUATE |
| Path outside project | Covered (fail-closed) | ADEQUATE |

**Missing edge case**: `glob.glob()` DoS. The function calls `glob.glob(str(path))` on user-controlled string literals. A pathological pattern like `/**/**/**/**` could cause excessive filesystem traversal. While the hook has a timeout (10 seconds per `guardian.default.json`), this could degrade performance. **MINOR CONCERN.**

**Missing edge case**: The `_STRING_LITERAL_PATTERN` regex uses `[^'\\]*(?:\\.[^'\\]*)*` for single-quoted strings, which models backslash-escaping. In POSIX shell, single-quoted strings do NOT support backslash escapes. However, since this function processes interpreter PAYLOADS (Python/Node/Perl code, not shell code), and these languages DO support backslash escapes in single-quoted strings (Python, Perl, Ruby), the regex is correct for its target context. **NOT AN ISSUE.**

### B.3 Security Gap: Pipe-to-Interpreter Bypass

The plan acknowledges `cat << EOF | bash` as a "known limitation" requiring "separate pipeline-aware analysis." However:

- This is a **trivially exploitable** bypass pattern
- It directly undermines the data/interpreter distinction that the plan depends on
- After `split_commands()`, the pipe produces two sub-commands: `cat << EOF` and `bash`
- The `bash` sub-command alone is benign -- it has no arguments or paths
- The heredoc body (containing `rm -rf .git`) is stripped because `cat` is a data command

**Recommendation**: Before implementing, add a simple heuristic: if a sub-command with a data heredoc is immediately followed (in the sub_commands list) by a pipe to a known interpreter, escalate to `ask`. This closes the most obvious exploitation vector without requiring full pipeline analysis.

### B.4 Security Regression: Database CLIs in Allowlist

The plan argues "the guardian protects the local filesystem, not remote databases." However, `guardian.default.json` already contains ask patterns for:
- `DROP TABLE` (line 139)
- `TRUNCATE TABLE` (line 143)
- `DELETE FROM` (line 147)

This demonstrates that SQL protection IS within the guardian's existing scope. Adding `mysql`, `psql`, `sqlite3` to `_DATA_HEREDOC_COMMANDS` creates a bypass:
- `mysql -e "DROP TABLE users;"` -> triggers ASK (pattern matches)
- `mysql << EOF\nDROP TABLE users;\nEOF` -> SILENTLY ALLOWED (body stripped)

**This is a security regression**, not merely a design choice. The plan contradicts the guardian's own configuration.

### B.5 Testing Plan Assessment

**Plan 1**: Testing plan is comprehensive with 5 test classes covering data command detection, selective body retention, Layer 0 false positive fixes, interpreter heredoc detection, and regression safety. The regression tests (verifying existing 168+ tests pass) are appropriate.

**Plan 2**: Testing plan covers unit tests, integration tests, and security regression tests. The test outline is adequate but less detailed than Plan 1 (some tests are sketched rather than fully implemented).

**Both plans**: No performance benchmarks are specified. Given that `split_commands()` is being moved earlier in the flow and `glob.glob()` is being added, a performance baseline comparison would be prudent.

### B.6 Completeness Summary

**PASS WITH CONCERNS** -- Both plans are thorough in their analysis and testing, but Plan 1 has three security concerns that need resolution before implementation:
1. `sed` must be removed from `_DATA_HEREDOC_COMMANDS`
2. Database CLIs (`mysql`, `psql`, `sqlite3`) must be removed from `_DATA_HEREDOC_COMMANDS`
3. Pipe-to-interpreter bypass needs at least a basic mitigation, not just acknowledgment

---

## C. Integration Coherence

### C.1 Plan 1 + Plan 2 Compatibility

The two plans address **different attack vectors** and do not conflict:

| Aspect | Plan 1 (Heredoc FP) | Plan 2 (Interpreter IPR) |
|--------|---------------------|--------------------------|
| Target | Heredoc bodies (`<< EOF`) | Inline payloads (`-c "..."`) |
| Problem | False positives (data in heredoc triggers patterns) | False positives (F1 fires on interpreter commands) |
| Mechanism | Selective body retention in `split_commands()` | Path extraction from string literals |
| Modified files | `bash_guardian.py` (main, split_commands, _consume_heredoc_bodies) | `_guardian_utils.py` (new function), `bash_guardian.py` (F1 block) |
| Code overlap | None -- different functions modified | None |

**No conflicts identified.** The plans modify different code paths and can be implemented independently or together.

### C.2 Integration with interpreter-heredoc-bypass.md

Plan 1 claims to **subsume** `interpreter-heredoc-bypass.md`. Verification:

- `interpreter-heredoc-bypass.md` proposes pattern-based ask for interpreter+heredoc (`INTERPRETER_HEREDOC_PATTERNS` regex list)
- Plan 1 achieves the same goal differently: by retaining interpreter heredoc bodies in sub-command output, Layer 0 block patterns naturally scan the body content
- Plan 1's approach is **more comprehensive**: it catches the actual dangerous content (e.g., `rm -rf .git` inside a bash heredoc) rather than just flagging the presence of an interpreter+heredoc combination

**Assessment**: The subsumption claim is valid. Plan 1's selective body retention provides a stronger mechanism than interpreter-heredoc-bypass.md's pattern-based ask. However, there is one nuance:

- `interpreter-heredoc-bypass.md` would trigger `ask` for ALL interpreter heredocs, even benign ones
- Plan 1 only triggers `block`/`ask` when the retained body content matches existing patterns
- This means Plan 1 is strictly more precise (fewer false positives) while catching the same true positives

**Recommendation**: After Plan 1 implementation, update `interpreter-heredoc-bypass.md` status to note that its mechanism is provided by Plan 1. Retain its test cases as regression tests.

### C.3 Overlapping Scope

There is **no problematic overlap** between the plans. Their concerns are adjacent but non-overlapping:

```
Heredoc FP plan:    cat << EOF (body stripped) vs bash << EOF (body retained)
Interpreter IPR:    python3 -c "os.remove('file')" (path extraction from -c payload)
Interpreter bypass: bash << EOF / rm -rf .git / EOF (interpreter heredoc detection)
```

### C.4 Integration Summary

**PASS** -- The plans are complementary, do not conflict, and the subsumption relationship with `interpreter-heredoc-bypass.md` is valid.

---

## D. Feasibility

### D.1 Code Changes Assessment

**Plan 1 modifications**:

| Change | Risk | Assessment |
|--------|------|------------|
| New `_DATA_HEREDOC_COMMANDS` frozenset + `_is_data_heredoc_command()` | LOW | Pure function, ~40 lines, no side effects |
| Modify `_consume_heredoc_bodies()` signature | MEDIUM | Changes return type from `int` to `tuple[int, str]`. All callers must be updated. Currently only one caller (line 427). |
| Modify `split_commands()` newline handler | MEDIUM | ~10 line change in critical parsing code. Requires careful testing. |
| Restructure `main()` flow (Layer 0/0b per-sub-command) | HIGH | Changes the fundamental execution order. Layer 0 no longer short-circuits on the raw string -- it iterates sub-commands. This is a significant behavioral change. |

**Concern with main() restructuring**: The plan moves `split_commands()` before Layer 0 and changes Layer 0 from single-shot to per-sub-command iteration. This is architecturally sound but changes timing: `split_commands()` runs on EVERY command (including simple ones like `ls`), whereas currently it only runs after Layer 0 passes. The performance impact should be negligible for typical commands but deserves measurement.

**Plan 2 modifications**:

| Change | Risk | Assessment |
|--------|------|------------|
| New `_STRING_LITERAL_PATTERN` + `extract_paths_from_interpreter_payload()` | LOW | New function in `_guardian_utils.py`, ~50 lines |
| Modify F1 block in `main()` | LOW | ~15 line addition within existing F1 block, fail-closed design |

### D.2 Existing Test Compatibility

**Plan 1**: The 168+ existing heredoc tests in `tests/test_heredoc_fixes.py` test `split_commands()` behavior. Since `split_commands()` will now include body text for interpreter heredocs (previously stripped), tests that check sub-command output for interpreter heredocs will FAIL and need updating. The plan does not explicitly address this.

**Key question**: Do existing tests check that heredoc bodies are NOT in sub-command output? If so, those tests will break when interpreter heredoc bodies are retained. This needs investigation before implementation.

**Plan 2**: No existing test breakage expected. The F1 modification only adds logic inside the existing F1 block; it doesn't change behavior when `is_interpreter_op` is False.

### D.3 `_DATA_HEREDOC_COMMANDS` Allowlist Soundness

The allowlist approach is architecturally sound but the specific entries need refinement:

| Command | In allowlist | Should be | Reason |
|---------|-------------|-----------|--------|
| `cat`, `tee` | Yes | Yes | Pure data output |
| `grep`, `head`, `tail`, etc. | Yes | Yes | Read-only text processing |
| `sed` | Yes | **NO** | `e` flag enables shell execution |
| `patch` | Yes | **Debatable** | Can modify arbitrary files, but body is diff format, not shell code |
| `echo`, `printf` | Yes | Yes | Pure output |
| `jq`, `yq` | Yes | Yes | Data processing |
| `mysql`, `psql`, `sqlite3` | Yes | **NO** | Contradicts existing SQL ask patterns |
| `mail`, `sendmail` | Yes | Yes | Mail data |

### D.4 Architectural Concerns

1. **Single point of classification**: The `_is_data_heredoc_command()` function becomes a critical security boundary. Every command must be correctly classified or the system fails. The fail-closed default (unknown = interpreter) is correct, but the function's parsing of command prefixes (env, sudo, etc.) adds complexity.

2. **Maintenance burden**: As new commands are encountered, the allowlist must be maintained. This is an ongoing security obligation, not a one-time implementation.

3. **The `_consume_heredoc_bodies` change is backward-incompatible**: The current function returns `int`; the proposed change returns `tuple[int, str]`. This is a clean breaking change with only one caller, but it must be done atomically.

### D.5 Feasibility Summary

**PASS WITH CONCERNS** -- Both plans are implementable without breaking the existing architecture. Key feasibility concerns:
1. Existing heredoc tests may need updates when interpreter bodies are retained
2. The allowlist entries need refinement (remove `sed`, database CLIs)
3. Performance impact of moving `split_commands()` earlier should be measured

---

## E. Cross-Model Synthesis

### Gemini 2.5 Pro Findings

The cross-model review identified the same three primary concerns found in this verification:

1. **`sed` in allowlist**: Gemini rated this a **VALID CONCERN**, noting the `s/.*/rm -rf .git/e` bypass vector. Gemini's recommendation to remove `sed` from the allowlist aligns with this verification's finding.

2. **Pipe-to-interpreter bypass**: Gemini rated this a **VALID CONCERN** and recommended adding a mitigation heuristic (detect data-heredoc piped to interpreter). This aligns with this verification's B.3 finding.

3. **Database CLIs in allowlist**: Gemini rated this a **VALID CONCERN**, noting the inconsistency with existing SQL ask patterns. This aligns with this verification's B.4 finding.

4. **`_STRING_LITERAL_PATTERN` for single-quoted strings**: Gemini rated this **NOT AN ISSUE**, correctly noting that the regex processes interpreter payloads (Python/Perl/Ruby code) where backslash escaping is valid. This aligns with this verification's B.2 finding.

5. **`glob.glob()` DoS**: Gemini rated this a **VALID CONCERN** and recommended input validation before calling `glob.glob()`. This verification concurs but rates it MINOR given the hook timeout protection.

6. **Multiple heredocs**: Gemini rated this **NOT AN ISSUE**, confirming the fail-closed behavior analysis. This aligns with this verification.

7. **`env -S` edge case**: Gemini rated this **NOT AN ISSUE**, correctly analyzing that `'bash -c evil'` as a single token would not match the allowlist. This aligns with this verification.

8. **Integration between plans**: Gemini rated this **NOT AN ISSUE**, confirming the complementary nature. This aligns with this verification's Section C findings.

### Vibe-Check Meta-Mentor Findings

The vibe-check raised an important meta-question: **Could the false positive problem be solved more simply?** Since `split_commands()` already strips heredoc bodies, running Layer 0/0b per-sub-command (after split) would already eliminate false positives WITHOUT needing the selective body retention mechanism. The selective retention is only needed for the SEPARATE goal of scanning interpreter heredoc bodies (from interpreter-heredoc-bypass.md).

This suggests the plan could be phased:
- **Phase A**: Move Layer 0/0b to per-sub-command scanning (solves false positives)
- **Phase B**: Add selective body retention (solves interpreter heredoc bypass)

This separation would reduce implementation risk and make each phase independently testable.

### Cross-Model Consensus

All three evaluators (this verification, Gemini 2.5 Pro, vibe-check) agree on:
- Remove `sed` from allowlist
- Remove database CLIs from allowlist
- Pipe-to-interpreter needs mitigation
- The plans are architecturally sound
- The integration between plans is valid

---

## F. Vibe Check Summary

The vibe-check identified:
- **Complex Solution Bias**: The selective body retention + allowlist approach solves two problems at once but increases implementation risk
- **Feature Creep potential**: Plan 2's Phase 2 AST-based extraction adds scope beyond the core problem
- **Sound core approach**: Moving `split_commands()` before Layer 0/0b is the correct architectural change

---

## Final Verdict

### PASS WITH CONCERNS

Both plans demonstrate thorough analysis, accurate source code references, comprehensive testing plans, and sound architectural reasoning. The integration between them and with `interpreter-heredoc-bypass.md` is coherent.

### Required Changes Before Implementation

1. **SECURITY**: Remove `sed` from `_DATA_HEREDOC_COMMANDS` -- the `e` flag enables shell command execution in sed scripts, creating a bypass vector
2. **SECURITY**: Remove `mysql`, `psql`, `sqlite3` from `_DATA_HEREDOC_COMMANDS` -- contradicts existing SQL ask patterns in `guardian.default.json` (lines 139-149), creating a security regression
3. **SECURITY**: Add basic pipe-to-interpreter mitigation -- at minimum, detect when a data-heredoc sub-command is piped to a known interpreter and escalate to `ask`

### Recommended Changes

4. **PHASING**: Consider splitting Plan 1 into Phase A (per-sub-command Layer 0/0b) and Phase B (selective body retention) for reduced implementation risk
5. **TESTING**: Audit existing heredoc tests for assertions about body content exclusion that will break when interpreter bodies are retained
6. **PERFORMANCE**: Add a simple benchmark comparing command processing time before/after moving `split_commands()` earlier
7. **PLAN 2**: Add input validation before `glob.glob()` calls to prevent pathological patterns

### Items Confirmed as Non-Issues

- Multiple heredocs on one line (fail-closed, correct behavior)
- `_STRING_LITERAL_PATTERN` backslash handling (correct for interpreter payload context)
- `env -S` edge case (fail-closed, correct behavior)
- Here-string (`<<<`) handling (already handled correctly)
- Integration coherence between the two plans (complementary, no conflicts)
- Subsumption of `interpreter-heredoc-bypass.md` (valid, Plan 1's mechanism is more comprehensive)
