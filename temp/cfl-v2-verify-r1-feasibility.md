# CFL v2 Research Document -- Round 1 Verification: Feasibility + Implementation Gaps

**Verifier**: Opus 4.6 (1M context)
**Date**: 2026-03-22
**Cross-model**: Codex 5.3 (adversarial review), Gemini 3 Pro (vibe check)
**Scope**: Technical feasibility, implementation gaps, dependency validation, tool/API verification, test infrastructure reuse

---

## Methodology

1. Read the main v2 document (`research/closed-feedback-loop.md`) + 3 supporting documents
2. Cross-referenced against actual code: `hooks/hooks.json`, `plugin.json`, `.claude/plugin-dirs`, `.gitignore`, `tests/conftest.py`
3. Verified specific technical claims: staging hash, `script -e` flag, `--plugin-dir` repeatability, pydantic version, test count
4. Codex 5.3 adversarial review via clink (181s, 470K input tokens)
5. Gemini 3 Pro vibe check on verification methodology via thinkdeep

### Vibe Check on Verification Approach

Gemini 3 Pro assessed the verification approach as **well-calibrated**:
- PASS: All 5 user feedback points traceable to specific design elements
- PASS: Phase dependency graph is acyclic (1->2->3->4->5)
- PASS: Honest Limitations section matches actual capabilities
- PASS: Self-contained claim defensible with guardian-ref pinned copy
- MINOR GAP: `--plugin-dir` fallback path buried in prose, should be a decision tree
- MINOR TENSION: "Screen capture first" framing vs TUI limitation acknowledged but slightly misleading at top level

Overall assessment: verification is thorough, not overthinking. One blind spot flagged: no runtime verification (actually running the composite setup) -- acceptable for a research document review.

---

## 1. Technical Claims Verification

### 1.1 `--plugin-dir` Repeatability

**[OK]** CONFIRMED. From `claude --help`:
```
--plugin-dir <path>  Load plugins from a directory for this session only
                     (repeatable: --plugin-dir A --plugin-dir B) (default: [])
```

The document's Phase 2 spike test for `--plugin-dir` repeatability (Section 14.3, Open Question #1) is already answered. The composite symlink directory fallback is unnecessary.

**Impact**: The `--plugin-dir` decision tree in the phase-redesign document (lines 1166-1187) can be simplified. The "YES" branch is confirmed; the "NO" branch (composite symlink) can be removed from the critical path and retained only as historical note.

### 1.2 `script -e` Flag

**[OK]** CONFIRMED. `/usr/bin/script` on this system supports `-e, --return` to preserve child process exit code. The document's recommendation to use `script -e -q -c "..." output.typescript` is technically correct for this platform.

### 1.3 Staging Hash

**[OK]** CONFIRMED. Independent computation:
```python
hashlib.sha256("/home/idnotbe/projects/claude-memory".encode()).hexdigest()[:12]
# Result: 52f0f4a8baed
```
Matches the document's claim exactly. The staging dir `/tmp/.claude-memory-staging-52f0f4a8baed` is correct.

### 1.4 Pydantic Version

**[OK]** CONFIRMED. System Python has pydantic 2.12.5. The document correctly notes this makes the venv bootstrap concern moot.

### 1.5 `--bare` Flag Warning

**[OK]** CONFIRMED. From `claude --help`:
```
--bare  Minimal mode: skip hooks, LSP, plugin sync, attribution,
        auto-memory, background prefetches...
```
The document correctly warns against `--bare` (Section 9: "절대 사용 금지").

### 1.6 `--permission-mode auto`

**[OK]** CONFIRMED. The `--permission-mode` flag supports `auto` mode as claimed.

### 1.7 `--output-format stream-json`

**[OK]** CONFIRMED. Supports `text`, `json`, and `stream-json` as claimed.

---

## 2. Test Count Discrepancy

**[MINOR]** The document claims "19개 테스트 파일, 1097개 테스트 케이스" (Section 1, line 19). Actual count:

- **Test files**: 21 (not 19)
- **Test cases**: 1158 (not 1097)

Delta: +2 files, +61 tests since the document was written. This is expected drift during active development but should be noted for accuracy.

**Verification command**: `python3 -m pytest tests/ --co -q` returned "1158 tests collected".

**Impact**: Low. The requirement markers effort (Phase 3) will need to cover 1158 tests, not 1097. Approximately 5.5% more work than estimated.

---

## 3. Script + Stream-JSON Interference

**[ISSUE]** The document proposes wrapping `claude -p --output-format stream-json` inside `script -e -q -c "..."` (Phase 1, Section 1.3.3, and Phase 2 runner design).

**Problem**: `script` creates a PTY (pseudo-terminal) wrapper. This has three consequences:
1. **CRLF injection**: PTY output gets `\r\n` line endings instead of `\n`
2. **Script wrappers**: The typescript file gets `Script started...`/`Script done...` prologue/epilogue
3. **stderr/stdout merging**: PTY captures both stdout and stderr into a single stream

If `script` wraps the entire `claude -p --output-format stream-json` invocation, the `stream-json` output (which is the primary machine-readable evidence channel) will be contaminated. JSON parsing will fail or produce incorrect results.

**Source**: Codex 5.3 adversarial review, independently verified.

**Fix**: Separate the captures into two runs or split the capture mechanism:
```bash
# Primary: clean machine-readable capture (NO script wrapper)
claude -p "$PROMPT" --output-format stream-json \
  --plugin-dir A --plugin-dir B \
  --permission-mode auto \
  >output.json 2>stderr.txt

# Secondary (optional): PTY capture for debugging
script -e -q -c "claude -p '$PROMPT' --plugin-dir A --plugin-dir B" stdout-raw.txt
```

Alternatively, use `script` only for the `stdout-raw.txt` auxiliary file, and capture `stream-json` through normal pipe/redirect.

**Severity justification**: ISSUE (not BLOCKER) because the Phase 2 runner code is conceptual pseudocode, not yet implemented. The fix is straightforward and can be incorporated during implementation.

---

## 4. Guardian Pinned Copy Provenance

**[ISSUE]** The document proposes `evidence/guardian-ref/` as a pinned copy of Guardian with a `VERSION` file. However:

1. No mechanism defined for tracking upstream Guardian commit SHA
2. No freshness check or update procedure
3. No way to detect if the pinned copy has drifted from the upstream Guardian that the real ops environment uses

**Source**: Codex 5.3 and Gemini 3 Pro both flagged this independently.

**Risk**: The CFL loop could validate against a stale Guardian and either miss real ops regressions or invent false ones.

**Fix options** (in order of preference):
1. **Git submodule**: `git submodule add <guardian-repo> evidence/guardian-ref` -- automatic version tracking, reproducible
2. **Pinned copy + SHA file**: Keep the current approach but add `evidence/guardian-ref/UPSTREAM_SHA` with the Guardian repo's commit hash, plus a script to check freshness: `git -C <guardian-repo> rev-parse HEAD` vs contents of `UPSTREAM_SHA`
3. **Bootstrap download**: `evidence/bootstrap.py` clones a specific Guardian tag/commit at runtime

The document recommends Option B (pinned copy) citing simplicity. This is acceptable IF provenance tracking is added.

---

## 5. Timeline Assessment

**[ISSUE]** The 5-week timeline (Section 10) is optimistic given current repo state:

**Week 1 deliverables** (as proposed):
- Evidence schema definition + 3 scenarios
- `--plugin-dir` spike (already resolved -- see Finding 1.1)
- Guardian + Memory co-load spike
- Guardian pinned copy preparation
- `.claude/guardian/config.json` creation
- `.gitignore` update
- Minimal runner (1 scenario)
- Manual checklist draft

**Current repo state** vs proposed:
| Item | Status |
|------|--------|
| `evidence/` directory | Does not exist |
| `.claude/plugin-dirs` dogfood entries | Not configured (only `vibe-check`) |
| `.claude/guardian/config.json` | Does not exist |
| `.gitignore` CFL rules | Not added |
| Guardian pinned copy | Not prepared |
| Evidence schemas | Not defined |
| Runner script | Not started |
| Requirement markers on 1158 tests | Not started |

**Assessment**: Weeks 1-3 (Phases 1-3) are achievable but tight. Weeks 4-5 (Phases 4-5: gap-to-action pipeline + manual improvement loops) are optimistic. The manual loop requires at least 3 successful iterations, each involving a full fix cycle.

**Source**: Codex 5.3 estimated 6-8 weeks for Phases 1-3 alone, 8-10+ weeks total.

**Recommendation**: Split into two milestones:
- Milestone 1 (Weeks 1-4): Phases 1-3 (evidence, runner, coverage)
- Milestone 2 (Weeks 5-8): Phases 4-5 (gap pipeline, manual/ralph loops)

---

## 6. Cost Estimation

**[MINOR]** The $5/iteration cap for Phase 5 ralph loop (Section 6.5, line 325) may be too low.

The cost table (Section 12) prices Tier 2 scenario execution but not the expensive step: the `claude -p` model-edit attempt itself. A scope-bounded code fix prompt with file reading, editing, and test execution could easily consume $3-5 of API cost before quality gates even run.

**Recommendation**: Separate generation cost from verification cost. Budget $3-5 for the model-edit attempt + $1-2 for quality gate verification = $5-7 per iteration realistic. The $25 total cap may need to be $35-50.

---

## 7. Phase Dependencies

**[OK]** Phase dependency ordering is correct and acyclic:

```
Phase 1 (Evidence Contract) -- no dependencies
  -> Phase 2 (Recursive Self-Testing) -- depends on Phase 1 schemas
    -> Phase 3 (Traceability + Coverage) -- depends on Phase 2 results
      -> Phase 4 (Gap-to-Action) -- depends on Phase 3 coverage report
        -> Phase 5 (Manual/Ralph Loop) -- depends on Phases 2-4
```

The document correctly merged v1's circular Phase 3/4 dependency into a single Phase 3 (Codex finding, acknowledged in Section 7.2, item 10).

---

## 8. Hooks.json Verification

**[OK]** The document's hook registration table (recursive-arch Section 2.3) matches the actual `hooks/hooks.json` exactly:

| Hook Event | Script | Timeout | Document | Actual |
|-----------|--------|---------|----------|--------|
| Stop | memory_triage.py | 30s | Match | Match |
| PreToolUse:Write | memory_write_guard.py | 5s | Match | Match |
| PreToolUse:Bash | memory_staging_guard.py | 5s | Match | Match |
| PostToolUse:Write | memory_validate_hook.py | 10s | Match | Match |
| UserPromptSubmit | memory_retrieve.py | 15s | Match | Match |

---

## 9. Plugin Manifest Verification

**[OK]** The document's plugin manifest summary (recursive-arch Section 2.2) matches `plugin.json` exactly:
- Name: claude-memory v5.1.0
- Commands: 3 (memory, memory-config, memory-save)
- Agents: 1 (memory-drafter)
- Skills: 2 (memory-management, memory-search)

---

## 10. Conftest Fixtures Reuse

**[OK]** The document claims reuse of existing fixtures: `memory_root`, `memory_project`, `write_memory_file`, `write_index`, `bulk_memories`. All verified present in `/home/idnotbe/projects/claude-memory/tests/conftest.py`.

Additionally, the conftest provides 6 factory functions (`make_decision_memory`, `make_preference_memory`, `make_tech_debt_memory`, `make_session_memory`, `make_runbook_memory`, `make_constraint_memory`) that cover all 6 memory categories. These are directly usable for Phase 2 scenario fixtures.

The `FOLDER_MAP` dictionary and `build_enriched_index` function can be reused for generating test index files in the CFL workspace.

---

## 11. Evidence Directory

**[OK]** The `evidence/` directory does not exist yet. This is expected -- the document describes it as infrastructure to be created during Phase 1, Week 1. Not a gap; it is a planned deliverable.

---

## 12. `.claude/plugin-dirs` State

**[MINOR]** Currently only contains `~/projects/vibe-check`. The document (recursive-arch Section 5.1) proposes adding `~/projects/claude-memory` (self) and `~/projects/claude-code-guardian`.

This is a Phase 0 prerequisite, not yet executed. The document correctly identifies this as an action item, not as current state.

**Note**: The `.claude/plugin-dirs` file is used by `ccyolo` (a bash function), not by `claude` directly. For CFL's `claude -p` invocations, `--plugin-dir` flags are passed directly. So `.claude/plugin-dirs` modification is only needed for interactive dogfood sessions, not for the automated runner.

---

## 13. Composite Symlink Directory -- Unnecessary

**[MINOR]** The document maintains a fallback design for composite symlink directories in `/tmp/` (phase-redesign lines 1166-1187). Since `--plugin-dir` is confirmed repeatable (Finding 1.1), this fallback adds complexity for no benefit.

**Recommendation**: Promote `--plugin-dir A --plugin-dir B` as the only supported path. Remove the composite symlink fallback from the main design. Keep it as a historical note if desired.

**Source**: Codex 5.3 agreed: "this fallback adds unsupported discovery assumptions and possible `$CLAUDE_PLUGIN_ROOT` confusion for no benefit."

---

## 14. Codex False Positive: `memory-save.md` Path Drift

**[OK -- Codex finding rejected]** Codex 5.3 flagged that `commands/memory-save.md` uses `/tmp/.memory-write-pending.json` while the staging system uses `/tmp/.claude-memory-staging-*`, calling this "path drift."

**Verification**: This is intentionally two separate, coexisting paths:
- `/tmp/.memory-write-pending.json` -- used by the **manual** `/memory:save` command (user-initiated one-off saves)
- `/tmp/.claude-memory-staging-<hash>/` -- used by the **automated** triage/Phase 1 flow (Stop hook -> memory-drafter agents)

Both paths are explicitly allowed in `memory_write.py` (line 1557-1562) and `memory_write_guard.py` (line 82-86). This is not drift; it is intentional separation of manual and automated save flows.

---

## 15. `.gitignore` Gap

**[MINOR]** The current `.gitignore` does not exclude:
- `.claude/memory/*.json` (memory data files)
- `.claude/guardian/` (guardian config if created)
- `.claude/cfl-data/` (CFL data collection directory)
- `evidence/runs/` (run results with potentially large artifacts)

The document (recursive-arch Section 0.3) correctly identifies these as Phase 0 prerequisites. Not yet executed.

---

## 16. Stop Hook Behavior: `--print` Mode

**[OK]** The document claims (Section 9) that all 4 hook types fire in `--print` mode (verified on v2.1.81). This is a critical foundation for Phase 2's `claude -p` based runner. The claim is asserted as "실증 확인" (empirically verified) with specific method (log file creation). Accepted.

The document also correctly warns against `--bare` which skips hooks entirely.

---

## 17. Meta-Validation Design (SCN-META-001)

**[OK]** The known-bad-build scenario is well-designed. Injecting a syntax error into triage and verifying FAIL verdict is a standard harness-trust technique. The acceptance criterion "이 시나리오가 PASS하면 러너에 버그가 있는 것" (if this scenario PASSES, the runner has a bug) is the correct framing.

---

## 18. Cross-Plugin Hook Interaction Model

**[OK]** The document's claim that "if ANY hook returns deny, the write is denied" (recursive-arch Section 3.3) matches Claude Code's documented behavior. The hook interaction matrix (Appendix B) correctly identifies:
- Stop: RACE between triage and auto-commit (mitigated by disabling auto-commit)
- PreToolUse:Write: CONFLICT on /tmp staging (mitigated by allowlist)
- All others: independent, no conflict

---

## Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| 1.1 | `--plugin-dir` repeatable | OK | Confirmed, spike resolved |
| 1.2 | `script -e` available | OK | Confirmed |
| 1.3 | Staging hash correct | OK | Confirmed (52f0f4a8baed) |
| 1.4 | Pydantic 2.12.5 in system | OK | Confirmed |
| 1.5 | `--bare` skips hooks warning | OK | Confirmed |
| 1.6 | `--permission-mode auto` | OK | Confirmed |
| 1.7 | `--output-format stream-json` | OK | Confirmed |
| 2 | Test count: 1158 not 1097 | MINOR | +61 tests since doc written |
| 3 | script + stream-json interference | ISSUE | PTY contaminates JSON; split captures |
| 4 | Guardian pinned copy provenance | ISSUE | No upstream SHA tracking or freshness check |
| 5 | 5-week timeline optimistic | ISSUE | Recommend 8-week split into 2 milestones |
| 6 | $5/iteration cost cap too low | MINOR | Recommend $5-7/iteration, $35-50 total |
| 7 | Phase dependencies acyclic | OK | Correct ordering confirmed |
| 8 | hooks.json matches document | OK | All 5 hooks verified |
| 9 | plugin.json matches document | OK | All fields verified |
| 10 | Conftest fixtures reusable | OK | All claimed fixtures present |
| 11 | evidence/ not yet created | OK | Expected (Phase 1 deliverable) |
| 12 | plugin-dirs not yet configured | MINOR | Phase 0 prerequisite, not yet executed |
| 13 | Composite symlink unnecessary | MINOR | --plugin-dir repeatable, simplify design |
| 14 | memory-save.md path (Codex claim) | OK | Intentional dual-path design, not drift |
| 15 | .gitignore not yet updated | MINOR | Phase 0 prerequisite, not yet executed |
| 16 | Stop hook in --print mode | OK | Empirically verified claim accepted |
| 17 | Meta-validation design | OK | Sound harness-trust technique |
| 18 | Cross-plugin hook interaction | OK | Correct model, mitigations identified |

### Blocker Count: 0
### Issue Count: 3 (script interference, Guardian provenance, timeline)
### Minor Count: 5 (test count, cost cap, plugin-dirs, composite fallback, gitignore)
### OK Count: 13

---

## Cross-Model Validation Summary

### Codex 5.3 (adversarial, 181s)
**Accepted findings**:
- script + stream-json interference (Finding 3) -- independently verified
- Guardian pinned copy needs provenance (Finding 4) -- agreed
- 5-week timeline optimistic (Finding 5) -- agreed, recommended 8-10+ weeks
- Composite symlink unnecessary (Finding 13) -- agreed
- $5/iteration too low (Finding 6) -- agreed

**Rejected findings**:
- `memory-save.md` path drift claim (Finding 14) -- verified as intentional dual-path design

**Positive assessments preserved**:
- Honest Limitations section is strong
- Meta-validation scenario is the right instinct
- Manual-first gate before automation is the right maturity model

### Gemini 3 Pro (vibe check)
**Assessment**: Verification approach is well-calibrated and thorough.
**Blind spot flagged**: No runtime verification (acceptable for document review phase).
**Minor gap**: `--plugin-dir` fallback path should be a clearer decision tree.

---

## Recommendations for Document Update

1. **Update test count**: 1097 -> 1158 (19 files -> 21 files)
2. **Split capture strategy**: Add explicit note that `script` wrapping and `stream-json` capture must be separate invocations
3. **Add Guardian provenance**: Define upstream SHA tracking mechanism for `evidence/guardian-ref/`
4. **Simplify --plugin-dir**: Remove composite symlink fallback from critical path; the flag is confirmed repeatable
5. **Adjust timeline**: 5 weeks -> 8 weeks, split into 2 milestones
6. **Adjust cost cap**: $5/iteration -> $5-7/iteration, $25 total -> $35-50 total
7. **Resolve --plugin-dir spike**: Mark Open Question #1 (Section 14.3) as RESOLVED
