> **WARNING: HISTORICAL DOCUMENT -- DO NOT IMPLEMENT FROM THIS SPEC**
>
> This is a historical design document for ACE v4.2. The v5.0.0 architecture differs significantly:
> - **Hooks**: 1 command-type Stop hook replaced the 6 prompt-type hooks described here
> - **CUD verification**: 2-layer system (Python + subagent) replaced the 3-layer system (Python + Sonnet triage + Opus write-phase)
> - **Triage output**: `<triage_data>` JSON with categories/scores/context_files replaced `lifecycle_event`/`cud_recommendation` fields (which no longer exist)
> - **Locking**: `mkdir`-based portable locking replaced `fcntl.flock`
>
> See README.md for current documentation and CLAUDE.md for current architecture.

# Memory Consolidation Proposal: Adaptive Consolidation Engine (ACE)

**Version**: 4.2 (Final)
**Date**: 2026-02-14
**Status**: Final for Founder Review (R2 revised)
**History**: v1.0 draft -> R1 review -> v2.0 -> R2 review -> v2.1 -> v3.0 CRUD expansion -> R1 CRUD validation -> v3.1 -> R2 CRUD validation -> v3.2 final -> v4.0 Python-tool-centric architecture -> v4.1 R1 fixes (subset-based merge validation, quarantine-not-delete, Pydantic v2 syntax, OCC --hash param, lock scope invariant, anti-anchoring honesty, unified timestamps, structured candidate excerpt) -> **v4.2 R2 fixes** (record_status lifecycle field, tag eviction policy, PreToolUse write-path block, dangling related_files cleanup, naming clarifications, token cost corrections)
**Research basis**: 3 parallel research tracks (codebase analysis, data systems, knowledge management) with cross-model validation (Claude Opus, Gemini, Codex). Validated through 2 rounds (4 independent reviewers) per version. v4.0 refinement by 3 specialized agents (algorithm simplifier, schema designer, verification designer) with Gemini/Codex cross-checks, reconciled by integration agent with Codex planner validation. v4.1 R1 validation by 2 independent reviewers (simplicity + engineering) with Codex cross-checks; fixes applied by revision agent with Codex clink validation. v4.2 R2 validation by 2 independent reviewers (holistic + adversarial) with Codex cross-checks; fixes applied by finalizer agent with Gemini/Codex cross-validation.

---

## 1. Executive Summary

The claude-memory plugin (v3.0.0) stores structured memories as JSON files with a keyword-based retrieval index, but its consolidation logic -- the process of deciding whether new information should update an existing memory or create a new one -- is entirely LLM-interpreted with no structured pre-filtering, no history preservation, no lifecycle management, and no cross-category awareness.

This proposal introduces the **Adaptive Consolidation Engine (ACE)**, a system that replaces the binary "update or create" logic with full CRUD lifecycle management, built on a **Python-tool-centric architecture** where mechanical Python tools handle deterministic work and the LLM makes minimal, focused decisions.

**Core architecture** (v4.0):

```
TRIAGE (6 Sonnet hooks, parallel, extended outputs)
  -> category + lifecycle_event + cud_recommendation

CANDIDATE SELECTION + STRUCTURAL VERIFICATION (memory_candidate.py, Python, zero-token)
  -> best_candidate, pre_action, vetoes, delete_allowed

CUD VERIFICATION (three independent layers)
  -> Layer 1: Python structural (already done by candidate tool)
  -> Layer 2: Sonnet triage cud_recommendation (already provided)
  -> Layer 3: Opus write-phase independent decision (decide-then-compare)
  -> Consensus or safe default

EXECUTION (memory_write.py, Python)
  -> Pydantic schema validation, mechanical merge protections
  -> OCC, atomic write, index update, slug rename if needed
```

**Key capabilities**:

- **CRUD action classification**: CREATE, UPDATE, or DELETE (soft-retire), with READ handled by retrieval
- **Python-owned mechanics**: Candidate selection, schema validation, merge rule enforcement, OCC, and atomic writes are all Python code -- the LLM never follows a flowchart
- **Three-layer CUD verification**: Python structural checks + Sonnet triage hint + Opus independent decision, with mechanical vetoes and safety defaults
- **Schema enforcement**: Pydantic-validated writes via `memory_write.py` with a PreToolUse write-path block and PostToolUse validation guardrail
- **Lifecycle management**: Soft delete with 30-day grace period, restore capability, archive/unarchive
- **Change log**: Append-only history with scalar old/new values, immutable fields, grow-only lists
- **Enriched index**: All tags in index.md lines, scored at 3x weight in retrieval
- **Session rolling window**: Keep last 5 sessions instead of hard overwrite
- **Concurrency safety**: OCC with flock + hash checks, anti-resurrection protection
- **File rename on UPDATE**: When an UPDATE changes the topic significantly, the file slug is regenerated and the file is atomically renamed

**Design principle**: Python owns all mechanical work. The LLM's only jobs are: (1) call `memory_candidate.py`, (2) make one CUD decision (compared against two prior assessments), (3) draft content, (4) call `memory_write.py`. Everything else is enforced by code.

---

## 2. Problem Statement

The current consolidation system fails in concrete, observable ways:

### Example 1: Silent Duplicate Accumulation

A project has a decision memory `adr003-three-repo-architecture-split.json`. Three sessions later, the LLM saves a new memory `repo-structure-three-way-split.json` about the same decision using different wording. The index grows, retrieval becomes noisier, and the user sees conflicting or redundant entries.

### Example 2: Lost Contradiction Context

A constraint memory says "Discourse Managed Pro plan costs $100/month." A later session discovers the price increased to $120/month. The LLM overwrites the file with the new price. Three months later, there is no record that the price was ever $100, when it changed, or why.

### Example 3: Tags Written But Never Read

Every memory file has a `tags` array described as "retrieval keywords." But `memory_retrieve.py` only scores against the one-line index.md summary -- tags are never consulted. Memories with good tags but generic titles become invisible.

### Example 4: Session History Erasure

The session summary strategy keeps only the latest session. After 20 sessions, sessions 1-19 -- including the context in which early decisions were made -- are permanently lost.

### Example 5: Inability to Remove Obsolete Memories

Resolved tech debts, removed constraints, and decommissioned-system runbooks accumulate in the index indefinitely, adding noise to retrieval. The system is append-only with no lifecycle end state.

### Example 6: LLM Schema Violations

The LLM writes JSON directly with no mechanical validation. Common errors: missing required fields, wrong enum values, wrong types (`tags: "auth"` instead of `["auth"]`), truncated lists on UPDATE. These cause silent data corruption.

### Example 7: Single-Point CUD Failure

The CUD decision (Create/Update/Delete) happens exactly once, by one LLM call. A wrong-target UPDATE modifies the wrong memory; a false-positive DELETE retires a valuable memory. No independent verification catches these errors.

---

## 3. Current State Analysis

### Architecture (Preserve This)

The plugin's two-phase architecture is well-designed and must be preserved:

1. **Triage Phase**: 6 parallel Sonnet hooks evaluate each Stop event, one per category. Each returns `{"ok": true}` (nothing to save) or `{"ok": false, "reason": "Save a <CATEGORY> memory about..."}`. Loop prevention via `stop_hook_active` flag is mechanical and foolproof.

2. **Write Phase**: The main agent (full model) receives the triage instruction and executes the save with full tool access. SKILL.md provides format instructions.

3. **Retrieval Phase**: `memory_retrieve.py` (Python stdlib, no LLM) scores index.md entries against user prompts on every `UserPromptSubmit`. Deterministic, fast (<10ms), no external dependencies.

### Identified Gaps (Prioritized)

| Priority | ID | Gap | Addressed? |
|----------|-----|-----|-----------|
| P0 | G1 | Tags never used in retrieval | Yes -- enriched index |
| P0 | G3 | LLM-only dedup with no structured pre-filter | Yes -- mechanical candidate selection |
| P0 | G13 | No schema enforcement on writes | Yes -- memory_write.py + Pydantic |
| P0 | G14 | Single-point CUD decision failure | Yes -- three-layer verification |
| P1 | G5 | Session summary hard overwrite | Yes -- rolling window (5) |
| P1 | G6 | No recency weighting in retrieval | Yes -- +1 bonus (30 days) |
| P1 | G11 | No mechanism to remove obsolete memories | Yes -- DELETE with soft delete |
| P1 | G12 | Resolved items persist in retrieval results | Yes -- DELETE removes from index |
| P0 | G2 | No cross-category relationship detection | Deferred to v1.1 |
| P1 | G7 | `retention_days` config not enforced | Deferred to v1.1 |
| P2 | G8 | No semantic similarity | Deferred (needs embeddings) |
| P2 | G9 | Silent retrieval failures | Yes -- errors to stderr |
| P2 | G10 | No index integrity auto-check | Partial -- post-write check |

### Positive Patterns to Preserve

1. **Two-phase architecture** (Sonnet triage + main agent write)
2. **Loop prevention** via `stop_hook_active`
3. **Schema discipline** (JSON schemas with required fields, enums, constraints)
4. **Index as lightweight retrieval layer** (avoid reading every JSON on every prompt)
5. **Deterministic retrieval** (faster, cheaper, more predictable than LLM-based)

---

## 4. Proposed Design

### 4.1 The Consolidation Algorithm (Python-Tool-Centric)

When a triage hook fires (returns `ok: false`), the main agent executes this flow:

```
TRIAGE HOOK fires (Sonnet, 1 of 6 categories)
    -> {ok: false, reason: "...", lifecycle_event: "resolved"|null,
        cud_recommendation: "CREATE"|"UPDATE"|"DELETE"}
              |
              v
MAIN AGENT receives triage instruction
              |
              v
    +----------------------------------+
    | Step 1: FIND CANDIDATE           |
    | Tool call: memory_candidate.py   |
    | (Python, mechanical, zero-token) |
    |                                  |
    | Input: category, new_info,       |
    |        lifecycle_event           |
    | Reads index.md, scores entries   |
    | by keyword/prefix/tag overlap    |
    |                                  |
    | Output: {                        |
    |   candidate: {path, title,       |
    |     tags, structured_excerpt}    |
    |   pre_action: "CREATE"|"NOOP"    |
    |     or null,                     |
    |   delete_allowed: bool,          |
    |   vetoes: [],                    |
    |   structural_cud: "CREATE" |     |
    |     "UPDATE_OR_DELETE" | null    |
    | }                                |
    +----------------------------------+
              |
       pre_action == "CREATE"?
         /          \
       yes           no (candidate found)
        |             |
        v             v
    Skip to      +----------------------------+
    Step 3       | Step 2: CUD DECISION        |
    (CREATE)     | Three-layer verification:   |
                 |                             |
                 | L1: structural_cud (Python, |
                 |     already computed)       |
                 | L2: cud_recommendation      |
                 |     (Sonnet, from triage)   |
                 | L3: Opus OWN decision       |
                 |     (decide-then-compare)   |
                 |                             |
                 | Resolution: mechanical      |
                 | vetoes trump all; safety    |
                 | defaults for disagreements  |
                 +----------------------------+
                          |
                          v
    +----------------------------+
    | Step 3: EXECUTE             |
    | Draft content (LLM)        |
    | Write JSON to temp file    |
    | Call memory_write.py       |
    | (Python: validates schema, |
    |  enforces merge rules,     |
    |  handles OCC, atomic write,|
    |  index update, slug rename)|
    +----------------------------+
```

**What the LLM actually does** (the simplified view):

1. Receive triage instruction: "Save a TECH_DEBT memory about X" (with optional lifecycle_event and cud_recommendation).
2. Call `memory_candidate.py` with the category and new info. Get back: candidate (or null) + pre_action + structural assessment.
3. If `pre_action == "CREATE"`: draft new memory JSON, call `memory_write.py` to create it. **Done.**
4. If `pre_action == "NOOP"`: do nothing (lifecycle event but no matching memory). **Done.**
5. If candidate exists: make own CUD decision (decide-then-compare with L1 structural + L2 triage hint). Resolve disagreements per protocol.
6. Based on resolved action:
   - **CREATE**: Draft new memory JSON, call `memory_write.py --action create`.
   - **UPDATE**: Read candidate file, integrate new info, call `memory_write.py --action update`.
   - **DELETE**: Call `memory_write.py --action delete --reason "..."`.

**Compare with v3.2**: The v3.2 algorithm asked the LLM to follow a 6-step branching flowchart (read index, select candidate, read candidate, apply CUD rubric, execute, OCC check). The v4.0 algorithm asks the LLM to make ONE tool call (candidate), receive a mechanically-determined result, make ONE CUD decision (compared against two prior assessments), and call ONE write tool. The flowchart is eliminated; Python tools own all mechanical work.

### 4.2 Step 1: Candidate Selection + Structural Verification (`memory_candidate.py`)

A new Python tool (~150 lines) that mechanizes candidate selection AND structural verification in one call. The main agent calls it once.

**Input** (from triage output):
```json
{
  "category": "tech_debt",
  "new_info": "The N+1 query issue was resolved",
  "lifecycle_event": "resolved"
}
```

**Process**:
1. Read index.md, filter to entries matching `category`.
2. Score entries against `new_info` using the same keyword/prefix matching logic already proven in `memory_retrieve.py` (exact word match = 2 points, prefix match = 1 point, tag match = 3 points).
3. Return the top-1 match if score exceeds threshold (>= 3 points), else null.
4. Apply hard gates: if `category` is `decision` or `preference`, set `delete_allowed = false`.
5. Apply pre-classification:
   - No candidate + no lifecycle event: `pre_action = "CREATE"` (skip LLM CUD entirely).
   - No candidate + lifecycle event: `pre_action = "NOOP"` (no target for lifecycle action).
   - Candidate found: `pre_action = null` (LLM decides CUD).
6. Generate structural vetoes (hard-blocking):
   - Cannot UPDATE/DELETE with 0 candidates.
   - Cannot DELETE in decision/preference categories (triage-initiated).
   - Lifecycle event + 0 candidates = NOOP.

**Output (candidate found)**:
```json
{
  "candidate": {
    "path": ".claude/memory/tech-debt/n-plus-one-query.json",
    "title": "N+1 Query Performance Issue",
    "tags": ["performance", "database", "query"],
    "excerpt": {"title": "N+1 Query Performance Issue", "record_status": "active", "tags": ["performance", "database", "query"], "last_change_summary": "Initial creation", "key_fields": {"context": "First 200 chars...", "decision": "First 200 chars..."}}
  },
  "lifecycle_event": "resolved",
  "delete_allowed": true,
  "pre_action": null,
  "structural_cud": "UPDATE_OR_DELETE",
  "vetoes": [],
  "hints": ["1 candidate found; lifecycle_event=resolved suggests DELETE if eligible"]
}
```

**Output (no candidate)**:
```json
{
  "candidate": null,
  "lifecycle_event": null,
  "delete_allowed": false,
  "pre_action": "CREATE",
  "structural_cud": "CREATE",
  "vetoes": [],
  "hints": []
}
```

**Why this works**: The retrieval scoring logic in `memory_retrieve.py` already handles keyword/prefix matching reliably for 50-200 files. Candidate selection follows the same scoring approach. The tag-scoring extension (3x weight from enriched `#tags:` lines) is new code that requires its own testing, but the core word-matching principles are proven.

**Structured excerpt**: The candidate excerpt is a structured object containing `{title, record_status, tags, last_change_summary, key_fields}` rather than raw character slicing. This gives Layer 3 (Opus) better evidence for subject verification -- it can see the memory's title and lifecycle status directly rather than parsing raw text. `key_fields` contains the first 200 characters of each category-specific content field (e.g., `context` and `decision` for decisions). For categories with multiple content fields (e.g., decisions: context, decision, alternatives, rationale, consequences), the excerpt can reach ~300-500 tokens rather than the ~150 tokens for simpler categories.

**What if Python picks the wrong candidate?** The three-layer CUD verification in Step 2 catches this. If the candidate is clearly wrong, Opus will see the mismatch when reading the candidate file and choose CREATE instead. For v1, this is acceptable; for v1.1, a confidence threshold could be added.

**Token savings**: The biggest win is removing index.md from the LLM's context. At 100 entries, this saves ~3,500 tokens per save. The LLM only sees the single best candidate's structured excerpt (~300-500 tokens of title/record_status/tags/key fields, varying by category complexity), not the entire index.

### 4.3 Step 2: Three-Layer CUD Verification

When a candidate exists (`pre_action` is null), three independent checks determine the CUD action. This satisfies the founder's requirement: "CRUD judgment must be done independently 2+ times before proceeding."

#### Layer 1: Python Structural Check (Zero-Token, Already Computed)

This is the output of `memory_candidate.py` from Step 1 -- structural_cud, vetoes, and hints. It provides:
- Candidate count and match quality
- Hard vetoes (structurally impossible actions)
- Advisory hints (suggested action based on structural signals)

**Independence**: Deterministic algorithm operating on keyword overlap. Different procedure type, different failure modes from LLM reasoning.

#### Layer 2: Sonnet Triage CUD Recommendation (Existing Hook, Extended)

The existing triage hooks are extended to output a `cud_recommendation` field alongside `reason` and `lifecycle_event`.

**Extended triage output**:
```json
{
  "ok": false,
  "reason": "The N+1 query issue was resolved",
  "lifecycle_event": "resolved",
  "cud_recommendation": "DELETE"
}
```

**Triage hook prompt addition** (~60-80 tokens per hook):
```
Also classify the CRUD action:
- CREATE: This is new information not previously saved.
- UPDATE: This modifies, corrects, or extends something previously saved.
- DELETE: A previously saved item is now resolved/removed/deprecated.
Return cud_recommendation with your classification.
The main agent will make the final decision independently.
```

**What Sonnet sees vs what it does NOT see**:
- SEES: Full conversation context (the Stop event arguments)
- DOES NOT SEE: index.md, candidate files, Layer 1 output
- CUD recommendation is based purely on conversational signals

**Independence**: Different model (Sonnet vs Opus), different evidence base (conversation context vs index + candidate content), different failure modes.

#### Layer 3: Opus Write-Phase CUD Decision (Independent, Decide-Then-Compare)

The main agent receives Layers 1 and 2 as input, then makes its OWN independent CUD decision based on ADDITIONAL evidence (candidate file content).

**Protocol** (decide-then-compare):
1. Read the candidate file (excerpt from L1 output). **Form a preliminary CUD decision BEFORE consulting L1/L2 assessments.**
2. Compare own decision with L1 (structural) and L2 (Sonnet).
3. Resolve disagreements per the resolution protocol.
4. State the final action: `"CUD: [ACTION] (L1:[structural], L2:[sonnet], L3:[my decision] [resolution])"`.

**Independence from Layer 2**: Opus sees the actual memory content, which Sonnet never sees. Opus may discover that:
- The candidate that L1 found is actually about a different subject -> CREATE
- The memory was already partially resolved -> UPDATE, not DELETE
- The lifecycle event applies to only part of the content -> partial UPDATE

**Known limitation (v1)**: The decide-then-compare protocol is instructional, not architectural. L1/L2 outputs are present in the LLM's context when L3 forms its decision, so anchoring bias cannot be fully prevented. In practice, this is mitigated by three factors: (1) L2 (Sonnet) is usually correct, so anchoring toward the right answer is harmless; (2) L3 has additional evidence (candidate content) that L2 never saw; (3) safety defaults (UPDATE over DELETE on disagreement) catch the highest-risk failure mode. The real protections are the mechanical vetoes and safety defaults, not L3 independence per se. **v1.1 plan**: Evaluate making L3 CUD decision a separate tool invocation with evidence separation (L3 receives only candidate content + new_info, not L1/L2 outputs), enabling true architectural independence.

#### CUD Disagreement Resolution Protocol

| L1 (Python) | L2 (Sonnet) | L3 (Opus) | Resolution | Rationale |
|-------------|-------------|-----------|------------|-----------|
| CREATE | CREATE | CREATE | CREATE | Unanimous |
| UPDATE_OR_DELETE | UPDATE | UPDATE | UPDATE | Unanimous |
| UPDATE_OR_DELETE | DELETE | DELETE | DELETE | Unanimous (structural permits) |
| CREATE | CREATE | UPDATE | UPDATE | Opus found candidate L1 missed |
| CREATE | UPDATE | CREATE | CREATE | Structural confirms none exists |
| UPDATE_OR_DELETE | UPDATE | DELETE | **UPDATE** | Safety default: non-destructive |
| UPDATE_OR_DELETE | DELETE | UPDATE | **UPDATE** | Safety default: non-destructive |
| CREATE | DELETE | * | **NOOP** | Cannot DELETE with 0 candidates (structural veto) |
| UPDATE_OR_DELETE | CREATE | CREATE | CREATE | Both LLMs say CREATE despite candidate |
| VETO | * | * | **OBEY VETO** | Mechanical invariant violated |
| NOOP | * | * | **NOOP** | No target for lifecycle action |

**Key principles**:
1. **Mechanical trumps LLM**: Python vetoes are absolute.
2. **Safety defaults for LLM disagreements**: UPDATE over DELETE (non-destructive), UPDATE over CREATE (avoids duplicates), NOOP for CREATE-vs-DELETE (contradictory signals).
3. **All resolution is automatic**: No user confirmation needed.

**Logging** (stderr, not user-visible):
```
[ACE-CUD] category=tech_debt subject="Redis N+1 query"
  L1(structural): UPDATE_OR_DELETE candidates=1 slug=redis-n1-query vetoes=[]
  L2(sonnet): DELETE lifecycle_event=resolved
  L3(opus): DELETE (confirmed candidate entire subject is obsolete)
  RESOLUTION: DELETE (unanimous, no vetoes)
```

### 4.4 Step 3: Schema-Enforced Execution (`memory_write.py`)

A new Python tool (~250-300 lines) that handles all write operations with Pydantic schema validation and mechanical merge protections.

#### 4.4.1 Invocation Model

The LLM calls `memory_write.py` via Bash, passing JSON content through a temporary file:

```bash
# CREATE operation
python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py" \
  --action create \
  --category decision \
  --target .claude/memory/decisions/use-jwt-auth.json \
  --input /tmp/.memory-write-pending.json

# UPDATE operation
python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py" \
  --action update \
  --category decision \
  --target .claude/memory/decisions/use-jwt-auth.json \
  --input /tmp/.memory-write-pending.json \
  --hash <md5-of-file-at-read-time>

# DELETE operation (retire)
python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py" \
  --action delete \
  --category decision \
  --target .claude/memory/decisions/use-jwt-auth.json \
  --reason "Decision reversed: switched to session tokens"
```

**Why temp file instead of stdin/heredoc**: Bash heredoc with JSON content has quoting hazards (backslashes, dollar signs, backticks). Writing JSON to a temp file via the Write tool is the LLM's natural workflow. The temp file is cleaned up by the script after processing.

#### 4.4.2 LLM Workflow

**For CREATE**:
1. LLM writes the full JSON object to `/tmp/.memory-write-pending.json` using Write tool
2. LLM calls `python3 memory_write.py --action create --category <cat> --target <path> --input /tmp/.memory-write-pending.json`
3. Script validates, writes to target, updates index.md, deletes temp file
4. On error: script prints structured error message, LLM fixes and retries

**For UPDATE**:
1. LLM reads the existing memory file
2. LLM writes the complete updated JSON to `/tmp/.memory-write-pending.json`
3. LLM calls `python3 memory_write.py --action update --category <cat> --target <path> --input /tmp/.memory-write-pending.json`
4. Script validates, applies mechanical merge protections, writes atomically

**For DELETE**:
1. LLM calls `python3 memory_write.py --action delete --category <cat> --target <path> --reason "..."`
2. Script sets `record_status` to "retired", adds retired_at/retired_reason, removes from index

#### 4.4.3 Pydantic Schema Validation

The validation engine uses Pydantic v2 models for all 6 categories (~250 lines of model definitions):

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal, Optional
from datetime import datetime

class DecisionContent(BaseModel):
    status: Literal["proposed", "accepted", "deprecated", "superseded"]
    context: str
    decision: str
    alternatives: Optional[list[Alternative]] = None
    rationale: list[str] = Field(min_length=1)
    consequences: Optional[list[str]] = None

class DecisionMemory(BaseModel):
    schema_version: Literal["1.0"]
    category: Literal["decision"]
    id: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$")
    title: str = Field(max_length=120)
    record_status: Literal["active", "retired", "archived"] = "active"
    created_at: datetime
    updated_at: datetime
    tags: list[str] = Field(min_length=1)
    related_files: Optional[list[str]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    content: DecisionContent

    model_config = ConfigDict(extra="forbid")  # rejects unknown fields
```

**Validation checks** (in order):
1. JSON parse validity
2. Required top-level fields (schema_version, category, id, title, record_status, created_at, updated_at, tags, content)
3. Category matches target path
4. id matches filename (sans .json)
5. id matches slug pattern
6. Title length <= 120
7. Tags: array, minItems 1, all strings
8. Timestamps: valid ISO 8601
9. Content required fields per category
10. Content enum fields per category
11. Content type checks per category
12. No additional properties (reject unknown fields)
13. Nested object validation

**Why Pydantic over stdlib**: 6 categories of nested schemas with enums, regex patterns, and strict type constraints. Pydantic: ~250 lines of declarative models. stdlib: ~500+ lines of fragile if/elif/else. The dependency cost is minimal (~2MB, well-maintained, Rust-backed v2).

**Pydantic installation**: Pydantic v2 is installed via `pip install "pydantic>=2.0,<3.0"` as a plugin prerequisite. `memory_write.py` includes a startup self-check:
```python
try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator
except ImportError:
    print("ERROR: pydantic>=2.0 is required. Install: pip install 'pydantic>=2.0,<3.0'", file=sys.stderr)
    sys.exit(1)
```
This prevents retry loops from cryptic ImportError tracebacks.

#### 4.4.4 Mechanical Merge Protections (UPDATE)

When `--action update` is used, `memory_write.py` applies these protections AFTER the LLM provides the updated JSON but BEFORE writing to disk:

| Field Type | Merge Rule | Mechanical Check |
|---|---|---|
| `tags[]` | Union only; eviction at cap (see Section 4.10) | Below cap: `set(old_tags) <= set(new_tags)` after case-normalization. At cap (12): eviction allowed if adding new tags; evictions logged in `changes[]`. Dedupe and sort before write. |
| `related_files[]` | Union only; dangling path cleanup | `set(old_files) - set(new_files)` checked: removal rejected if removed path points to an existing file; removal allowed if path points to a non-existent file (dangling reference). Dedupe before write. |
| `changes[]` | Append only | `len(new_changes) > len(old_changes)` -- new entry required |
| `created_at` | Immutable | Reject if changed from original |
| `schema_version` | Immutable | Reject if changed |
| `category` | Immutable | Reject if changed |
| `id` | Immutable (except slug rename, see 4.4.6) | Reject if changed without rename flag |
| Scalar content fields | Overwrite allowed | Record old_value in change log automatically |
| List content fields | Append preferred | Warn if `len(new) < len(old)` but allow |

These checks are MECHANICAL -- the script compares old and new versions and rejects violations regardless of LLM intent.

#### 4.4.5 Auto-Fix Rules

The script automatically corrects trivial issues without requiring LLM retry:

| Issue | Auto-Fix | Rationale |
|---|---|---|
| Missing `updated_at` | Set to current UTC ISO 8601 | Always correct |
| Missing `created_at` on CREATE | Set to current UTC ISO 8601 | Always correct |
| `tags` is a string instead of array | Wrap in array: `"auth"` -> `["auth"]` | Common LLM error |
| `id` has uppercase or spaces | Slugify: `"Use JWT"` -> `"use-jwt"` | Mechanical fix |
| `confidence` outside 0.0-1.0 | Clamp to range | Safe default |
| `schema_version` missing | Set to `"1.0"` | Only one version exists |
| Trailing/leading whitespace | Strip | Never intentional |

Auto-fixes are logged to stderr: `[AUTO-FIX] field: description`.

#### 4.4.6 File Rename on UPDATE (Slug Regeneration)

When an UPDATE changes the topic significantly, the memory file name (slug) should also be updated for accurate retrieval. Example: `use-jest-for-testing.json` -> UPDATE to Vitest -> rename to `use-vitest-for-testing.json`.

**Mechanism** (handled by `memory_write.py`):
1. Compare the new `title` with the existing `title`.
2. If the title changed significantly (>50% word difference), regenerate the slug from the new title.
3. Atomic rename: create new file at new path -> update index.md (new path) -> delete old file.
4. Update the `id` field to match the new slug.

**What about references?**
- `index.md`: Updated atomically by `memory_write.py` as part of the rename.
- `related_files` in other memories: Dangling references (paths to files that no longer exist) are cleaned up automatically during the next UPDATE of those memories -- the `related_files` merge rule allows removal of non-existent paths (see Section 4.10). Cross-reference repair tooling is deferred to v1.1 (see Section 13.9) for proactive detection.
- Git history: The rename is a new file + delete, which git may detect as a rename. History of the old path is preserved via `git log --follow`.

**Edge cases**:
- If the new slug collides with an existing file: abort rename, keep old slug, log warning.
- If the title change is minor (<50% word difference): keep existing slug.

#### 4.4.7 Error Output Format

On validation failure:
```
VALIDATION_ERROR
field: content.status
expected: one of ["proposed", "accepted", "deprecated", "superseded"]
got: "active"
fix: Change content.status to a valid enum value
```

#### 4.4.8 Write-Path Protection (PreToolUse Block + PostToolUse Guardrail)

Two hooks work together to prevent bypassing `memory_write.py`:

**Primary defense: PreToolUse hook** (`memory_write_guard.py`, ~20 lines)

A PreToolUse hook on the Write tool that **blocks** any write whose resolved path falls under `.claude/memory/` (all files, not just `*.json`). This prevents the LLM from directly writing memory JSON files, `index.md`, or any other artifact in the memory directory. All writes to memory storage MUST go through `memory_write.py` (via Bash).

**Hook configuration** (hooks.json):
```json
{
  "PreToolUse": [
    {
      "matcher": "Write",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write_guard.py\"",
          "timeout": 5,
          "statusMessage": "Checking memory write path..."
        }
      ]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "Write",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_validate_hook.py\"",
          "timeout": 10,
          "statusMessage": "Validating memory file..."
        }
      ]
    }
  ]
}
```

**PreToolUse hook logic** (`memory_write_guard.py`):
1. Check if the Write tool's target path resolves to anything under `.claude/memory/`.
2. If YES: Return `{"ok": false, "error": "Direct writes to .claude/memory/ are blocked. Use memory_write.py via Bash instead: python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action <create|update|delete> ..."}`.
3. If NO: Return `{"ok": true}` (allow non-memory writes).

**Secondary guardrail: PostToolUse hook** (`memory_validate_hook.py`, ~80 lines)

A PostToolUse hook that runs Pydantic schema validation as a **detection-only** fallback. This catches edge cases where the PreToolUse hook might not fire (e.g., Write tool invoked through an unexpected code path).

**PostToolUse hook logic** (`memory_validate_hook.py`):
1. Check if written path matches `.claude/memory/**/*.json` (skip non-memory writes).
2. Read the just-written file.
3. Run the same Pydantic validation as `memory_write.py`.
4. If VALID: `{"ok": true}` (log warning that the write bypassed PreToolUse).
5. If INVALID: **quarantine** the invalid file by renaming to `<slug>.json.invalid.<timestamp>` (preserves evidence). Return `{"ok": false, "error": "Schema validation failed: <details>. Use memory_write.py instead."}`. If a valid version of the file existed before the Write (detected via index.md entry), log a warning: the quarantine preserves the invalid write but the previously valid content was already overwritten by the Write tool.

**Important**: The PostToolUse hook is a **detection-only guardrail**, not a defense. It cannot prevent data loss from a direct Write -- it can only detect and quarantine invalid writes after the fact. The PreToolUse block is the primary defense that eliminates the bypass path entirely. The PostToolUse hook cannot enforce merge invariants (subset checks, append-only changes, immutable fields) because it has no access to the pre-write file state.

### 4.5 The CRUD Action Model

Every consolidation operation (except session summaries) is classified into exactly one CUD action.

| Action | When to Use | What Happens |
|--------|-------------|-------------|
| **CREATE** | No matching candidate, OR new info is genuinely distinct from candidate | Create new file, add to index |
| **UPDATE** | Candidate exists and new info modifies, extends, or corrects it | Read file, integrate new info with merge rules, write back with change log |
| **DELETE** | Lifecycle event + matching candidate + candidate's **entire subject** is obsolete | Set `record_status` to "retired", add retired_at/retired_reason, remove from index, keep file |

**Default bias -- UPDATE over DELETE**: When uncertain, always prefer UPDATE. UPDATE is non-destructive. A memory that should have been deleted but was updated costs a few extra tokens. A memory that should have been updated but was deleted loses active knowledge.

**Partial obsolescence**: If only part of a memory's content is obsolete, use UPDATE to remove the obsolete parts. DELETE is only for when the entire subject is no longer relevant.

**RECLASSIFY procedure**: When a memory is in the wrong category, use a two-step process: (1) CREATE in the correct category with full change log and a reclassification note, (2) RETIRE the old memory. For v1, this is manual; `/memory --reclassify` deferred to v1.1.

### 4.6 DELETE Detection: Extended Triage Hooks

Each of the 6 category hooks gains an optional `lifecycle_event` field and a `cud_recommendation` field.

**`lifecycle_event` values** (enum, optional, defaults to null):

| Value | Meaning | Write-Phase Bias |
|-------|---------|-----------------|
| `null` | No lifecycle change | CREATE or UPDATE |
| `"resolved"` | Issue/debt/problem was fixed | DELETE candidate |
| `"removed"` | System/dependency decommissioned | DELETE candidate |
| `"reversed"` | Decision/preference reversed | UPDATE preferred |
| `"superseded"` | Replaced by something new | UPDATE preferred |
| `"deprecated"` | No longer recommended/supported | DELETE candidate |

**Important**: Both `lifecycle_event` and `cud_recommendation` are **hints**, not binding actions. The write phase (Layer 3) makes the final decision after reading the candidate and comparing with all three layers.

**Detection heuristics for triage hooks**:

Strong deletion signals (high confidence):
- "We fixed/resolved [X]" + X matches a known memory subject
- "We removed/decommissioned/dropped [X]"
- "[X] is no longer needed/relevant/applicable"

Weak signals (prefer UPDATE):
- "We changed from X to Y" -> UPDATE
- "X was wrong, it's actually Y" -> UPDATE with correction
- "We decided against X" -> UPDATE with new status

Not deletion signals:
- "Project X is complete" (context remains valuable)
- "Let's move on from X" (historical context valuable)

### 4.7 Uniform Lifecycle Strategy

All non-session categories use the same consolidation strategy: **CRUD lifecycle with change log**.

**Category DELETE eligibility** (hard-gated in `memory_candidate.py`, not LLM guidance):

| Category | Triage-initiated DELETE? | User-initiated DELETE? | Preferred alternative |
|----------|------------------------|----------------------|----------------------|
| tech_debt | **Yes** | **Yes** | -- |
| constraint | **Yes** | **Yes** | -- |
| runbook | **Yes** | **Yes** | UPDATE with "deprecated" status |
| decision | **No** (hard gate) | **Yes** (via /memory --retire only) | UPDATE with reversal in change log |
| preference | **No** (hard gate) | **Yes** (via /memory --retire only) | UPDATE with new value |
| session_summary | **No** (rolling window) | **No** | Rolling window handles lifecycle |

### 4.8 Candidate Selection Details

`memory_candidate.py` selects the **best matching entry** in the **same category** using:

1. **Keyword overlap**: Tokenize `new_info`, score against index entry titles (2 points per exact word match).
2. **Tag overlap**: Score against tags in enriched index lines (3 points per tag match).
3. **Prefix matching**: Partial matches for words with 4+ characters (1 point).
4. **Threshold**: Score >= 3 points to qualify as a candidate.
5. **Single candidate** (max 1): If the best match doesn't qualify, action is CREATE.

**Category filtering**: Always filter to target category. At 200 entries across 6 categories, this means evaluating ~30-50 entries per save.

**DELETE target resolution**: For DELETE triggered by a lifecycle event, candidate selection is the same. If no candidate is found, action is **NOOP** (not CREATE). The lifecycle event is logged for observability.

### 4.9 Enriched Index Format

**Current**:
```
- [DECISION] ADR-003: Split into 3 repos -> .claude/memory/decisions/adr003-repo-split.json
```

**Proposed**:
```
- [DECISION] ADR-003: Split into 3 repos -> .claude/memory/decisions/adr003-repo-split.json #tags:architecture,repository,deployment
```

- All tags included, not just top 3.
- `#tags:` delimiter (curly braces would break the parser).
- Comma-separated, no spaces.
- When a memory is retired, its index line is **removed entirely**.

### 4.10 Field-Level Merge Rules (UPDATE)

| Field Type | Merge Rule | Enforcement |
|-----------|-----------|-------------|
| Scalar (string, number, boolean) | Last-Writer-Wins; record old/new in change log | `memory_write.py` auto-generates change log entry |
| Tag array | Grow-only union; cap at 12; eviction allowed at cap | `memory_write.py` subset check with eviction policy (see below); dedupes and sorts |
| File reference array | Grow-only union; dangling path cleanup allowed | `memory_write.py` subset check: rejects removal of paths pointing to existing files (path-normalized); allows removal of paths pointing to non-existent files (dangling references); dedupes |
| Content list (array) | Append new, keep all existing | `memory_write.py` warns if count decreases |
| Prose field (long string) | LLM semantic merge | LLM responsibility; change log records old text |
| `created_at`, `schema_version`, `category`, `id`, `record_status` | Immutable (except via `--action delete`/archive) | `memory_write.py` rejects changes; lifecycle transitions only via dedicated action flags |
| `changes[]` | Append only | `memory_write.py` requires new entry |

**Tag cap at 12 with eviction policy**: Grow-only semantics prevent accidental loss during normal updates. When the tag count is already at cap (12) and an UPDATE adds new tags, the following eviction policy applies:

1. **Below cap** (`len(old_tags) < 12`): Standard subset check -- `set(old_tags) <= set(new_tags)` must hold. No tag may be removed.
2. **At cap** (`len(old_tags) >= 12`): The LLM may evict tags to make room for new ones. `memory_write.py` validates: `set(old_tags) - set(new_tags)` (evicted tags) must be non-empty only if `len(new_tags) + len(evicted)` would have exceeded 12. The resulting set must satisfy `len(new_tags) <= 12`. Evicted tags are logged in `changes[]` with `field: "tags"`, `old_value: [evicted list]`, `new_value: [added list]`.
3. **No net shrink without addition**: If no new tags are being added, no tags may be removed regardless of count. This prevents accidental tag loss during content-only updates.

**Known limitation**: Eviction selection relies on LLM judgment of tag relevance. The mechanical check prevents *accidental* drops (below cap) and enforces the cap constraint, but it cannot prevent intentional context replacement at cap. This is acceptable because: (a) tags are retrievable from `changes[]` history, (b) the LLM must be adding new tags to evict old ones, and (c) the cap itself limits total tag count.

### 4.11 Session Rolling Window

Session summaries use a distinct strategy: keep last 5 sessions (configurable via `memory-config.json`), delete oldest when limit exceeded.

**Session deletion guard**: Before deleting the oldest session, compare its key content against the main index. If any item appears to be a decision, constraint, or tech debt not captured elsewhere, flag with a warning in stderr.

---

## 5. Change Log Schema

### 5.1 New Fields (Added to Base Schema)

```json
{
  "record_status": {
    "type": "string",
    "enum": ["active", "retired", "archived"],
    "default": "active",
    "description": "System lifecycle status (top-level, distinct from content.status)"
  },
  "changes": {
    "type": "array",
    "description": "Append-only log of changes to this memory",
    "items": {
      "type": "object",
      "required": ["date", "summary"],
      "properties": {
        "date": { "type": "string", "format": "date-time" },
        "summary": { "type": "string", "maxLength": 300 },
        "field": { "type": "string" },
        "old_value": {},
        "new_value": {}
      }
    },
    "maxItems": 50
  },
  "times_updated": { "type": "integer", "default": 0 },
  "retired_at": { "type": "string", "format": "date-time" },
  "retired_reason": { "type": "string", "maxLength": 300 },
  "archived_at": { "type": "string", "format": "date-time" },
  "archived_reason": { "type": "string", "maxLength": 300 }
}
```

- `changes[]` with FIFO overflow at 50 entries (oldest dropped; enforced by `memory_write.py`)
- `retired_at`/`retired_reason` set only during DELETE; `archived_at`/`archived_reason` set only during archive
- CREATE does not add a change log entry (changes array starts empty)

**Timestamp format**: All temporal fields (`created_at`, `updated_at`, `changes[].date`, `retired_at`, `archived_at`) use RFC 3339 datetime format (e.g., `2026-02-14T09:30:00Z`). This is unified across the schema -- no date-only fields.

### 5.2 Lifecycle Status: `record_status` (Top-Level)

The lifecycle of a memory record is tracked by a **top-level** `record_status` field, separate from any category-specific `content.status`.

```json
{
  "record_status": {
    "enum": ["active", "retired", "archived"],
    "default": "active"
  }
}
```

**Two distinct status fields**:
- **`record_status`** (top-level): System lifecycle -- controls indexing, retrieval visibility, and GC eligibility. Applies uniformly to all categories. Managed by `memory_write.py`.
- **`content.status`** (inside `content`): Category-specific domain state. Only defined for categories that need it (e.g., decisions: `proposed|accepted|deprecated|superseded`). `content.status` MUST NOT contain lifecycle values (`retired`, `archived`).

| `record_status` | Behavior |
|-----------------|----------|
| active | Indexed and retrievable (default for all new memories) |
| retired | Excluded from index; GC-eligible after 30-day grace period |
| archived | Excluded from index; NOT GC-eligible (preserved indefinitely) |

**Lifecycle state machine** (governs `record_status`):
```
          +-------------------+
          |      active       |<---------+
          |                   |          |
          +----+--------+-----+          |
               |        |               |
     DELETE    |        | /memory       |
     action    |        | --archive     |
               v        v               |
     +---------+  +------------+        |
     | retired |  |  archived  |        |
     +---------+  +------------+        |
          |              |               |
     --gc |     /memory --unarchive     |
          v              +---------------+
     +---------+
     | purged  |
     +---------+
```

**Invariants**:
- When `record_status == "retired"`: `retired_at` and `retired_reason` MUST be present and non-null. `archived_at`/`archived_reason` MUST be absent.
- When `record_status == "archived"`: `archived_at` and `archived_reason` MUST be present and non-null. `retired_at`/`retired_reason` MUST be absent.
- When `record_status == "active"`: All four lifecycle timestamp/reason fields MUST be absent.
- `--unarchive` sets `record_status = "active"`, clears `archived_at`/`archived_reason`, and records the transition in `changes[]`.

### 5.3 Backward Compatibility

All new fields are optional with sensible defaults. Existing files remain valid without modification. When the LLM next updates an existing memory, it adds the new fields ("lazy migration"). Code reading these fields uses defensive access (`get('changes', [])`).

---

## 6. Concurrency Safety

### 6.1 Optimistic Concurrency Control (OCC)

The write step uses OCC with file locking, handled entirely by `memory_write.py`:

```python
def safe_write_memory(index_path, memory_path, index_hash_before, memory_hash_before=None):
    with open(index_path, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            current_hash = hashlib.md5(f.read().encode()).hexdigest()
            if current_hash != index_hash_before:
                return False, "Index changed during operation"

            if memory_hash_before and os.path.exists(memory_path):
                with open(memory_path, 'rb') as mf:
                    if hashlib.md5(mf.read()).hexdigest() != memory_hash_before:
                        return False, "Memory file changed by concurrent session"

            # Both checks passed -- safe to write
            # ... write memory file (atomic: tmp + rename), update index ...
            return True, "Success"
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
```

Max 1 retry; if still conflicted: CREATE with warning (for UPDATE failures), skip entirely (for DELETE failures).

**Lock scope invariant**: The index flock MUST enclose the entire transaction: hash checks, memory file write, and index update. No writes to memory files or index.md may occur outside the locked region.

**Platform note**: `fcntl` is Unix-only. Platform check with no-op fallback on other platforms.

### 6.2 Atomic File Writes

Memory JSON files are written atomically: write to `<slug>.json.tmp`, then `os.rename()`. This prevents partial writes on interruption.

**Crash recovery**: `--rebuild` recovers orphaned files and detects retired memories not yet removed from index.

### 6.3 DELETE Concurrency

| Race | Resolution |
|------|-----------|
| DELETE vs UPDATE | DELETE wins if first; UPDATE retries, sees `record_status == "retired"`, abandons |
| DELETE vs DELETE | First wins; second returns success (idempotent) |
| UPDATE first, then DELETE | DELETE retries, reads updated file, confirms obsolescence, retires |

### 6.4 Anti-Resurrection Protection

After a DELETE removes the index entry, a concurrent UPDATE might fall back to CREATE (since the entry is gone). To prevent this:
- Before committing a CREATE, check whether a file with `record_status == "retired"` and `retired_at` within the last **24 hours** exists at the computed path.
- If found, suppress the CREATE with a warning.

### 6.5 Rename Atomicity

File renames during UPDATE (Section 4.4.6) follow this sequence:
1. Write new content to `<new-slug>.json.tmp`
2. Rename `.tmp` to `<new-slug>.json`
3. Update index.md (remove old line, add new line) under flock
4. Delete old file `<old-slug>.json`

If the process crashes between steps 2 and 4, both files exist. `--rebuild` detects the duplicate (same content, different slugs) and resolves by keeping the newer file.

---

## 7. Enhanced Retrieval

### 7.1 Scoring Changes

```python
def score_entry(entry, prompt_words):
    tags = parse_tags(entry)        # from #tags: suffix
    entry_words = tokenize(title)    # from entry title

    exact_title = len(prompt_words & entry_words) * 2
    exact_tags = len(prompt_words & tags) * 3
    prefix_matches = count_prefix_matches(prompt_words, entry_words | tags)
    recency_bonus = 1 if is_recent(entry, days=30) else 0

    return exact_title + exact_tags + prefix_matches + recency_bonus
```

Key changes from current:
- Tags parsed from `#tags:` suffix, scored at 3 points (vs 2 for title words)
- Prefix matching applies to tags as well
- Recency bonus: +1 for memories updated within 30 days
- Retired memories excluded (index line removed by DELETE)

### 7.2 Index Rebuild

`memory_index.py --rebuild`:
- Glob `*.json` in each category directory
- Read tags from JSON files, append `#tags:tag1,tag2,...`
- Skip files with `record_status == "retired"` or `"archived"`

---

## 8. Implementation Plan

### Phase 1: Python Tools + Schema Enforcement

1. **`memory_candidate.py`** (~150 lines): Mechanical candidate selection + structural verification. Reuses `memory_retrieve.py` scoring logic.
2. **`memory_write.py`** (~250-300 lines): Schema validation (Pydantic models for all 6 categories), mechanical merge protections, OCC, atomic writes, index management, slug rename, change log auto-generation.
3. **`memory_write_guard.py`** (~20 lines): PreToolUse hook that blocks direct Write tool access to `.claude/memory/`.
3b. **`memory_validate_hook.py`** (~80 lines): PostToolUse detection-only guardrail.
4. **Base schema updates**: Add `record_status` (top-level lifecycle field, default "active"), `changes`, `times_updated`, `retired_at`, `retired_reason`, `archived_at`, `archived_reason`. Category-specific `content.status` enums remain unchanged.
5. **Triage hook extension**: Add `lifecycle_event` + `cud_recommendation` to each hook's output (~60-80 tokens per hook).
6. **SKILL.md rewrite**: Replace 6-step flowchart with 3-step Python-tool-centric instructions + CUD verification protocol.
7. **`memory-config.json`**: Add `delete.grace_period_days` (30), `delete.archive_retired` (true).

### Phase 2: Enhanced Retrieval

1. **`memory_retrieve.py`**: Parse `#tags:` from index lines, score at 3 points, add recency bonus.
2. **`memory_index.py --validate`**: Add desync detection.

### Phase 3: Session Rolling Window

1. Keep last 5 sessions, delete oldest when exceeded.
2. Deletion guard for unique content.
3. `memory-config.json`: Add `categories.session_summary.max_retained` (5).

### Phase 4: Observability

1. **`/memory`**: Show total by category, high-update memories, recent retirements, index health.
2. **`memory_index.py --health`**: Report counts, heavily-updated, desync, retirement activity.
3. **`memory_index.py --gc`**: Garbage collect retired memories past 30-day grace period.
4. **`/memory --retire <slug>`**: User-initiated retirement (only path for decisions/preferences).
5. **`/memory --archive <slug>`** and **`--unarchive <slug>`**: Shelve/restore memories.
6. **`/memory --restore <slug>`**: Restore retired memory within grace period. Staleness warning after 7 days.
7. **`/memory --list-archived`**: List all archived memories.

### Implementation Sequence

```
Phase 1 (Python Tools + Schema + Triage + SKILL.md)
    |
    +---> Phase 2 (Retrieval)     [parallel]
    |
    +---> Phase 3 (Sessions)      [parallel]
              |
              v
         Phase 4 (Observability)  [after Phase 3]
```

---

## 9. Token Cost Analysis

### 9.1 v4.0 Architecture Token Costs

The Python-tool-centric architecture significantly reduces per-save token costs by removing index.md from the LLM's context and mechanizing candidate selection.

#### Path A: No Candidate (CREATE) -- ~50-70% of saves

| Component | Tokens |
|-----------|--------|
| 6 triage hooks (with lifecycle + CUD) | ~1,080-1,140 |
| memory_candidate.py (Python, no LLM tokens) | 0 |
| SKILL.md loaded on write | ~1,200 |
| LLM drafts new memory JSON | ~300-500 |
| memory_write.py (Python, no LLM tokens) | 0 |
| Write to temp + Bash call overhead | ~50 |
| **Total per CREATE** | **~2,630-2,890** |

#### Path B: Candidate Found, Layers Agree -- ~25-40% of saves

| Component | Tokens |
|-----------|--------|
| 6 triage hooks (with lifecycle + CUD) | ~1,080-1,140 |
| memory_candidate.py (Python, no LLM tokens) | 0 |
| SKILL.md loaded on write | ~1,200 |
| LLM reads candidate structured excerpt (from L1) | ~300-500 |
| LLM reads candidate file (for UPDATE) | ~500-1,000 |
| LLM CUD decision + comparison output | ~100-150 |
| LLM drafts updated memory JSON | ~300-500 |
| memory_write.py (Python, no LLM tokens) | 0 |
| Write to temp + Bash call overhead | ~50 |
| **Total per UPDATE/DELETE** | **~3,530-4,540** |

#### Path C: Candidate Found, Layers Disagree -- ~5-10% of saves

Same as Path B, plus ~50-100 tokens for disagreement resolution reasoning.

| **Total per disagreement** | **~3,580-4,640** |

### 9.2 Comparison with v3.2

| Scenario | v3.2 | v4.0 | Savings |
|----------|------|------|---------|
| CREATE (no candidate) | ~6,730-6,890 | ~2,630-2,890 | **~60% reduction** |
| UPDATE (candidate found) | ~6,730-6,890 | ~3,530-4,540 | **~35-50% reduction** |
| DELETE | ~6,430-6,490 | ~3,530-4,540 | **~30-45% reduction** |

**Why the massive savings**: The v3.2 design required the LLM to read the entire index.md (~3,500 tokens at 100 entries, ~7,000 at 200). The v4.0 design removes this entirely -- `memory_candidate.py` reads the index mechanically (zero tokens) and returns only the best candidate's structured excerpt (~300-500 tokens, varying by category complexity). These are design-time estimates; actual token costs should be measured against a real index during implementation and the cost tables updated.

### 9.3 At Scale (200 entries)

| Component | v3.2 (200 entries) | v4.0 (200 entries) |
|-----------|-------------------|-------------------|
| Index read cost | ~7,000 (LLM reads full index) | 0 (Python reads index) |
| Candidate excerpt | N/A (LLM selects) | ~300-500 (from tool output) |
| Total per save | ~9,930-10,390 | ~2,630-4,540 |

The v4.0 design **does not scale with entry count** for the LLM's token budget. The Python tool handles index scaling; the LLM's cost is constant regardless of whether there are 50 or 500 entries.

### 9.4 Verification Overhead

The three-layer CUD verification adds ~300-350 tokens per save:
- Layer 1 (Python): 0 tokens
- Layer 2 (Sonnet CUD in triage): ~0-30 tokens additional output per hook
- Layer 3 (Opus comparison): ~100-150 tokens
- SKILL.md verification rubric: ~200 tokens

This is negligible compared to the ~3,500-7,000 token savings from removing index.md from the LLM context.

### 9.5 Over a Project Lifecycle

8-week project (~40 sessions, ~3 saves/session = ~120 saves):
- v3.2: ~120 * ~6,800 = ~816K tokens
- v4.0: ~120 * ~3,400 (weighted average) = ~408K tokens
- **Savings: ~408K tokens (~50%)**

---

## 10. Comparison Matrix

| Dimension | Current System | ACE v3.2 | ACE v4.0 |
|-----------|---------------|----------|----------|
| **Architecture** | LLM-interpreted | LLM follows flowchart | Python tools + LLM minimal decisions |
| **Candidate selection** | LLM reads full index | LLM reads full index | Python scores mechanically (zero-token) |
| **CUD decision** | N/A (binary update/create) | LLM follows rubric (single check) | Three-layer verification (Python + Sonnet + Opus) |
| **Schema enforcement** | None | None | Pydantic validation + PreToolUse write-path block + PostToolUse guardrail |
| **Merge rules** | LLM decides everything | LLM follows rubric | Python enforces mechanically |
| **Write actions** | 2 (update/create) | 3 (CUD with rubric) | 3 (CUD with mechanical enforcement) |
| **Information preservation** | Silent overwrite | Change log | Change log + mechanical merge protections |
| **Tag utilization** | Written, never read | All tags in index | All tags in index (unchanged) |
| **Session handling** | Hard overwrite | Rolling window (5) | Rolling window (5) (unchanged) |
| **Concurrency** | None | OCC | OCC (unchanged, now in memory_write.py) |
| **DELETE safety** | N/A | Soft delete + grace | Soft delete + three-layer verification + hard gates |
| **File rename on UPDATE** | N/A | N/A | Automatic slug regeneration |
| **Token cost (per save, 100 entries)** | ~3,900 | ~6,730-6,890 | ~2,630-4,540 |
| **Token cost (per save, 200 entries)** | ~5,400 | ~9,930-10,390 | ~2,630-4,540 |

---

## 11. Decided Parameters

All open questions from v3.2 have been decided by the founder.

| Parameter | Decision | Value | Rationale |
|-----------|----------|-------|-----------|
| Q1: Session Rolling Window | **5** | `memory-config.json: categories.session_summary.max_retained = 5` | Balances context preservation vs storage |
| Q2: Tag Cap | **12** | Maximum tags per memory | Balances preservation vs retrieval precision |
| Q3: Recency Bonus | **+1 (30 days)** | Memories updated within 30 days get +1 retrieval score | Simple, predictable, easy to debug |
| Q4: Category Filtering | **Always** | Candidate selection always filters to target category | Reduces noise, bounded evaluation set |
| Q5: DELETE Policy | **Option A (Hybrid)** | Triage hints + write-phase validation + dual independent verification | Catches clear lifecycle events; strong evidence threshold prevents false positives |
| Q6: Soft Delete Grace | **30 days** | `memory-config.json: delete.grace_period_days = 30` | Ample recovery window; tiny files |
| Q7: DELETE Confirmation | **Option A (No extra)** | Write phase executes without extra confirmation; soft delete is safety net | Three-layer verification + soft delete makes interactive confirmation unnecessary |
| Q8: Anti-Resurrection | **24 hours** | Window for preventing re-creation of retired memory | Catches concurrent races without permanently blocking re-creation |

---

## 12. Trade-offs and Risks

### Accepted Trade-offs

| Trade-off | What We Gain | What We Pay |
|-----------|-------------|-------------|
| Single candidate instead of 3 | Lower token cost | May miss a true match if best index match is wrong |
| CUD instead of 4 actions | Reliable LLM compliance | One more decision boundary vs binary (defended by 3-layer verification) |
| Uniform lifecycle for all categories | Simpler instructions; one code path | Decisions don't get category-specific audit trails |
| Tag cap at 12 | Retrieval precision | May lose context tags after many merges |
| Pydantic dependency | Robust schema enforcement for 6 categories | ~2MB external dependency |
| Python-owned mechanics | LLM can't make mechanical errors | Two new Python scripts to maintain (~400 lines total) |
| Keyword-based candidate selection | Zero-token, deterministic | Misses semantic similarity ("error" vs "bug") |
| Dangling related_files cleaned up on next UPDATE | Automatic cleanup without full cross-reference repair tooling | Brief window of stale references until next UPDATE of referring memories |

### Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| LLM bypasses memory_write.py, uses Write directly | High | Very Low | PreToolUse hook blocks all writes to `.claude/memory/`; PostToolUse guardrail as fallback detection |
| memory_candidate.py misses true match (keyword gap) | Medium | Medium | Three-layer verification catches; Opus sees candidate content; duplicates are safe (vs data loss) |
| All 3 CUD layers agree on wrong action | High | Very Low | Three independent checks with different failure modes; unanimous wrong agreement extremely unlikely |
| Pydantic version incompatibility | Low | Low | Pin to pydantic>=2.0,<3.0; stable API |
| Auto-fix silently alters LLM intent | Low | Low | Auto-fixes limited to trivially correct changes; all logged to stderr |
| File rename creates dangling references | Low | Medium | Dangling paths cleaned up automatically during next UPDATE (non-existent paths removable); proactive repair tooling in v1.1 |
| Slug collision on rename | Low | Low | Abort rename, keep old slug, log warning |
| Anchoring bias (Opus influenced by Sonnet hint) | Medium | Medium | Known v1 limitation (see Section 4.3); safety defaults are the real protection; v1.1 plans architectural fix |
| LLM incorrectly retires valuable memory | High | Very Low | Three-layer verification + soft delete + 30-day grace + hard-gated categories |

### What This Does NOT Solve

1. **Semantic similarity**: "error" vs "bug" remain unrelated in keyword matching (requires embeddings).
2. **Perfect dedup**: LLM-interpreted dedup will never be 100% reliable.
3. **Cross-project memory sharing**: Memories are per-project.
4. **Cascading deletes**: Deleting a decision does not auto-retire related constraints.
5. **Composite operations**: MERGE, SPLIT, BULK RETIRE require manual multi-pass in v1.

---

## 13. Future Work (v1.1+)

### 13.1 Category-Specific Write Strategies
Different consolidation strategies per category. **Trigger**: When uniform CRUD produces incorrect results for a specific category.

### 13.2 Leech Detection
Stability state machine for memories corrected 3+ times. **Trigger**: When `times_updated` shows flip-flopping.

### 13.3 Cross-Category Links (`related_records`)
Typed links between memories across categories. **Trigger**: When link maintenance tooling is implemented.

### 13.4 Mechanical List Merge Protection (`memory_patch.py`)
Python script for delta-only list operations. **Trigger**: Any confirmed list truncation during UPDATE.

### 13.5 History Compaction
Compact oldest change log entries into summary. **Trigger**: High-churn memories regularly hit 50-entry cap.

### 13.6 Semantic Similarity
Embedding-based retrieval. **Trigger**: When the plugin considers optional dependencies.

### 13.7 DELETE Policy Automation
Stronger deletion detection, confidence scoring, staging area. **Trigger**: When manual deletion becomes burdensome.

### 13.8 GC Automation
Automated purge of retired files past grace period. **Trigger**: When retired file count exceeds 50.

### 13.9 Dangling Reference Detection + Repair
After DELETE or rename, scan and repair `related_files` entries. **Trigger**: When cross-category links (13.3) are implemented.

### 13.10 Reclassify Command
`/memory --reclassify <slug> --to <category>`. **Trigger**: Frequent category misclassifications.

### 13.11 Composite Actions (MERGE, SPLIT)
First-class compound CUD operations. **Trigger**: Duplicate accumulation or over-broad memories.

### 13.12 Bulk Retire Command
`/memory --bulk-retire --query <term>`. **Trigger**: Subsystem decommissioning events.

### 13.13 Embedding-Enhanced Candidate Selection
Augment keyword-based `memory_candidate.py` with optional embedding similarity for synonym matching. **Trigger**: When false-negative candidate selection (keyword gaps) causes measurable duplication.

### 13.14 Confidence-Based Verification Escalation
Add an optional extra Sonnet verifier call for DELETE-only or low-confidence cases. **Trigger**: If three-layer verification proves insufficient for DELETE accuracy.

---

## Appendix A: Cross-Model Validation Summary

### v4.0 Refinement Validation

| Agent | Focus | Cross-Model Check | Key Recommendation |
|-------|-------|-------------------|-------------------|
| Algorithm Simplifier | Section 4.1 simplification | Codex (planner), Gemini Flash | C+D hybrid: Python owns mechanics, LLM answers one question |
| Schema Designer | memory_write.py design | Gemini Flash (planner), Gemini Pro (thinkdeep) | Two-layer defense: write helper + PostToolUse hook; Pydantic from v1 |
| Verification Designer | Three-layer CUD verification | Gemini Flash, Codex (planner) | Design B (Python structural + Sonnet triage + Opus independent) over dual Sonnet calls |
| Integration Agent | Architecture reconciliation | Codex (planner) | Adopt Design B backbone; merge candidate/verify into one tool; no extra Sonnet calls |

### Architecture Reconciliation (Codex Planner)

The algorithm simplifier proposed two independent Sonnet calls for CUD verification. The verification designer proposed three layers (Python + Sonnet triage hint + Opus). Codex planner recommended:

1. **Adopt three-layer approach** (reuses existing hooks, near-zero marginal cost)
2. **Merge candidate selection + structural verification** into one Python tool
3. **No extra Sonnet calls** beyond existing triage hooks
4. **Optional DELETE-specific Sonnet verifier** deferred to v1.1 if needed

### Prior Validation (v1.0 through v3.2)

All prior cross-model validations remain relevant. Key consensus points:

| Decision | Claude | Gemini | Codex |
|----------|--------|--------|-------|
| Python owns mechanics, LLM minimal decisions | Agree (v4.0) | Agree | Agree |
| Pydantic for schema enforcement | Agree (v4.0) | Agree | Agree |
| Three-layer CUD verification | Agree (v4.0) | Agree | Agree |
| Soft DELETE with grace period | Agree | Agree | Agree |
| Uniform lifecycle strategy | Agree | Agree | Agree |
| OCC in v1 | Agree | Agree (critical) | Agree (critical) |
| Tag cap at 12 | Agree | Agree | Agree |
| Default UPDATE bias over DELETE | Agree | Agree | Agree |
| Hard-gated category DELETE eligibility | Agree | Agree | Agree |

---

## Appendix B: SKILL.md Instructions (Replacement for Section 4.1)

The following replaces the 6-step flowchart in SKILL.md:

```markdown
## Memory Consolidation

When a triage hook fires with a save instruction:

### 1. Find Candidate
Call `memory_candidate.py` with the category and new information summary.
You will receive one of:
- `pre_action: "CREATE"` -- no matching memory exists. Skip to step 3.
- `pre_action: "NOOP"` -- lifecycle event but no matching memory. Do nothing.
- `candidate: {...}` -- a potential match was found. Proceed to step 2.

### 2. CUD Verification (decide-then-compare)
You have three assessments:
- L1 (STRUCTURAL): From memory_candidate.py output (structural_cud, vetoes).
- L2 (TRIAGE): From triage hook output (cud_recommendation).
- L3 (YOUR DECISION): Form your OWN CUD decision FIRST by reading the
  candidate excerpt. Only THEN compare with L1 and L2.

RESOLUTION RULES:
- If L1 has vetoes -> OBEY the veto (mechanical trumps LLM)
- If all 3 agree -> Proceed with agreed action
- If you disagree with L2:
  - CREATE vs UPDATE -> UPDATE (preserves existing)
  - UPDATE vs DELETE -> UPDATE (non-destructive)
  - CREATE vs DELETE -> NOOP (contradictory signals)
- State: "CUD: [ACTION] (L1:[x], L2:[y], L3:[z] [resolution])"

### 3. Execute
Based on the action:
- **CREATE**: Draft a new memory JSON following the schema.
  Write to `/tmp/.memory-write-pending.json`.
  Call `memory_write.py --action create --category <cat> --target <path>
  --input /tmp/.memory-write-pending.json`.
- **UPDATE**: Read the candidate file. Integrate new info (tags: union,
  lists: append, scalars: update). Write complete updated JSON to
  `/tmp/.memory-write-pending.json`.
  Call `memory_write.py --action update --category <cat> --target <path>
  --input /tmp/.memory-write-pending.json`.
- **DELETE**: Call `memory_write.py --action delete --target <path>
  --reason "<why>"`. Do not write a temp file for DELETE.

State your chosen action and one-line justification before calling
memory_write.py.
```

---

## Appendix C: Change History

### What Changed from v4.0 to v4.1 (R1 Fixes)

**Source**: 2 independent R1 reviews (simplicity + engineering) with Codex cross-validation.

#### Must-Fix (3 items, all applied)
1. **Array merge validation**: Changed from length-based (`len(new) >= len(old)`) to subset-based (`set(old) <= set(new)`) with case-normalization for tags and path-normalization for files. Also enforces mechanical dedupe+sort before write. (Sections 4.4.4, 4.10)
2. **PostToolUse hook quarantine**: Changed from "delete invalid file" to "quarantine as `<slug>.json.invalid.<timestamp>`". Documented that PostToolUse runs after the Write, so prior valid content is already overwritten; added v1.1 plan for PreToolUse snapshot+restore. (Section 4.4.8)
3. **Pydantic v2 syntax**: Changed `class Config: extra = "forbid"` to `model_config = ConfigDict(extra="forbid")`. Added `ConfigDict` to import. (Section 4.4.3)

#### Should-Fix (4 items, all applied)
4. **OCC --hash parameter**: Added `--hash <md5>` parameter to UPDATE CLI invocation so the LLM passes the hash of the version it read. (Section 4.4.1)
5. **Lock scope invariant**: Added explicit statement: "The index flock MUST enclose the entire transaction." (Section 6.1)
6. **Anti-anchoring honesty**: Documented that decide-then-compare is instructional, not architectural. L3 independence is aspirational for v1; real protections are mechanical vetoes and safety defaults. Added v1.1 plan for evidence-separated tool invocation. (Section 4.3, Section 12 risks table)
7. **Unified timestamps**: Changed `changes[].date`, `retired_at`, and `archived_at` from `format: "date"` to `format: "date-time"` (RFC 3339). Added unification note. (Section 5.1)

#### From Simplicity Review (1 item, applied)
8. **Structured candidate excerpt**: Changed from "first 500 chars" raw text to structured object `{title, record_status, tags, last_change_summary, key_fields}` for better L3 subject verification. (Section 4.2)

#### Consistency Updates
- Updated all "~500 chars" references to "structured excerpt"
- Updated ASCII art diagram field name
- Updated token cost table descriptions
- Added structured excerpt explanation paragraph
- Updated research basis line with R1 validation credit

### What Changed from v4.1 to v4.2 (R2 Fixes)

**Source**: 2 independent R2 reviews (holistic + adversarial) with Codex cross-validation.

#### Must-Fix (4 items, all applied)
1. **`record_status` lifecycle field**: Added top-level `record_status: Literal["active", "retired", "archived"]` (default "active") to base memory model. `content.status` is now strictly category-specific (e.g., decisions: `proposed|accepted|deprecated|superseded`). All `content.status == "retired"` references updated to `record_status == "retired"`. Pydantic model updated. Status state machine now explicitly describes `record_status`. Invariants refined with MUST-language and unarchive semantics. (Sections 4.4.3, 5.2, 6.3, 6.4, 7.2, 8)
2. **Tag eviction policy**: Defined explicit eviction policy for tags at cap (12). Below cap: standard subset check (no removal allowed). At cap: LLM may evict tags to make room for new ones; evictions logged in `changes[]`. No net shrink without addition. Resolves the deadlock between grow-only subset check and cap enforcement. (Sections 4.10, 4.4.4)
3. **PreToolUse write-path block**: Added `memory_write_guard.py` (~20 lines) as PreToolUse hook that blocks ALL writes under `.claude/memory/` (not just `*.json`), forcing all writes through `memory_write.py` via Bash. Eliminates the bypass path where schema-valid but invariant-violating writes could pass the PostToolUse hook undetected. (Section 4.4.8)
4. **Dangling `related_files` cleanup**: Changed `related_files` merge rule to allow removal of paths pointing to non-existent files (dangling references) while preserving grow-only semantics for paths pointing to existing files. Resolves the contradiction between "next UPDATE can fix" and union-only enforcement. (Sections 4.4.4, 4.4.6, 4.10)

#### Should-Fix (5 items, all applied)
5. **PostToolUse renamed**: Changed "Layer 2 Defense" to "Write-Path Guardrail (detection only)" to avoid naming collision with "Layer 2: Sonnet Triage CUD Recommendation" and to accurately reflect detection-only capability. (Section 4.4.8)
6. **Token cost correction**: Structured excerpt is ~300-500 tokens (not ~150) due to multi-field `key_fields` for complex categories. All token cost tables updated. Added note that estimates should be measured during implementation. (Sections 4.2, 9.1-9.5)
7. **Pydantic installation**: Added installation instruction (`pip install "pydantic>=2.0,<3.0"`) and startup self-check with actionable error message. (Section 4.4.3)
8. **"TRIAGE unchanged" corrected**: Changed to "extended outputs" in ASCII diagram to reflect the addition of `lifecycle_event` and `cud_recommendation` fields. (Section 1)
9. **"Reuses proven logic" softened**: Changed to "follows the same scoring approach" with note that tag-scoring extension is new code requiring its own testing. (Section 4.2)

#### Consistency Updates
- Updated all `~150 tokens` excerpt references to `~300-500 tokens`
- Updated `record_status` in candidate excerpt JSON example
- Updated immutable fields list to include `record_status` (except via dedicated action flags)
- Updated risks table: Write bypass risk reduced to "Very Low" with PreToolUse block; dangling references risk reduced to "Low"
- Updated trade-offs table for dangling references cleanup
- Updated comparison matrix for schema enforcement
- Updated research basis line with R2 validation credit
- Updated closing paragraph

### New in v4.0

- **Python-tool-centric architecture**: Core design shift from "LLM follows flowchart" to "Python tools own mechanics, LLM makes minimal decisions"
- **`memory_candidate.py`**: Mechanical candidate selection + structural verification (~150 lines). Removes index.md from LLM context entirely.
- **`memory_write.py`**: Schema-enforced writes with Pydantic validation, mechanical merge protections, OCC, atomic writes, index management (~250-300 lines)
- **`memory_validate_hook.py`**: PostToolUse detection-only guardrail (~80 lines); superseded by PreToolUse write-path block in v4.2
- **Three-layer CUD verification**: Python structural + Sonnet triage CUD hint + Opus independent decision with decide-then-compare protocol
- **Triage hook `cud_recommendation` field**: Extends existing hooks with advisory CUD classification
- **File rename on UPDATE**: When title changes significantly, slug is regenerated and file atomically renamed
- **Pydantic dependency**: Schema enforcement uses Pydantic v2 (~2MB, Rust-backed)
- **All Open Questions resolved**: Q1-Q8 moved to Decided Parameters section
- **Problem Statement expanded**: Added Examples 6 (schema violations) and 7 (single-point CUD failure)
- **Gap table expanded**: Added G13 (no schema enforcement) and G14 (single-point CUD failure)
- **Future Work expanded**: Added 13.13 (embedding-enhanced candidate selection) and 13.14 (confidence-based verification escalation)

### Removed from v3.2

- **6-step flowchart** (Section 4.1): Replaced by Python-tool-centric 3-step flow
- **LLM reads index.md**: Eliminated; Python reads index mechanically
- **LLM-only candidate selection**: Replaced by mechanical keyword/tag scoring
- **Single-point CUD decision**: Replaced by three-layer verification
- **Open Questions section**: All questions decided; moved to Decided Parameters
- **"stdlib-only" constraint**: Relaxed to allow Pydantic (~2MB) for schema enforcement

### Token Cost Impact

| Scenario | v3.2 | v4.0 | Change |
|----------|------|------|--------|
| CREATE (100 entries) | ~6,730-6,890 | ~2,630-2,890 | -60% |
| UPDATE (100 entries) | ~6,730-6,890 | ~3,530-4,540 | -35-50% |
| CREATE (200 entries) | ~9,930-10,390 | ~2,630-2,890 | -70-75% |
| UPDATE (200 entries) | ~9,930-10,390 | ~3,530-4,540 | -55-65% |

---

*This document synthesizes research from 3 parallel research tracks (codebase analysis, data systems, knowledge management), validated through 6 rounds of independent review (12 reviewers total) with cross-model checks (Claude Opus, Gemini, Codex). The v4.0 revision was produced by 3 specialized agents (algorithm simplifier, schema designer, verification designer) operating in parallel, reconciled by an integration agent with Codex planner validation. The v4.1 revision applied targeted fixes from 2 independent R1 reviewers (simplicity + engineering) with Codex clink cross-validation. The v4.2 revision applied targeted fixes from 2 independent R2 reviewers (holistic + adversarial) with Gemini/Codex cross-validation, resolving all specification gaps and internal contradictions. The architecture represents a fundamental shift from LLM-interpreted flowcharts to Python-tool-centric mechanics, reducing token costs by 35-75% while adding schema enforcement, write-path protection, and three-layer CUD verification.*
