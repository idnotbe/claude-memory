"""P0 regression tests: prevent approval popup issues from recurring.

These tests verify three invariants that, if violated, cause unexpected
approval popups (Guardian "ask" verdicts or Guardian pattern matches)
when the memory plugin operates:

1. No hook script ever outputs a 'permissionDecision' of 'ask'.
2. SKILL.md bash commands don't match Guardian block/ask patterns.
3. SKILL.md follows its own Rule 0 for Guardian compatibility.

The Guardian patterns are embedded as constants so these tests run without
depending on the guardian repository.
"""

import ast
import os
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
HOOKS_SCRIPTS = PROJECT_ROOT / "hooks" / "scripts"
SKILL_MD = PROJECT_ROOT / "skills" / "memory-management" / "SKILL.md"

GUARD_SCRIPTS = [
    HOOKS_SCRIPTS / "memory_write_guard.py",
    HOOKS_SCRIPTS / "memory_staging_guard.py",
    HOOKS_SCRIPTS / "memory_validate_hook.py",
]

# ---------------------------------------------------------------------------
# Guardian patterns (from guardian.default.json -- embedded here so tests
# are self-contained and don't depend on the guardian repo).
# ---------------------------------------------------------------------------

# Block patterns: these result in unconditional deny.
GUARDIAN_BLOCK_PATTERNS = [
    # Claude deletion: rm/rmdir/del/delete targeting .claude
    re.compile(
        r'(?i)(?:^\s*|[;|&`({]\s*)(?:rm|rmdir|del|delete|deletion|remove-item)\b\s+.*'
        r'\.claude(?:\s|/|[;&|)`\'"]|$)',
        re.MULTILINE,
    ),
    # find with -delete
    re.compile(r'(?i)find\s+.*\s+-delete'),
    # Interpreter deletion: python3 ... os.remove/shutil.rmtree etc.
    # Note: [^|&\n]* stops at newlines, so multiline python3 -c won't match.
    re.compile(
        r'(?:py|python[23]?|python\d[\d.]*)\s[^|&\n]*'
        r'(?:os\.remove|os\.unlink|shutil\.rmtree|shutil\.move|os\.rmdir)',
    ),
    # Pathlib deletion: python3 ... pathlib.Path(...).unlink()
    re.compile(
        r'(?:py|python[23]?|python\d[\d.]*)\s[^|&\n]*'
        r'pathlib\.Path\([^)]*\)\.unlink',
    ),
]

# Ask patterns: these trigger a confirmation popup.
GUARDIAN_ASK_PATTERNS = [
    # Recursive/force rm
    re.compile(r'rm\s+-[rRf]+'),
    # find with exec delete
    re.compile(r'find\s+.*-exec\s+(?:rm|del|shred)'),
    # Moving protected dotfiles (.env/.git/.claude) — capturing group to match Guardian exactly
    re.compile(r'mv\s+[\'"]?(?:\./)?\.(env|git|claude)'),
    # xargs with delete
    re.compile(r'xargs\s+(?:rm|del|shred)'),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_bash_blocks(markdown_path: Path) -> list[tuple[str, int]]:
    """Extract bash/shell code blocks from a markdown file.

    Returns a list of (code_content, line_number) tuples.
    """
    text = markdown_path.read_text(encoding="utf-8")
    blocks = []
    in_block = False
    current_lines: list[str] = []
    block_start = 0

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("```") and any(
                lang in stripped.lower()
                for lang in ("bash", "sh", "shell", "console", "terminal", "zsh")
            ):
                in_block = True
                current_lines = []
                block_start = i + 1
        else:
            if stripped == "```":
                in_block = False
                blocks.append(("\n".join(current_lines), block_start))
            else:
                current_lines.append(line)

    return blocks


def _find_string_literals_with_permission(source: str) -> list[dict]:
    """Walk the AST of a Python source file and collect all string literals
    that are part of a dict/keyword assignment involving 'permissionDecision'.

    Returns list of dicts with keys: value, lineno, context.
    Also detects non-constant (dynamic) values which are flagged as
    'DYNAMIC' to force a test failure -- guard scripts must use static
    string literals for permissionDecision values.
    """
    results = []
    tree = ast.parse(source)

    for node in ast.walk(tree):
        # Check dict literals: {"permissionDecision": <value>}
        if isinstance(node, ast.Dict):
            for key_node, val_node in zip(node.keys, node.values):
                if (
                    isinstance(key_node, ast.Constant)
                    and key_node.value == "permissionDecision"
                ):
                    if (
                        isinstance(val_node, ast.Constant)
                        and isinstance(val_node.value, str)
                    ):
                        results.append({
                            "value": val_node.value,
                            "lineno": val_node.lineno,
                            "context": "dict_literal",
                        })
                    else:
                        # Non-constant value (variable, f-string, concat, etc.)
                        # Flag as DYNAMIC so test_only_allow_or_deny catches it.
                        results.append({
                            "value": "DYNAMIC",
                            "lineno": key_node.lineno,
                            "context": "dynamic_value",
                        })

    return results


# ===================================================================
# Test Class 1: No guard script outputs "ask"
# ===================================================================

class TestNoAskVerdict:
    """Verify that no guard script ever outputs permissionDecision='ask'.

    Guard scripts should only output 'allow' or 'deny'. An 'ask' verdict
    would cause an approval popup to appear for the user, which defeats
    the purpose of auto-approving known-safe operations.
    """

    @pytest.mark.parametrize(
        "script_path",
        GUARD_SCRIPTS,
        ids=[p.name for p in GUARD_SCRIPTS],
    )
    def test_no_ask_in_source(self, script_path: Path):
        """Parse Python source to find all permissionDecision values and
        verify none are 'ask'."""
        source = script_path.read_text(encoding="utf-8")
        literals = _find_string_literals_with_permission(source)

        ask_literals = [
            lit for lit in literals if lit["value"].lower() == "ask"
        ]
        assert not ask_literals, (
            f"{script_path.name} contains permissionDecision='ask' at "
            f"line(s): {[l['lineno'] for l in ask_literals]}. "
            f"Guard scripts must only output 'allow' or 'deny'."
        )

    @pytest.mark.parametrize(
        "script_path",
        GUARD_SCRIPTS,
        ids=[p.name for p in GUARD_SCRIPTS],
    )
    def test_only_allow_or_deny(self, script_path: Path):
        """All permissionDecision values in each guard script should be
        exactly 'allow' or 'deny'."""
        source = script_path.read_text(encoding="utf-8")
        literals = _find_string_literals_with_permission(source)

        # There should be at least one permissionDecision in each script
        # (otherwise the script never emits a verdict, which might be a bug).
        assert len(literals) > 0, (
            f"{script_path.name} has no permissionDecision literals. "
            f"Expected at least one 'allow' or 'deny' verdict."
        )

        allowed_values = {"allow", "deny"}
        bad = [
            lit for lit in literals if lit["value"] not in allowed_values
        ]
        assert not bad, (
            f"{script_path.name} has unexpected permissionDecision value(s): "
            f"{[(l['value'], l['lineno']) for l in bad]}. "
            f"Only {allowed_values} are permitted."
        )

    @pytest.mark.parametrize(
        "script_path",
        GUARD_SCRIPTS,
        ids=[p.name for p in GUARD_SCRIPTS],
    )
    def test_no_ask_in_raw_text(self, script_path: Path):
        """Belt-and-suspenders: regex scan for 'ask' near permissionDecision
        in case the AST walk misses dynamically constructed strings.

        Uses DOTALL to catch multi-line constructs like:
            {"permissionDecision":
                "ask"}
        """
        source = script_path.read_text(encoding="utf-8")

        # Single-line check (original, fast path)
        for i, line in enumerate(source.splitlines(), start=1):
            if "permissionDecision" in line and re.search(
                r'''['"]ask['"]''', line
            ):
                pytest.fail(
                    f"{script_path.name}:{i} contains 'ask' near "
                    f"permissionDecision: {line.strip()}"
                )

        # Multi-line check: find 'ask' within ~200 chars after permissionDecision
        # (covers dict formatting across lines)
        match = re.search(
            r'permissionDecision.{0,200}?[\'"]ask[\'"]',
            source,
            re.DOTALL,
        )
        if match:
            line_num = source[:match.start()].count('\n') + 1
            pytest.fail(
                f"{script_path.name}:{line_num} contains 'ask' near "
                f"permissionDecision (multi-line match)"
            )


# ===================================================================
# Test Class 2: SKILL.md bash commands vs Guardian patterns
# ===================================================================

class TestSkillMdGuardianConflicts:
    """Verify that bash commands in SKILL.md don't match Guardian
    block or ask patterns.

    If a SKILL.md command matches a Guardian pattern, the user will
    see an approval popup (ask) or the command will be silently
    blocked (deny) during memory operations.
    """

    @pytest.fixture(scope="class")
    def bash_blocks(self) -> list[tuple[str, int]]:
        """Extract all bash code blocks from SKILL.md."""
        blocks = extract_bash_blocks(SKILL_MD)
        assert len(blocks) > 0, "No bash blocks found in SKILL.md"
        return blocks

    @pytest.mark.parametrize(
        "pattern,pattern_name",
        [
            (GUARDIAN_BLOCK_PATTERNS[0], "block:claude_deletion"),
            (GUARDIAN_BLOCK_PATTERNS[1], "block:find_delete"),
            (GUARDIAN_BLOCK_PATTERNS[2], "block:interpreter_deletion"),
            (GUARDIAN_BLOCK_PATTERNS[3], "block:pathlib_unlink"),
        ],
    )
    def test_no_block_pattern_matches(
        self, bash_blocks, pattern, pattern_name
    ):
        """No bash block in SKILL.md should match a Guardian block pattern."""
        violations = []
        for code, line_no in bash_blocks:
            match = pattern.search(code)
            if match:
                violations.append(
                    f"  SKILL.md line ~{line_no}: matched {pattern_name}\n"
                    f"    Pattern: {pattern.pattern[:80]}...\n"
                    f"    Match: {match.group()!r}\n"
                    f"    Command: {code.strip()[:120]}"
                )
        assert not violations, (
            f"SKILL.md bash commands match Guardian block pattern "
            f"'{pattern_name}':\n" + "\n".join(violations)
        )

    @pytest.mark.parametrize(
        "pattern,pattern_name",
        [
            (GUARDIAN_ASK_PATTERNS[0], "ask:rm_recursive_force"),
            (GUARDIAN_ASK_PATTERNS[1], "ask:find_exec_delete"),
            (GUARDIAN_ASK_PATTERNS[2], "ask:mv_claude"),
            (GUARDIAN_ASK_PATTERNS[3], "ask:xargs_delete"),
        ],
    )
    def test_no_ask_pattern_matches(
        self, bash_blocks, pattern, pattern_name
    ):
        """No bash block in SKILL.md should match a Guardian ask pattern."""
        violations = []
        for code, line_no in bash_blocks:
            match = pattern.search(code)
            if match:
                violations.append(
                    f"  SKILL.md line ~{line_no}: matched {pattern_name}\n"
                    f"    Pattern: {pattern.pattern}\n"
                    f"    Match: {match.group()!r}\n"
                    f"    Command: {code.strip()[:120]}"
                )
        assert not violations, (
            f"SKILL.md bash commands match Guardian ask pattern "
            f"'{pattern_name}':\n" + "\n".join(violations)
        )

    def test_python3_c_multiline_does_not_match_block(self, bash_blocks):
        """Verify that any multiline python3 -c commands do NOT match
        the interpreter deletion block pattern.

        The block pattern uses [^|&\\n]* which stops at newlines, so
        `python3 -c "import ...\\nos.remove(f)"` should not match because
        os.remove is on a different line from python3.

        NOTE: As of P1 popup fix, SKILL.md no longer uses python3 -c for
        file operations (Rule 0 forbids it). This test remains as a guard
        against regressions if python3 -c is reintroduced.
        """
        interpreter_block = GUARDIAN_BLOCK_PATTERNS[2]
        python3_c_blocks = [
            (code, line_no)
            for code, line_no in bash_blocks
            if "python3 -c" in code
        ]
        for code, line_no in python3_c_blocks:
            match = interpreter_block.search(code)
            assert match is None, (
                f"SKILL.md line ~{line_no}: python3 -c block unexpectedly "
                f"matches interpreter deletion block pattern.\n"
                f"Match: {match.group()!r}\n"
                f"Code: {code.strip()[:200]}\n"
                f"This means Guardian would unconditionally BLOCK this "
                f"command (not just ask)."
            )


# ===================================================================
# Test Class 3: SKILL.md Rule 0 compliance
# ===================================================================

class TestSkillMdRule0Compliance:
    """Verify that SKILL.md bash commands follow Rule 0.

    Rule 0 (from SKILL.md Rules section):
    'Never combine heredoc (<<), Python interpreter, and .claude path
    in a single Bash command. All staging file content must be written
    via Write tool (not Bash). Bash is only for running python3 scripts.
    Do NOT use python3 -c with inline code referencing .claude paths.
    Do NOT use find -delete or rm with .claude paths. Do NOT pass inline
    JSON containing .claude paths on the Bash command line.'

    Violations of Rule 0 are the root cause of Guardian approval popups.
    """

    @pytest.fixture(scope="class")
    def bash_blocks(self) -> list[tuple[str, int]]:
        """Extract all bash code blocks from SKILL.md."""
        return extract_bash_blocks(SKILL_MD)

    def test_no_heredoc_with_claude_path(self, bash_blocks):
        """No bash block should combine heredoc (<<) with .claude paths."""
        # Heredoc pattern: << followed by some delimiter
        heredoc_re = re.compile(r'<<\s*[\'"]?\w+')
        claude_path_re = re.compile(r'\.claude')

        violations = []
        for code, line_no in bash_blocks:
            if heredoc_re.search(code) and claude_path_re.search(code):
                violations.append(
                    f"  SKILL.md line ~{line_no}: heredoc + .claude path\n"
                    f"    Command: {code.strip()[:150]}"
                )
        assert not violations, (
            "SKILL.md bash blocks combine heredoc (<<) with .claude paths. "
            "This triggers Guardian write detection.\n" +
            "\n".join(violations)
        )

    def test_no_find_delete_with_claude_path(self, bash_blocks):
        """No bash block should use find -delete with .claude paths."""
        find_delete_re = re.compile(r'find\s+.*\.claude.*-delete', re.DOTALL)
        find_delete_alt_re = re.compile(
            r'find\s+.*-delete.*\.claude', re.DOTALL
        )

        violations = []
        for code, line_no in bash_blocks:
            if find_delete_re.search(code) or find_delete_alt_re.search(code):
                violations.append(
                    f"  SKILL.md line ~{line_no}: find -delete + .claude\n"
                    f"    Command: {code.strip()[:150]}"
                )
        assert not violations, (
            "SKILL.md bash blocks use 'find -delete' with .claude paths. "
            "This triggers Guardian block pattern.\n" +
            "\n".join(violations)
        )

    def test_no_rm_with_claude_path(self, bash_blocks):
        """No bash block should use rm with .claude paths."""
        # Match rm (with optional flags) followed by something containing .claude
        rm_claude_re = re.compile(
            r'\brm\s+(?:-[a-zA-Z]*\s+)?[^\n]*\.claude'
        )

        violations = []
        for code, line_no in bash_blocks:
            if rm_claude_re.search(code):
                violations.append(
                    f"  SKILL.md line ~{line_no}: rm + .claude path\n"
                    f"    Command: {code.strip()[:150]}"
                )
        assert not violations, (
            "SKILL.md bash blocks use 'rm' with .claude paths. "
            "This triggers Guardian block/ask pattern.\n" +
            "\n".join(violations)
        )

    def test_no_inline_json_with_claude_path(self, bash_blocks):
        """No bash block should pass inline JSON containing .claude paths.

        The --result-file approach (writing JSON to a file first, then
        passing the file path) is OK and should NOT be flagged.

        We specifically look for JSON object literals (quoted strings with
        braces like '{"key": "value"}') that contain .claude paths, NOT
        mere shell variable references like ${CLAUDE_PLUGIN_ROOT} or
        .claude as a plain CLI argument.
        """
        # Match JSON object literals: '{' followed by a quoted key pattern,
        # indicating an actual JSON string being passed on the command line.
        # This catches: echo '{"path": ".claude/memory/..."}' but not:
        #   python3 "${CLAUDE_PLUGIN_ROOT}/..." --staging-dir .claude/...
        inline_json_re = re.compile(
            r"""['"]\s*\{[^}]*\.claude[^}]*\}"""  # '{"...claude..."}
            r"""|"""
            r"""\{[^}]*['"]\.claude[^}]*\}"""  # {"...'.claude'...}
        )

        violations = []
        for code, line_no in bash_blocks:
            for i, line in enumerate(code.splitlines()):
                # Skip lines that use --result-file (the safe approach)
                if "--result-file" in line:
                    continue
                # Skip comment lines
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Strip shell variable references to avoid false positives
                cleaned = re.sub(r'\$\{?\w+\}?', '', line)
                if inline_json_re.search(cleaned):
                    violations.append(
                        f"  SKILL.md line ~{line_no + i}: "
                        f"inline JSON + .claude path\n"
                        f"    Line: {line.strip()[:150]}"
                    )
        assert not violations, (
            "SKILL.md bash blocks contain inline JSON with .claude paths. "
            "Use --result-file approach instead.\n" +
            "\n".join(violations)
        )

    def test_no_python3_c_with_claude_path(self, bash_blocks):
        """No bash block should use python3 -c with .claude paths.

        Rule 0 forbids python3 -c for any file operations. The Phase 0
        cleanup command was migrated to use cleanup-intents action in
        memory_write.py to avoid Guardian interpreter payload detection.

        This test fails if ANY python3 -c blocks with .claude paths appear.
        """
        python3_c_claude_re = re.compile(
            r'python3\s+-c\s+["\'].*\.claude', re.DOTALL
        )

        violations = []
        for code, line_no in bash_blocks:
            if python3_c_claude_re.search(code):
                violations.append((code.strip()[:200], line_no))

        assert not violations, (
            f"SKILL.md has {len(violations)} python3 -c block(s) with "
            f".claude paths. Rule 0 forbids python3 -c for file operations. "
            f"Use dedicated scripts instead.\n"
            f"Violations:\n" +
            "\n".join(
                f"  Line ~{ln}: {cmd[:120]}" for cmd, ln in violations
            )
        )


# ===================================================================
# Test Class 4: Guard script file existence
# ===================================================================

class TestGuardScriptsExist:
    """Sanity check: all guard scripts referenced in these tests exist."""

    @pytest.mark.parametrize(
        "script_path",
        GUARD_SCRIPTS,
        ids=[p.name for p in GUARD_SCRIPTS],
    )
    def test_script_exists(self, script_path: Path):
        assert script_path.exists(), f"Guard script not found: {script_path}"

    def test_skill_md_exists(self):
        assert SKILL_MD.exists(), f"SKILL.md not found: {SKILL_MD}"


# ===================================================================
# Test Class 5: Guardian pattern sync check (optional)
# ===================================================================

class TestGuardianPatternSync:
    """Optional sync check: verify embedded patterns match the live
    Guardian config.

    These tests are skipped if the Guardian repo is not available as a
    sibling directory. When present, they verify that the embedded
    patterns haven't drifted from the actual Guardian defaults.
    """

    GUARDIAN_CONFIG_PATHS = [
        PROJECT_ROOT.parent / "claude-code-guardian" / "assets" / "guardian.default.json",
    ]

    @pytest.fixture(scope="class")
    def guardian_config(self):
        """Load guardian.default.json from sibling directory."""
        import json
        for path in self.GUARDIAN_CONFIG_PATHS:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        pytest.skip(
            "Guardian repo not found as sibling directory. "
            "Skipping pattern sync check."
        )

    @staticmethod
    def _normalize(pattern: str) -> str:
        """Normalize regex escaping for comparison.

        Raw strings in Python may add unnecessary escapes (e.g. \\' vs ')
        that are functionally equivalent in regex character classes.
        """
        # In character classes, \' and ' are equivalent
        return pattern.replace("\\'", "'")

    def test_block_patterns_in_sync(self, guardian_config):
        """Verify critical embedded block patterns match Guardian defaults."""
        guardian_blocks = guardian_config.get("bashToolPatterns", {}).get("block", [])
        guardian_block_set = {self._normalize(p["pattern"]) for p in guardian_blocks}

        # Check our 4 embedded block patterns are present in Guardian
        for compiled in GUARDIAN_BLOCK_PATTERNS:
            normalized = self._normalize(compiled.pattern)
            assert normalized in guardian_block_set, (
                f"Embedded block pattern not found in Guardian config:\n"
                f"  Pattern: {normalized[:80]}...\n"
                f"  Guardian may have changed. Update GUARDIAN_BLOCK_PATTERNS."
            )

    def test_ask_patterns_in_sync(self, guardian_config):
        """Verify critical embedded ask patterns match Guardian defaults."""
        guardian_asks = guardian_config.get("bashToolPatterns", {}).get("ask", [])
        guardian_ask_set = {self._normalize(p["pattern"]) for p in guardian_asks}

        # Check our 4 embedded ask patterns are present in Guardian
        for compiled in GUARDIAN_ASK_PATTERNS:
            normalized = self._normalize(compiled.pattern)
            assert normalized in guardian_ask_set, (
                f"Embedded ask pattern not found in Guardian config:\n"
                f"  Pattern: {normalized}\n"
                f"  Guardian may have changed. Update GUARDIAN_ASK_PATTERNS."
            )


# ===================================================================
# Test Class 6: P4 — Zero python3 -c commands in SKILL.md
# ===================================================================

class TestZeroPython3CInSkill:
    """Verify SKILL.md has ZERO python3 -c commands.

    P1 popup fix replaced all python3 -c inline code with dedicated
    script actions (cleanup-intents). This test enforces zero tolerance
    for regressions.
    """

    def test_no_python3_c_in_any_bash_block(self):
        """No bash block in SKILL.md should contain python3 -c."""
        blocks = extract_bash_blocks(SKILL_MD)
        violations = []
        for code, line_no in blocks:
            if "python3 -c" in code:
                violations.append(
                    f"  Line ~{line_no}: {code.strip()[:120]}"
                )
        assert not violations, (
            f"SKILL.md contains {len(violations)} bash block(s) with "
            f"'python3 -c'. P1 popup fix requires ALL inline python to "
            f"be replaced with dedicated script actions.\n"
            + "\n".join(violations)
        )

    def test_no_python3_c_in_non_bash_code_blocks(self):
        """No non-bash code block in SKILL.md should contain python3 -c.

        Prose/documentation mentions (like Rule 0 saying 'Do NOT use
        python3 -c') are allowed. Only executable code blocks matter,
        and those are already covered by test_no_python3_c_in_any_bash_block.

        This test catches python3 -c in non-bash code blocks (e.g., plain
        ``` blocks that might be copy-pasted as commands).
        """
        text = SKILL_MD.read_text(encoding="utf-8")
        # Find all code blocks (any language)
        in_block = False
        is_bash_block = False
        violations = []
        block_start = 0

        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not in_block and stripped.startswith("```"):
                in_block = True
                block_start = i
                # Check if it's a bash block (already covered by other test)
                is_bash_block = any(
                    lang in stripped.lower()
                    for lang in ("bash", "sh", "shell", "console", "terminal", "zsh")
                )
            elif in_block and stripped == "```":
                in_block = False
                is_bash_block = False
            elif in_block and not is_bash_block:
                if re.search(r'python3\s+-c\b', line):
                    violations.append((i, line.strip()))

        assert not violations, (
            f"SKILL.md has 'python3 -c' in non-bash code block(s) at "
            f"line(s): " + ", ".join(f"{ln}" for ln, _ in violations)
        )


# ===================================================================
# Test Class 7: P4 — Save execution heredoc safety (v6: orchestrator-based)
# ===================================================================

class TestNoHeredocInSavePrompt:
    """Verify SKILL.md save execution does not expose heredoc risk.

    v5: Phase 3 haiku saver subagent needed explicit heredoc warnings.
    v6: Save execution is handled by memory_orchestrate.py (Python subprocess),
    which structurally eliminates heredoc risk. These tests verify that
    SKILL.md does not reintroduce heredoc-based save patterns.
    """

    def test_heredoc_warning_in_rules(self):
        """Rules section must still contain the heredoc warning text."""
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "heredoc" in text.lower(), (
            "SKILL.md missing heredoc warning in Rules section"
        )
        assert "<<" in text, (
            "SKILL.md should mention << to warn against it"
        )

    def test_no_heredoc_in_bash_commands(self):
        """No bash command in SKILL.md should use heredoc (<<) for file writes."""
        text = SKILL_MD.read_text(encoding="utf-8")
        lines = text.splitlines()
        in_bash = False
        bash_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```bash") or stripped.startswith("```sh"):
                in_bash = True
                continue
            if stripped == "```" and in_bash:
                in_bash = False
                continue
            if in_bash:
                bash_lines.append(stripped)

        # Check none of the actual bash commands use heredoc
        heredoc_pattern = re.compile(r'<<\s*[\'"]?\w+')
        for bash_line in bash_lines:
            assert not heredoc_pattern.search(bash_line), (
                f"SKILL.md bash command uses heredoc: {bash_line}"
            )

    def test_no_haiku_saver_subagent(self):
        """v6 should not contain Phase 3 haiku saver subagent instructions."""
        text = SKILL_MD.read_text(encoding="utf-8")
        # Phase 3 Save subagent was removed in v6
        assert "### Phase 3: Save" not in text, (
            "SKILL.md v6 should not have Phase 3 Save section (replaced by orchestrator)"
        )

    def test_save_via_orchestrator(self):
        """Phase 2 COMMIT must use memory_orchestrate.py for save execution."""
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "memory_orchestrate.py" in text
        assert "--action run" in text, (
            "SKILL.md should reference --action run for combined prepare+commit"
        )


# ===================================================================
# Test Class 8: P4 — No Write tool to .claude/memory/.staging/
# ===================================================================

class TestStagingPathOutsideClaudeDir:
    """Verify SKILL.md never instructs Write tool for .claude/memory/.staging/.

    P3 popup fix moved staging from .claude/memory/.staging/ to
    <staging_base>/.claude-memory-staging-<hash>/ (XDG 4-tier resolution).
    This test ensures no Write tool instructions target the old path.
    """

    def test_no_write_to_old_staging(self):
        """SKILL.md should not instruct Write tool for old staging path."""
        text = SKILL_MD.read_text(encoding="utf-8")
        # Check for literal .claude/memory/.staging/ references
        old_staging_pattern = re.compile(r'\.claude/memory/\.staging/')
        matches = []
        for i, line in enumerate(text.splitlines(), start=1):
            if old_staging_pattern.search(line):
                matches.append((i, line.strip()))
        assert not matches, (
            f"SKILL.md references old staging path .claude/memory/.staging/ "
            f"at line(s): "
            + ", ".join(f"{ln}" for ln, _ in matches)
            + "\nAll staging should use <staging_base>/.claude-memory-staging-<hash>/"
        )

    def test_staging_uses_xdg_tier_description(self):
        """SKILL.md staging references should describe XDG 4-tier resolution."""
        text = SKILL_MD.read_text(encoding="utf-8")
        # Should reference the 4-tier staging base resolution
        assert "<staging_base>/.claude-memory-staging-" in text, (
            "SKILL.md should reference <staging_base>/.claude-memory-staging- prefix"
        )
        assert "No `/tmp/` fallback" in text, (
            "SKILL.md should explicitly state no /tmp/ fallback"
        )

    def test_no_write_tool_to_claude_staging(self):
        """No Write tool call in SKILL.md should target .claude/.staging."""
        text = SKILL_MD.read_text(encoding="utf-8")
        # Write tool calls look like: Write( or file_path: ".../.staging/..."
        # Look for file_path with .claude and .staging
        write_staging_pattern = re.compile(
            r'file_path.*\.claude.*\.staging|'
            r'Write\(.*\.claude.*\.staging',
            re.DOTALL,
        )
        # Check line by line to avoid DOTALL matching across sections
        for i, line in enumerate(text.splitlines(), start=1):
            if re.search(r'file_path.*\.claude.*\.staging', line):
                pytest.fail(
                    f"SKILL.md line {i} has Write tool targeting old "
                    f"staging path: {line.strip()}"
                )
