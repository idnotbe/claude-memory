# Phase 4 Verification — Round 2 (Adversarial)

**Verifier:** Opus 4.6 (1M context)
**Cross-model:** Gemini 3 Pro Preview
**Date:** 2026-03-21
**Verdict:** PASS WITH CONCERNS

## Test Execution

All 27 tests pass, 1 expected warning (Phase 0 cleanup python3 -c trade-off):

```
27 passed, 1 warning in 0.04s
```

---

## A. Pattern Evasion Analysis

### A1. Future SKILL.md commands evading tests
**Severity: Negligible**
The tests are CI regression gates — they run against the proposed SKILL.md state. Any new bash command is evaluated before merge. This is exactly how static analysis gates are designed to work.

### A2. Embedded Guardian patterns vs actual patterns — DIFF RESULTS
Compared `test_regression_popups.py` embedded patterns against `/home/idnotbe/projects/claude-code-guardian/assets/guardian.default.json`:

**Block patterns (4 of 18 embedded):**
- `claude_deletion` — EXACT MATCH
- `find_delete` — EXACT MATCH
- `interpreter_deletion` (os.remove etc.) — EXACT MATCH
- `pathlib_unlink` — EXACT MATCH

**Not embedded (correctly omitted — irrelevant to memory plugin):** root deletion, git deletion, archive deletion, git push --force, git filter-branch, git reflog, shred, curl|wget pipe, fork bomb, command substitution deletion, backtick substitution deletion, eval deletion, node interpreter deletion, perl/ruby interpreter deletion.

**Ask patterns (4 of 17 embedded):**
- `rm -rf` — EXACT MATCH
- `find -exec delete` — EXACT MATCH
- `xargs delete` — EXACT MATCH
- `mv .claude` — **SUBSET**: Test uses `mv\s+['"]?(?:\./)?\.claude`, Guardian uses `mv\s+['"]?(?:\./)?\.(?:env|git|claude)`. Functionally correct (memory plugin only touches `.claude`), but the narrower pattern could miss a hypothetical future SKILL.md command moving `.env`.

**Not embedded (correctly omitted):** Windows del, Remove-Item, git reset --hard, git clean, git checkout --, git stash drop, git push --force-with-lease, git branch -d, truncate, mv CLAUDE.md, mv outside project, SQL patterns.

### A3. Dynamic permissionDecision construction
**Severity: Negligible**
The AST scan flags any non-constant value as `DYNAMIC`, which fails `test_only_allow_or_deny`. String concatenation (`"as" + "k"`) produces a `BinOp` AST node, not a `Constant`, so it IS caught. The regex fallback's 200-char window is belt-and-suspenders for a first-party codebase where adversarial obfuscation is not the threat model.

---

## B. False Sense of Security

### B1. Guardian check_interpreter_payload() not tested
**Severity: Low (Accepted Risk)**
Guardian's Layer 3/4 logic extracts `python3 -c` payloads and scans for destructive APIs independently of the regex block patterns. The Phase 0 cleanup command (`python3 -c "...os.remove(f)..."`) would trigger:
1. `check_interpreter_payload()` detects `os.remove` in payload
2. `is_delete_command()` returns True
3. `extract_paths()` can't resolve glob targets → `sub_paths=[]`
4. F1 safety net: `("ask", "Detected delete but could not resolve target paths")`

The tests correctly verify the block regex doesn't match (no unconditional denial). The F1 safety net ask is a known trade-off documented in the test comments and action plan Phase 6. Replicating Guardian's extraction logic would be integration testing, not regression testing.

**Mitigation:** The `max_known = 1` cap on python3 -c + .claude instances is the correct defense — it blocks NEW instances from being added silently.

### B2. Guardian is_delete_command() F1 safety net
**Covered:** See B1 above. The F1 safety net triggers "ask" (not "deny"), producing a confirmation popup but not blocking. This is documented as an accepted trade-off.

### B3. bashPathScan interaction with memory commands
**Severity: Negligible**
Guardian's `bashPathScan` scans for `zeroAccessPaths` (`.env`, `*.pem`, `*.key`, etc.) in command arguments. Memory plugin commands reference `.claude/memory/` paths, not zero-access paths. No interaction.

---

## C. Operational Edge Cases

### C1. New SKILL.md bash commands
**Mitigated:** Tests extract ALL bash blocks (including console/terminal/zsh fenced blocks) and test each against patterns. New commands are automatically covered when added to SKILL.md.

### C2. Guardian adds new patterns — staleness risk
**Severity: Medium (maintainability concern)**
The embedded patterns are a frozen snapshot. If Guardian adds a new block pattern that matches a memory plugin command, the tests would not catch it. However:
- The tests are scoped as plugin regression tests, not Guardian integration tests
- The relevant patterns (deletion, find, interpreter) are mature and unlikely to change semantics
- The action plan Phase 6 addresses Guardian-side improvements

**Recommended mitigation:** Add an optional sync-check test that loads `guardian.default.json` from sibling directory (if present) and warns on divergence. Uses `pytest.skip()` when Guardian repo is absent.

### C3. Guard script refactoring with dynamic permissionDecision
**Mitigated:** AST analysis catches non-constant values as `DYNAMIC`. The `test_only_allow_or_deny` test rejects any value not in `{"allow", "deny"}`, including `DYNAMIC`. This covers: f-strings, concatenation, variable references, function calls.

---

## D. Test Robustness

### D1. Test execution
All 27 tests pass. Runtime: 0.04s.

### D2. Mutation testing (conceptual)
- If a guard script is modified to output "ask": `test_no_ask_in_source` catches it via AST, `test_no_ask_in_raw_text` catches it via regex, `test_only_allow_or_deny` catches it via value whitelist. Triple defense.
- If a new bash block matching a Guardian pattern is added to SKILL.md: `test_no_block_pattern_matches` or `test_no_ask_pattern_matches` catches it.
- If a new python3 -c with .claude appears in SKILL.md: `test_python3_c_with_claude_path_warning` fails hard (cap exceeded).

### D3. Fake bash block injection
Adding a hypothetical `rm -rf .claude/memory/` bash block to SKILL.md would be caught by BOTH:
- `test_no_block_pattern_matches[block:claude_deletion]`
- `test_no_ask_pattern_matches[ask:rm_recursive_force]`
- `test_no_rm_with_claude_path` (Rule 0 compliance)

---

## E. Security Review

### E1. Regex injection in embedded Guardian patterns
**Severity: Negligible**
The patterns are compile-time constants defined in the test file source code. There is no path for external input to reach `re.compile()`. Not exploitable.

### E2. TOCTOU in file reading
**Severity: Negligible**
Tests read source files once per test class (`scope="class"` fixture for bash_blocks). The files are on local filesystem and read during CI. No concurrent modification risk.

### E3. Test isolation
**Clean:** Each test class has independent fixtures. No shared mutable state. No side effects (no files written, no processes spawned). Parametrized tests are fully independent.

---

## Summary of Concerns

| # | Concern | Severity | Status | Recommended Action |
|---|---------|----------|--------|-------------------|
| 1 | mv pattern is subset of Guardian | Low | Cosmetic | Update to match Guardian exactly (P3) |
| 2 | Guardian pattern staleness | Medium | Maintainability | Add optional sync-check test with pytest.skip() (P2) |
| 3 | F1 safety net not tested | Low | Accepted | Documented in test comments + max_known=1 cap (no action) |
| 4 | Future SKILL.md commands | Negligible | By design | CI regression gate works correctly (no action) |
| 5 | Dynamic permissionDecision | Negligible | Mitigated | AST DYNAMIC detection works (no action) |

---

## Verdict: PASS WITH CONCERNS

The regression tests are well-designed for their scope (P0 plugin regression prevention). The triple-defense approach for guard scripts (AST + regex + value whitelist) and the comprehensive SKILL.md scanning are solid. Two low-priority improvements would strengthen maintainability:

1. **(P2)** Add optional Guardian pattern sync-check test (skip when repo absent)
2. **(P3)** Update mv ask pattern to match Guardian exactly

Neither concern is blocking. The F1 safety net gap is correctly scoped out as a Guardian-side issue (Phase 6 of the action plan).

**Cross-model concurrence:** Gemini 3 Pro Preview independently rated the same severity levels (negligible/low/medium) and recommended the same two mitigations.
