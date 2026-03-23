---
status: done
progress: "All phases complete (0-5). 8 compile checks OK. 1455 tests passed (21 pre-existing failures). Ready for deployment."
---

# Architecture Simplification -- Action Plan (v2)

**Last Updated**: 2026-03-22
**Review Basis**: 9 independent perspectives, 2 verification rounds, 3 external models (Codex 5.3, Gemini 3.1 Pro, Gemini 2.5 Pro)
**Estimated Effort**: 2-3 days

## What Changed from the Original Proposal

The original action plan (v1) proposed collapsing the 5-phase save orchestration to 3 phases. A multi-round review with 9 perspectives revealed:

1. **`memory_orchestrate.py` already exists (387 lines)** -- it implements Phase 1.5 deterministically (collect, candidate, CUD, draft, deletes, manifest). The plan to create `memory_commit.py` from scratch is unnecessary; we extend the existing orchestrator instead.
2. **`memory_detect.py` is vestigial** -- after V-R1/R2 fixed candidate selection ordering, SETUP is trivial (cleanup + parse). No new detection script is needed.
3. **Option B (per-category drafters) is decided** -- battle-tested, better isolation. Option A (single drafter) remains a future optimization only.
4. **Verification is optional by default** -- Option 3 (drop verification) as default delivers the full performance benefit. Config flag enables verification between prepare and commit for high-value categories.
5. **7 pre-implementation and implementation fixes discovered** -- C1/C2 critical bugs, H1-H6 high-priority fixes that must be incorporated.
6. **Performance target adjusted** -- 4-8 min (not 3-8 min) based on realistic Phase 1 DRAFT timing.
7. **Guardian compatibility is inherently solved** -- Python subprocess calls from the orchestrator are invisible to Guardian. This is a benefit, not a gap.

---

## 1. Current Architecture Problems

| Problem | Root Cause | Impact |
|---------|-----------|--------|
| 17-28 min save time | 5 serial phases, 2 subagent waves (draft + verify), each with cold-start | User waits; re-fire loop triggered by TTL expiry |
| ~26 visible tool calls | Each phase has multiple Read/Write/Bash/Agent calls | Screen noise violates silent-operation principle |
| 3 subagent types | memory-drafter (Agent), verifier (Agent), saver (Task/haiku) | Complex orchestration, model compliance issues |
| Mixed execution models | Hook (deterministic) -> Skill (LLM-interpreted) -> Subagent (LLM) -> Script (deterministic) | Inconsistent error handling, hard to debug |
| Verification always-on | Phase 2 verifier spawns for every category regardless of risk | Doubles subagent cost with marginal quality improvement |
| Phase 1.5 is LLM-orchestrated but deterministic | CUD resolution, candidate selection are mechanical rules executed by LLM reading SKILL.md | Unnecessary LLM hop, error-prone, tokens wasted |
| Phase 3 haiku saver is fragile | Haiku subagent must construct heredoc Bash commands | Most fragile component; Guardian conflicts; heredoc escaping bugs |

---

## 2. Proposed Architecture: 3 Phases + Optional Verify

```
CURRENT (5 phases, 3 subagent types, 17-28 min):
  Stop hook -> SKILL.md -> Pre-Phase cleanup
    -> Phase 0 parse -> Phase 1 draft (Agent x N)
    -> Phase 1.5 CUD (main agent, LLM-interpreted)
    -> Phase 2 verify (Agent x N)
    -> Phase 3 save (Task x 1, haiku)
    -> cleanup

PROPOSED (3 phases, 1 subagent type, target 4-8 min):
  Stop hook -> SKILL.md -> SETUP (deterministic: parse triage, cleanup)
    -> Phase 1 DRAFT (Agent x N, per-category)
    -> [Phase 1.5 VERIFY -- OPTIONAL, config-controlled]
    -> Phase 2 COMMIT (deterministic: memory_orchestrate.py)
    -> cleanup
```

### SETUP (deterministic, no LLM, < 1s)

- Parse triage data from hook output (file-based `<triage_data_file>` with inline `<triage_data>` fallback)
- Clean stale intent files (`memory_write.py --action cleanup-intents`)
- Read config for parallel processing settings
- Output: categories to process, staging directory path, config

No new script needed. SKILL.md instructions handle this with existing tools.

### Phase 1: DRAFT (LLM, per-category Agent subagents)

**Option B (default, decided)**: Per-category memory-drafter Agent subagents. Each drafter has tools `Read, Write` only (no Bash), reads its `context-<CATEGORY>.txt`, and writes `intent-<CATEGORY>.json`. All categories spawn in parallel.

**Option A (future optimization only)**: Single drafter agent for all categories. Lower latency but less isolation. Not implemented in this plan.

Drafters return structured intent JSON with: `category`, `new_info_summary`, `intended_action`, `partial_content`, `lifecycle_hints`.

### Phase 1.5: VERIFY (OPTIONAL, between prepare and commit)

**Default: DISABLED** (Option 3). Pydantic schema validation + mechanical merge rules in `memory_write.py` provide sufficient quality guarantees.

**When enabled** (`triage.parallel.verification_enabled: true`): SKILL.md inserts a verification step between `--action prepare` output and `--action commit` execution. The verifier inspects **assembled draft JSON** (the correct artifact), not raw intent files.

**Risk-based triggers** (when verification is enabled, only trigger for):
- `decision` or `constraint` categories (high-value, harder to undo)
- `DELETE` or `RETIRE` operations (destructive)
- Low-confidence drafts (confidence < 0.5 in intent)

This works because the `--action prepare` / `--action commit` split (H3) naturally creates a checkpoint between draft assembly and save execution.

### Phase 2: COMMIT (deterministic, no LLM, < 30s)

Single script call: `python3 memory_orchestrate.py --staging-dir <dir> --action commit` (or `--action run` for combined prepare+commit without verification).

The orchestrator performs:

| Step | Function | Description |
|------|----------|-------------|
| 1 | `collect_intents()` | Read intent-*.json, skip NOOPs, strip markdown fences (H5) |
| 2 | `run_candidate_selection()` | Run memory_candidate.py per intent. Then read candidate file from returned path and compute MD5 hash for OCC (H4). Hash is captured HERE (step 2), not at save time (step 7), to cover the 30+ second drafting window. |
| 3 | `resolve_cud()` | Combine L1 structural + L2 intended action via CUD_TABLE |
| 4 | `execute_drafts()` | Run memory_draft.py per CREATE/UPDATE, generate target paths (H2) |
| 5 | `handle_deletes()` | Write retire JSONs for DELETE actions |
| 6 | `build_manifest()` | Orchestration result with per-category status |
| 7 | `execute_saves()` | **NEW**: sentinel -> memory_write.py calls (with --skip-auto-enforce) -> explicit enforce -> cleanup -> result file |

**Prepare/Commit Split (H3)**: The orchestrator supports three action modes:
- **No `--action` flag (default, backward-compatible)**: Runs steps 1-6 only and writes manifest. This preserves the current behavior exactly -- existing SKILL.md v5 calls `memory_orchestrate.py --staging-dir <dir>` without `--action` and expects steps 1-6 only.
- `--action prepare`: Alias for the no-flag default. Runs steps 1-6, writes manifest with assembled drafts and OCC hashes. Outputs full JSON manifest to stdout (same as no-flag default). SKILL.md can then optionally run verification before proceeding.
- `--action commit`: Reads the manifest from `orchestration-result.json` in staging dir, runs step 7 only (save execution). Uses OCC hashes captured at step 2 time. Accepts optional `--exclude-categories cat1,cat2` to skip categories vetoed by verifiers.
- `--action run`: Runs steps 1-7 sequentially (used when verification is disabled -- the common case).

**Verification Data Contract**: When verification is enabled, the flow is:
1. SKILL.md calls `--action prepare` -> manifest written to `<staging_dir>/orchestration-result.json`
2. SKILL.md reads the manifest, identifies risk-eligible categories, spawns verifiers per category
3. Each verifier reads the assembled draft file (path in `manifest.categories.<cat>.draft_path`) and outputs a verdict: `PASS`, `BLOCK` (hallucination detected), or `REVISE` (minor quality issue, advisory only)
4. SKILL.md collects verdicts. For any `BLOCK` verdict, adds that category to the exclude list
5. SKILL.md calls `--action commit --exclude-categories <blocked_cats>` -> step 7 skips excluded categories
6. Blocked categories are recorded in `last-save-result.json` with `status: "blocked_by_verifier"` and reason

This ensures verification is **controlling**, not merely observational.

---

## 3. Pre-Implementation Fixes (Phase 0 of This Plan)

These are latent bugs that would be amplified by batch orchestration. Must be fixed BEFORE extending the orchestrator.

### C1: `do_create()` Silently Overwrites Active Files (CRITICAL)

**Location**: `memory_write.py:1043`
**Problem**: `do_create()` only checks for recently-retired targets (anti-resurrection). If the target path already has an active file, it overwrites without error. In batch orchestration, a slug collision or replayed CREATE destroys an existing memory.
**Fix**: Fail if target exists and `record_status == "active"`. Only allow overwrite for idempotent replay (same content hash).
**Found by**: Codex (final review)

- [ ] Add active-file existence check to `do_create()`
- [ ] Allow idempotent replay (same content hash bypass)
- [ ] Add test: CREATE on existing active file -> error
- [ ] Add test: CREATE idempotent replay -> success

### C2: `add_to_index()` Has No Path Deduplication (CRITICAL)

**Location**: `memory_write.py:430`
**Problem**: Blindly appends and sorts. Partial failure retry creates duplicate index entries for the same path. Corrupts FTS5 index syncing and candidate retrieval.
**Fix**: Strip existing entry for the same `rel_path` before appending (reuse `remove_from_index()` logic). ~5 lines of code.
**Found by**: Adversarial R2, confirmed by Codex + Gemini

- [ ] Add path deduplication to `add_to_index()` before append
- [ ] Add test: duplicate path in index -> deduplicated
- [ ] Add test: partial failure retry -> no duplicate entries

### H1: Double Enforcement via `--skip-auto-enforce` Flag (HIGH)

**Location**: `memory_write.py:1072`
**Problem**: `do_create()` auto-spawns `memory_enforce.py` after `session_summary` CREATE. Explicit enforce call in orchestrator runs enforcement twice, adding unnecessary latency.
**Fix**: Add `--skip-auto-enforce` flag to `memory_write.py`. Orchestrator passes this flag, then runs enforce exactly once at the end.
**Found by**: Devil's Advocate R1, Practitioner R1, confirmed by both external models

- [ ] Add `--skip-auto-enforce` CLI flag to `memory_write.py`
- [ ] Wire flag into `do_create()` to suppress auto-enforcement
- [ ] Add test: create with `--skip-auto-enforce` -> no enforce spawned
- [ ] Add test: create without flag -> enforce still auto-spawns (regression)

---

## 4. Implementation Plan

### Phase 1: Design (1-2 hours)

Design decisions that must be resolved before coding.

- [ ] **D1: Orchestrator action modes** -- Define CLI interface for `--action prepare`, `--action commit`, `--action run`. Decide argument passing (manifest file path between prepare and commit).
- [ ] **D2: Save execution function signature** -- Design `execute_saves(manifest, staging_dir, memory_root, skip_enforce)` with sentinel management, OCC hash passing, per-category error tracking.
- [ ] **D3: Failure path contract** -- On partial failure: which categories succeeded? Preserve staging, write `.triage-pending.json` with failed categories listed. Define the JSON schema for this file. The `.triage-pending.json` file is read by `memory_retrieve.py` (the retrieval hook) to display "pending save" notifications to the user on the next session start. Schema must be compatible with the retrieval hook's existing parsing logic.
- [ ] **D4: Result file contract** -- Define `last-save-result.json` schema including `session_id` preservation (M2). The retrieval hook (`memory_retrieve.py`) uses this file for three purposes: (1) save confirmation display on next session (Block 1), (2) orphan detection when triage-data exists without a result (Block 2), (3) same-session re-triage suppression via `session_id` matching. The schema must preserve all three contracts.
- [ ] **D5: Venv bootstrap strategy (H6)** -- `memory_orchestrate.py` currently has no pydantic dependency (stdlib only). Save execution (step 7) calls `memory_write.py` via subprocess, which handles its own venv bootstrap. But H2 requires importing `slugify()` from `memory_write.py`. Decision: add venv bootstrap at the **very top of the script** (before any imports from sibling modules), matching the `memory_draft.py` pattern (lines 23-30). The bootstrap must NOT be lazy/mid-pipeline — `os.execv()` replaces the process entirely, so triggering it mid-pipeline discards all accumulated state. Bootstrap is **mode-gated**: only triggers when `--action run` or `--action commit` is used (steps needing pydantic). No-flag default (steps 1-6 only) remains stdlib-only. After bootstrap, `slugify` and `CATEGORY_FOLDERS` can be safely imported from `memory_write.py`.
- [ ] **D6: OCC hash timing (H4)** -- Hash captured at step 2, AFTER `memory_candidate.py` subprocess returns. The orchestrator reads the candidate file at `candidates[cat]["candidate"]["path"]` and computes `hashlib.md5(file_bytes).hexdigest()`. Stored in `candidates[cat]["file_hash"]`. Passed through `resolved` dict to `build_manifest()`. In step 7, passed as `--hash` to `memory_write.py --action update`. Note: `memory_candidate.py` does NOT compute hashes — the orchestrator does a secondary read. The TOCTOU window (candidate.py read → orchestrator hash) is negligible in single-user CLI context.
- [ ] **D7: JSON markdown stripping (H5)** -- In `collect_intents()`, strip leading/trailing ` ```json\n` and ` ``` ` fences before `json.loads()`. Handle variations: ` ```JSON`, ` ```\n{`, trailing whitespace.
- [ ] **D8: Target path generation (H2)** -- For CREATE actions, generate `{memory_root}/{category_folder}/{slugify(title)}.json`. Import `slugify()` and `CATEGORY_FOLDERS` from `memory_write.py` (available after venv bootstrap from D5). The `CATEGORY_FOLDERS` dict in `memory_write.py` (line 67-74) maps category names to folder names (e.g., `"session_summary" -> "sessions"`, `"tech_debt" -> "tech-debt"`).
- [ ] **D9: Verification interleaving contract** -- Define the full data flow for prepare -> verify -> commit:
  1. `--action prepare` writes `orchestration-result.json` containing: per-category `{action, draft_path, candidate_path, occ_hash, target_path}`.
  2. SKILL.md reads the manifest, identifies categories eligible for verification (decision/constraint categories, DELETE/RETIRE actions, confidence < 0.5).
  3. For each eligible category, SKILL.md spawns a verifier Agent that reads the assembled draft JSON at `draft_path` and outputs a verdict: `PASS`, `BLOCK` (with reason), or `REVISE` (advisory).
  4. SKILL.md collects verdicts. Any `BLOCK` verdict adds that category to an exclude list.
  5. SKILL.md calls `--action commit --exclude-categories <comma-separated-blocked>`.
  6. `--action commit` reads the manifest, skips excluded categories, executes saves for the rest. Blocked categories are recorded in `last-save-result.json` with `status: "blocked_by_verifier"`.
  This contract must be documented in SKILL.md and tested in Phase 4.

### Phase 2: Extend memory_orchestrate.py (1 day)

All changes to the existing `memory_orchestrate.py` (387 lines).

- [ ] **Step 2.1: Venv bootstrap** -- Add unconditional venv bootstrap at the **very top** of the script (copy from `memory_draft.py` lines 23-30). The bootstrap is a no-op when pydantic is already available (including global installs), so it is safe to run unconditionally for all action modes. This avoids fragile `sys.argv` peeking (which fails on `--action=commit` equals form). After bootstrap, `slugify` and `CATEGORY_FOLDERS` are imported from `memory_write.py` inside `main()` only when needed (steps 4 and 7). The no-flag default (steps 1-6) still works if pydantic is unavailable — the import is guarded and only used in steps that generate target paths.
- [ ] **Step 2.2: JSON markdown stripping (H5)** -- Update `collect_intents()` to strip ` ```json ` / ` ``` ` fences from intent file contents before `json.loads()`. Add regex: `re.sub(r'^```(?:json|JSON)?\s*\n?', '', content)` and `re.sub(r'\n?```\s*$', '', content)`.
- [ ] **Step 2.3: OCC hash capture (H4)** -- After `run_candidate_selection()` completes, add a secondary loop: for each category with a non-None candidate, read the candidate file at `candidates[cat]["candidate"]["path"]`, compute `hashlib.md5(Path(path).read_bytes()).hexdigest()`, and store as `candidates[cat]["file_hash"]`. Pass through `resolve_cud()` into `resolved[cat]["occ_hash"]`. This ensures the hash is captured at step 2 time, not at step 7 save time.
- [ ] **Step 2.4: CREATE target path generation (H2)** -- Add function `generate_target_path(memory_root, category, title)` that calls `slugify(title)` (lazy-imported from `memory_write.py`), resolves category folder from config, returns `{memory_root}/{folder}/{slug}.json`. Call in `execute_drafts()` for CREATE actions, store in `resolved[cat]["target_path"]`.
- [ ] **Step 2.5: `--action` modes with backward compatibility** -- Add `--action` argument with choices `[prepare, commit, run]`. Default (no `--action` flag) preserves current behavior: steps 1-6 only. `prepare` is an explicit alias for this. `run` runs steps 1-7. `commit` runs step 7 only from existing manifest. Add `--exclude-categories` argument (comma-separated) for `commit` mode to skip verifier-blocked categories.
- [ ] **Step 2.6: Implement `execute_saves()` (step 7)** -- New function that performs the actual save to the memory directory. Full subprocess command details below.

  **Sentinel management** (updates the `.save-in-progress` sentinel file used by the triage hook to prevent re-fires during active saves):
  ```
  python3 memory_write.py --action update-sentinel-state --state saving --staging-dir <staging_dir>
  ```

  **Per-category save commands** -- for each resolved category with action CREATE/UPDATE/DELETE (skipping categories in `--exclude-categories` list):

  CREATE (target path must contain the full `.claude/memory/` prefix — `memory_write.py` derives memory root from `--target` via `_resolve_memory_root()`, so NO `--root` flag is needed or accepted):
  ```
  python3 memory_write.py --action create \
    --target <memory_root>/<category_folder>/<slug>.json \
    --input <staging_dir>/draft-<cat>.json \
    --category <cat> \
    --skip-auto-enforce
  ```

  UPDATE (with OCC hash from candidate selection):
  ```
  python3 memory_write.py --action update \
    --target <candidate_path> \
    --input <staging_dir>/draft-<cat>.json \
    --hash <occ_hash_from_step2> \
    --skip-auto-enforce
  ```

  DELETE/RETIRE:
  ```
  python3 memory_write.py --action retire \
    --target <candidate_path> \
    --reason "<reason_from_intent>" \
    --skip-auto-enforce
  ```

  **Note**: `memory_write.py` does NOT accept a `--root` flag. It derives the memory root from the `--target` path via `_resolve_memory_root()`. All `--target` paths must be absolute or relative paths containing the `.claude/memory/` segment.

  Each command is run via `subprocess.run(cmd, capture_output=True, text=True, timeout=30)`. Results are tracked per-category in a `save_results` dict.

  **Post-save steps**:
  1. Run `memory_enforce.py --category session_summary` exactly once (only if a session_summary was created/updated). Note: `memory_enforce.py` requires `--category` (mandatory) but does NOT accept `--root` — it resolves the memory root from the project directory. Optional: `--max-retained N` (default from config).
  2. On full success: `memory_write.py --action cleanup-staging --staging-dir <staging_dir>`
  3. On partial failure: preserve staging directory, write `.triage-pending.json` to staging with schema `{"categories": ["cat1", "cat2"], "reason": "partial_failure", "timestamp": "ISO8601"}` — the `categories` key is REQUIRED (the retrieval hook `memory_retrieve.py` line 509 reads `_pending_data.get("categories", [])` to count and display pending categories). Using any other key name (e.g., `pending_categories`) would silently break pending notifications.
  4. Write `last-save-result.json` via `memory_write.py --action write-save-result --staging-dir <staging_dir> --result-json '<json>'` (or `--result-file <path>` if JSON is large). The `--result-json` must contain `{"saved_at": "ISO8601", "categories": ["cat1"], "titles": ["title1"], "errors": []}`. The `session_id` field is auto-populated from the sentinel file by `memory_write.py`. Must use the EXISTING `write-save-result` action with `--result-json` or `--result-file` — NOT `--categories`/`--titles` as separate flags. The retrieval hook at Blocks 1-3 parses `saved_at`, `categories`, `titles` — any schema change would break US-3 save confirmation (M2).
  5. Update sentinel: `memory_write.py --action update-sentinel-state --state saved --staging-dir <staging_dir>` (or `--state failed` if any category failed)
- [ ] **Step 2.7: `--action commit` mode** -- Reads manifest from `orchestration-result.json` in staging dir, runs step 7 only. Uses OCC hashes from the manifest (captured at step 2 time).
- [ ] **Step 2.8: Memory root resolution** -- `memory_write.py` does NOT accept `--root` — it derives memory root from `--target` via `_resolve_memory_root()`. The orchestrator must ensure all `--target` paths contain the full `.claude/memory/` prefix. `memory_enforce.py` also does NOT accept `--root` — it resolves the root from the project directory. The orchestrator accepts its own `--root` CLI argument to know the memory root for target path generation (H2). This value is used internally (not passed to subprocess calls).
- [ ] **Step 2.9: Error handling** -- Wrap step 7 in try/except. On unhandled exception: write `.triage-pending.json`, update sentinel to failed, preserve staging. Return non-zero exit code.

### Phase 3: Update SKILL.md + Documentation (half day)

- [ ] **Step 3.1: Rewrite SKILL.md** -- Replace Pre-Phase + Phase 0 + Phase 1 + Phase 1.5 + Phase 2 + Phase 3 with SETUP + Phase 1 DRAFT + Phase 2 COMMIT. Target: ~100 lines (from ~300).
  - SETUP: Parse triage output, cleanup stale intents (2-3 SKILL.md lines)
  - Phase 1 DRAFT: Spawn per-category memory-drafter agents (keep existing drafter instructions, ~20 lines)
  - Phase 1.5 VERIFY (optional): If `verification_enabled: true`, read manifest from `--action prepare`, spawn verifiers for risk-eligible categories, then call `--action commit` (~10 lines, conditional)
  - Phase 2 COMMIT: Single call `python3 memory_orchestrate.py --staging-dir <dir> --action run` (or `prepare` + `commit` if verification enabled) (~5 lines)
- [ ] **Step 3.2: Add fallback for total Phase 1 failure (M1)** -- If ALL Phase 1 drafters fail (no intent-*.json files produced), SKILL.md instructs writing `.triage-pending.json` before allowing stop. This ensures the retrieval hook can detect the orphaned triage and notify the user.
- [ ] **Step 3.3: Update CLAUDE.md** -- Update architecture table (Hook Type descriptions), Key Files table (add memory_orchestrate.py with new role), update Architecture section text describing the 3-phase flow.
- [ ] **Step 3.4: Update PRD (M3)** -- Update PRD sections:
  - Section 3.1.2 (Phase 2/3): Reflect new COMMIT phase replacing haiku saver
  - Section 4.1 (Phase 3 Bash): Update to reflect Python subprocess execution
  - Section 4.2 (subagent costs): Update cost model to reflect 1 subagent type
- [ ] **Step 3.5: Config changes** -- Update `assets/memory-config.default.json`:
  - Change `triage.parallel.verification_enabled` default from `true` to `false` (implements #4 from mandatory changes)
  - Add `architecture.simplified_flow: true` key (implements rollback feature flag from #23)
  - Update CLAUDE.md config documentation to list new `architecture.simplified_flow` as agent-interpreted key
  - Update SKILL.md to check `architecture.simplified_flow` and fall back to v5 flow when `false`
- [ ] **Step 3.6: Config tests** -- Add test that `memory-config.default.json` has `verification_enabled: false` and `architecture.simplified_flow: true`. These are regression guards against accidental reversion.
- [ ] **Step 3.7: Atomic deployment** -- New `memory_orchestrate.py` + new `SKILL.md` must deploy together. Version the SKILL.md (v6) and ensure both files are committed in the same changeset. Old SKILL.md backed up as `SKILL.md.v5` for rollback.

### Phase 4: Testing (half day)

- [ ] **Step 4.1: Unit tests for `execute_saves()`** -- Test save execution with mocked subprocess calls. Cover: single-category CREATE, multi-category mixed actions, OCC hash passing, sentinel state transitions, `--skip-auto-enforce` flag presence.
- [ ] **Step 4.2: Unit tests for new functions** -- Test `generate_target_path()`, JSON markdown stripping in `collect_intents()`, OCC hash capture in `run_candidate_selection()`, `--action prepare`/`commit` argument parsing.
- [ ] **Step 4.3: Integration test -- single category save** -- End-to-end: write intent file -> run orchestrator -> verify memory file created, index updated, staging cleaned, result file written, sentinel state correct.
- [ ] **Step 4.4: Integration test -- multi-category save** -- 3+ categories with mixed CREATE/UPDATE/DELETE actions. Verify all operations complete correctly.
- [ ] **Step 4.5: Integration test -- partial failure + recovery** -- Simulate one category's memory_write.py call failing. Verify: successful categories saved, failed category in `.triage-pending.json`, staging preserved, sentinel set to failed.
- [ ] **Step 4.6: Integration test -- prepare/commit split** -- Run `--action prepare`, inspect manifest, run `--action commit`, verify saves use manifest OCC hashes.
- [ ] **Step 4.7: Regression tests** -- Verify existing `tests/test_memory_orchestrate.py` passes without modification. Add regression test: calling `memory_orchestrate.py --staging-dir <dir>` without `--action` runs steps 1-6 only (no save execution). This test guards the backward-compatibility invariant that makes SKILL.md v5 rollback safe. Run full `pytest tests/ -v`.
- [ ] **Step 4.8: Contract tests** -- Verify `last-save-result.json` schema compatibility with retrieval hook. Verify `.triage-pending.json` schema compatibility with retrieval hook. Verify `session_id` field preserved (M2).
- [ ] **Step 4.9: Performance benchmark** -- Measure save time before/after in a real session with 2-3 categories triggered. Target: 4-8 min total.

### Phase 5: Validation + Deployment (2-3 hours)

- [ ] **Step 5.1: Compile check** -- `python3 -m py_compile hooks/scripts/memory_orchestrate.py`
- [ ] **Step 5.2: Full test suite** -- `pytest tests/ -v` -- all tests pass
- [ ] **Step 5.3: Manual smoke test** -- Trigger a real save (stop a session with decision + session_summary content), observe full SETUP -> DRAFT -> COMMIT flow
- [ ] **Step 5.4: Verify rollback** -- Swap back `SKILL.md.v5`, verify old flow still works. The extended `memory_orchestrate.py` is backward-compatible because calling it without `--action` runs steps 1-6 only (the original behavior). Also test config-based disable: set `architecture.simplified_flow: false` with SKILL.md v6 and verify it falls back to the v5 orchestration path.
- [ ] **Step 5.5: Deploy** -- Commit all changes together (atomic deployment). Update action plan status to done.

---

## 5. Expected Improvements

| Metric | Current | Target | Rationale |
|--------|---------|--------|-----------|
| Save time | 17-28 min | 4-8 min | Phase 1 DRAFT dominates (2-5 min); COMMIT < 30s |
| Visible tool calls | ~26 | 3-9 | SETUP (1-2) + DRAFT (1-6) + COMMIT (1) |
| Subagent spawns | 3-6 (draft + verify + save) | 1-6 (draft only) | Verification optional; no saver subagent |
| Token cost | ~220k tokens/save | ~60-80k tokens/save | No verification/saver subagents, simpler SKILL.md |
| SKILL.md instructions | ~300 lines | ~100 lines | Major simplification |
| Subagent types | 3 (drafter, verifier, saver) | 1 (drafter) | Simpler mental model |
| Guardian conflicts | Frequent (heredoc Bash) | None | Python subprocess is invisible to Guardian |

---

## 6. Risk Register

| # | Risk | Severity | Mitigation | Status |
|---|------|----------|------------|--------|
| R1 | CREATE overwrite destroys active memory (C1) | CRITICAL | Fix `do_create()` to reject existing active files | Pre-implementation fix (Phase 0) |
| R2 | Index duplication on retry (C2) | CRITICAL | Fix `add_to_index()` to deduplicate by path | Pre-implementation fix (Phase 0) |
| R3 | Double enforcement latency (H1) | HIGH | `--skip-auto-enforce` flag | Pre-implementation fix (Phase 0) |
| R4 | Venv bootstrap crash on `slugify` import (H6) | HIGH | Lazy-import inside function, re-exec under .venv if needed | Phase 2, Step 2.1 |
| R5 | JSON markdown fences cause silent intent loss (H5) | HIGH | Strip fences in `collect_intents()` | Phase 2, Step 2.2 |
| R6 | OCC hash at save time defeats concurrency protection (H4) | HIGH | Capture hash at candidate selection (Step 2) | Phase 2, Step 2.3 |
| R7 | CREATE without target path fails (H2) | HIGH | Generate path via `slugify()` in orchestrator | Phase 2, Step 2.4 |
| R8 | All Phase 1 drafters fail -> no orchestrator run -> orphaned triage | HIGH | SKILL.md fallback writes `.triage-pending.json` (M1) | Phase 3, Step 3.2 |
| R9 | FlockIndex proceed-without-lock in batch saves | MEDIUM | Use `require_acquired()` for batch saves | Deferred (single-user unlikely) |
| R10 | `do_update()` reads old_data outside lock | MEDIUM | Always pass `--hash` (OCC) from orchestrator | Phase 2, Step 2.6 |
| R11 | Sentinel stuck after SIGKILL | LOW | Existing `FLAG_TTL_SECONDS=1800` safety net | Existing mitigation |
| R12 | SKILL.md v6 breaks existing workflow | LOW | Keep `SKILL.md.v5` backup, feature flag in config | Phase 3, Step 3.5 |
| R13 | Non-atomic deployment (orchestrator updated before SKILL.md) | MEDIUM | Commit both in same changeset, backward-compatible orchestrator | Phase 5, Step 5.5 |

---

## 7. Files Changed

| File | Status | Action | Phase |
|------|--------|--------|-------|
| `hooks/scripts/memory_write.py` | EXISTING | Fix C1 (do_create overwrite), C2 (add_to_index dedup), H1 (--skip-auto-enforce) | Phase 0 |
| `hooks/scripts/memory_orchestrate.py` | EXISTING (387 lines) | Extend with: venv bootstrap (H6), JSON stripping (H5), OCC hash capture (H4), target path gen (H2), prepare/commit split (H3), save execution (step 7), failure handling | Phase 2 |
| `skills/memory-management/SKILL.md` | EXISTING | Rewrite to 3-phase flow (~100 lines), add M1 fallback | Phase 3 |
| `skills/memory-management/SKILL.md.v5` | NEW | Backup of current SKILL.md for rollback | Phase 3 |
| `CLAUDE.md` | EXISTING | Update architecture table and descriptions | Phase 3 |
| `docs/requirements/prd.md` | EXISTING | Update sections 3.1.2, 4.1, 4.2 (M3) | Phase 3 |
| `tests/test_memory_write.py` | EXISTING | Add tests for C1, C2, H1 fixes | Phase 0 |
| `tests/test_memory_orchestrate.py` | EXISTING | Add tests for save execution, prepare/commit split, H2-H6 | Phase 4 |
| `assets/memory-config.default.json` | EXISTING | Change `verification_enabled` default from `true` to `false`; add `architecture.simplified_flow: true` key | Phase 3 |

**Files NOT changed** (explicitly removed from original plan):
- ~~`hooks/scripts/memory_detect.py`~~ -- vestigial, never existed as file
- ~~`hooks/scripts/memory_commit.py`~~ -- replaced by extending `memory_orchestrate.py`

---

## 8. Rollback Plan

If the simplified architecture causes regressions in production:

1. **Immediate rollback**: Rename `SKILL.md.v5` back to `SKILL.md`. This is safe because the orchestrator extension is **backward-compatible by design**: calling `memory_orchestrate.py --staging-dir <dir>` without `--action` still runs steps 1-6 only (the original behavior). Step 7 (`execute_saves`) only executes when `--action run` or `--action commit` is explicitly passed. The old SKILL.md v5 never passes `--action`, so it never triggers step 7.
2. **Config-based disable**: The new SKILL.md v6 checks `architecture.simplified_flow` (default: `true`). Setting it to `false` makes SKILL.md v6 fall back to the v5 flow (Phase 1.5 via main agent + Phase 3 via haiku saver). When using this fallback, ALSO set `triage.parallel.verification_enabled: true` to restore v5's verification-on behavior (since the simplified flow changes this default to `false`). This allows testing the new flow without committing to it.
3. **Verification re-enable**: Set `triage.parallel.verification_enabled: true` in config. SKILL.md v6 switches from `--action run` to `--action prepare` + verify + `--action commit`. No code change needed.
4. **Scope**: All 5 hooks remain unchanged throughout. The security perimeter (write guard, staging guard, validation hook) is never modified. Rollback only affects SKILL.md orchestration instructions and which `--action` mode is used.
5. **Backward-compatibility invariant**: The no-`--action` default of `memory_orchestrate.py` must NEVER change from steps-1-6-only behavior. This is what makes SKILL.md v5 rollback safe. Enforced by a regression test (Phase 4, Step 4.7).

---

## 9. PRD Update Requirements (M3)

The following PRD sections describe the CURRENT architecture specifically and must be updated to reflect the simplification. These are functional improvements, not regressions.

| PRD Section | Current Requirement | Updated Requirement | Rationale |
|-------------|-------------------|---------------------|-----------|
| 3.1.2 Phase 2/3 | Phase 2: Content verification by Task subagent. Phase 3: Foreground haiku Task subagent executes all writes. | Phase 2 COMMIT: `memory_orchestrate.py` executes saves via subprocess. Verification optional (config-controlled, between prepare and commit). | Eliminates most fragile component (haiku saver). Better error handling via Python. |
| 4.1 (Phase 3 Bash) | "Combines all commands into single Bash call" | "Orchestrator executes all commands via Python subprocess calls" | Equivalent consolidation with better reliability. Eliminates Guardian conflicts. |
| 4.2 (subagent costs) | "1 haiku Task subagent" for Phase 3 | No Phase 3 subagent. Cost model: 1-N drafter subagents only. | Reduces token cost ~50%. |
| R52 | "One foreground Task subagent (haiku) executes all writes" | "Orchestrator script executes all writes via subprocess" | Functional improvement, not regression. |
| R53/R144 | "Combines all commands into single Bash call" | "Python subprocess calls in orchestrator" | Same consolidation, better mechanism. |

---

## 10. Mandatory Changes Checklist

All 23 mandatory changes from the review briefing, tracked to implementation phase:

| # | Change | Category | Phase | Step |
|---|--------|----------|-------|------|
| 1 | Remove memory_detect.py entirely | Structural | N/A | Already removed from this plan |
| 2 | Use memory_orchestrate.py (extend, not replace) | Structural | Phase 2 | All |
| 3 | Option B (per-category drafters) as default | Structural | Phase 3 | 3.1 |
| 4 | G5: Drop verification by default, config flag for opt-in | Structural | Phase 3 | 3.1, 3.5 |
| 5 | Adjust performance target to 4-8 min | Structural | N/A | Section 5 updated |
| 6 | Guardian compatibility noted as benefit | Structural | N/A | Section 2, Section 5 |
| 7 | Atomic deployment (scripts + SKILL.md together) | Structural | Phase 5 | 5.5 |
| 8 | C1: Fix do_create() overwrite | Pre-impl | Phase 0 | C1 |
| 9 | C2: Fix add_to_index() dedup | Pre-impl | Phase 0 | C2 |
| 10 | H1: --skip-auto-enforce flag | Pre-impl | Phase 0 | H1 |
| 11 | H2: CREATE target-path generation | Impl | Phase 2 | 2.4 |
| 12 | H3: Prepare/commit split | Impl | Phase 2 | 2.5, 2.7 |
| 13 | H4: OCC hash at candidate selection time | Impl | Phase 2 | 2.3 |
| 14 | H5: JSON markdown stripping | Impl | Phase 2 | 2.2 |
| 15 | H6: Venv bootstrap import order | Impl | Phase 2 | 2.1 |
| 16 | Sentinel state management | Orchestration | Phase 2 | 2.6 |
| 17 | Failure path specification | Orchestration | Phase 2 | 2.6, 2.9 |
| 18 | M1: SKILL.md fallback on total drafter failure | Orchestration | Phase 3 | 3.2 |
| 19 | M2: session_id preservation in result file | Other | Phase 2 | 2.6 |
| 20 | M3: PRD sections update | Other | Phase 3 | 3.4 |
| 21 | Verification as risk-based triggers | Other | Phase 3 | 3.1 |
| 22 | Testing strategy | Other | Phase 4 | All |
| 23 | Rollback plan | Other | Phase 3/5 | Section 8, Step 3.5, 5.4 |

---

## Dependencies

- `fix-stop-hook-refire.md` (P0) -- should complete first; faster saves reduce TTL pressure
- `eliminate-all-popups.md` (P0, DONE) -- write-staging approach already in place

---

## Summary

This plan collapses the 5-phase save orchestration to 3 phases by:

1. **Eliminating Phase 1.5** (LLM-interpreted deterministic rules) -- already implemented as `memory_orchestrate.py`
2. **Eliminating Phase 3** (fragile haiku saver subagent) -- absorbed into orchestrator step 7
3. **Making Phase 2 verification optional** -- config-controlled, risk-based triggers only

The implementation is **~2-3 days** because `memory_orchestrate.py` already has 6 of 7 steps implemented. The primary work is adding save execution (step 7), fixing 3 pre-existing bugs (C1, C2, H1), and incorporating 4 implementation fixes (H2-H5 with H6 bootstrap safety).

All 11 PRD user stories remain covered. All 5 hooks are unchanged. The security perimeter is preserved. All 194 traced requirements are satisfiable with the identified fixes.
