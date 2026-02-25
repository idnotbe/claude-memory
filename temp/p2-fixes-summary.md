# Plan #2 V1+V2 Fix Summary

**Date:** 2026-02-25

## Fixes Applied (7 issues from V1+V2)

| # | Severity | Issue | Fix | File | Status |
|---|----------|-------|-----|------|--------|
| 1 | HIGH | `os.makedirs` symlink traversal | Added `resolve().relative_to()` containment check after makedirs | memory_logger.py:297-301 | FIXED |
| 2 | MEDIUM | `os.makedirs` mode missing | Added `mode=0o700` to both makedirs calls | memory_logger.py:163,295 | FIXED |
| 3 | MEDIUM | NaN/Infinity non-RFC JSON | Added `allow_nan=False` + `math.isfinite()` sanitization | memory_logger.py:247-253,284 | FIXED |
| 4 | MEDIUM | `.last_cleanup` symlink bypass | Added `is_symlink()` check + `os.lstat()` instead of `stat()` | memory_logger.py:122-128 | FIXED |
| 5 | MEDIUM | `bool("false")` = True | Added string-aware boolean parsing | memory_logger.py:56-62 | FIXED |
| 6 | MEDIUM | Schema contract mismatch | Updated `temp/p2-logger-schema.md` to match actual emit payloads | p2-logger-schema.md | FIXED |
| 7 | LOW | SyntaxError not caught in lazy import | Changed `except ImportError` to `except (ImportError, SyntaxError)` | 4 consumer scripts | FIXED |

## Additional Fixes Found During Testing

| # | Issue | Fix | File |
|---|-------|-----|------|
| 8 | `_sanitize_category` safe-path missing truncation | Added `[:64]` on safe regex match path too | memory_logger.py:194 |
| 9 | Double `datetime.now()` midnight race | Captured `now` once, reused for timestamp + filename | memory_logger.py:263,268,291 |
| 10 | Category name length limit | Added `[:64]` truncation in `_sanitize_category` | memory_logger.py:194,198 |

## New Tests Added (14 tests in 6 classes)

| Test Class | Count | Coverage |
|------------|-------|----------|
| TestBoolStringConfig | 3 | "false"/"true"/"1"/"yes"/"0"/"no" parsing |
| TestNaNInfinityHandling | 3 | NaN, Infinity, -Infinity -> null |
| TestSymlinkContainment | 1 | Symlink escape prevention |
| TestLastCleanupSymlinkBypass | 1 | .last_cleanup symlink removal |
| TestCategoryLengthLimit | 1 | 1000-char category -> <=64 |
| TestMidnightDateConsistency | 1 | Timestamp date == filename date |

## Test Results

- **Before fixes:** 838 passed
- **After fixes:** 852 passed (+14 new tests)
- **Compile check:** 13/13 scripts OK
- **Zero regressions**

## V1+V2 Finding Resolution

| Finding | V1/V2 | Resolution |
|---------|-------|------------|
| F-01 Schema: search.query | V1 | Schema doc updated |
| F-02 Schema: judge.evaluate | V1 | Schema doc updated |
| F-03 Schema: retrieval.search fields | V1 | DEFERRED (data available across events) |
| F-04 Schema: output_mode missing | V1 | DEFERRED (needs memory_retrieve.py output_mode tracking) |
| F-05 candidates_found == candidates_post_threshold | V1 | DEFERRED (needs score_with_body refactor) |
| F-06 makedirs mode | V1+V2 | FIXED |
| F-07 TOCTOU cleanup race | V1 | Mitigated by F-06 fix (mode=0o700) |
| F-08 O_NOFOLLOW fallback | V1 | ACCEPTED (documented limitation) |
| F-09 monotonic vs perf_counter | V1 | ACCEPTED (pre-existing) |
| F-10 Query tokens at info level | V1 | ACCEPTED (by design, .gitignore guided) |
| Finding #1 symlink makedirs | V2 | FIXED |
| Finding #2 NaN JSON | V2 | FIXED |
| Finding #3 .last_cleanup symlink | V2 | FIXED |
| Finding #4 bool("false") | V2 | FIXED |
| Finding #5 SyntaxError import | V2 | FIXED |
| Finding #6 double datetime | V2 | FIXED |
| Finding #7 category length | V2 | FIXED |
| Finding #8 payload size | V2 | DEFERRED (fail-open catches MemoryError) |
