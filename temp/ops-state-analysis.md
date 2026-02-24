# Ops Project Session Memory State Analysis

**Date:** 2026-02-24
**Analyzed directory:** `/home/idnotbe/projects/ops/.claude/memory/sessions/`
**Config file:** `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`

---

## 1. Config Values

| Config Key | Value | Notes |
|---|---|---|
| `categories.session_summary.max_retained` | **5** | Category-specific limit |
| `max_memories_per_category` | 100 | Global default (overridden by per-category `max_retained`) |
| `categories.session_summary.retention_days` | 90 | Files older than 90 days eligible for expiry |
| `categories.session_summary.auto_capture` | true | |
| `delete.grace_period_days` | **30** | Retired files kept 30 days before archival |
| `delete.archive_retired` | **true** | Retired files should be archived (not deleted) after grace |
| `retrieval.max_inject` | 5 | |

**Key observation:** `max_retained: 5` is the operative limit for active sessions. The enforcement mechanism (rolling window via `memory_enforce.py`) retires sessions beyond this limit but does **not** delete or archive the retired files. Archival/deletion is a separate process gated by `grace_period_days`.

---

## 2. File Counts and Status Breakdown

| Status | Count |
|---|---|
| **active** | 5 |
| **retired** | 62 |
| **archived** | 0 |
| **Total files on disk** | **67** |

All 67 files are valid JSON with correct schema. No malformed files, no non-JSON files, no files with missing `created_at`.

---

## 3. Date Range

| Metric | Date | File |
|---|---|---|
| **Oldest created_at** | 2026-02-11T00:00:00Z | `phase1-launch-strategy-pending-decisions.json` |
| **Newest created_at** | 2026-02-24T07:30:00Z | `bulk-commit-push-7-repos-all-synced-to-github.json` |
| **Oldest retired_at** | 2026-02-20T00:39:39Z | (earliest retirement) |
| **Newest retired_at** | 2026-02-24T11:03:46Z | (most recent retirement) |

**Span:** 13 days of session history (Feb 11 - Feb 24, 2026).

---

## 4. The 5 Files That Should Be Retained (Most Recent by created_at)

These are the 5 most recent sessions and they are already correctly marked `active`:

| # | created_at | Filename |
|---|---|---|
| 1 | 2026-02-24T07:30:00Z | `bulk-commit-push-7-repos-all-synced-to-github.json` |
| 2 | 2026-02-23T14:12:51Z | `file-disposition-analysis-and-fix-application-complete.json` |
| 3 | 2026-02-23T13:55:12Z | `post-sync-follow-up-ssot-facts-fixed-f019-f005-temp-tracking-corrected-issues-5.json` |
| 4 | 2026-02-23T13:10:01Z | `sync-completion-plan-created-3-tier-plan-awaiting-founder-approval.json` |
| 5 | 2026-02-23T04:10:51Z | `prompt-redesign-p3-complete-founder-corrections-applied-dual-verification-pass.json` |

**The rolling window enforcement is working correctly** -- exactly 5 files are active, matching `max_retained: 5`.

---

## 5. Retirement Reason Breakdown

| Count | Reason |
|---|---|
| 53 | `Session rolling window: exceeded max_retained limit` |
| 6 | `Session rolling window: exceeded max_retained limit of 5` |
| 2 | `Session rolling window: exceeded max_retained limit (6 active, max 5)` |
| 1 | `Improperly written by haiku agent bypassing memory_draft.py pipeline; re-creating through proper pipeline` |

All 62 retired files have a valid `retired_at` timestamp. No files are missing retirement metadata.

---

## 6. Grace Period Analysis

- **Grace period:** 30 days (from config)
- **Files past grace period:** 0
- **Files within grace period:** 62 (all retired files)

Since the oldest retirement date is 2026-02-20 and today is 2026-02-24, no retired files have exceeded the 30-day grace period yet. The earliest any file could be eligible for archival is **2026-03-22**.

---

## 7. Index Anomalies

The index file (`/home/idnotbe/projects/ops/.claude/memory/index.md`) has **16 session entries**, which is significantly more than the 5 active files:

### Index entries referencing files that do NOT exist on disk (6 phantom entries):
| Filename | Exists on Disk |
|---|---|
| `doc-sync-ssot-execution-phase-1-verified-phase-2-ring-execution-in-progress.json` | NO |
| `fractal-wave-action-plan-created-v1-0-final-with-full-dual-verification.json` | NO |
| `fractal-wave-action-plan-pip-to-poetry-migration-19-locations-3-verification-rou.json` | NO |
| `fw-phase-0-ops-claude-md-updated-daemon-prompt-drafted-v1-done-v2-in-progress.json` | NO |
| `sync-plan-phase-4-marked-superseded-execution-order-confirmed.json` | NO |
| `vscode-multi-repo-workspace-setup.json` | NO |

### Index entries referencing files that exist but are `retired` (5 stale entries):
| Filename | record_status |
|---|---|
| `dormancy-p0-complete-all-verified-deploy-instructions-given-commit-pending.json` | retired |
| `dormancy-policy-action-plan-creation-and-p0-discourse-settings-applied.json` | retired |
| `fractal-wave-adoption-research-complete-strategy-b-recommended-2-verification-ro.json` | retired |
| `ssot-research-v1-verification-2-3-complete-v1-fixes-pending.json` | retired |
| `type-b-fix-remaining-phases-wrangler-v4-upgrade-smoke-test-complete.json` | retired |

### Index entries correctly referencing active files (5 correct entries):
- `bulk-commit-push-7-repos-all-synced-to-github.json`
- `file-disposition-analysis-and-fix-application-complete.json`
- `post-sync-follow-up-ssot-facts-fixed-f019-f005-temp-tracking-corrected-issues-5.json`
- `prompt-redesign-p3-complete-founder-corrections-applied-dual-verification-pass.json`
- `sync-completion-plan-created-3-tier-plan-awaiting-founder-approval.json`

**The index is stale and out of sync.** It contains 6 phantom entries (files that no longer exist) and 5 entries pointing to retired files. A `memory_index.py --rebuild` would fix this.

---

## 8. Schema Structure (from sampled files)

All sampled files follow a consistent schema:

```json
{
  "schema_version": "1.0",
  "category": "session_summary",
  "id": "<slug>",
  "title": "<plain text>",
  "created_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",
  "tags": ["<string>", ...],
  "record_status": "active" | "retired",
  "changes": [{"date": "...", "summary": "...", ...}],
  "times_updated": <int>,
  "related_files": ["<path>", ...],
  "confidence": <float 0-1>,
  "content": {
    "goal": "<string>",
    "outcome": "success" | "partial",
    "completed": ["<string>", ...],
    "in_progress": ["<string>", ...],
    "blockers": ["<string>", ...],
    "next_actions": ["<string>", ...],
    "key_changes": ["<string>", ...]
  },
  // Retired files additionally have:
  "retired_at": "<ISO 8601>",
  "retired_reason": "<string>"
}
```

**Notable observations:**
- Some files have extensive `changes` arrays (up to 20+ entries), indicating heavy session updates
- `times_updated` ranges from 0 (single-write sessions) to 9
- Tags are capped at 12 per file (tag eviction entries visible in changes)

---

## 9. Summary

**The active session count is correctly limited to 5.** The rolling window enforcement (`memory_enforce.py`) is working as designed -- it retires sessions beyond the `max_retained: 5` limit.

**The core issue is that 62 retired files remain on disk.** This is technically by design:
1. Retired files enter a 30-day grace period (`grace_period_days: 30`)
2. After grace period, they should be archived (`archive_retired: true`)
3. Since all retirements occurred within the last 4 days (Feb 20-24), none have exceeded the grace period

**However, there are two real problems:**

1. **No automated archival mechanism exists.** The config specifies `archive_retired: true` and `grace_period_days: 30`, but there is no cron job or hook that automatically archives files after the grace period expires. The `memory_enforce.py` script only handles the retirement step (rolling window), not the archival step. This means retired files will accumulate indefinitely unless manually archived.

2. **The index is stale.** 11 of 16 session entries in `index.md` are incorrect -- 6 reference files that don't exist on disk at all (possibly deleted or never created properly), and 5 reference files that are retired. Only the 5 active entries are correct. The index needs a rebuild via `memory_index.py --rebuild`.

**Recommended actions:**
- Rebuild the index: `python3 hooks/scripts/memory_index.py --rebuild --root /home/idnotbe/projects/ops/.claude/memory`
- Consider implementing automated archival for post-grace-period retired files
- For immediate cleanup, the 62 retired files could be bulk-archived using `memory_write.py --action archive`
