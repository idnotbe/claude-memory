# Root File Cleanup Worklog

## Candidate Files for Deletion

### Category A: Ad-hoc test scripts (root test_*.py)
All created on 2025-02-21, clearly one-off debugging/exploration scripts.

| File | Size | Purpose | Initial Verdict |
|------|------|---------|----------------|
| test_bypass.py | 976B | Regex bypass testing for confidence spoofing | DELETE |
| test_extract.py | 485B | Tests extract_body_text from memory_retrieve | DELETE |
| test_fifo | 0B (FIFO pipe) | Named pipe created by test_fifo_zero.py | DELETE |
| test_fifo_zero.py | 695B | Tests check_recency with FIFO and /dev/zero | DELETE |
| test_file_io.py | 553B | Benchmarks reading 500 small files | DELETE |
| test_fts5.py | 1.8KB | FTS5 injection testing | DELETE |
| test_fts5_bench.py | 2.1KB | FTS5 benchmark with random data | DELETE |
| test_fts5_smoke.py | 12KB | Comprehensive FTS5 smoke test | DELETE (but note: most thorough) |
| test_gil.py | 639B | GIL/threading benchmark for urllib | DELETE |
| test_input.py | 351B | Tests tokenize function from memory_retrieve | DELETE |
| test_nested_path.py | 224B | Tests path resolution for staging | DELETE |
| test_path_val.py | 368B | Tests transcript path validation | DELETE |
| test_re.py | 223B | Regex edge case tests (confidence spoof) | DELETE |
| test_regex.py | 106B | Regex test for .index.md tokenization | DELETE |
| test_resolve.py | 622B | Tests symlink/FIFO path resolution | DELETE |
| test_sanitize.py | 420B | Tests ZWS sanitization in titles | DELETE |
| test_score.py | 945B | Tests scoring logic simulation | DELETE |
| test_script.py | 244B | Tests regex single-pass confidence strip | DELETE |
| test_sqlite.py | 763B | SQLite FTS5 hyphenated token tests | DELETE |
| test_sqlite2.py | 349B | SQLite FTS5 dot-separated token tests | DELETE |
| test_tags.py | 254B | Regex iterative confidence tag strip | DELETE |
| test_unicode_crash.py | 338B | Tests check_recency with invalid UTF-8 | DELETE |
| test_zero.py | 425B | Tests check_recency with /dev/zero | DELETE |

### Category B: Documentation files (uncertain)
| File | Size | Purpose | Initial Verdict |
|------|------|---------|----------------|
| TEST-PLAN.md | 8.1KB | Detailed test plan, referenced in CLAUDE.md | KEEP? |
| MEMORY-CONSOLIDATION-PROPOSAL.md | 78KB | Historical ACE v4.2 design doc, marked OBSOLETE | DELETE? |

### Category C: Keepers
| File | Purpose |
|------|---------|
| on_notification.wav | User confirmed in use |
| on_stop.wav | User confirmed in use |

## External AI Opinions

### Codex 5.3 (via pal clink)
- **All 23 test_*.py + test_fifo**: DELETE -- ad-hoc print-based probes, no assertions, breaks pytest collection (test_fifo_zero.py crashes on import with exit(1))
- **TEST-PLAN.md**: KEEP -- referenced in CLAUDE.md:88 and README.md:442
- **MEMORY-CONSOLIDATION-PROPOSAL.md**: KEEP -- historical reference, linked in README/SKILL
- Extra note: recommends adding pytest.ini with `testpaths = tests`

### Gemini 3 Pro (via pal clink)
- **All test_*.py + test_fifo**: DELETE -- scratchpad scripts, formal equivalents exist in tests/
- **TEST-PLAN.md**: KEEP -- actively referenced, testing roadmap
- **MEMORY-CONSOLIDATION-PROPOSAL.md**: KEEP -- prevents rehashing discarded architectural paths
- Extra note: suggests auditing for unported edge cases before deletion

### Claude Opus (my analysis)
- **All test_*.py + test_fifo**: DELETE -- one-off debugging, no assertions, not part of test suite
- **TEST-PLAN.md**: KEEP -- referenced in core docs
- **MEMORY-CONSOLIDATION-PROPOSAL.md**: KEEP -- referenced, clearly marked historical

### Consensus: 3/3 unanimous
- DELETE: 23 test_*.py files + test_fifo (24 items)
- KEEP: TEST-PLAN.md, MEMORY-CONSOLIDATION-PROPOSAL.md

## Verification Checklist
- [x] Round 1 judgment: All 24 ad-hoc files safe to delete (see analysis above)
- [x] Round 2 judgment (devil's advocate): Confirmed safe. Found: (a) canary effect from crashing pytest - but this is harmful not helpful, (b) intentionally committed as "scratch" - but that doesn't mean permanent, (c) no imports/references from any production/test code
- [x] External opinions: Codex, Gemini, Claude all agree unanimously
- [x] Vibe check: PROCEED -- plan is solid, low-risk, git history preserves everything
- [x] Post-deletion verification round 1: ls confirms 0 test_*.py, 0 test_fifo in root. Root directory is clean.
- [x] Post-deletion verification round 2: find confirms 0 test_* files, 0 FIFO pipes. git status shows 21 staged deletions (D). Kept files (TEST-PLAN.md, MEMORY-CONSOLIDATION-PROPOSAL.md, on_notification.wav, on_stop.wav) all present and intact.

## Result
- Deleted: 21 git-tracked test scripts (via git rm) + 2 untracked files (test_path_val.py, test_fifo via rm)
- Kept: TEST-PLAN.md, MEMORY-CONSOLIDATION-PROPOSAL.md (referenced in core docs), on_notification.wav, on_stop.wav (user-confirmed in use)
- Deletions staged in git but NOT committed (per user's preference)

## Final Deletion Plan
- **git rm** (21 tracked files): test_bypass.py test_extract.py test_fifo_zero.py test_file_io.py test_fts5.py test_fts5_bench.py test_fts5_smoke.py test_gil.py test_input.py test_nested_path.py test_re.py test_regex.py test_resolve.py test_sanitize.py test_score.py test_script.py test_sqlite.py test_sqlite2.py test_tags.py test_unicode_crash.py test_zero.py
- **rm** (2 untracked): test_path_val.py test_fifo
