# Master Plan: Fix 5 Architectural Issues in claude-memory

## Issues to Fix

### Issue 1: index.md Git merge conflict (높음)
- **File:** hooks/scripts/memory_index.py, hooks/scripts/memory_write.py
- **Problem:** index.md is a central file modified on every memory write, causing Git merge conflicts
- **Fix Strategy:** Validate resolved root ends with .claude/memory marker; reject fallback writes outside

### Issue 2: _resolve_memory_root() fallback allows external writes (중간)
- **File:** hooks/scripts/memory_write.py
- **Problem:** When --target lacks .claude/memory marker, fallback uses parent.parent allowing writes outside memory dir
- **Fix Strategy:** Validate resolved root ends with .claude/memory, reject otherwise

### Issue 3: max_inject value unclamped (중간)
- **File:** hooks/scripts/memory_retrieve.py
- **Problem:** max_inject from config has no validation; negative/extreme values cause issues
- **Fix Strategy:** Clamp to valid range (1-20), warn on invalid values

### Issue 4: NFS/SMB flock instability (중간)
- **File:** hooks/scripts/memory_write.py
- **Problem:** fcntl.flock() unreliable on network filesystems
- **Fix Strategy:** Add fallback locking mechanism with detection of network FS

### Issue 5: Prompt injection via memory titles (중간)
- **File:** hooks/scripts/memory_retrieve.py, hooks/scripts/memory_write.py
- **Problem:** Titles injected verbatim into prompt context, can contain malicious instructions
- **Fix Strategy:** Sanitize titles on write AND on retrieval injection

## Phases

| Phase | Teammates | Output |
|-------|-----------|--------|
| 1. Planning | planner | temp/detailed-fix-plan.md |
| 2. Tests | test-writer, test-reviewer | tests/ files, temp/test-report.md |
| 3. Implementation | implementer | source files, temp/impl-report.md |
| 4. V&C Round 1 | v1-security, v1-correctness | temp/v1-findings.md, corrections |
| 5. V&C Round 2 | v2-security, v2-correctness | temp/v2-findings.md, corrections |

## Communication Protocol
- All inter-teammate communication via files in temp/
- Direct messages contain only file links
- Each teammate uses vibe-check and pal clink independently

## Status: COMPLETED

## Final Results: 239/239 tests pass (0 failures)

### Team Members (9 agents total)
| Agent | Role | Phase |
|-------|------|-------|
| planner | Fix plan design | 1 |
| test-writer | Test creation (50 tests) | 2 |
| test-reviewer | Multi-perspective test review | 2 |
| implementer | All 5 fixes | 3 |
| v1-security | Security validation R1 | 4 |
| v1-correctness | Correctness validation R1 | 4 |
| v2-security | Security validation R2 | 5 |
| v2-correctness | Correctness validation R2 | 5 |

### V&C Corrections Applied
| Round | Finding | Fix |
|-------|---------|-----|
| R1 | OverflowError crash (max_inject: 1e999) | Added OverflowError to except clause |
| R1 | Unhandled subprocess.TimeoutExpired | Wrapped rebuild subprocess in try/except |
| R1 | Zero-width Unicode chars pass through | Added Unicode Cf category filtering |
| R2 | XML boundary breakout via < > in titles | Added HTML entity escaping |

### Artifacts
- temp/detailed-fix-plan.md -- Detailed fix plan (Codex + Gemini reviewed)
- temp/test-report.md -- Test creation report
- temp/test-review.md -- Multi-perspective test review
- temp/impl-report.md -- Implementation report
- temp/v1-security-findings.md -- V&C R1 security findings
- temp/v1-correctness-findings.md -- V&C R1 correctness findings
- temp/v2-security-findings.md -- V&C R2 security findings
- temp/v2-correctness-findings.md -- V&C R2 correctness findings
