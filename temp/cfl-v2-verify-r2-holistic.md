# CFL v2 Verification Round 2: Holistic Quality + Actionability

**Verifier**: Opus 4.6 (1M context)
**Cross-model**: Codex 5.3 (holistic quality review, 187s, 285K input tokens)
**Date**: 2026-03-22
**Scope**: Internal consistency, completeness, R1 integration, actionability, user feedback alignment, cross-reference accuracy, design decision trail

---

## Methodology

1. Full read of main v2 document (`research/closed-feedback-loop.md`, 599 lines)
2. Full read of both R1 reports (feasibility + risks)
3. Cross-referenced all file paths, test counts, section references, and supporting document existence
4. Codex 5.3 holistic quality review via clink (187s, line-anchored analysis with explicit references)
5. Independent verification of cross-references (all 8 referenced files confirmed to exist)
6. Vibe check on overall research maturity

---

## 1. Internal Consistency

**[MINOR]** The 5-phase structure is logically ordered and acyclic. Phase dependencies are correct: 1 -> 2 -> 3 -> 4 -> 5. No circular dependencies.

**One internal contradiction identified:**

Phase 1's evidence capture strategy (Section 6.1, lines 202-206) creates an ambiguity between `stream-json` as the "primary analysis source" and `script -e` as a capture method used in the same pipeline. The document says:

- Line 203: `script -e -q -c "..." output.typescript`: child exit code preservation
- Line 205: `stream-json` is the primary analysis source, stdout plaintext is auxiliary

R1-Feasibility Finding #3 confirms these two mechanisms interfere with each other -- PTY wrapping contaminates JSON output. The document presents them as complementary elements of a single capture strategy, but they are actually mutually exclusive for the same invocation.

**Two minor consistency notes:**

- Section 8.1 (line 372) repeats the stale "1097 tests, 19 files" from Section 1 (line 19). R1 confirmed 1158 tests, 21 files. The document is internally consistent (both sections have the same number) but both are outdated.
- Section 14.3 Open Question #1 (line 573) lists `--plugin-dir` repeatability as unresolved, but Section 6.2 (line 231) already describes the decision tree assuming it could go either way. R1 resolved this: it IS repeatable. The open question and the decision tree's "NO" branch are now dead text.

---

## 2. Completeness

**[ACTION NEEDED]** The document covers Phases 1-4 comprehensively but has critical gaps in Phase 5.

**Present and adequate:**
- Problem statement with clear v1 -> v2 evolution rationale
- External reference analysis (autoresearch, ralph) with specific borrowed patterns
- Screen capture research with 3-tier recommendation and cross-model consensus
- Recursive self-installation architecture with path analysis and Guardian hazards
- 5-phase architecture with per-phase deliverables and verification gates
- Cross-model analysis with disagreement resolution
- Test infrastructure reuse strategy
- Hook behavior empirical verification
- Implementation timeline
- Risk matrix (13 items)
- Cost estimation
- File structure
- References (all verified to exist)

**Missing -- prevents complete action plan creation:**

1. **Phase 5 sandbox requirement**: The document relies entirely on prompt-level safety constraints (10 items in Section 6.5, lines 320-330). R1-Risks identified two show-stoppers: `--permission-mode auto` grants unrestricted Bash access (no OS-level containment), and the ralph loop can modify tests (Goodhart's law). Neither risk appears in the 13-risk matrix. These are not edge cases -- they are architectural requirements for Phase 5.

2. **Guardian provenance tracking**: The `evidence/guardian-ref/VERSION` file is mentioned (line 516) but no mechanism for tracking upstream SHA, detecting drift, or defining update cadence. R1-Feasibility Finding #4 and R1-Risks MR-5 both flagged this independently.

3. **Capture strategy clarification**: A developer cannot safely implement Phase 1's evidence collection without knowing that `script` and `stream-json` must be separate invocations. The current text implies they can be combined.

**Missing -- desirable but not blocking:**

4. **Model specification for cost estimates**: Section 12 does not specify which model (Haiku/Sonnet) the cost table assumes. R1-Risks Section 6 shows the difference is 2-5x.
5. **Ralph loop config requirements**: R1-Risks MR-4 recommends `retrieval.enabled: false` AND `triage.enabled: false` for ralph loop sessions. The document mentions "per-run isolation" but does not mandate these specific config settings.

---

## 3. R1 Findings Integration Assessment

**[ACTION NEEDED]** R1 findings are important enough to warrant document updates before action plan creation.

| R1 Finding | Severity | In Main Doc? | Needs Update? |
|-----------|----------|--------------|---------------|
| script + stream-json interference | ISSUE | Contradicted (lines 203-205) | **YES** -- capture strategy must split invocations |
| Guardian provenance gap | ISSUE | Partially (VERSION file only) | **YES** -- add SHA tracking + update cadence |
| 5-week timeline optimistic | ISSUE | No acknowledgment | **YES** -- split into 2 milestones (8 weeks) |
| $5/iteration cost cap too low | MINOR | No acknowledgment | YES -- add model-specific estimates |
| Test count drift (1097 -> 1158) | MINOR | Stale in 2 locations | YES -- factual correction |
| `--plugin-dir` resolved | OK | Still open question | YES -- mark resolved, simplify design |
| Sandbox escape (ralph loop) | SHOW-STOPPER | **NOT IN DOC** | **YES** -- add to risk matrix + Phase 5 requirements |
| Goodhart test mutilation | SHOW-STOPPER | **NOT IN DOC** | **YES** -- add to risk matrix + Phase 5 requirements |
| os.execv() crash cascade | HIGH | Not mentioned | YES -- add to risk matrix |
| Degenerative self-contamination | MEDIUM | Partially (R4/R5) | YES -- mandate config disable for ralph |
| Guardian pinned copy staleness | MEDIUM | Partially | Already covered above |
| Cost model (Sonnet pricing) | LOW | Missing model spec | Already covered above |

**Assessment**: 5 findings require document updates before the document can serve as an action plan foundation. The 2 show-stoppers and 1 issue (capture strategy) are the most urgent -- they represent architectural gaps, not just errata.

---

## 4. Actionability

**[MINOR]** A developer can start Phase 1 from this document but will hit friction points.

**Phase 1 actionability (Evidence Contract):**
- Scenario schemas: Adequately described (Section 6.1 + Section 13 file structure). A developer knows what files to create.
- Run result schema: Clear (stdout, stderr, logs, metadata.json in `evidence/runs/`).
- Track A vs Track B: Clear separation with distinct deliverables.
- **Friction**: The capture command specifics are ambiguous. The document needs to explicitly show two separate command invocations (one for stream-json, one for optional PTY capture).

**Phase 2 actionability (Recursive Self-Testing):**
- Scenario list: 6 scenarios with IDs and descriptions. Adequate.
- Runner design: Pseudocode level only. A developer would need to design the runner from scratch.
- Composite plugin loading: `--plugin-dir` approach is clear (especially after R1 resolves repeatability).
- **Friction**: The meta-validation scenario (SCN-META-001) is well-specified but the other 5 scenarios lack detailed acceptance criteria beyond their 1-line descriptions.

**Phase 3 actionability (Traceability):**
- Requirement marker pattern is clear (`@pytest.mark.requirement("REQ-3.1.1")`).
- Requirements registry structure is clear.
- Domain/ID mapping table is comprehensive (10 domains, 70+ requirements).
- **Friction**: The 70+ requirement IDs are listed by range, not individually enumerated. The implementer must derive individual IDs from the PRD.

**Phase 4 actionability (Gap-to-Action):**
- Pipeline description is clear (flowchart in Section 6.4).
- Dedup strategy is clear (requirement ID exact match).
- Template is mentioned but not shown.

**Phase 5 actionability:**
- **NOT actionable as-is**. Missing sandbox requirements (R1 show-stoppers) make the design unsafe to implement.

**Codex 5.3 assessment agrees**: "A developer can start outlining Phase 1, but not implement it safely/correctly from this text alone until capture strategy is corrected."

---

## 5. User Feedback Alignment

**[OK]** All 4 user feedback points have clear, traceable architectural responses.

| User Feedback | Architectural Response | Section | Adequate? |
|--------------|----------------------|---------|-----------|
| 1. ops env reproduction impossible | Recursive self-installation in canonical repo + Guardian co-load | 5.1 | YES |
| 2. Manual dependency | Phase 2 automated runner + Phase 4 gap-to-action pipeline | 6.2, 6.4 | YES |
| 3. Insufficient logs | Dual-track evidence (Track A: stream-json + logs, Track B: manual TUI) | 4.2, 6.1 | YES |
| 4. No closed loop | Phase 4 -> 5 pipeline: gap detection -> action plan -> fix -> verify | 6.4, 6.5 | YES |

**Strengths:**
- The "Honest Limitations" section (Section 2, lines 48-53) explicitly acknowledges what the architecture CANNOT solve (TUI popup auto-verification, Guardian bugs, user allow/deny capture). This is unusually transparent for a research document.
- The v1 -> v2 comparison table (Section 2, lines 39-46) makes the evolution explicit for each feedback point.

**One gap noted but not serious**: User feedback point #3 ("logs") is addressed by the dual-track system, but the Track A capture mechanism has the script/stream-json ambiguity noted above. The response exists but the implementation path is unclear.

---

## 6. Cross-Reference Accuracy

**[MINOR]** All external references verified. Minor staleness in internal data.

### File Path References (8 checked, 8 exist)

| Referenced Path | Exists? | Notes |
|----------------|---------|-------|
| `docs/requirements/prd.md` | YES | |
| `docs/architecture/architecture.md` | YES | |
| `action-plans/observability-and-logging.md` | YES | |
| `temp/cfl-v2-screen-capture.md` | YES | |
| `temp/cfl-v2-recursive-arch.md` | YES | |
| `temp/cfl-v2-phase-redesign.md` | YES | |
| `temp/cfl-cross-model-synthesis.md` | YES | |
| `temp/cfl-verify-r*` (4 v1 verification files) | YES | All 4 present |

### Internal Data Accuracy

| Claim | Document | Actual | Status |
|-------|----------|--------|--------|
| Test files | 19 | 20 (test_*.py) or 21 (including conftest.py) | **STALE** |
| Test cases | 1097 | 1158 (per R1) | **STALE** |
| Staging hash | 52f0f4a8baed | 52f0f4a8baed (R1 confirmed) | OK |
| Pydantic version | 2.x | 2.12.5 (R1 confirmed) | OK |
| Claude Code version | v2.1.81 | v2.1.81 (R1 reference) | OK |

### Test File Coverage in Section 8.1

The document's Section 8.1 test listing is missing 3 test files that exist in the repo:
- `test_arch_fixes.py` -- not listed
- `test_memory_staging_utils.py` -- not listed
- `test_v2_adversarial_fts5.py` -- partially covered by "test_adversarial_*.py" glob pattern

These are the files added since the document was written, consistent with R1's +2 files finding (R1 said 21 vs 19; actual delta from document's list is +3 `test_*.py` files, but the document counted differently).

---

## 7. Design Decision Trail

**[MINOR]** Major decisions are documented with rationale. Some decisions lack justification depth.

**Well-documented decisions:**
- v1 -> v2 pivot rationale (4 user feedback points -> architectural response)
- True dogfood vs worktree isolation (Section 5.1, user intent prioritized over safety isolation)
- TUI scraping rejection (3-model consensus in Section 4.3)
- Phase 3/4 merge (circular dependency resolution, Codex-originated)
- Manual-first before automation (Section 6.5, maturity model)
- /tmp staging preservation over project-internal (popup regression prevention)

**Under-documented decisions:**
- **Guardian pinned copy vs submodule vs runtime clone**: The document names Option B (pinned copy) but rationale is only "simplicity." R1 provides the options analysis that the main document should have included.
- **$5/iteration cost cap**: No derivation shown. Section 12 provides cost breakdown but constraint #5 ($5/iteration) appears without supporting math.
- **5-week timeline**: No estimation methodology. Just a week-by-week breakdown without risk buffer.
- **10 safety constraints**: Listed without priority ordering. Are constraints #1 (no auto-merge) and #4 (test regression) more critical than #8 (git cleanliness)? The document treats them equally.

---

## 8. Vibe Check

### Overall Research Maturity

**Strong research document with a Phase 5 blind spot.**

The document demonstrates several markers of high-quality research:
- **Intellectual honesty**: The "Honest Limitations" section is genuinely honest. It admits TUI popup verification is impossible, not "difficult." It admits user allow/deny capture has no solution, not "needs further research."
- **Cross-model validation**: Three independent models (Opus, Codex, Gemini) assessed the architecture. Disagreements are documented with resolution rationale (Section 7.3).
- **Progressive disclosure**: The main document (599 lines) provides the complete picture with references to 4 supporting documents for deep dives. A reader does not need to read all 4 to understand the architecture.
- **Borrowed patterns with attribution**: External references (autoresearch, ralph) cite specific patterns borrowed, not vague "inspired by."
- **Concrete deliverables**: Each phase has named output files, verification gates, and a file structure showing where everything goes.

**The blind spot** is Phase 5. The document applies the "manual-first" principle correctly (don't automate until you've done it 3 times manually), but it then designs the ralph loop automation as if prompt-level constraints provide security guarantees. R1's two show-stoppers expose this gap. The rest of the document (Phases 1-4) is significantly more mature than Phase 5.

**Calibration**: This is a research document, not an implementation spec. At this maturity level, Phase 5's gaps are acceptable IF:
1. The action plan treats Phase 5 as gated on sandbox infrastructure
2. The R1 findings are incorporated before action plan creation
3. The document is updated with an errata section or inline corrections

### Codex 5.3 Agreement

Codex independently rated 7 dimensions and arrived at compatible conclusions:
- Internal Consistency: [MINOR] (I agree)
- Completeness: [ACTION NEEDED] (I agree)
- Actionability: [ACTION NEEDED] (I rated [MINOR] -- difference is whether capture strategy ambiguity is blocking or friction. I lean toward friction since the fix is a single sentence clarification.)
- Design Decision Trail: [MINOR] (I agree)
- User Feedback Alignment: [OK] (I agree)
- Risk Coverage: [ACTION NEEDED] (I agree)
- Overall Quality: [MINOR] (I agree)

**One disagreement with Codex**: Codex rated Actionability as [ACTION NEEDED], arguing a developer "cannot implement safely/correctly from this text alone." I rate it [MINOR] because the capture strategy fix is trivial (add one sentence: "These must be separate invocations") and the Phase 5 sandbox gap does not block Phases 1-4 work. A developer CAN start Phase 1 today; they just cannot start Phase 5.

---

## 9. Summary Verdict Table

| Dimension | Verdict | Key Finding |
|-----------|---------|------------|
| 1. Internal Consistency | **[MINOR]** | Phase structure is sound; capture strategy self-contradicts; 2 stale data points |
| 2. Completeness | **[ACTION NEEDED]** | Phase 5 missing sandbox + test immutability; Guardian provenance incomplete |
| 3. R1 Integration | **[ACTION NEEDED]** | 2 show-stoppers + 1 architectural issue not yet reflected in main doc |
| 4. Actionability | **[MINOR]** | Phases 1-4 actionable with friction; Phase 5 not actionable until sandbox added |
| 5. User Feedback Alignment | **[OK]** | All 4 points have clear responses; Honest Limitations adds credibility |
| 6. Cross-Reference Accuracy | **[MINOR]** | All file paths valid; test count and 2 data points stale |
| 7. Design Decision Trail | **[MINOR]** | Major decisions documented; cost/timeline/guardian-copy under-justified |

### Overall Assessment

**The CFL v2 research document is a strong foundation for Phases 1-4 action plans after a focused errata pass. Phase 5 requires architectural updates (sandbox, test immutability) before action plan creation.**

### Required Updates Before Action Plan Creation

**Priority 1 (architectural -- blocks Phase 5 action plan):**
1. Add sandbox/containerization requirement to Phase 5 ralph loop design
2. Add read-only test pinning to ralph loop safety constraints
3. Add both to risk matrix as R14 and R15

**Priority 2 (correctness -- blocks Phase 1 action plan accuracy):**
4. Split capture strategy: explicit separate invocations for stream-json and script -e
5. Add Guardian provenance tracking (upstream SHA + update cadence)

**Priority 3 (errata -- trust and accuracy):**
6. Update test count: 1097 -> 1158, 19 files -> 21 files (2 locations)
7. Mark `--plugin-dir` repeatability as RESOLVED; simplify decision tree
8. Split timeline: 5 weeks -> 8 weeks in 2 milestones
9. Add model-specific cost estimates (Haiku vs Sonnet)
10. Mandate `retrieval.enabled: false` + `triage.enabled: false` for ralph loop config

### What to Keep (Strengths)

- Honest Limitations section -- unusually transparent, builds trust
- Acyclic 5-phase structure with verification gates per phase
- Manual-first maturity model before automation
- Residual Risk Register concept (acknowledges imperfect coverage)
- Dual-track evidence (automated + manual) design
- Cross-model consensus documentation with disagreement resolution
- Progressive disclosure with supporting documents

---

## Cross-Model Validation Log

### Codex 5.3 (clink, codereviewer role, 187s, 285K input tokens)

**Methodology**: Line-anchored review with explicit file:line references. Verified test count independently (confirmed 21 files via `rg --files tests | wc -l`).

**Agreed with my findings**:
- Phase 5 not safe as written (CRITICAL)
- Risk matrix incomplete (missing 2 show-stoppers)
- Capture strategy internally inconsistent
- Guardian provenance needs tracking
- Planning facts stale

**Codex-specific additions**:
- Explicit line references for all contradictions (useful for implementer)
- Recommended update order: (1) capture commands, (2) Phase 5 safety + risk matrix, (3) Guardian provenance, (4) errata refresh

**Codex-specific emphasis**:
- Rated Actionability as [ACTION NEEDED] where I rated [MINOR] -- Codex is more conservative about whether Phase 1 can start without capture fix. Reasonable position but I think the fix is trivially small.

**Positive practices Codex highlighted**:
- "Honest Limitations, acyclic phase structure, residual-risk register, and manual-first before automation" -- worth preserving through updates
