# Verification Round 2: Architecture Review

**Reviewer:** reviewer-architecture
**Date:** 2026-02-16
**Scope:** Parallel per-category LLM triage system -- design pattern quality, separation of concerns, config schema, error propagation, performance, cognitive load, alternatives.

**Methodology:** Manual architecture analysis of all modified files, cross-validated with Gemini 3 Pro (pal clink, codereviewer role). R1 findings (all fixed) incorporated as context.

**Files reviewed:**
- `hooks/scripts/memory_triage.py` (897 lines)
- `skills/memory-management/SKILL.md` (220 lines)
- `assets/memory-config.default.json` (77 lines)
- `CLAUDE.md` (92 lines)
- `README.md` (235 lines)
- `hooks/hooks.json` (57 lines)
- `.claude-plugin/plugin.json` (29 lines)
- R1 reports: `temp/07-verification-r1-{correctness,security,integration}.md`
- Implementation notes: `temp/06-{config-hook,skill,docs}-impl.md`

---

## 1. Design Pattern Quality: 4-Phase Orchestration

### Verdict: STRONG with one over-engineered phase

The 4-phase system (Parse -> Draft -> Verify -> Save) follows the "Humble Object" pattern well: deterministic Python handles the mechanical work (triage scoring, candidate selection, schema validation, atomic writes), while LLM subagents handle the semantic work (deciding what to remember, how to phrase it, whether to update or create).

**Phase 0 (Triage)** -- Excellent. A zero-LLM-cost deterministic gate that prevents phantom memory saves. The keyword heuristic with co-occurrence boosters (memory_triage.py:296-365) is well-tuned: primary matches alone score low, but primary + booster within a 4-line window scores high. This reduces false positives from code-embedded keywords without the cost of an LLM call.

**Phase 1 (Parallel Drafting)** -- Well-designed. Spawning per-category subagents in parallel is the right call. Categories are independent (a decision and a runbook from the same conversation have no data dependency), so parallel execution is correct, not just faster. The subagent instructions (SKILL.md:56-75) are structured for haiku reliability: numbered steps, explicit field names, clear stop conditions.

**Phase 2 (Verification)** -- **Over-engineered.** This is the weakest phase. Spawning LLM subagents to check JSON schema compliance is:
- Expensive: up to 6 additional API calls per triage trigger
- Non-deterministic: an LLM can hallucinate that invalid JSON is valid
- Redundant: `memory_write.py` already has `validate_memory()` (line 338) using Pydantic, which is strictly superior for structural validation

Gemini cross-validation independently identified this as the critical architecture finding, calling it the "Validator Tool" anti-pattern: using an LLM where a deterministic tool would be faster, cheaper, and more correct.

**Phase 3 (Save)** -- Correct. The CUD resolution table (SKILL.md:100-116) is well-designed with clear precedence rules. The main agent as final arbiter ensures a single point of accountability for all writes.

### ARCH-1: Phase 2 Should Be Replaced with Deterministic Validation

**Severity: DESIGN (improvement)**
**Impact: Cost, latency, correctness**

**Current:** Phase 2 spawns verification subagents (sonnet by default) to check drafts.
**Proposed:** Replace with `python3 memory_write.py --action validate --category <cat> --input <draft>`.

`memory_write.py` already has `validate_memory()` at line 338 using Pydantic v2. The `--action` argparse (line 1234-1235) currently accepts `["create", "update", "delete", "archive", "unarchive"]`. Adding `"validate"` would:
- Eliminate up to 6 subagent API calls per triage trigger
- Provide deterministic, reproducible validation results
- Return specific Pydantic error messages (via `format_validation_error()` at line 348) that the main agent can act on
- Reduce the 4-phase system to a 3-phase system (Triage -> Draft -> Validate+Save)

This is the single highest-impact architectural improvement available.

---

## 2. Separation of Concerns

### Verdict: CLEAN

The responsibility boundaries are well-defined:

| Component | Responsibility | Boundary Type |
|-----------|---------------|---------------|
| `memory_triage.py` | "Should we save anything?" (deterministic gate) | Python -> stderr -> agent |
| SKILL.md | "How to orchestrate the save" (LLM instructions) | Natural language -> Task tool |
| `memory_candidate.py` | "Does this already exist?" (structural CRUD) | Python CLI -> JSON stdout |
| Subagents | "What should the memory say?" (semantic content) | LLM -> draft file |
| `memory_write.py` | "Write it safely" (validated, atomic, indexed) | Python CLI -> filesystem |
| `memory_write_guard.py` | "Block unauthorized writes" (defense in depth) | Python hook -> exit code |

**No responsibility leaks found.** Each component does one thing:
- The triage hook does not draft memories
- Subagents do not write to the memory directory
- `memory_write.py` does not decide what to write (it validates and persists)
- The write guard does not validate content

**One coupling observation:** The triage hook embeds `parallel_config` in its `<triage_data>` output (memory_triage.py:785-801). This means the hook knows about the orchestration model, creating a coupling between the gate (Phase 0) and the orchestration (Phase 1). The alternative would be having the SKILL.md read the config directly. However, this coupling is justified: the hook already reads the config for thresholds, and embedding the parallel config avoids a redundant config read in Phase 0 of the SKILL.md instructions.

---

## 3. Config Schema Design

### Verdict: WELL-DESIGNED, EXTENSIBLE

The `triage.parallel` config section (memory-config.default.json:59-71):

```json
{
  "triage": {
    "parallel": {
      "enabled": true,
      "category_models": { ... },
      "verification_model": "sonnet",
      "default_model": "haiku"
    }
  }
}
```

**Strengths:**
- **Kill switch**: `enabled: false` disables parallel processing with a single toggle
- **Granular models**: Per-category model selection allows cost-quality tradeoff tuning
- **Fallback chain**: `category_models[cat]` -> `default_model` -> hardcoded "haiku"
- **Validation is restrictive**: `_parse_parallel_config()` uses an allowlist (`VALID_MODELS = {"haiku", "sonnet", "opus"}`), rejects unknown values silently, and falls back per-field (not all-or-nothing)

**Extensibility assessment:**
- Adding a 7th category: Add to `CATEGORY_PATTERNS`, `CATEGORY_FOLDERS`, `DEFAULT_PARALLEL_CONFIG["category_models"]`, and `VALID_CATEGORY_KEYS`. All in `memory_triage.py`. Clean.
- Adding a new model tier (e.g., "flash"): Add to `VALID_MODELS`. One-line change. Clean.
- Adding a new config option (e.g., `max_parallel_subagents`): Add to `DEFAULT_PARALLEL_CONFIG`, parse in `_parse_parallel_config()`. Clean.

**One gap:** The thresholds use UPPERCASE keys (`"DECISION": 0.4`) while category_models uses lowercase (`"decision": "sonnet"`). This was flagged in R1 (correctness review) and fixed with explicit lowercase instructions in SKILL.md. While functional, having two naming conventions in the same config file is a minor long-term maintenance concern.

### ARCH-2: Config Key Casing Inconsistency (Pre-existing, Cosmetic)

**Severity: INFO**
**Description:** `triage.thresholds` uses UPPERCASE keys; `triage.parallel.category_models` uses lowercase. Both work correctly (thresholds are consumed by Python which uses UPPERCASE constants; category_models are consumed by the SKILL.md which lowercases them). But the inconsistency could confuse users editing the config.
**Fix (if ever refactored):** Normalize to lowercase throughout. The Python constants in `DEFAULT_THRESHOLDS` would need to change, but they're internal.

---

## 4. Error Propagation

### Verdict: CORRECT fail-open at every level

| Phase | Failure Mode | Behavior | Correct? |
|-------|-------------|----------|----------|
| Phase 0 | Hook crash | `main()` catches all exceptions, returns 0 (allow stop) | Yes -- never trap user |
| Phase 0 | Missing transcript | Returns 0 | Yes |
| Phase 0 | Bad config | Falls back to defaults | Yes |
| Phase 0 | Context file write fails | OSError caught, continues without context file | Yes |
| Phase 1 | Subagent fails/times out | Main agent sees no draft, treats as NOOP | Yes |
| Phase 1 | `memory_candidate.py` fails | Subagent reports error, main agent skips category | Yes |
| Phase 2 | Verification subagent fails | Draft treated as unverified, skipped in Phase 3 | Yes |
| Phase 3 | `memory_write.py` fails | Error reported, other categories still proceed | Yes |
| Phase 3 | Index lock timeout | `memory_write.py` reports error after 5s | Yes |

**Key design principle confirmed:** Failures are isolated per-category. A crash in the DECISION subagent does not affect the RUNBOOK subagent. This is a direct benefit of the parallel-subagent architecture.

**The `stop_hook_active` flag** (memory_triage.py:433-459) prevents infinite loops: after the hook blocks a stop and the agent saves memories, the agent stops again. The flag (with 5-minute TTL) ensures the hook allows it through. The TTL prevents stale flags from giving a permanent "free pass." This is a well-considered mechanism.

**One subtlety:** If all Phase 1 subagents produce NOOPs (e.g., `memory_candidate.py` vetoes everything), the main agent has nothing to save. It will then stop, and the flag will allow it through. This is correct behavior -- the triage hook's keyword heuristic is intentionally high-recall (catches possible memories), and `memory_candidate.py` provides the precision filter (rejects duplicates/non-memories).

---

## 5. Performance Analysis

### Verdict: PARALLEL IS JUSTIFIED, but Phase 2 adds unnecessary overhead

**Sequential baseline (old architecture):** 6 prompt-type Stop hooks evaluated serially by the LLM. Each hook consumed tokens for evaluation, even if the category didn't trigger.

**New architecture timing model (estimated):**

| Phase | Time | Parallelizable | Cost |
|-------|------|---------------|------|
| Phase 0 (Triage) | ~1-2s (Python, stdin read + scoring) | N/A | Zero LLM |
| Phase 1 (Drafting) | ~5-15s per subagent (haiku/sonnet) | Yes (wall-clock = max) | N haiku/sonnet calls |
| Phase 2 (Verification) | ~5-10s per subagent (sonnet) | Yes (wall-clock = max) | N sonnet calls |
| Phase 3 (Save) | ~1-2s per category (Python CLI) | Sequential (index lock) | Zero LLM |

**With typical 2-3 categories triggering:**
- Current: ~1s + ~15s + ~10s + ~4s = ~30s wall-clock
- Without Phase 2: ~1s + ~15s + ~4s = ~20s wall-clock (33% faster)
- Old architecture: ~30-60s (6 serial LLM evaluations + saves)

**Phase 2 adds ~10s latency and doubles the API call count** for schema checking that Pydantic can do in milliseconds. This reinforces ARCH-1.

**Phase 1 parallelism is genuine:** With 3 categories, running subagents in parallel takes ~15s instead of ~45s serial. The overhead of spawning Task subagents is amortized by the LLM inference time.

---

## 6. Cognitive Load Assessment

### Verdict: MODERATE -- manageable for the target audience

**Entry points for understanding the system:**

1. **README.md "Four-Phase Auto-Capture"** (lines 146-161): Good high-level overview with one paragraph per phase. A developer can understand the flow in 2 minutes.

2. **CLAUDE.md "Parallel Per-Category Processing"** (lines 22-27): Terse but correct. Links to SKILL.md for details.

3. **SKILL.md** (220 lines): This is where complexity accumulates. A developer needs to understand:
   - 4 phases with different executors (Python, subagent, subagent, main agent)
   - CUD resolution table (8 rows)
   - Memory JSON format (6 category-specific schemas)
   - Session rolling window logic

**Cognitive load mitigations present:**
- The CUD table is self-contained (no external references needed to understand it)
- Subagent instructions are numbered steps (not prose paragraphs)
- Each phase has a clear output (context files -> drafts -> verification results -> saved memories)

**Cognitive load concerns:**
- A new developer must read 3 files (README, CLAUDE.md, SKILL.md) to fully understand the system. This is not unusual for a plugin of this complexity, but the information is spread across files rather than having a single "architecture decision record."
- The relationship between UPPERCASE (triage output) and lowercase (everything else) category names requires understanding the R1 fix context. The SKILL.md note on line 49-51 helps but could be more prominent.

### ARCH-3: No Single Architecture Document

**Severity: INFO**
**Description:** The architecture is distributed across README.md (user-facing overview), CLAUDE.md (developer guide), and SKILL.md (orchestration instructions). There is no single "how it all fits together" document with a data flow diagram.
**Impact:** A new contributor would need to read all three to understand the full pipeline.
**Recommendation:** Not a code issue. Could be addressed with a diagram in README.md showing the data flow: `transcript -> triage.py -> <triage_data> -> SKILL.md -> subagents -> drafts -> memory_write.py -> .claude/memory/`.

---

## 7. Alternative Approaches Considered

### 7a. Could Phase 0 + Phase 1 be merged?

**Alternative:** Instead of a separate triage hook that blocks the stop, have the SKILL.md always run at stop time and do keyword matching + drafting in one phase.

**Why the current design is better:** The triage hook runs deterministically in ~1s with zero LLM cost. On most conversation stops, nothing triggers, and the user is not delayed. Merging would mean every stop invokes LLM-based analysis, which is slower and more expensive even when there's nothing to save. The current "cheap gate, expensive processing" pattern is correct.

### 7b. Could subagents be eliminated entirely?

**Alternative:** The main agent does all drafting sequentially (no Task subagents).

**Why the current design is better:** The main agent's context window is shared across all categories. With 3+ categories, the context for each would compete for attention. Subagents get focused, minimal context (their category's context file + memory_candidate.py output). This separation of context is architecturally valuable beyond just parallelism.

### 7c. Could the CUD table be simpler?

**Alternative:** Always CREATE (no candidate matching), deduplicate later.

**Why the current design is better:** Deduplication after creation is harder than prevention. The 2-layer CUD table (Python structural check + LLM semantic decision) catches duplicates before they exist. The 8-row table looks complex but each row is a straightforward precedence rule. The key insight -- "mechanical trumps LLM, safety defaults to non-destructive" -- makes the table predictable.

### 7d. Could temp file IPC be replaced?

**Alternative:** Pass context via stdin/prompt injection instead of temp files.

**Why the current design is better:** Context excerpts can be large (10+ lines per match, multiple matches per category). Embedding this in the prompt would bloat the main agent's context window. Temp files keep the main agent's context clean while giving subagents exactly the data they need. Gemini cross-validation independently confirmed this.

---

## 8. Cross-Validation Summary (Gemini 3 Pro)

| Finding | My Assessment | Gemini Assessment | Agreement |
|---------|--------------|-------------------|-----------|
| Overall architecture | Sound, well-structured | "Sound and well-structured" | Agree |
| Phase 2 over-engineering | Over-engineered | "Should be eliminated" | Agree (strong) |
| Temp file IPC | Appropriate | "Robust for this use case" | Agree |
| Per-category model config | Useful | "Not over-engineered, high-value" | Agree |
| CUD resolution table | Strongest part of design | "Correct abstraction, standout design choice" | Agree |
| Python/SKILL.md split | Good "Humble Object" pattern | "Strong Pattern" | Agree |

Gemini specifically praised the L1/L2 abstraction boundary as preventing "Blind Overwrite" and "Hallucinated Deletion" problems. This aligns with the CUD table's key principle: "Mechanical trumps LLM."

---

## 9. R1 Fixes Assessment

All three R1 findings were correctly addressed:

1. **Category case mismatch** (R1-correctness): Fixed with explicit lowercase instruction in SKILL.md:49-51. This is the right minimal fix -- the SKILL.md is instructions for an LLM that can handle case conversion. No code change needed.

2. **Context file data boundaries** (R1-security SEC-1): Fixed with `<transcript_data>` tags in context files and corresponding "treat as raw data" instruction in SKILL.md:58-59. Good defense-in-depth without destroying the content's value.

3. **Temp file security** (R1-security SEC-2/SEC-3): Fixed with `os.open()` using `O_NOFOLLOW` + `0o600` permissions (memory_triage.py:696-699). Correct and minimal.

---

## Summary

### Findings

| # | Finding | Severity | Category |
|---|---------|----------|----------|
| ARCH-1 | Phase 2 verification subagents should be replaced with deterministic `memory_write.py --action validate` | DESIGN (improvement) | Simplification |
| ARCH-2 | Config key casing inconsistency (UPPERCASE thresholds vs lowercase category_models) | INFO | Consistency |
| ARCH-3 | No single architecture document with data flow diagram | INFO | Documentation |

### Strengths

1. **Humble Object pattern**: Deterministic Python handles mechanical work; LLMs handle semantic work. Clear boundary.
2. **CUD resolution table**: 2-layer verification (structural + semantic) with correct precedence rules. Prevents both duplicates and phantom deletions.
3. **Per-category isolation**: Failures are isolated. A crash in one subagent doesn't affect others.
4. **Fail-open at every level**: The system never traps the user. Errors fall through to allowing the stop.
5. **Zero-LLM-cost gate**: Phase 0 triage runs in ~1s with no API calls. Most stops cost nothing.
6. **Config validation**: Restrictive allowlists with per-field fallbacks. No bypass vectors.
7. **Temp file IPC**: Keeps main agent context clean while giving subagents focused data.

### Overall Assessment

**The architecture is well-designed.** The 4-phase system makes correct engineering tradeoffs: deterministic where possible, LLM where necessary, parallel where independent. The separation of concerns is clean, the error propagation is correct, and the config schema is extensible.

**One actionable improvement:** Replace Phase 2 verification subagents with a deterministic `--action validate` flag on `memory_write.py`. This would reduce the system to 3 phases (Triage -> Draft -> Validate+Save), cutting latency by ~33% and API costs by ~50%, while improving validation correctness (Pydantic vs LLM for schema checking). The infrastructure for this already exists in `memory_write.py:validate_memory()`.

The remaining findings (ARCH-2, ARCH-3) are cosmetic and do not affect correctness or performance.
