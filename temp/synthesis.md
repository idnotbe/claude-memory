# Synthesis: All Popup & Screen Noise Root Causes (2026-03-22)

## Evidence Sources
- Research teammates: temp/prd.md, temp/architecture.md, temp/bug-analysis.md, temp/guardian-analysis.md
- Cross-model: Codex 5.3 (planner) + Gemini 3.1 Pro (planner)
- User-provided live session logs (2 sessions)

## All Popup Sources (Complete Inventory from User Logs)

### Type 1: Guardian PreToolUse:Bash Popups
| Source | Trigger | Count/Session | Root Cause |
|--------|---------|---------------|------------|
| Phase 0 intent cleanup `python3 -c "import glob,os; os.remove(f)"` | Guardian F1: check_interpreter_payload() → os.remove in -c payload → ASK | 1-2x | Inline python3 -c instead of script |
| Haiku save subagent using `cat > file << 'DONE'` | Guardian: heredoc + .claude path → ASK | 0-1x | Haiku ignoring SKILL.md Rule 0 |

### Type 2: Write Tool Permission Popups
| Source | Trigger | Count/Session | Root Cause |
|--------|---------|---------------|------------|
| Write(.staging/intent-*.json) | "Do you want to make this edit?" | 1-3x | write_guard outputs permissionDecision but popup still shows — NEEDS INVESTIGATION |
| Write(.staging/new-info-*.txt) | Same | 1x | Same |
| Write(.staging/input-*.json) | Same | 1x | Same |
| Write(.staging/last-save-result-input.json) | Same | 1x | Same |

### Type 3: Stop Hook Re-fire Loop
| Source | Trigger | Count/Session | Root Cause |
|--------|---------|---------------|------------|
| memory_triage.py re-fires 2-3x | .triage-handled deleted by cleanup + FLAG_TTL=300s expired | 2-3x EXTRA fires | Both idempotency guards destroyed |

## Screen Noise Total
- ~80+ visible items + ~8 popup confirmations per session end
- User-useful items: ~3

## Cross-Model Consensus
- Codex 5.3: Patch first (P0), then state redesign (P1), then simplify (P1)
- Gemini 3.1 Pro: Patch only (no redesign needed)
- My assessment (Opus 4.6): Codex is right — patch first, then redesign

## Logging Gaps
- User popup confirmations NOT recorded
- Guardian popup triggers NOT in memory JSONL
- Save flow end-to-end timing NOT tracked
- Subagent compliance (haiku heredoc) NOT recorded
- Re-fire loop counter NOT implemented

## Action Plans Needed
1. P0: Fix Re-fire Loop (2-line fix + defense-in-depth)
2. P0: Eliminate All Popups (cleanup-intents + Write permission fix + haiku compliance)
3. P1: Observability (log the gaps)
4. P1: Screen Noise Reduction
5. P2: Architecture Simplification (5→3 phases)
