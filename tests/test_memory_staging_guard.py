"""Tests for memory_staging_guard.py -- PreToolUse:Bash guard for .staging/ writes.

Test matrix from action-plans/plan-guardian-conflict-memory-fix.md (T1-T15).
"""

import json
import subprocess
import sys

SCRIPT = "hooks/scripts/memory_staging_guard.py"


def run_guard(tool_name: str, command: str) -> tuple[str, int]:
    """Run the staging guard with given tool_name and command."""
    input_data = json.dumps({
        "tool_name": tool_name,
        "tool_input": {"command": command},
    })
    result = subprocess.run(
        [sys.executable, SCRIPT],
        input=input_data,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), result.returncode


def assert_deny(output: str, msg: str = ""):
    """Assert the output contains a deny decision."""
    assert output, f"Expected deny output, got empty string. {msg}"
    parsed = json.loads(output)
    decision = parsed["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny", f"Expected 'deny', got '{decision}'. {msg}"
    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Write tool" in reason, f"Deny message should mention Write tool. {msg}"


def assert_allow(output: str, msg: str = ""):
    """Assert the output is empty (allow = no output, exit 0)."""
    assert output == "", f"Expected empty output (allow), got: {output!r}. {msg}"


# ============================================================
# T1-T4, T10-T14: True Positives (should DENY)
# ============================================================

class TestTruePositives:
    """Bash writes to .staging/ that must be blocked."""

    def test_t1_heredoc_to_staging(self):
        """T1: cat heredoc to .staging/"""
        out, rc = run_guard(
            "Bash",
            "cat > .claude/memory/.staging/input-decision.json << 'EOFZ'\n"
            '{\"title\": \"test\"}\n'
            "EOFZ",
        )
        assert_deny(out, "T1: heredoc")

    def test_t2_echo_to_staging(self):
        """T2: echo redirect to .staging/"""
        out, rc = run_guard(
            "Bash",
            "echo '{\"title\":\"test\"}' > .claude/memory/.staging/input.json",
        )
        assert_deny(out, "T2: echo redirect")

    def test_t3_tee_to_staging(self):
        """T3: tee to .staging/"""
        out, rc = run_guard(
            "Bash",
            "echo '{}' | tee .claude/memory/.staging/test.json",
        )
        assert_deny(out, "T3: tee")

    def test_t4_cp_to_staging(self):
        """T4: cp to .staging/"""
        out, rc = run_guard(
            "Bash",
            "cp /tmp/test.json .claude/memory/.staging/test.json",
        )
        assert_deny(out, "T4: cp")

    def test_t10_mv_to_staging(self):
        """T10: mv to .staging/"""
        out, rc = run_guard(
            "Bash",
            "mv /tmp/x.json .claude/memory/.staging/x.json",
        )
        assert_deny(out, "T10: mv")

    def test_t11_dd_to_staging(self):
        """T11: dd to .staging/"""
        out, rc = run_guard(
            "Bash",
            "dd if=/tmp/x.json of=.claude/memory/.staging/x.json",
        )
        assert_deny(out, "T11: dd")

    def test_t12_install_to_staging(self):
        """T12: install to .staging/"""
        out, rc = run_guard(
            "Bash",
            "install /tmp/x.json .claude/memory/.staging/x.json",
        )
        assert_deny(out, "T12: install")

    def test_t13_bare_redirect_to_staging(self):
        """T13: bare redirect (no command) to .staging/"""
        out, rc = run_guard(
            "Bash",
            "> .claude/memory/.staging/test.json",
        )
        assert_deny(out, "T13: bare redirect")

    def test_t14_tee_with_flags(self):
        """T14: tee with -a flag to .staging/"""
        out, rc = run_guard(
            "Bash",
            "echo '{}' | tee -a .claude/memory/.staging/test.json",
        )
        assert_deny(out, "T14: tee -a")

    def test_printf_to_staging(self):
        """printf redirect to .staging/"""
        out, rc = run_guard(
            "Bash",
            "printf '{\"title\":\"x\"}' > .claude/memory/.staging/input.json",
        )
        assert_deny(out, "printf redirect")

    def test_append_redirect_to_staging(self):
        """>> (append) redirect to .staging/"""
        out, rc = run_guard(
            "Bash",
            "echo '{}' >> .claude/memory/.staging/test.json",
        )
        assert_deny(out, "append redirect")


# ============================================================
# T5-T9: True Negatives (should ALLOW)
# ============================================================

class TestTrueNegatives:
    """Commands that must NOT be blocked."""

    def test_t5_write_tool(self):
        """T5: Write tool to .staging/ should be allowed (not Bash)."""
        out, rc = run_guard(
            "Write",
            ".claude/memory/.staging/input.json",
        )
        assert_allow(out, "T5: Write tool")

    def test_t6_read_from_staging(self):
        """T6: cat (read) from .staging/ should be allowed."""
        out, rc = run_guard(
            "Bash",
            "cat .claude/memory/.staging/input.json",
        )
        assert_allow(out, "T6: cat read")

    def test_t7_ls_staging(self):
        """T7: ls .staging/ should be allowed."""
        out, rc = run_guard(
            "Bash",
            "ls .claude/memory/.staging/",
        )
        assert_allow(out, "T7: ls")

    def test_t8_other_directory(self):
        """T8: cat redirect to other directory should be allowed."""
        out, rc = run_guard(
            "Bash",
            "cat > /tmp/test.json << 'EOF'\n{}\nEOF",
        )
        assert_allow(out, "T8: other directory")

    def test_t9_memory_write_script(self):
        """T9: python3 memory_write.py execution should be allowed."""
        out, rc = run_guard(
            "Bash",
            "python3 hooks/scripts/memory_write.py --action create --category decision",
        )
        assert_allow(out, "T9: memory_write.py")

    def test_grep_staging(self):
        """grep inside .staging/ should be allowed."""
        out, rc = run_guard(
            "Bash",
            "grep -r 'title' .claude/memory/.staging/",
        )
        assert_allow(out, "grep in staging")

    def test_rm_staging(self):
        """rm in .staging/ should be allowed (cleanup, not write)."""
        out, rc = run_guard(
            "Bash",
            "rm .claude/memory/.staging/test.json",
        )
        assert_allow(out, "rm in staging")

    def test_non_bash_tool(self):
        """Non-Bash tools should be ignored entirely."""
        out, rc = run_guard(
            "Read",
            ".claude/memory/.staging/input.json",
        )
        assert_allow(out, "Read tool")


# ============================================================
# Edge cases
# ============================================================

class TestEdgeCases:
    """Edge cases and robustness tests."""

    def test_empty_command(self):
        """Empty command should be allowed."""
        out, rc = run_guard("Bash", "")
        assert_allow(out, "empty command")

    def test_invalid_json_input(self):
        """Invalid JSON input should not crash (exit 0)."""
        result = subprocess.run(
            [sys.executable, SCRIPT],
            input="not json",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_empty_stdin(self):
        """Empty stdin should not crash (exit 0)."""
        result = subprocess.run(
            [sys.executable, SCRIPT],
            input="",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_missing_tool_input(self):
        """Missing tool_input should not crash."""
        input_data = json.dumps({"tool_name": "Bash"})
        result = subprocess.run(
            [sys.executable, SCRIPT],
            input=input_data,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_deny_message_contains_write_tool_guidance(self):
        """T15: Deny message should include Write tool usage guidance."""
        out, _ = run_guard(
            "Bash",
            "cat > .claude/memory/.staging/test.json << 'EOF'\n{}\nEOF",
        )
        parsed = json.loads(out)
        reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
        assert "Write tool" in reason
        assert ".staging/" in reason
