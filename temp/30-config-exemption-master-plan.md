# Config Exemption Fix -- Master Plan

## Objective
Exempt `memory-config.json` from hook guards (PreToolUse write guard + PostToolUse validation hook).
Spec: `temp/fix-hook-config-exemption-spec.md`

## Changes Required
- **File 1**: `hooks/scripts/memory_write_guard.py` -- Add `_CONFIG_BASENAME` constant + basename exemption before deny block
- **File 2**: `hooks/scripts/memory_validate_hook.py` -- Add `_CONFIG_BASENAME` constant + basename exemption before validation

## Team Structure

### Phase 1: Implementation (parallel)
- **implementer**: Code changes to both files per spec
- **test-writer**: New test cases for config exemption in both test files

### Phase 2: Verification Round 1 (parallel, 3 perspectives)
- **v1-security**: Security-focused review (injection risks, bypass scenarios)
- **v1-correctness**: Correctness review (spec compliance, edge cases)
- **v1-integration**: Integration review (existing tests pass, hook chain works)

### Phase 3: Verification Round 2 (parallel, 2 perspectives)
- **v2-adversarial**: Adversarial testing (malicious filenames, path traversal)
- **v2-holistic**: Holistic review (architecture, conventions, completeness)

## Communication Protocol
All inter-teammate communication via files in `temp/` folder.
- Implementation output: `temp/30-impl-output.md`
- Test output: `temp/30-test-output.md`
- V1 reviews: `temp/30-v1-security.md`, `temp/30-v1-correctness.md`, `temp/30-v1-integration.md`
- V2 reviews: `temp/30-v2-adversarial.md`, `temp/30-v2-holistic.md`

## Status Tracking
- [x] Phase 1: Implementation (implementer + test-writer, parallel)
- [x] Phase 2: Verification Round 1 (v1-security, v1-correctness, v1-integration, parallel)
  - v1-security found basename collision in subdirectories -> FIXED
- [x] Phase 3: Verification Round 2 (v2-adversarial, v2-holistic, parallel)
  - v2-adversarial: PASS (all attack vectors handled)
  - v2-holistic: PASS, MERGE recommended
- [x] Final sign-off: ALL PASS, ready to merge
