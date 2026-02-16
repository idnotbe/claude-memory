# Parallel Per-Category LLM Triage -- Implementation Plan

**Date:** 2026-02-16
**Status:** Final (post-vibe-check + Gemini 3 Pro review)
**Version:** 1.2

---

## 1. Problem Statement

**Current flow:**
```
Stop hook (deterministic keyword heuristic)
  → blocks stop with stderr message listing categories
  → Main agent (Opus) sequentially processes each category via SKILL.md
  → For each: candidate check → CUD verification → draft JSON → save
```

**Problems:**
- Single LLM (Opus) handles all categories sequentially — slow, expensive
- No per-category model optimization (simple categories don't need Opus)
- No formal verification step after summarization
- All processing happens in one context window

**Desired flow:**
```
Stop hook (deterministic keyword heuristic)
  → blocks stop with structured output per category
  → Command prompt triggers orchestration
  → For EACH category: spawn LLM subagent with configured model
    → subagent: summarize/organize → draft JSON with CRUD awareness
  → Verify each draft with LLM
  → Save each verified memory file
```

---

## 2. Architecture Changes

### 2.1 Configuration Schema (memory-config.json)

Extend existing `triage` section with parallel processing config:

```json
{
  "triage": {
    "enabled": true,
    "max_messages": 50,
    "thresholds": { ... },
    "parallel": {
      "enabled": true,
      "category_models": {
        "session_summary": "haiku",
        "decision": "sonnet",
        "runbook": "haiku",
        "constraint": "sonnet",
        "tech_debt": "haiku",
        "preference": "haiku"
      },
      "verification_model": "sonnet",
      "default_model": "haiku"
    }
  }
}
```

**Design rationale for JSON config (not .env):**
- Consistent with existing memory-config.json pattern
- Supports structured per-category config (not possible with flat .env)
- Already has config loading + validation infrastructure
- Already has per-category defaults pattern

**Model values:** `"haiku"` | `"sonnet"` | `"opus"` — maps to Claude Code Task tool's model param.

### 2.2 Stop Hook Changes (memory_triage.py)

**Minimal changes needed.** The stop hook already:
- Reads transcript, scores categories, outputs which categories to save
- Returns snippets per category

**Changes:**
1. Add structured JSON block to stderr output (alongside human-readable text)
2. Include per-category: `category`, `score`, `snippets[]`, `cud_recommendation`
3. **Write per-category context files** to `/tmp/.memory-triage-context-<category>.txt`
   with relevant transcript excerpts (not just snippets). Subagents (especially haiku)
   need sufficient context to draft quality memories.
4. Include parallel config from memory-config.json in structured output

**Output format change:**
```
The following items should be saved as memories before stopping:

<triage_data>
{
  "categories": [
    {
      "category": "DECISION",
      "score": 0.72,
      "snippets": ["decided to use JWT because..."],
      "transcript_excerpt": "... relevant conversation fragment ..."
    },
    ...
  ],
  "config": {
    "category_models": { ... },
    "verification_model": "sonnet"
  }
}
</triage_data>

Use the memory-management skill to save each item. After saving, you may stop.
```

### 2.3 SKILL.md Rewrite (Memory Management Skill)

Major update to the "Memory Consolidation" section:

**New flow:**
1. **Parse triage output** — extract `<triage_data>` JSON block
2. **Read config** — load per-category models from memory-config.json
3. **Phase 1: Parallel Drafting** — For each triggered category:
   - Spawn Task subagent with configured model (haiku/sonnet/opus)
   - Subagent receives: category, snippets, transcript excerpt, schema template
   - Subagent runs `memory_candidate.py` for CRUD awareness
   - Subagent does CUD verification (L1 structural + L2 own decision)
   - Subagent outputs: draft JSON + CUD action + justification
   - Subagent writes draft to `/tmp/.memory-draft-<category>-<pid>.json`
4. **Phase 2: Verification** — For each draft:
   - Spawn Task subagent with `verification_model`
   - Subagent reads draft JSON
   - Checks: schema compliance, content quality, no hallucination, deduplication
   - Outputs: pass/fail with issues list
5. **Phase 3: Save** — For each verified draft:
   - Call `memory_write.py` with appropriate action (create/update/delete)
   - Handle OCC (hash-based) for updates

**CUD verification simplified to 2-layer for subagents:**
- L1 (STRUCTURAL): From memory_candidate.py output (unchanged)
- L2 (SUBAGENT DECISION): The subagent itself decides (replaces old L2+L3)
- Mechanical vetoes still absolute
- Safety defaults preserved (UPDATE > DELETE, UPDATE > CREATE)

**2-Layer CUD Resolution Table:**
| L1 (Python) | L2 (Subagent) | Resolution | Rationale |
|-------------|---------------|------------|-----------|
| CREATE | CREATE | CREATE | Agreement |
| UPDATE_OR_DELETE | UPDATE | UPDATE | Agreement |
| UPDATE_OR_DELETE | DELETE | DELETE | Structural permits |
| CREATE | UPDATE | CREATE | Structural: no candidate exists |
| CREATE | DELETE | NOOP | Cannot DELETE with 0 candidates |
| UPDATE_OR_DELETE | CREATE | CREATE | Subagent says new despite candidate |
| VETO | * | OBEY VETO | Mechanical invariant |
| NOOP | * | NOOP | No target |

**Orchestration split:**
- **Main agent (Opus)**: Orchestrates — parses triage output, spawns subagents,
  collects results, runs verification, calls memory_write.py
- **Subagents (haiku/sonnet)**: Simple task — "summarize this conversation
  context into JSON for category X" + run memory_candidate.py for CRUD awareness
- Keep subagent instructions simple for haiku reliability

**Verification severity levels:**
- **BLOCK**: Schema validation failure (missing required fields, invalid types)
- **ADVISORY**: Content quality concern, possible hallucination, dedup warning
- Advisory issues are logged but do not prevent saving

### 2.4 Default Config Changes (assets/memory-config.default.json)

Add `parallel` section to default config template.

### 2.5 Preserved Behavior

- **CRUD operations**: memory_candidate.py + memory_write.py pipeline unchanged
- **Write guard**: PreToolUse:Write hook still blocks direct writes
- **Validation**: PostToolUse:Write hook still validates after write
- **Retrieval**: UserPromptSubmit hook unchanged
- **Index**: index.md management unchanged
- **Session rolling window**: Unchanged
- **OCC/locking**: Unchanged

---

## 3. Files to Modify

| File | Change Type | Description |
|------|-------------|-------------|
| `hooks/scripts/memory_triage.py` | MODIFY | Add structured JSON output with per-category data |
| `skills/memory-management/SKILL.md` | REWRITE | Parallel subagent orchestration + verification flow |
| `assets/memory-config.default.json` | MODIFY | Add `triage.parallel` config section |
| `CLAUDE.md` | MODIFY | Update architecture table, add parallel processing docs |
| `README.md` | MODIFY | Update auto-capture description |

**No new files needed** — the parallel processing is orchestrated via SKILL.md instructions + Task tool, not new Python scripts.

---

## 4. Config Loading Changes

In `memory_triage.py`, extend `load_config()` to:
1. Read `triage.parallel` section
2. Validate `category_models` values (must be haiku/sonnet/opus)
3. Validate `verification_model` value
4. Default: `default_model: "haiku"`, `verification_model: "sonnet"`
5. Include parallel config in structured output

---

## 5. Risk Analysis

| Risk | Mitigation |
|------|-----------|
| Subagent fails mid-processing | Fail-open + explicit timeout: if subagent fails or times out, skip that category (log warning). Main agent retains gatekeeper role for memory_write.py calls |
| Model not available | Fallback to default_model, then to "sonnet" |
| Concurrent writes from parallel subagents | Existing flock-based locking handles this |
| Verification rejects valid content | Verification is advisory; log issues but save unless critical |
| Increased latency (more LLM calls) | Parallel execution compensates; haiku is fast |
| Cost increase (more API calls) | haiku for simple categories offsets this |
| Config migration for existing users | Defaults apply if new config absent |

---

## 6. Implementation Order

1. Config schema changes (default config + config loading)
2. Triage hook structured output
3. SKILL.md rewrite
4. CLAUDE.md + README.md updates
5. Testing

---

## 7. Verification Criteria

- [ ] Config parsing works with new `triage.parallel` section
- [ ] Config parsing works without new section (backwards compat)
- [ ] Triage hook outputs structured JSON in `<triage_data>` block
- [ ] Triage hook still outputs human-readable message
- [ ] SKILL.md clearly instructs parallel subagent spawning
- [ ] Per-category model selection works
- [ ] CUD verification preserved in subagent context
- [ ] Verification step catches schema violations
- [ ] memory_write.py integration preserved
- [ ] Existing tests still pass
- [ ] Security: no new prompt injection vectors
