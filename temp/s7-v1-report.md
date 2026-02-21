# S7 Verification Round 1 -- Combined Report

**Date:** 2026-02-21
**Reviewers:** v1-correctness, v1-security, v1-integration

## Overall Verdict: CONDITIONAL PASS (3 MEDIUM fixes required)

### Test Suite: 683/683 PASS (no regressions)

## Findings Summary

| # | Severity | Source | Issue | Status |
|---|----------|--------|-------|--------|
| M1 | MEDIUM | correctness | FTS5 judge pool capped at max_inject (3) not candidate_pool_size (15) | FIX REQUIRED |
| M2 | MEDIUM | security + correctness | No title sanitization in format_judge_input() | FIX REQUIRED |
| M3 | MEDIUM | security | Transcript path traversal -- no validation in extract_recent_context() | FIX REQUIRED |
| L1 | LOW | correctness | n_candidates parameter unused in parse_response/extract_indices | ACCEPTED (future guard) |
| L2 | LOW | correctness | dual_verification config key present but unused | ACCEPTED (Phase 4 placeholder) |
| L3 | LOW | security | Debug output to stderr not gated | ACCEPTED (stderr not injected) |

## Fixes Applied

### M1: FTS5 judge pool size
- **Problem:** score_with_body() applies max_inject cap BEFORE judge sees candidates
- **Fix:** When judge is enabled, pass candidate_pool_size as max_inject to score_with_body(), then re-cap after judge filtering
- **File:** memory_retrieve.py FTS5 path

### M2: Title sanitization in judge input
- **Problem:** format_judge_input() passes raw titles to judge LLM without XML escaping
- **Fix:** HTML-escape titles in format_judge_input() before sending to judge
- **File:** memory_judge.py format_judge_input()

### M3: Transcript path validation
- **Problem:** extract_recent_context() opens any path without validation
- **Fix:** Add path validation matching memory_triage.py pattern (check under /tmp/ or $HOME/)
- **File:** memory_judge.py extract_recent_context()

## Individual Reports
- `/home/idnotbe/projects/claude-memory/temp/s7-v1-correctness.md`
- `/home/idnotbe/projects/claude-memory/temp/s7-v1-security.md`
- `/home/idnotbe/projects/claude-memory/temp/s7-v1-integration.md`
