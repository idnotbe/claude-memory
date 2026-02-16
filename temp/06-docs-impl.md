# Documentation Updates -- Implementation Notes

**Task:** #3 -- Update CLAUDE.md and README.md documentation
**Date:** 2026-02-16
**Author:** config-hook-dev

---

## CLAUDE.md Changes

1. **Architecture table**: Updated Stop hook description to mention structured `<triage_data>` output and context files
2. **New "Parallel Per-Category Processing" section**: Added below the architecture table explaining the 3 outputs (human-readable, JSON block, context files) and linking to SKILL.md for the full 4-phase flow
3. **Key Files table**: Updated memory_triage.py description to mention structured output + context files
4. **Config line**: Added reference to `assets/memory-config.default.json`
5. **Smoke check**: Added `memory_triage.py` to the compile check list

## README.md Changes

1. **"What It Does" paragraph**: Replaced "6 parallel Stop hooks" description with deterministic triage + parallel subagent architecture
2. **Architecture section**: Replaced "Two-Phase Auto-Capture" with "Four-Phase Auto-Capture" (Phase 0: Triage, Phase 1: Parallel Drafting, Phase 2: Verification, Phase 3: Save)
3. **Category table**: Updated from triage questions (old prompt-based) to triage signals (keyword heuristic descriptions)
4. **Shared Index section**: Updated to reflect main agent writes in Phase 3 (not Phase 2), mention flock-based locking
5. **Token Cost section**: Rewrote to reflect zero-LLM-cost triage, haiku/sonnet subagent costs, configurable model assignments
6. **Configuration table**: Added 4 new `triage.parallel.*` settings with defaults and description

## Consistency Checks

- All references to "6 parallel Stop hooks" or "Sonnet triage" updated
- Phase numbering consistent (0-3) across README and SKILL.md
- Config option names match actual implementation in memory_triage.py
- No references to the old 6-hook architecture remain
