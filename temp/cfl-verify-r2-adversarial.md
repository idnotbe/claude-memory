# Adversarial Review (R2): Closed Feedback Loop Research

**Reviewer stance**: Contrarian. What is missing, wrong, or falsely reassuring?

---

## 1. Circular Reasoning: The Plugin Tests Itself

Section 4.3 (Phase 2) runs `claude -p` with `--plugin-dir .` to verify plugin behavior. But the plugin's own hooks fire during that execution. If the triage hook has a subtle bug that *also* corrupts the test harness's log output, the runner's `check_log_events` reads corrupted data and may still report PASS. The document treats workspace isolation (Section 6.2) as sufficient, but isolation only prevents cross-run contamination -- it does not prevent intra-run self-interference where the plugin under test poisons its own evaluation artifacts. Section 6.3 acknowledges this ("그 claude 인스턴스는 플러그인 훅의 영향을 받음 (이것이 의도)") but waves it away. This is the core circularity problem and it is unaddressed.

## 2. Missing Failure Modes in Risk Matrix (Section 8)

The risk matrix omits at least three critical scenarios:
- **Flaky deterministic oracles**: `claude -p` output is LLM-generated. Even with `expected_signals` string matching, the model can rephrase, producing FAIL on correct behavior. This is not "LLM judging noise" -- it is oracle instability in what the document calls the "deterministic" tier.
- **Claude version skew**: The runner records `claude_version` but nothing gates on it. A Claude CLI update could change hook dispatch semantics, output format, or `--output-format json` schema silently, breaking all scenarios without any code change in the plugin.
- **Runner script bit-rot**: Who tests the test infrastructure? If `runner.sh` has a bug in `check_expected_signals`, every scenario silently passes. There is no meta-validation proposed.

## 3. False Confidence: Tests Pass, Real Behavior Broken

Section 4.2 scenario SCN-UX-001 checks "popup-free quiet operation" by looking for `forbidden_signals` in stdout. But popups in Claude Code are Guardian approval dialogs -- they exist in the interactive TUI, not in `claude -p` JSON output. A regression that adds a new approval popup would be invisible to `claude -p` because `--permission-mode dontAsk` suppresses them. The test passes; users suffer. This is the most dangerous false-confidence vector in the entire design.

## 4. Phase 5 Shadow Loop: Complexity Without Payoff

Section 4.6 proposes `--permission-mode plan` which generates a plan but does not execute it. Then `pytest` and `runner.py` run as quality gates. But if the fix was never actually applied (plan mode), what are pytest/runner validating? The old code. The script then does `git add -A && git commit` -- committing what exactly? The document's own pseudocode is internally inconsistent. Either `plan` mode produces code changes (contradicting its description) or the quality gates test nothing new. This is complexity for its own sake until the execution model is clarified.

## 5. Cost Analysis: Missing Entirely

Running `claude -p` is not free. Each scenario invocation costs API tokens (the spawned Claude session reasons, calls tools, generates output). With 3 scenarios in Phase 2 expanding to N scenarios in Phase 4, and the Shadow Loop running 5 iterations each calling `claude -p` plus a full `claude -p` fix attempt: a single loop execution could easily cost $5-20 in API calls. The document contains zero cost estimation, no budget constraints, no discussion of when the feedback loop's cost exceeds the value of the bugs it finds. For a plugin with 1097 existing pytest tests that run in seconds for free, the ROI argument is never made.

## 6. "Deterministic Oracles Only" Is a Fiction

Section 3.1 item 4 claims universal agreement on "deterministic oracles primary." But Section 4.5 maps REQ-4.1 ("Minimal Screen Noise") to live scenarios. Screen noise is inherently a UX/subjective property. Checking for specific forbidden strings is not deterministic verification of "minimal noise" -- it is a brittle proxy that passes until the noise takes a form you did not anticipate. The document never reconciles this tension. Either admit some requirements need LLM judgment for pass/fail (contradicting Section 3.1), or admit some requirements are unverifiable by this framework (reducing its coverage claims).

## 7. Cross-Repo Promotion (Section 4.4) Has No Dedup Mechanism

The document says "기존 항목과 매칭하여 update (새 항목 스팸 방지)" but provides zero detail on how matching works. Fuzzy title matching? Exact scenario ID? If the same failure manifests differently across sessions, you get duplicate action plans. If matching is too aggressive, distinct failures get merged. This is hand-waved as a one-liner when it is actually the hardest problem in the promotion pipeline.

---

**Bottom line**: The architecture borrows good patterns from autoresearch and ralph, but the document systematically underestimates the gap between "string matching on CLI output" and "verifying plugin behavior." The most valuable next step is not building the loop -- it is running the spike test (Section 6.1) and discovering how much of the design survives contact with `claude -p`'s actual behavior.
