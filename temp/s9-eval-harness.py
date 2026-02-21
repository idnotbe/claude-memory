#!/usr/bin/env python3
"""Synthetic evaluation harness for BM25 precision analysis.

Creates synthetic memory corpus, runs BM25 queries, outputs structured results
for qualitative analysis of BM25-only vs BM25+judge retrieval.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add hooks/scripts to path
SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_search_engine import (
    build_fts_index,
    build_fts_query,
    query_fts,
    apply_threshold,
    tokenize,
    parse_index_line,
    extract_body_text,
    HAS_FTS5,
)

# ---------------------------------------------------------------------------
# Synthetic Memory Corpus
# ---------------------------------------------------------------------------

MEMORIES = [
    # DECISIONS
    {
        "id": "d01", "category": "decision", "folder": "decisions",
        "title": "Use JWT for API authentication",
        "tags": ["auth", "jwt", "api", "security"],
        "content": {
            "context": "Needed stateless authentication for REST API endpoints",
            "decision": "Use JWT tokens with RS256 signing and 15-minute expiry",
            "rationale": "Stateless, no server-side session storage needed, works with microservices",
            "consequences": "Must handle token refresh, need secure key rotation strategy",
        },
    },
    {
        "id": "d02", "category": "decision", "folder": "decisions",
        "title": "PostgreSQL over MongoDB for primary datastore",
        "tags": ["database", "postgresql", "mongodb", "storage"],
        "content": {
            "context": "Choosing between relational and document database for user data",
            "decision": "PostgreSQL 15 with JSONB columns for semi-structured data",
            "rationale": "ACID transactions, mature ecosystem, JSONB gives document flexibility",
            "consequences": "Need migration tooling (Alembic), connection pooling (pgbouncer)",
        },
    },
    {
        "id": "d03", "category": "decision", "folder": "decisions",
        "title": "React with TypeScript for frontend framework",
        "tags": ["react", "typescript", "frontend", "ui"],
        "content": {
            "context": "Selecting frontend framework for dashboard application",
            "decision": "React 18 with TypeScript strict mode",
            "rationale": "Team expertise, large ecosystem, type safety catches bugs early",
            "consequences": "Longer initial setup, need TypeScript training for junior devs",
        },
    },
    {
        "id": "d04", "category": "decision", "folder": "decisions",
        "title": "Redis for session caching and rate limiting",
        "tags": ["redis", "caching", "rate-limiting", "performance"],
        "content": {
            "context": "Need fast key-value store for session data and API rate limits",
            "decision": "Redis 7 with Sentinel for HA, separate instances for cache vs rate-limit",
            "rationale": "Sub-millisecond latency, built-in TTL, Lua scripting for atomic rate-limit checks",
            "consequences": "Additional infrastructure to manage, need monitoring for memory usage",
        },
    },
    {
        "id": "d05", "category": "decision", "folder": "decisions",
        "title": "Monorepo with Turborepo for build orchestration",
        "tags": ["monorepo", "turborepo", "build", "ci"],
        "content": {
            "context": "Frontend and backend code share types and utilities",
            "decision": "Single monorepo with Turborepo for task caching and parallel builds",
            "rationale": "Shared TypeScript types, atomic cross-project changes, cached CI builds",
            "consequences": "Larger repo size, need careful dependency management, longer initial clone",
        },
    },
    # CONSTRAINTS
    {
        "id": "c01", "category": "constraint", "folder": "constraints",
        "title": "HIPAA compliance requires encrypted data at rest",
        "tags": ["hipaa", "encryption", "compliance", "security"],
        "content": {
            "rule": "All PII and PHI must be encrypted at rest using AES-256",
            "impact": "Cannot use unencrypted storage, affects database config and backup strategy",
            "workarounds": "PostgreSQL TDE, application-level field encryption for sensitive columns",
        },
    },
    {
        "id": "c02", "category": "constraint", "folder": "constraints",
        "title": "API rate limit of 1000 requests per minute per user",
        "tags": ["api", "rate-limit", "throttling"],
        "content": {
            "rule": "Hard limit of 1000 req/min per authenticated user, 100 for anonymous",
            "impact": "Batch operations must use pagination, webhooks preferred over polling",
            "workarounds": "Bulk endpoints for batch operations, WebSocket for real-time updates",
        },
    },
    {
        "id": "c03", "category": "constraint", "folder": "constraints",
        "title": "Python 3.11 minimum version requirement",
        "tags": ["python", "version", "compatibility"],
        "content": {
            "rule": "All backend services must target Python 3.11+ (no 3.10 or earlier)",
            "impact": "Can use match/case, ExceptionGroup, tomllib; cannot support older runtimes",
            "workarounds": "None needed -- 3.11 features actively encouraged",
        },
    },
    # RUNBOOKS
    {
        "id": "r01", "category": "runbook", "folder": "runbooks",
        "title": "Fix database connection pool exhaustion",
        "tags": ["database", "connection-pool", "pgbouncer", "outage"],
        "content": {
            "trigger": "Application logs show 'connection pool exhausted' or response times spike above 5s",
            "symptoms": "HTTP 503 errors, high p99 latency, pg_stat_activity shows idle connections",
            "steps": ["Check pg_stat_activity for idle-in-transaction connections",
                      "Kill idle connections older than 5 minutes",
                      "Restart pgbouncer if connection count exceeds 80% of max",
                      "Check for missing connection.close() in recent deployments"],
            "verification": "Response times return to normal, connection count drops below 50%",
            "root_cause": "Usually unclosed connections in error paths or missing context manager usage",
        },
    },
    {
        "id": "r02", "category": "runbook", "folder": "runbooks",
        "title": "Deploy hotfix to production Kubernetes cluster",
        "tags": ["deployment", "kubernetes", "hotfix", "production"],
        "content": {
            "trigger": "Critical bug in production requires immediate fix",
            "steps": ["Create hotfix branch from production tag",
                      "Apply fix and run smoke tests locally",
                      "Build Docker image with hotfix tag",
                      "kubectl set image deployment/api api=registry/api:hotfix-XXX",
                      "Monitor rollout: kubectl rollout status deployment/api",
                      "Verify fix in production, then backport to main"],
            "verification": "Health check endpoints return 200, error rate drops to baseline",
        },
    },
    {
        "id": "r03", "category": "runbook", "folder": "runbooks",
        "title": "Rotate JWT signing keys without downtime",
        "tags": ["jwt", "key-rotation", "auth", "security"],
        "content": {
            "trigger": "Scheduled quarterly key rotation or suspected key compromise",
            "steps": ["Generate new RS256 keypair",
                      "Add new public key to JWKS endpoint (both old and new active)",
                      "Update signing service to use new private key",
                      "Wait for token expiry window (15 min + grace period)",
                      "Remove old public key from JWKS endpoint"],
            "verification": "No auth failures during rotation, JWKS endpoint serves new key",
        },
    },
    {
        "id": "r04", "category": "runbook", "folder": "runbooks",
        "title": "Debug memory leak in Node.js worker process",
        "tags": ["nodejs", "memory-leak", "debugging", "heap"],
        "content": {
            "trigger": "Worker process RSS exceeds 512MB or OOMKilled in Kubernetes",
            "symptoms": "Gradual memory increase over hours, GC pauses increase",
            "steps": ["Take heap snapshot: node --inspect worker.js",
                      "Connect Chrome DevTools, record allocation timeline",
                      "Compare two snapshots to find growing objects",
                      "Check for event listener leaks, unclosed streams, global caches"],
            "verification": "RSS stays stable under sustained load test",
            "root_cause": "Common: unclosed database cursors, growing Map/Set without eviction",
        },
    },
    # TECH DEBT
    {
        "id": "t01", "category": "tech_debt", "folder": "tech-debt",
        "title": "Migrate from Jest to Vitest for frontend tests",
        "tags": ["testing", "jest", "vitest", "migration", "frontend"],
        "content": {
            "description": "Jest configuration is complex and slow; Vitest offers native ESM and faster execution",
            "reason_deferred": "Mid-sprint, too risky to change test runner during feature development",
            "impact": "CI frontend tests take 4 minutes instead of estimated 1.5 with Vitest",
            "suggested_fix": "Migrate test configs, update mocking patterns, benchmark before/after",
            "acceptance_criteria": "All 847 frontend tests pass with Vitest, CI time reduced by 50%+",
        },
    },
    {
        "id": "t02", "category": "tech_debt", "folder": "tech-debt",
        "title": "Replace hand-rolled CSV parser with pandas",
        "tags": ["csv", "pandas", "parsing", "data-import"],
        "content": {
            "description": "Custom CSV parser in utils/csv_parser.py has edge cases with quoted fields and unicode",
            "reason_deferred": "Works for current data sources, fix when new data format arrives",
            "impact": "Occasional import failures with international customer data (non-ASCII names)",
            "suggested_fix": "Replace with pandas.read_csv() using proper encoding detection",
        },
    },
    {
        "id": "t03", "category": "tech_debt", "folder": "tech-debt",
        "title": "Remove deprecated v1 API endpoints",
        "tags": ["api", "deprecation", "v1", "cleanup"],
        "content": {
            "description": "v1 API endpoints still active but deprecated since 2025-06, creating maintenance burden",
            "reason_deferred": "Some enterprise clients still on v1, need migration support",
            "impact": "Dual maintenance of v1 and v2 handlers, confusing for new developers",
            "suggested_fix": "Set hard deprecation date, provide migration guide, remove v1 routes",
        },
    },
    # PREFERENCES
    {
        "id": "p01", "category": "preference", "folder": "preferences",
        "title": "Use snake_case for Python, camelCase for TypeScript",
        "tags": ["naming", "convention", "python", "typescript"],
        "content": {
            "topic": "Variable and function naming conventions",
            "value": "Python: snake_case everywhere. TypeScript: camelCase for variables/functions, PascalCase for types/classes",
            "reason": "Follow language community standards, enforced by linters (pylint, ESLint)",
        },
    },
    {
        "id": "p02", "category": "preference", "folder": "preferences",
        "title": "Always use absolute imports in Python",
        "tags": ["python", "imports", "style"],
        "content": {
            "topic": "Import style in Python codebase",
            "value": "Use absolute imports (from package.module import X), never relative (from .module import X)",
            "reason": "Clearer, easier to grep, avoids confusion in monorepo with multiple packages",
        },
    },
    {
        "id": "p03", "category": "preference", "folder": "preferences",
        "title": "Prefer composition over inheritance",
        "tags": ["design-pattern", "composition", "oop"],
        "content": {
            "topic": "OOP design approach",
            "value": "Use composition and protocols/interfaces instead of deep inheritance hierarchies",
            "reason": "More flexible, easier to test, avoids fragile base class problem",
        },
    },
    {
        "id": "p04", "category": "preference", "folder": "preferences",
        "title": "Use ruff for Python linting and formatting",
        "tags": ["python", "linting", "ruff", "formatting"],
        "content": {
            "topic": "Python code quality tooling",
            "value": "Use ruff for both linting and formatting (replaces black, isort, flake8)",
            "reason": "10-100x faster than alternatives, single tool for lint+format, good defaults",
        },
    },
    # SESSION SUMMARIES
    {
        "id": "s01", "category": "session_summary", "folder": "sessions",
        "title": "Set up CI/CD pipeline with GitHub Actions",
        "tags": ["ci", "github-actions", "deployment", "pipeline"],
        "content": {
            "goal": "Implement automated CI/CD pipeline for the project",
            "outcome": "Working pipeline with lint, test, build, deploy stages",
            "completed": ["GitHub Actions workflow for PR checks", "Docker build and push to ECR",
                          "Staging auto-deploy on merge to main"],
            "in_progress": ["Production deploy approval gate"],
            "next_actions": ["Add canary deployment strategy", "Set up Datadog monitoring integration"],
        },
    },
    {
        "id": "s02", "category": "session_summary", "folder": "sessions",
        "title": "Implement user authentication system",
        "tags": ["auth", "jwt", "login", "oauth"],
        "content": {
            "goal": "Build complete authentication flow with JWT and OAuth2",
            "outcome": "Login, register, password reset working; OAuth2 Google provider integrated",
            "completed": ["JWT token generation and validation", "Login/register API endpoints",
                          "Password reset email flow", "Google OAuth2 provider"],
            "in_progress": ["GitHub OAuth2 provider"],
            "blockers": ["Waiting for GitHub app credentials from DevOps"],
            "next_actions": ["Add MFA support", "Rate limit login attempts"],
        },
    },
    {
        "id": "s03", "category": "session_summary", "folder": "sessions",
        "title": "Database migration and schema refactoring",
        "tags": ["database", "migration", "schema", "alembic"],
        "content": {
            "goal": "Refactor user table schema and add audit logging",
            "outcome": "Schema migrated, audit log table created, existing data preserved",
            "completed": ["Split user profile into separate table", "Add audit_log table",
                          "Alembic migration scripts for both changes"],
            "next_actions": ["Add index on audit_log.created_at", "Backfill audit entries for existing users"],
        },
    },
    {
        "id": "s04", "category": "session_summary", "folder": "sessions",
        "title": "Performance optimization for API response times",
        "tags": ["performance", "optimization", "api", "caching"],
        "content": {
            "goal": "Reduce p95 API response time from 800ms to under 200ms",
            "outcome": "Achieved 150ms p95 through caching and query optimization",
            "completed": ["Added Redis caching for user profiles", "Optimized N+1 queries with eager loading",
                          "Added database query logging for slow query detection"],
            "next_actions": ["Set up automated performance regression tests"],
        },
    },
    {
        "id": "s05", "category": "session_summary", "folder": "sessions",
        "title": "React component library setup with Storybook",
        "tags": ["react", "storybook", "components", "frontend", "ui"],
        "content": {
            "goal": "Create shared component library with documentation",
            "outcome": "10 core components built, Storybook deployed to internal docs site",
            "completed": ["Button, Input, Modal, Table, Card components",
                          "Storybook with auto-generated docs", "Visual regression tests with Chromatic"],
            "next_actions": ["Add form validation components", "Theme customization support"],
        },
    },
    # Additional edge-case memories for testing
    {
        "id": "d06", "category": "decision", "folder": "decisions",
        "title": "ThreadPoolExecutor for parallel API calls",
        "tags": ["concurrency", "threadpool", "python", "parallel"],
        "content": {
            "context": "Need to parallelize external API calls that are IO-bound",
            "decision": "Use concurrent.futures.ThreadPoolExecutor with max_workers=4",
            "rationale": "IO-bound work benefits from threads, GIL not a bottleneck for network IO",
            "consequences": "Need thread-safe data structures, careful exception handling",
        },
    },
    {
        "id": "c04", "category": "constraint", "folder": "constraints",
        "title": "Docker image size must stay under 500MB",
        "tags": ["docker", "image-size", "deployment", "constraint"],
        "content": {
            "rule": "Production Docker images must be under 500MB compressed",
            "impact": "Affects base image choice, must use multi-stage builds, no dev dependencies in prod",
            "workarounds": "Alpine-based images, .dockerignore, multi-stage builds with builder pattern",
        },
    },
    {
        "id": "r05", "category": "runbook", "folder": "runbooks",
        "title": "Recover from Redis cluster failover",
        "tags": ["redis", "failover", "cluster", "recovery"],
        "content": {
            "trigger": "Redis Sentinel triggers failover, application reports connection errors",
            "symptoms": "Increased error rate, cache misses spike, rate limiting stops working",
            "steps": ["Check Sentinel logs for failover reason",
                      "Verify new primary is accepting writes: redis-cli -h NEW_PRIMARY ping",
                      "Check application reconnection (Sentinel-aware clients auto-reconnect)",
                      "If manual intervention needed: update connection config and restart pods"],
            "verification": "Cache hit rate returns to baseline, no connection errors in logs",
        },
    },
    {
        "id": "t04", "category": "tech_debt", "folder": "tech-debt",
        "title": "Consolidate duplicate error handling middleware",
        "tags": ["error-handling", "middleware", "refactoring", "express"],
        "content": {
            "description": "Three separate error handling middlewares with overlapping logic in Express app",
            "reason_deferred": "Each was added for different error types, works but hard to maintain",
            "impact": "Inconsistent error response format, hard to add new error types",
            "suggested_fix": "Single unified error handler with error type registry pattern",
        },
    },
]


def create_synthetic_data(tmp_dir: Path):
    """Create index.md and JSON files in tmp_dir/.claude/memory/."""
    memory_root = tmp_dir / ".claude" / "memory"

    # Create category folders
    folders = {"decisions", "constraints", "runbooks", "tech-debt",
               "preferences", "sessions"}
    for folder in folders:
        (memory_root / folder).mkdir(parents=True, exist_ok=True)

    # Create JSON files and index lines
    index_lines = []
    for mem in MEMORIES:
        folder = mem["folder"]
        filename = f"{mem['id']}.json"
        filepath = memory_root / folder / filename

        json_data = {
            "title": mem["title"],
            "category": mem["category"],
            "tags": mem["tags"],
            "content": mem["content"],
            "record_status": "active",
            "updated_at": "2026-02-20T12:00:00Z",
        }
        filepath.write_text(json.dumps(json_data, indent=2))

        rel_path = f".claude/memory/{folder}/{filename}"
        tags_str = ",".join(mem["tags"])
        cat_upper = mem["category"].upper()
        index_lines.append(
            f"- [{cat_upper}] {mem['title']} -> {rel_path} #tags:{tags_str}"
        )

    index_path = memory_root / "index.md"
    index_path.write_text("\n".join(index_lines) + "\n")

    return memory_root


def run_query(query: str, memory_root: Path, max_results: int = 10) -> list[dict]:
    """Run a BM25 query against the synthetic corpus."""
    from memory_search_engine import cli_search
    return cli_search(query, memory_root, mode="search", max_results=max_results)


# ---------------------------------------------------------------------------
# Evaluation Queries
# ---------------------------------------------------------------------------

QUERIES = [
    # Category 1: Direct topic matches (should return precise results)
    {
        "id": "Q01",
        "query": "JWT authentication token signing",
        "category": "direct_match",
        "expected_relevant": ["d01", "r03", "s02"],
        "expected_irrelevant_noise": [],
        "description": "Direct match on JWT auth -- should find JWT decision, key rotation runbook, auth session",
    },
    {
        "id": "Q02",
        "query": "PostgreSQL database migration",
        "category": "direct_match",
        "expected_relevant": ["d02", "s03"],
        "expected_irrelevant_noise": ["r01"],  # connection pool is DB-related but not migration
        "description": "Database migration -- should find PostgreSQL decision and migration session",
    },
    {
        "id": "Q03",
        "query": "Redis caching strategy",
        "category": "direct_match",
        "expected_relevant": ["d04", "s04", "r05"],
        "expected_irrelevant_noise": [],
        "description": "Redis caching -- decision, performance session, failover runbook all relevant",
    },
    {
        "id": "Q04",
        "query": "React TypeScript frontend components",
        "category": "direct_match",
        "expected_relevant": ["d03", "s05"],
        "expected_irrelevant_noise": ["p01"],  # naming convention mentions TypeScript but less relevant
        "description": "React+TS frontend -- should find framework decision and component library session",
    },
    {
        "id": "Q05",
        "query": "Kubernetes deployment hotfix",
        "category": "direct_match",
        "expected_relevant": ["r02"],
        "expected_irrelevant_noise": ["c04"],  # Docker size constraint is deployment-adjacent
        "description": "K8s hotfix deployment -- should find hotfix runbook",
    },

    # Category 2: Cross-domain queries (memories exist but in different context)
    {
        "id": "Q06",
        "query": "how to handle API errors gracefully",
        "category": "cross_domain",
        "expected_relevant": ["t04"],  # error handling middleware
        "expected_irrelevant_noise": ["c02", "t03"],  # rate limit, deprecated API
        "description": "Error handling -- tech debt about error middleware is relevant, API rate limit is noise",
    },
    {
        "id": "Q07",
        "query": "security best practices for production",
        "category": "cross_domain",
        "expected_relevant": ["c01", "d01", "r03"],
        "expected_irrelevant_noise": [],
        "description": "Security broadly -- HIPAA, JWT, key rotation all relevant in security context",
    },
    {
        "id": "Q08",
        "query": "improve build speed",
        "category": "cross_domain",
        "expected_relevant": ["d05", "t01"],
        "expected_irrelevant_noise": [],
        "description": "Build speed -- Turborepo decision and Jest-to-Vitest migration both relevant",
    },

    # Category 3: Ambiguous/vague queries (match many entries superficially)
    {
        "id": "Q09",
        "query": "fix the bug",
        "category": "ambiguous",
        "expected_relevant": [],
        "expected_irrelevant_noise": [],
        "description": "Very vague -- after stop words, only 'fix' and 'bug' remain. Should return little/nothing",
    },
    {
        "id": "Q10",
        "query": "update the configuration",
        "category": "ambiguous",
        "expected_relevant": [],
        "expected_irrelevant_noise": [],
        "description": "Very vague -- 'update' and 'configuration' are generic. Many entries could loosely match",
    },
    {
        "id": "Q11",
        "query": "what should I work on next",
        "category": "ambiguous",
        "expected_relevant": [],
        "expected_irrelevant_noise": [],
        "description": "Planning query -- not about any specific memory topic",
    },

    # Category 4: Technical identifiers
    {
        "id": "Q12",
        "query": "ThreadPoolExecutor max_workers concurrency",
        "category": "tech_identifier",
        "expected_relevant": ["d06"],
        "expected_irrelevant_noise": [],
        "description": "Exact class name match -- should find ThreadPoolExecutor decision",
    },
    {
        "id": "Q13",
        "query": "pgbouncer connection pooling",
        "category": "tech_identifier",
        "expected_relevant": ["r01", "d02"],
        "expected_irrelevant_noise": [],
        "description": "pgbouncer -- connection pool runbook mentions it, PostgreSQL decision mentions it",
    },
    {
        "id": "Q14",
        "query": "Alembic migration scripts",
        "category": "tech_identifier",
        "expected_relevant": ["s03", "d02"],
        "expected_irrelevant_noise": [],
        "description": "Alembic -- migration session and PostgreSQL decision both mention it",
    },
    {
        "id": "Q15",
        "query": "ruff linter formatting",
        "category": "tech_identifier",
        "expected_relevant": ["p04"],
        "expected_irrelevant_noise": [],
        "description": "ruff tool -- should find the ruff preference precisely",
    },

    # Category 5: Multi-word concepts
    {
        "id": "Q16",
        "query": "thread safety in concurrent database access",
        "category": "multi_word",
        "expected_relevant": ["d06", "r01"],
        "expected_irrelevant_noise": [],
        "description": "Thread safety + database -- ThreadPoolExecutor decision and connection pool runbook",
    },
    {
        "id": "Q17",
        "query": "automated testing continuous integration pipeline",
        "category": "multi_word",
        "expected_relevant": ["s01", "t01"],
        "expected_irrelevant_noise": ["d05"],  # monorepo mentions CI but less about testing
        "description": "CI testing -- CI/CD session and Jest migration tech debt",
    },
    {
        "id": "Q18",
        "query": "encryption compliance data protection",
        "category": "multi_word",
        "expected_relevant": ["c01"],
        "expected_irrelevant_noise": [],
        "description": "Data protection -- HIPAA compliance constraint is the target",
    },
    {
        "id": "Q19",
        "query": "API versioning deprecation strategy",
        "category": "multi_word",
        "expected_relevant": ["t03"],
        "expected_irrelevant_noise": ["c02"],  # API rate limit shares 'API' token
        "description": "API deprecation -- v1 API removal tech debt entry",
    },

    # Category 6: Negative cases (no relevant memories)
    {
        "id": "Q20",
        "query": "machine learning model training",
        "category": "negative",
        "expected_relevant": [],
        "expected_irrelevant_noise": [],
        "description": "ML topic -- no memories about ML/AI. Should return nothing",
    },
    {
        "id": "Q21",
        "query": "mobile app iOS Swift development",
        "category": "negative",
        "expected_relevant": [],
        "expected_irrelevant_noise": [],
        "description": "iOS development -- no memories about mobile. Should return nothing",
    },
    {
        "id": "Q22",
        "query": "GraphQL schema federation",
        "category": "negative",
        "expected_relevant": [],
        "expected_irrelevant_noise": [],
        "description": "GraphQL -- not in corpus. Should return nothing",
    },

    # Category 7: Partial overlap (some results relevant, others noise)
    {
        "id": "Q23",
        "query": "Python import style conventions",
        "category": "partial_overlap",
        "expected_relevant": ["p02", "p01"],
        "expected_irrelevant_noise": ["c03", "p04"],  # Python version, ruff -- Python-adjacent but not about imports
        "description": "Python conventions -- absolute import pref and naming convention, but Python version constraint is noise",
    },
    {
        "id": "Q24",
        "query": "Docker container deployment production",
        "category": "partial_overlap",
        "expected_relevant": ["r02", "c04"],
        "expected_irrelevant_noise": ["s01"],  # CI/CD mentions deploy but focus is on pipeline not Docker
        "description": "Docker deployment -- hotfix runbook and image size constraint, CI session is peripheral",
    },
    {
        "id": "Q25",
        "query": "memory leak debugging performance",
        "category": "partial_overlap",
        "expected_relevant": ["r04"],
        "expected_irrelevant_noise": ["s04"],  # performance optimization session shares 'performance' but no leak
        "description": "Memory leak -- Node.js debugging runbook is target, performance session is noise",
    },
]


def evaluate(memory_root: Path):
    """Run all queries and produce evaluation output."""
    results = {}

    for q in QUERIES:
        query_results = run_query(q["query"], memory_root, max_results=10)

        # Map results back to memory IDs
        matched_ids = []
        for r in query_results:
            # Extract ID from path: .claude/memory/decisions/d01.json -> d01
            filename = Path(r["path"]).stem
            matched_ids.append(filename)

        # Classify results
        relevant_found = [mid for mid in matched_ids if mid in q["expected_relevant"]]
        relevant_missed = [mid for mid in q["expected_relevant"] if mid not in matched_ids]
        noise_found = [mid for mid in matched_ids if mid in q["expected_irrelevant_noise"]]
        unexpected = [mid for mid in matched_ids
                     if mid not in q["expected_relevant"] and mid not in q["expected_irrelevant_noise"]]

        results[q["id"]] = {
            "query": q["query"],
            "category": q["category"],
            "description": q["description"],
            "bm25_results": [
                {
                    "id": Path(r["path"]).stem,
                    "title": r["title"],
                    "category": r["category"],
                    "score": r.get("score", 0),
                    "snippet": r.get("snippet", "")[:100],
                }
                for r in query_results
            ],
            "relevant_found": relevant_found,
            "relevant_missed": relevant_missed,
            "noise_found": noise_found,
            "unexpected": unexpected,
            "precision_assessment": "",  # filled in later
        }

    return results


def print_results(results: dict):
    """Print evaluation results in a readable format."""
    for qid, data in sorted(results.items()):
        print(f"\n{'='*80}")
        print(f"## {qid}: {data['query']}")
        print(f"Category: {data['category']}")
        print(f"Description: {data['description']}")
        print(f"\nBM25 Results ({len(data['bm25_results'])} hits):")
        for i, r in enumerate(data["bm25_results"]):
            print(f"  {i+1}. [{r['category']}] {r['title']} (score={r['score']:.4f}) [{r['id']}]")
            if r["snippet"]:
                print(f"     Snippet: {r['snippet']}")

        print(f"\nAnalysis:")
        print(f"  Relevant found: {data['relevant_found']}")
        print(f"  Relevant missed: {data['relevant_missed']}")
        print(f"  Noise found: {data['noise_found']}")
        print(f"  Unexpected results: {data['unexpected']}")


def main():
    if not HAS_FTS5:
        print("ERROR: FTS5 not available in this Python build", file=sys.stderr)
        sys.exit(1)

    # Create temp directory with synthetic data
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        memory_root = create_synthetic_data(tmp_path)

        print(f"Created synthetic corpus: {len(MEMORIES)} memories in {memory_root}")
        print(f"Running {len(QUERIES)} evaluation queries...\n")

        results = evaluate(memory_root)
        print_results(results)

        # Output JSON for further analysis
        json_output = json.dumps(results, indent=2, default=str)
        output_path = Path(__file__).parent / "s9-eval-raw-results.json"
        output_path.write_text(json_output)
        print(f"\n\nRaw results written to {output_path}")


if __name__ == "__main__":
    main()
