# CFL Verification R1: Feasibility + Gap Analysis

Reviewer: Opus 4.6 | Date: 2026-03-22 | Perspective: Feasibility + Gap Analysis

---

## 1. The `claude --print` vs pexpect Debate: RESOLVED

**Empirical finding: `claude -p` fires ALL four hook types.**

Tested against Claude Code v2.1.81 with isolated test directories:

| Hook Type | Fires in `--print` mode? | Verified |
|-----------|--------------------------|----------|
| UserPromptSubmit | YES | Wrote to log file on every prompt |
| Stop | YES | Wrote to log file at session end |
| PreToolUse | YES | Fired before Write tool call |
| PostToolUse | YES | Fired after Write tool call |

**Resolution: pexpect/PTY harness is unnecessary.** `claude -p` with `--permission-mode bypassPermissions` (or `auto`) provides full hook coverage without the complexity of terminal emulation. The Gemini concern about hooks not firing in non-interactive mode is empirically disproven.

**Important nuance:** The `--bare` flag explicitly "skip[s] hooks, LSP, plugin sync." Tests MUST NOT use `--bare`. The `--plugin-dir` flag can load plugins from a specific directory per session, which is useful for testing modified plugin copies without polluting the installed plugin.

**Implication for synthesis:** The proposed test harness simplifies dramatically. A pytest fixture wrapping `subprocess.run(["claude", "-p", ...])` with `--plugin-dir` is sufficient for full E2E coverage.

---

## 2. Is the 5-Phase Approach Feasible Given the Existing Codebase?

**Yes, with caveats.**

### What exists and is reusable

- **1,095 unit/integration tests** across 19 test files already cover all Python scripts at the function level.
- `conftest.py` provides 6 memory factory functions (`make_decision_memory`, `make_preference_memory`, etc.), filesystem fixtures (`memory_root`, `memory_project`), index builder (`build_enriched_index`, `write_index`), and bulk memory generation (500 entries for benchmarks).
- Every script has its own test file with comprehensive coverage including adversarial inputs and regression tests.

### What the proposed phases map to

| Proposed Phase | Feasible? | Notes |
|----------------|-----------|-------|
| Phase 1: Evidence Contract | YES | Schema already exists in Pydantic models. Just needs a scenario run output schema. |
| Phase 2: Minimal Loop | YES | `claude -p` + `--plugin-dir` + `--permission-mode bypassPermissions` + temp directory isolation. pytest subprocess fixture. |
| Phase 3: Cross-Repo Promotion | CAUTIOUS | Requires a second repo (the "consumer" repo). Works but adds CI complexity. Start without it. |
| Phase 4: Req Traceability | YES | PRD sections map cleanly to test modules. pytest markers are the right mechanism. |
| Phase 5: Ralph/Auto-fix Loop | DEFER | Shadow Loop (patch generation) is sensible, but premature until Phases 1-2 prove stable. |

### Feasibility risks

1. **Cost per E2E run**: Each `claude -p` call with hooks costs API tokens. A full scenario exercising the save flow (triage -> 5-phase -> write) triggers multiple model calls internally (drafter subagents, verification subagents, save subagent). Budget: ~$0.50-2.00 per save-flow scenario. Must batch strategically.
2. **Test duration**: A single save-flow E2E test takes 30-120 seconds (subagent spawns, hook timeouts). Full suite of 20 scenarios = 10-40 minutes. Acceptable for CI but not for developer iteration.
3. **Non-determinism**: LLM-driven phases (Phase 1 drafting, Phase 2 verification) produce variable outputs. Tests must assert on structural outcomes (file created, correct category, valid schema) not exact content.

---

## 3. PRD Requirements NOT Coverable by pytest Alone

These requirements MUST have live session verification because they depend on Claude Code's runtime behavior (hook dispatch, subagent orchestration, SKILL.md interpretation):

### Hard live-session requirements

| PRD Section | Requirement | Why pytest cannot cover |
|-------------|-------------|------------------------|
| 3.1.1 | Stop hook triage fires on session end and blocks stop | Requires actual stop event dispatch from Claude Code |
| 3.1.2 | 5-phase save orchestration (SKILL.md) | SKILL.md is LLM-interpreted; subagent spawning is Claude Code internal |
| 3.1.3 | CUD resolution with L1+L2 combination | L2 comes from LLM subagent intent; unit tests cover L1 only |
| 3.2.1 | UserPromptSubmit injects memories into context | Requires Claude Code's hook-to-context injection pipeline |
| US-1 | Auto-capture produces correct memories for realistic conversations | Requires full transcript -> triage -> save -> verify pipeline |
| US-2 | Injected memories influence Claude's responses | Requires LLM actually reading injected context |
| US-3 | Save confirmation on next session | Requires multi-session sequence (save -> new session -> confirm) |
| US-4 | Orphan crash detection | Requires interrupted session state |
| 4.1 | No approval popups / minimal screen noise | Requires Guardian interaction observation |
| 4.1 | Guardian compatibility | Structural (agent file `tools:`) + runtime (Guardian pattern matching) |
| 6.1 | Stop hook re-fire prevention | Requires actual double-stop scenario |

### Coverable by pytest (no live session needed)

Everything else in the PRD -- schema validation, FTS5 search, index operations, candidate selection, draft assembly, config parsing, sanitization, path security, OCC, FlockIndex, rolling window, logging -- is already tested or testable with pure Python unit/integration tests.

**Ratio: ~11 requirement areas need live sessions out of ~40+ total.** The synthesis document's instinct to keep most verification in Tier 1 (pytest) is correct.

---

## 4. Existing Test Infrastructure Reusable for CFL

### Directly reusable from conftest.py

| Fixture/Helper | CFL Use |
|----------------|---------|
| `make_*_memory()` (6 factories) | Seed memory state before E2E scenarios |
| `memory_root` / `memory_project` fixtures | Create isolated test workspaces |
| `write_memory_file()` | Pre-populate memories for retrieval tests |
| `write_index()` / `build_enriched_index()` | Pre-build index for retrieval scenarios |
| `bulk_memories` fixture (500 entries) | Performance/scale scenarios |
| `FOLDER_MAP` constant | Category-to-folder mapping |

### Needs to be built

| Component | Purpose |
|-----------|---------|
| `claude_session()` fixture | Wraps `subprocess.run(["claude", "-p", ...])` with `--plugin-dir`, `--permission-mode`, timeout, output capture |
| Workspace isolation fixture | Creates temp project dir with `.claude/memory/` + copies plugin under test + sets up config |
| Multi-turn session fixture | Chains multiple `claude -p` calls against same workspace (for save -> confirm scenarios) |
| Scenario registry | YAML/JSON files defining prompt + expected signals (files created, index entries, hook outputs) |
| Deterministic oracle helpers | Assert on filesystem state (file exists, valid JSON, correct category) rather than LLM output content |

---

## 5. Hidden Dependencies and Circular References

### Identified dependency chain

```
claude -p invocation
  -> Claude Code loads plugin (hooks.json + SKILL.md)
    -> Hook scripts read memory-config.json
      -> Scripts read/write .claude/memory/ filesystem
        -> SKILL.md orchestration spawns subagents
          -> Subagents call memory_write.py
            -> memory_write.py may re-exec under .venv
```

### Potential circular/problematic references

1. **Plugin venv dependency**: `memory_write.py` re-execs under `~/.claude/plugins/claude-memory/.venv`. If the test copies the plugin to a temp `--plugin-dir`, the venv path breaks because it is resolved relative to the installed plugin root, not the test copy. **Mitigation**: Either symlink the venv, set `CLAUDE_PLUGIN_ROOT` explicitly, or ensure pydantic is in the system Python.

2. **Global state contamination**: The `.claude/.stop_hook_active` flag and `.staging/.triage-handled` sentinel persist between test runs if cleanup fails. The 5-minute TTL on the stop flag means sequential E2E tests within 5 minutes may see stale flags. **Mitigation**: Workspace isolation per test (tmp_path) fully prevents this since each test gets its own `.claude/` directory.

3. **Transcript path coupling**: The triage hook reads `transcript_path` from stdin. In `--print` mode, the transcript location is determined by Claude Code internals (typically `~/.claude/projects/*/sessions/*/transcript.jsonl`). Tests cannot easily control or predict this path. **Mitigation**: For triage testing, call `memory_triage.py` directly with crafted input (already done in unit tests). For full E2E, accept that transcript path is opaque and verify outcomes only.

4. **No circular references detected** in the proposed loop design. The flow is strictly: scenario prompt -> hook dispatch -> script execution -> filesystem mutation -> oracle verification. The "promotion" from repo B to repo A is unidirectional.

---

## 6. Show-Stoppers

**None found.** The approach is feasible. Key risk mitigations:

1. Use `claude -p` (confirmed working) instead of pexpect -- eliminates the largest technical uncertainty.
2. Keep Tier 1 (pytest unit/integration) as the primary verification layer (1,095 tests already exist).
3. Build Tier 2 (live E2E) incrementally, starting with 3-5 critical scenarios (triage fires, retrieval injects, save completes).
4. Solve the venv path issue before first E2E test (symlink or env var override).
5. Budget ~$5-10/CI run for live E2E scenarios (10-20 scenarios at $0.25-0.50 each after optimizing prompt length).

---

## 7. Recommended Phase 1 Starter Scenarios

Highest-value live session tests to build first:

1. **Retrieval injection**: Seed 3 memories, run `claude -p "What do you know about JWT authentication?"`, verify response references seeded memory content.
2. **Triage trigger**: Run `claude -p` with a prompt that produces a conversation matching DECISION keywords, verify triage-data.json appears in staging.
3. **Write guard**: Run `claude -p "Write a file to .claude/memory/decisions/test.json"`, verify the write is blocked (guard returns deny).
4. **Full save flow**: Trigger triage -> let 5-phase orchestration complete -> verify memory JSON file created with valid schema.
5. **Multi-session confirmation**: After save flow, start new `claude -p` session -> verify save confirmation message appears in output.
