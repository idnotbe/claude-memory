"""Tests for memory_triage.py -- Stop hook triage.

Tests cover:
- Category description feature (original 14 tests)
- Bug 1: extract_text_content() transcript format fix
- Bug 2: extract_activity_metrics() transcript format fix
- Bug 3: Exit protocol (stdout JSON + exit 0)
- Bug 4: parse_transcript() deque filtering
- Score logging improvement
- End-to-end integration test
"""

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import time

from memory_triage import (
    load_config,
    write_context_files,
    format_block_message,
    build_triage_data,
    extract_text_content,
    extract_activity_metrics,
    parse_transcript,
    run_triage,
    score_session_summary,
    check_stop_flag,
    set_stop_flag,
    _run_triage,
    main,
    DEFAULT_THRESHOLDS,
    FLAG_TTL_SECONDS,
    _deep_copy_parallel_defaults,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path, config_data):
    """Write a memory-config.json inside a fake project .claude/memory/ dir.

    Returns the project root (cwd) path that load_config() expects.
    """
    proj = tmp_path / "project"
    mem_dir = proj / ".claude" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    config_path = mem_dir / "memory-config.json"
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    return str(proj)


SAMPLE_DESCRIPTIONS = {
    "session_summary": "High-level summary of work done in a session",
    "decision": "Architectural and technical choices with rationale",
    "runbook": "Step-by-step procedures for diagnosing and fixing issues",
    "constraint": "External limitations and platform restrictions",
    "tech_debt": "Known shortcuts, deferred work, and cleanup tasks",
    "preference": "User conventions, tool choices, and workflow preferences",
}


def _config_with_descriptions(descriptions=None):
    """Build a config dict that includes category descriptions."""
    descs = descriptions or SAMPLE_DESCRIPTIONS
    return {
        "categories": {
            cat: {"enabled": True, "folder": cat, "description": desc}
            for cat, desc in descs.items()
        },
        "triage": {"enabled": True},
    }


# ---------------------------------------------------------------------------
# load_config tests -- category descriptions
# ---------------------------------------------------------------------------


class TestLoadConfigCategoryDescriptions:
    """Tests for loading category descriptions from config."""

    def test_load_config_reads_category_descriptions(self, tmp_path):
        """Config with descriptions should return them in config dict."""
        cwd = _write_config(tmp_path, _config_with_descriptions())
        config = load_config(cwd)
        # The config should have a category_descriptions key
        assert "category_descriptions" in config, (
            "load_config() should return a 'category_descriptions' key"
        )
        descs = config["category_descriptions"]
        assert isinstance(descs, dict)
        assert descs["decision"] == "Architectural and technical choices with rationale"
        assert descs["runbook"] == "Step-by-step procedures for diagnosing and fixing issues"
        assert descs["preference"] == "User conventions, tool choices, and workflow preferences"

    def test_load_config_missing_descriptions_fallback(self, tmp_path):
        """Config without descriptions should fallback to empty strings."""
        config_data = {
            "categories": {
                "decision": {"enabled": True, "folder": "decisions"},
                "runbook": {"enabled": True, "folder": "runbooks"},
            },
            "triage": {"enabled": True},
        }
        cwd = _write_config(tmp_path, config_data)
        config = load_config(cwd)
        assert "category_descriptions" in config
        descs = config["category_descriptions"]
        # Missing description should be empty string
        assert descs.get("decision", "") == ""
        assert descs.get("runbook", "") == ""

    def test_load_config_descriptions_non_string_ignored(self, tmp_path):
        """Non-string description values should fallback to empty string."""
        config_data = {
            "categories": {
                "decision": {"enabled": True, "description": 42},
                "runbook": {"enabled": True, "description": ["not", "a", "string"]},
                "constraint": {"enabled": True, "description": None},
                "preference": {"enabled": True, "description": True},
            },
            "triage": {"enabled": True},
        }
        cwd = _write_config(tmp_path, config_data)
        config = load_config(cwd)
        descs = config["category_descriptions"]
        # All non-string descriptions should be empty string
        assert descs.get("decision", "") == ""
        assert descs.get("runbook", "") == ""
        assert descs.get("constraint", "") == ""
        assert descs.get("preference", "") == ""

    def test_load_config_empty_string_description(self, tmp_path):
        """Explicit empty string description should be preserved as empty."""
        config_data = {
            "categories": {
                "decision": {"enabled": True, "description": ""},
            },
            "triage": {"enabled": True},
        }
        cwd = _write_config(tmp_path, config_data)
        config = load_config(cwd)
        descs = config["category_descriptions"]
        assert descs.get("decision") == ""

    def test_load_config_no_config_file_has_empty_descriptions(self, tmp_path):
        """When no config file exists, category_descriptions should exist but be empty."""
        proj = tmp_path / "noconfig"
        proj.mkdir()
        config = load_config(str(proj))
        assert "category_descriptions" in config
        assert config["category_descriptions"] == {}


# ---------------------------------------------------------------------------
# write_context_files tests -- description in context
# ---------------------------------------------------------------------------


class TestContextFileIncludesDescription:
    """Tests that write_context_files() includes category description."""

    def test_context_file_includes_description(self, tmp_path):
        """Context file should include a Description: header when provided."""
        text = "We decided to use PostgreSQL because it supports JSONB."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]
        category_descriptions = {
            "decision": "Architectural and technical choices with rationale",
        }

        context_paths = write_context_files(
            text, metrics, results,
            category_descriptions=category_descriptions,
        )

        assert "decision" in context_paths
        content = Path(context_paths["decision"]).read_text(encoding="utf-8")
        assert "Description: Architectural and technical choices with rationale" in content

    def test_context_file_no_description_when_absent(self, tmp_path):
        """Context file should NOT have Description header when not provided."""
        text = "We decided to use PostgreSQL because it supports JSONB."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]

        # Call without category_descriptions (backward compat)
        context_paths = write_context_files(text, metrics, results)

        assert "decision" in context_paths
        content = Path(context_paths["decision"]).read_text(encoding="utf-8")
        assert "Description:" not in content

    def test_context_file_session_summary_with_description(self):
        """SESSION_SUMMARY context file should also include description."""
        text = ""
        metrics = {"tool_uses": 15, "distinct_tools": 5, "exchanges": 20}
        results = [
            {"category": "SESSION_SUMMARY", "score": 0.80, "snippets": ["15 tool uses"]},
        ]
        category_descriptions = {
            "session_summary": "High-level summary of work done in a session",
        }

        context_paths = write_context_files(
            text, metrics, results,
            category_descriptions=category_descriptions,
        )

        assert "session_summary" in context_paths
        content = Path(context_paths["session_summary"]).read_text(encoding="utf-8")
        assert "Description: High-level summary of work done in a session" in content


# ---------------------------------------------------------------------------
# format_block_message tests -- description in triage_data
# ---------------------------------------------------------------------------


class TestTriageDataIncludesDescription:
    """Tests that format_block_message() includes descriptions in triage_data."""

    def test_triage_data_includes_description(self):
        """triage_data JSON should include description field per category."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
            {"category": "RUNBOOK", "score": 0.55, "snippets": ["error fixed by"]},
        ]
        context_paths = {"decision": "/tmp/.memory-triage-context-decision.txt"}
        parallel_config = _deep_copy_parallel_defaults()
        category_descriptions = {
            "decision": "Architectural and technical choices with rationale",
            "runbook": "Step-by-step procedures for diagnosing and fixing issues",
        }

        message = format_block_message(
            results, context_paths, parallel_config,
            category_descriptions=category_descriptions,
        )

        # Parse the triage_data JSON from the message
        assert "<triage_data>" in message
        start = message.index("<triage_data>") + len("<triage_data>")
        end = message.index("</triage_data>")
        triage_json = json.loads(message[start:end])

        categories = triage_json["categories"]
        decision_cat = next(c for c in categories if c["category"] == "decision")
        runbook_cat = next(c for c in categories if c["category"] == "runbook")

        assert decision_cat["description"] == "Architectural and technical choices with rationale"
        assert runbook_cat["description"] == "Step-by-step procedures for diagnosing and fixing issues"

    def test_triage_data_no_description_when_absent(self):
        """triage_data should NOT include description when not provided."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]
        context_paths = {}
        parallel_config = _deep_copy_parallel_defaults()

        # Call without category_descriptions (backward compat)
        message = format_block_message(results, context_paths, parallel_config)

        start = message.index("<triage_data>") + len("<triage_data>")
        end = message.index("</triage_data>")
        triage_json = json.loads(message[start:end])

        decision_cat = triage_json["categories"][0]
        assert "description" not in decision_cat

    def test_human_readable_includes_description(self):
        """Human-readable part of message should mention category description."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]
        context_paths = {}
        parallel_config = _deep_copy_parallel_defaults()
        category_descriptions = {
            "decision": "Architectural and technical choices with rationale",
        }

        message = format_block_message(
            results, context_paths, parallel_config,
            category_descriptions=category_descriptions,
        )

        # The human-readable part (before <triage_data>) should mention description
        human_part = message[:message.index("<triage_data>")]
        assert "Architectural and technical choices" in human_part


# ---------------------------------------------------------------------------
# Backward compatibility -- everything works without descriptions
# ---------------------------------------------------------------------------


class TestBackwardCompatNoDescriptions:
    """All functions work identically when descriptions are absent."""

    def test_load_config_still_returns_standard_keys(self, tmp_path):
        """Standard config keys (enabled, max_messages, thresholds, parallel) still work."""
        config_data = {
            "triage": {
                "enabled": True,
                "max_messages": 75,
                "thresholds": {"decision": 0.3},
            }
        }
        cwd = _write_config(tmp_path, config_data)
        config = load_config(cwd)
        assert config["enabled"] is True
        assert config["max_messages"] == 75
        assert config["thresholds"]["DECISION"] == 0.3

    def test_write_context_files_works_without_descriptions(self):
        """write_context_files() works when called without description param."""
        text = "We decided to use PostgreSQL because of JSONB support."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]
        # Should not raise
        context_paths = write_context_files(text, metrics, results)
        assert isinstance(context_paths, dict)

    def test_format_block_message_works_without_descriptions(self):
        """format_block_message() works when called without description param."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided something"]},
        ]
        parallel_config = _deep_copy_parallel_defaults()
        # Should not raise
        message = format_block_message(results, {}, parallel_config)
        assert "<triage_data>" in message
        assert "DECISION" in message


# ---------------------------------------------------------------------------
# Helpers for new tests (Bug 1-4, improvement, integration)
# ---------------------------------------------------------------------------

def _user_msg(content, nested=True):
    """Build a user message in either nested (real) or flat (legacy) format."""
    if nested:
        return {"type": "user", "message": {"role": "user", "content": content}}
    else:
        return {"type": "human", "content": content}


def _assistant_msg(content, nested=True):
    """Build an assistant message in nested format."""
    if nested:
        return {"type": "assistant", "message": {"role": "assistant", "content": content}}
    else:
        return {"type": "assistant", "content": content}


def _progress_msg(data="running"):
    """Build a progress message (non-content type)."""
    return {"type": "progress", "data": data}


def _system_msg(text="system init"):
    """Build a system message (non-content type)."""
    return {"type": "system", "text": text}


def _file_history_msg():
    """Build a file-history-snapshot message (non-content type)."""
    return {"type": "file-history-snapshot", "files": ["/foo/bar.py"]}


def _write_transcript(tmp_path, messages, filename="transcript.jsonl"):
    """Write a list of message dicts as a JSONL file. Returns the file path."""
    path = tmp_path / filename
    lines = [json.dumps(m) for m in messages]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Bug 1: extract_text_content() -- transcript format fixes
# ---------------------------------------------------------------------------


class TestExtractTextContent:
    """Tests for extract_text_content() with real transcript format."""

    def test_user_string_content_nested(self):
        """type: 'user' with string content at msg['message']['content']."""
        messages = [_user_msg("I decided to use PostgreSQL")]
        text = extract_text_content(messages)
        assert "decided to use PostgreSQL" in text

    def test_user_list_content_text_blocks(self):
        """type: 'user' with list content -- only 'text' blocks extracted."""
        messages = [_user_msg([
            {"type": "tool_result", "content": "file contents should be ignored"},
            {"type": "text", "text": "Here is my question about the code"},
        ])]
        text = extract_text_content(messages)
        assert "Here is my question about the code" in text
        assert "file contents should be ignored" not in text

    def test_assistant_list_content_text_blocks(self):
        """type: 'assistant' with list content (text + tool_use + thinking)."""
        messages = [_assistant_msg([
            {"type": "text", "text": "I decided to use PostgreSQL because of JSONB."},
            {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/x"}},
            {"type": "thinking", "thinking": "Let me analyze this carefully..."},
        ])]
        text = extract_text_content(messages)
        assert "decided to use PostgreSQL" in text
        assert "Read" not in text  # tool_use name not extracted
        assert "analyze this carefully" not in text  # thinking not extracted

    def test_thinking_blocks_excluded(self):
        """Thinking blocks must NOT be extracted as text."""
        messages = [_assistant_msg([
            {"type": "thinking", "thinking": "secret internal reasoning about decisions"},
            {"type": "text", "text": "Here is my visible response."},
        ])]
        text = extract_text_content(messages)
        assert "secret internal reasoning" not in text
        assert "visible response" in text

    def test_tool_result_blocks_excluded(self):
        """tool_result blocks in user content must NOT be extracted."""
        messages = [_user_msg([
            {"type": "tool_result", "content": "def foo(): return 42"},
            {"type": "text", "text": "Please review this function."},
        ])]
        text = extract_text_content(messages)
        assert "def foo" not in text
        assert "review this function" in text

    def test_human_backwards_compat(self):
        """Old type: 'human' with flat content string still works."""
        messages = [_user_msg("I prefer using snake_case", nested=False)]
        text = extract_text_content(messages)
        assert "prefer using snake_case" in text

    def test_mixed_formats(self):
        """Mix of old-format (human/flat) and new-format (user/nested) messages."""
        messages = [
            _user_msg("I decided to use bun", nested=False),  # old format
            _assistant_msg([
                {"type": "text", "text": "Great choice because it is faster."},
            ]),
            _user_msg("Also, always use TypeScript"),  # new format (string)
            _user_msg([  # new format (list)
                {"type": "text", "text": "One more preference noted."},
            ]),
        ]
        text = extract_text_content(messages)
        assert "decided to use bun" in text
        assert "Great choice because" in text
        assert "always use TypeScript" in text
        assert "One more preference noted" in text

    def test_empty_messages_returns_empty(self):
        """Empty messages list returns empty string (after code stripping)."""
        text = extract_text_content([])
        assert text.strip() == ""

    def test_non_content_types_skipped(self):
        """Messages with types other than user/human/assistant are skipped."""
        messages = [
            {"type": "progress", "data": "important keyword decided"},
            {"type": "system", "text": "system decided to do things"},
            _user_msg("Actual user content here"),
        ]
        text = extract_text_content(messages)
        assert "important keyword decided" not in text
        assert "system decided" not in text
        assert "Actual user content" in text

    def test_assistant_flat_content_backwards_compat(self):
        """Assistant with flat string content (old format) still works."""
        messages = [_assistant_msg("I chose to implement it this way.", nested=False)]
        text = extract_text_content(messages)
        assert "chose to implement it this way" in text


# ---------------------------------------------------------------------------
# Bug 2: extract_activity_metrics() -- transcript format fixes
# ---------------------------------------------------------------------------


class TestExtractActivityMetrics:
    """Tests for extract_activity_metrics() with real transcript format."""

    def test_user_counted_as_exchange(self):
        """type: 'user' messages should be counted as exchanges."""
        messages = [
            _user_msg("Hello"),
            _assistant_msg([{"type": "text", "text": "Hi"}]),
            _user_msg("Another question"),
        ]
        metrics = extract_activity_metrics(messages)
        assert metrics["exchanges"] == 3  # 2 user + 1 assistant

    def test_nested_tool_use_counted(self):
        """tool_use blocks inside assistant content should be counted."""
        messages = [_assistant_msg([
            {"type": "text", "text": "Let me read that file."},
            {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/x"}},
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "foo"}},
        ])]
        metrics = extract_activity_metrics(messages)
        assert metrics["tool_uses"] == 2
        assert metrics["distinct_tools"] == 2

    def test_tool_result_not_counted_as_tool_use(self):
        """tool_result in user content must NOT be counted as tool_use."""
        messages = [
            _user_msg([
                {"type": "tool_result", "content": "file contents here"},
                {"type": "text", "text": "What about this?"},
            ]),
            _assistant_msg([
                {"type": "text", "text": "Analyzing..."},
                {"type": "tool_use", "name": "Read", "input": {}},
            ]),
        ]
        metrics = extract_activity_metrics(messages)
        # Only the assistant's Read should be counted
        assert metrics["tool_uses"] == 1
        assert metrics["distinct_tools"] == 1

    def test_thinking_not_counted(self):
        """thinking blocks in assistant content must NOT be counted."""
        messages = [_assistant_msg([
            {"type": "thinking", "thinking": "reasoning..."},
            {"type": "text", "text": "Result"},
            {"type": "tool_use", "name": "Bash", "input": {}},
        ])]
        metrics = extract_activity_metrics(messages)
        assert metrics["tool_uses"] == 1  # Only tool_use, not thinking
        assert metrics["distinct_tools"] == 1

    def test_backwards_compat_flat_format(self):
        """Old flat format with top-level tool_use messages still works."""
        messages = [
            {"type": "human", "content": "Hello"},
            {"type": "assistant", "content": "Hi"},
            {"type": "tool_use", "name": "Read"},
        ]
        metrics = extract_activity_metrics(messages)
        assert metrics["exchanges"] == 2  # human + assistant
        assert metrics["tool_uses"] == 1
        assert metrics["distinct_tools"] == 1

    def test_multiple_assistant_messages_with_tools(self):
        """Multiple assistant messages each with tool_use blocks."""
        messages = [
            _user_msg("Read two files"),
            _assistant_msg([
                {"type": "text", "text": "Reading first file"},
                {"type": "tool_use", "name": "Read", "input": {}},
            ]),
            _assistant_msg([
                {"type": "text", "text": "Reading second file"},
                {"type": "tool_use", "name": "Read", "input": {}},
                {"type": "tool_use", "name": "Grep", "input": {}},
            ]),
        ]
        metrics = extract_activity_metrics(messages)
        assert metrics["exchanges"] == 3  # 1 user + 2 assistant
        assert metrics["tool_uses"] == 3  # Read + Read + Grep
        assert metrics["distinct_tools"] == 2  # Read, Grep

    def test_empty_messages(self):
        """Empty messages list returns zero metrics."""
        metrics = extract_activity_metrics([])
        assert metrics["tool_uses"] == 0
        assert metrics["distinct_tools"] == 0
        assert metrics["exchanges"] == 0

    def test_assistant_no_nested_content(self):
        """Assistant message with string content (no tool_use blocks)."""
        messages = [_assistant_msg("Just a simple text response.", nested=False)]
        metrics = extract_activity_metrics(messages)
        assert metrics["exchanges"] == 1
        assert metrics["tool_uses"] == 0


# ---------------------------------------------------------------------------
# Bug 3: Exit protocol -- stdout JSON + exit 0
# ---------------------------------------------------------------------------


class TestExitProtocol:
    """Tests for the exit protocol using stdout JSON (advanced hook API)."""

    def _make_blocking_transcript(self, tmp_path):
        """Create a transcript that will trigger a triage block (high SESSION_SUMMARY score).

        Uses many exchanges and tool uses to exceed SESSION_SUMMARY threshold of 0.6.
        """
        messages = []
        for i in range(20):
            messages.append(_user_msg(f"User message {i}"))
            messages.append(_assistant_msg([
                {"type": "text", "text": f"Response {i}"},
                {"type": "tool_use", "name": f"Tool{i % 5}", "input": {}},
            ]))
        return _write_transcript(tmp_path, messages)

    def _make_nonblocking_transcript(self, tmp_path):
        """Create a transcript with minimal content that won't trigger any category."""
        messages = [
            _user_msg("Hello"),
            _assistant_msg([{"type": "text", "text": "Hi"}]),
        ]
        return _write_transcript(tmp_path, messages)

    def test_block_output_is_valid_stdout_json(self, tmp_path):
        """Blocking path outputs valid JSON to stdout with decision + reason keys."""
        transcript_path = self._make_blocking_transcript(tmp_path)
        # Set up cwd with config
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        # Capture stdout
        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        stdout_text = captured_out.getvalue()
        assert exit_code == 0, "Blocking path should return exit code 0"
        assert stdout_text.strip() != "", "Blocking path should produce stdout output"

        # Parse as JSON
        response = json.loads(stdout_text.strip())
        assert "decision" in response, "Response must have 'decision' key"
        assert "reason" in response, "Response must have 'reason' key"
        assert response["decision"] == "block"
        assert len(response["reason"]) > 0

    def test_block_output_no_extra_stdout(self, tmp_path):
        """No non-JSON text on stdout in blocking path."""
        transcript_path = self._make_blocking_transcript(tmp_path)
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        stdout_text = captured_out.getvalue().strip()
        # The entire stdout should be parseable as a single JSON object
        # No extra lines, no debug prints
        lines = [l for l in stdout_text.split("\n") if l.strip()]
        assert len(lines) == 1, f"Expected exactly 1 JSON line on stdout, got {len(lines)}"
        json.loads(lines[0])  # Should not raise

    def test_allow_stop_no_stdout(self, tmp_path):
        """Allow-stop case: exit 0, no stdout output."""
        transcript_path = self._make_nonblocking_transcript(tmp_path)
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        assert exit_code == 0
        assert captured_out.getvalue().strip() == "", "Allow-stop should produce no stdout"

    def test_error_handler_no_stdout(self):
        """Error path in main(): no stdout, only stderr."""
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        with mock.patch("memory_triage.read_stdin", side_effect=RuntimeError("test error")), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("sys.stderr", captured_err):
            exit_code = main()

        assert exit_code == 0, "Error handler should return 0 (fail-open)"
        assert captured_out.getvalue().strip() == "", "Error path should not write to stdout"
        assert "Error" in captured_err.getvalue(), "Error should appear on stderr"

    def test_empty_stdin_returns_0_no_stdout(self):
        """Empty stdin should return 0 with no stdout."""
        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=""), \
             mock.patch("sys.stdout", captured_out):
            exit_code = _run_triage()

        assert exit_code == 0
        assert captured_out.getvalue() == ""

    def test_invalid_json_stdin_returns_0_no_stdout(self):
        """Invalid JSON on stdin should return 0 with no stdout."""
        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value="not json {"), \
             mock.patch("sys.stdout", captured_out):
            exit_code = _run_triage()

        assert exit_code == 0
        assert captured_out.getvalue() == ""


# ---------------------------------------------------------------------------
# Bug 4: parse_transcript() -- deque filtering
# ---------------------------------------------------------------------------


class TestParseTranscriptFiltering:
    """Tests for parse_transcript() deque filtering of non-content messages."""

    def test_filters_non_content_messages(self, tmp_path):
        """progress, system, file-history-snapshot messages excluded from result."""
        messages = [
            _progress_msg(),
            _user_msg("Hello there"),
            _progress_msg(),
            _system_msg(),
            _assistant_msg([{"type": "text", "text": "Hi"}]),
            _file_history_msg(),
            _progress_msg(),
        ]
        path = _write_transcript(tmp_path, messages)
        result = parse_transcript(path, max_messages=100)
        # Only user and assistant messages should be in result
        assert len(result) == 2
        assert result[0]["type"] == "user"
        assert result[1]["type"] == "assistant"

    def test_deque_capacity_preserves_content(self, tmp_path):
        """With low max_messages, content messages should not be pushed out by noise."""
        messages = []
        # 5 user messages interspersed with 100 progress messages
        for i in range(5):
            for _ in range(20):
                messages.append(_progress_msg())
            messages.append(_user_msg(f"User message {i}"))
        path = _write_transcript(tmp_path, messages)

        # max_messages=3: should get the last 3 user messages
        result = parse_transcript(path, max_messages=3)
        assert len(result) == 3
        for msg in result:
            assert msg["type"] == "user"

    def test_human_preserved_by_filter(self, tmp_path):
        """Old type: 'human' messages should pass the deque filter."""
        messages = [
            _progress_msg(),
            _user_msg("Old format message", nested=False),
            _progress_msg(),
            _assistant_msg([{"type": "text", "text": "Response"}]),
        ]
        path = _write_transcript(tmp_path, messages)
        result = parse_transcript(path, max_messages=100)
        assert len(result) == 2
        assert result[0]["type"] == "human"
        assert result[1]["type"] == "assistant"

    def test_empty_file_returns_empty(self, tmp_path):
        """Empty transcript file returns empty list."""
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        result = parse_transcript(str(path), max_messages=50)
        assert result == []

    def test_missing_file_returns_empty(self, tmp_path):
        """Missing transcript file returns empty list."""
        result = parse_transcript(str(tmp_path / "nonexistent.jsonl"), max_messages=50)
        assert result == []

    def test_all_noise_returns_empty(self, tmp_path):
        """Transcript with only non-content messages returns empty list."""
        messages = [_progress_msg() for _ in range(50)]
        path = _write_transcript(tmp_path, messages)
        result = parse_transcript(path, max_messages=50)
        assert result == []

    def test_deque_window_keeps_latest(self, tmp_path):
        """With max_messages=2 and 5 user messages, only the last 2 are kept."""
        messages = [_user_msg(f"Message {i}") for i in range(5)]
        path = _write_transcript(tmp_path, messages)
        result = parse_transcript(path, max_messages=2)
        assert len(result) == 2
        # Should be the last 2 messages
        content_3 = result[0].get("message", {}).get("content", "")
        content_4 = result[1].get("message", {}).get("content", "")
        assert "Message 3" in content_3
        assert "Message 4" in content_4


# ---------------------------------------------------------------------------
# Improvement: Score logging
# ---------------------------------------------------------------------------


class TestScoreLogging:
    """Tests for the score logging improvement."""

    def test_score_log_written(self, tmp_path):
        """After triage, .triage-scores.log should be written to staging dir with valid JSON."""
        # Create a transcript that triggers SESSION_SUMMARY
        messages = []
        for i in range(20):
            messages.append(_user_msg(f"Message {i}"))
            messages.append(_assistant_msg([
                {"type": "text", "text": f"Response {i}"},
                {"type": "tool_use", "name": f"Tool{i % 5}", "input": {}},
            ]))
        transcript_path = _write_transcript(tmp_path, messages)

        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        # Score log now goes to {cwd}/.claude/memory/.staging/.triage-scores.log
        log_path = str(proj / ".claude" / "memory" / ".staging" / ".triage-scores.log")
        # Remove old log file if it exists to get a clean state
        try:
            os.remove(log_path)
        except OSError:
            pass

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        # Verify log file was written
        assert os.path.isfile(log_path), "Score log file should exist in staging dir"
        with open(log_path, "r", encoding="utf-8") as f:
            last_line = None
            for line in f:
                if line.strip():
                    last_line = line.strip()
            assert last_line is not None, "Log file should have at least one line"

        log_entry = json.loads(last_line)
        assert "ts" in log_entry
        assert "cwd" in log_entry
        assert "text_len" in log_entry
        assert "exchanges" in log_entry
        assert "tool_uses" in log_entry
        assert "triggered" in log_entry
        assert isinstance(log_entry["triggered"], list)

    def test_score_log_no_stdout_interference(self, tmp_path):
        """Score logging should not produce any output on stdout."""
        messages = [
            _user_msg("Hello"),
            _assistant_msg([{"type": "text", "text": "Hi"}]),
        ]
        transcript_path = _write_transcript(tmp_path, messages)

        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        # For a non-triggering session, stdout should be empty
        stdout_text = captured_out.getvalue()
        if stdout_text.strip():
            # If something triggered (unlikely with 2 messages), it should be valid JSON
            response = json.loads(stdout_text.strip())
            assert "decision" in response


# ---------------------------------------------------------------------------
# End-to-end integration test
# ---------------------------------------------------------------------------


class TestEndToEndIntegration:
    """End-to-end tests: realistic JSONL transcript through full pipeline."""

    def _build_realistic_transcript(self):
        """Build a realistic transcript with all message types as seen in production."""
        messages = []
        # System/progress noise at session start
        messages.append({"type": "system", "text": "Session started"})
        messages.append(_progress_msg("initializing"))
        messages.append(_file_history_msg())

        # User asks about architecture
        messages.append(_user_msg(
            "I want to discuss the database choice. We need to decide between "
            "PostgreSQL and MySQL for the new service."
        ))
        messages.append(_progress_msg("processing"))

        # Assistant responds with decision keywords
        messages.append(_assistant_msg([
            {"type": "thinking", "thinking": "The user wants a database decision. Let me compare the options."},
            {"type": "text", "text": (
                "I recommend PostgreSQL. We decided to go with PostgreSQL because "
                "it has better JSONB support and advanced indexing. This is a good "
                "choice over MySQL for this use case due to the complex query patterns."
            )},
            {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/schema.sql"}},
        ]))

        # User tool_result + follow-up
        messages.append(_user_msg([
            {"type": "tool_result", "content": "CREATE TABLE users (id SERIAL PRIMARY KEY);"},
            {"type": "text", "text": "Great, the schema looks good. I always prefer PostgreSQL."},
        ]))
        messages.append(_progress_msg("processing"))

        # More assistant work with tools
        for i in range(8):
            messages.append(_assistant_msg([
                {"type": "text", "text": f"Working on step {i}..."},
                {"type": "tool_use", "name": ["Read", "Grep", "Edit", "Bash"][i % 4], "input": {}},
            ]))
            messages.append(_progress_msg("tool running"))
            messages.append(_user_msg([
                {"type": "tool_result", "content": f"Output of step {i}"},
                {"type": "text", "text": "Continue"},
            ]))

        # Final user message
        messages.append(_user_msg("Looks good, let's wrap up."))
        messages.append(_assistant_msg([
            {"type": "text", "text": "All done! We selected PostgreSQL for the project."},
        ]))

        return messages

    def test_e2e_realistic_transcript(self, tmp_path):
        """Full pipeline: JSONL file -> parse -> extract -> triage -> output decision."""
        messages = self._build_realistic_transcript()
        transcript_path = _write_transcript(tmp_path, messages)

        # Parse
        parsed = parse_transcript(transcript_path, max_messages=50)
        # Only user/human/assistant messages should be in result
        for msg in parsed:
            assert msg["type"] in ("user", "human", "assistant")
        # There should be no progress, system, or file-history-snapshot messages
        assert all(m["type"] not in ("progress", "system", "file-history-snapshot") for m in parsed)

        # Extract text content
        text = extract_text_content(parsed)
        assert len(text) > 0, "Should extract non-empty text from realistic transcript"
        # Decision keywords should be present
        assert "decided" in text.lower() or "selected" in text.lower()
        # thinking block content should NOT be present
        assert "Let me compare the options" not in text
        # tool_result content should NOT be present
        assert "CREATE TABLE" not in text

        # Extract metrics
        metrics = extract_activity_metrics(parsed)
        assert metrics["exchanges"] > 0
        assert metrics["tool_uses"] > 0
        assert metrics["distinct_tools"] > 0

        # Run triage
        results = run_triage(text, metrics, dict(DEFAULT_THRESHOLDS))
        # With decision-heavy content and many tool uses, we expect some triggers
        categories_triggered = {r["category"] for r in results}
        # DECISION should trigger due to "decided", "chose", "selected", "because", etc.
        assert "DECISION" in categories_triggered, (
            f"DECISION should trigger for decision-heavy transcript. "
            f"Triggered: {categories_triggered}"
        )

    def test_e2e_full_pipeline_blocking_output(self, tmp_path):
        """Full _run_triage() pipeline with a transcript that triggers blocking."""
        messages = self._build_realistic_transcript()
        transcript_path = _write_transcript(tmp_path, messages)

        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        assert exit_code == 0

        stdout_text = captured_out.getvalue().strip()
        if stdout_text:
            # Should be valid JSON
            response = json.loads(stdout_text)
            assert response["decision"] == "block"
            assert "reason" in response
            # Reason should contain the human-readable message
            assert "memories before stopping" in response["reason"]

    def test_e2e_non_triggering_transcript(self, tmp_path):
        """Minimal transcript should not trigger any categories."""
        messages = [
            _user_msg("Hi"),
            _assistant_msg([{"type": "text", "text": "Hello!"}]),
        ]
        transcript_path = _write_transcript(tmp_path, messages)

        parsed = parse_transcript(transcript_path, max_messages=50)
        text = extract_text_content(parsed)
        metrics = extract_activity_metrics(parsed)
        results = run_triage(text, metrics, dict(DEFAULT_THRESHOLDS))
        assert results == [], "Minimal transcript should not trigger any categories"

    def test_e2e_session_summary_triggers(self, tmp_path):
        """A session with many tool uses should trigger SESSION_SUMMARY."""
        messages = []
        for i in range(15):
            messages.append(_user_msg(f"Do step {i}"))
            messages.append(_assistant_msg([
                {"type": "text", "text": f"Step {i} done"},
                {"type": "tool_use", "name": f"Tool{i % 5}", "input": {}},
            ]))
        transcript_path = _write_transcript(tmp_path, messages)

        parsed = parse_transcript(transcript_path, max_messages=50)
        text = extract_text_content(parsed)
        metrics = extract_activity_metrics(parsed)

        # Verify metrics are correct
        assert metrics["exchanges"] == 30  # 15 user + 15 assistant
        assert metrics["tool_uses"] == 15
        assert metrics["distinct_tools"] == 5

        # SESSION_SUMMARY score = 15*0.05 + 5*0.1 + 30*0.02 = 0.75 + 0.5 + 0.6 = 1.0 (capped)
        score, snippets = score_session_summary(metrics)
        assert score >= 0.6, f"SESSION_SUMMARY score should exceed 0.6 threshold, got {score}"

        results = run_triage(text, metrics, dict(DEFAULT_THRESHOLDS))
        categories_triggered = {r["category"] for r in results}
        assert "SESSION_SUMMARY" in categories_triggered


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge case tests."""

    def test_extract_text_malformed_message_no_crash(self):
        """Messages missing expected keys should not crash extraction."""
        messages = [
            {"type": "user"},  # no "message" key
            {"type": "assistant", "message": {}},  # no "content" key
            {"type": "user", "message": {"content": None}},  # content is None
        ]
        # Should not raise
        text = extract_text_content(messages)
        assert isinstance(text, str)

    def test_extract_metrics_malformed_message_no_crash(self):
        """Messages missing expected keys should not crash metrics extraction."""
        messages = [
            {"type": "user"},
            {"type": "assistant", "message": {}},
            {"type": "assistant", "message": {"content": "string not list"}},
        ]
        metrics = extract_activity_metrics(messages)
        assert metrics["exchanges"] == 3
        assert metrics["tool_uses"] == 0

    def test_extract_text_content_list_with_plain_strings(self):
        """Content list containing plain strings (defensive handling)."""
        messages = [_user_msg(["plain string in a list"], nested=False)]
        # flat format: msg["content"] = ["plain string in a list"]
        text = extract_text_content(messages)
        assert "plain string in a list" in text

    def test_score_session_summary_zero_activity(self):
        """Zero activity should produce zero score."""
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 0}
        score, snippets = score_session_summary(metrics)
        assert score == 0.0
        assert snippets == []

    def test_run_triage_respects_thresholds(self):
        """run_triage only returns categories exceeding their threshold."""
        # Use text with a DECISION keyword but set threshold very high
        text = "We decided to go with PostgreSQL because it is better."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        thresholds = dict(DEFAULT_THRESHOLDS)
        thresholds["DECISION"] = 1.0  # Impossible to reach
        results = run_triage(text, metrics, thresholds)
        categories = {r["category"] for r in results}
        assert "DECISION" not in categories


# ---------------------------------------------------------------------------
# R2: Staging path tests -- write_context_files() with cwd parameter
# ---------------------------------------------------------------------------


class TestStagingPaths:
    """Tests for R2: context files written to .claude/memory/.staging/ when cwd is provided."""

    def test_context_files_use_staging_dir_when_cwd_provided(self, tmp_path):
        """When cwd is provided, context files should go to {cwd}/.claude/memory/.staging/."""
        text = "We decided to use PostgreSQL because of JSONB support."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]

        context_paths = write_context_files(
            text, metrics, results,
            cwd=str(tmp_path),
        )

        assert "decision" in context_paths
        path = context_paths["decision"]
        expected_dir = str(tmp_path / ".claude" / "memory" / ".staging")
        assert path.startswith(expected_dir), f"Path {path} should start with {expected_dir}"
        assert path.endswith("context-decision.txt")
        assert os.path.isfile(path)

    def test_context_files_fallback_to_tmp_when_no_cwd(self):
        """When cwd is empty, context files should fall back to /tmp/."""
        text = "We decided to use PostgreSQL because of JSONB support."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]

        context_paths = write_context_files(text, metrics, results)

        assert "decision" in context_paths
        assert context_paths["decision"].startswith("/tmp/")

    def test_staging_dir_created_if_absent(self, tmp_path):
        """The .staging/ directory should be created if it doesn't exist."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        assert not staging_dir.exists()

        text = "We decided to use PostgreSQL because it supports JSONB."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]

        write_context_files(text, metrics, results, cwd=str(tmp_path))

        assert staging_dir.exists()
        assert staging_dir.is_dir()

    def test_multiple_categories_in_staging(self, tmp_path):
        """Multiple category context files should all go to staging dir."""
        text = "We decided to use PostgreSQL because of JSONB. There was an error that we fixed by restarting."
        metrics = {"tool_uses": 10, "distinct_tools": 3, "exchanges": 20}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
            {"category": "SESSION_SUMMARY", "score": 0.80, "snippets": ["10 tool uses"]},
        ]

        context_paths = write_context_files(
            text, metrics, results,
            cwd=str(tmp_path),
        )

        staging_dir = str(tmp_path / ".claude" / "memory" / ".staging")
        for cat, path in context_paths.items():
            assert path.startswith(staging_dir), f"Category {cat} path {path} not in staging"
            assert os.path.isfile(path)

    def test_staging_content_matches_tmp_content(self, tmp_path):
        """Content in staging path should be the same quality as /tmp/ path."""
        text = "We decided to use PostgreSQL because of JSONB support."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]

        staging_paths = write_context_files(
            text, metrics, results,
            cwd=str(tmp_path),
        )

        content = Path(staging_paths["decision"]).read_text(encoding="utf-8")
        assert "Category: decision" in content
        assert "Score: 0.72" in content
        assert "<transcript_data>" in content

    def test_context_file_permissions(self, tmp_path):
        """Context files should be created with restrictive permissions (0o600)."""
        text = "We decided to use PostgreSQL because it supports JSONB."
        metrics = {"tool_uses": 0, "distinct_tools": 0, "exchanges": 2}
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PostgreSQL"]},
        ]

        context_paths = write_context_files(text, metrics, results, cwd=str(tmp_path))

        stat_result = os.stat(context_paths["decision"])
        perms = stat_result.st_mode & 0o777
        assert perms == 0o600, f"Expected 0o600 permissions, got {oct(perms)}"

    def test_score_log_in_staging_dir(self, tmp_path):
        """Score log should be written to staging dir when cwd is provided."""
        messages = []
        for i in range(20):
            messages.append(_user_msg(f"User message {i}"))
            messages.append(_assistant_msg([
                {"type": "text", "text": f"Response {i}"},
                {"type": "tool_use", "name": f"Tool{i % 5}", "input": {}},
            ]))
        transcript_path = _write_transcript(tmp_path, messages)

        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        log_path = proj / ".claude" / "memory" / ".staging" / ".triage-scores.log"
        assert log_path.is_file(), "Score log should be in staging dir"

        with open(str(log_path), "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) >= 1
        log_entry = json.loads(lines[-1])
        assert "ts" in log_entry
        assert "triggered" in log_entry


# ---------------------------------------------------------------------------
# R3: Sentinel idempotency tests
# ---------------------------------------------------------------------------


class TestSentinelIdempotency:
    """Tests for R3: sentinel-based idempotency prevents repeated hook firing."""

    def _make_blocking_transcript(self, tmp_path):
        """Create a transcript that triggers SESSION_SUMMARY."""
        messages = []
        for i in range(20):
            messages.append(_user_msg(f"User message {i}"))
            messages.append(_assistant_msg([
                {"type": "text", "text": f"Response {i}"},
                {"type": "tool_use", "name": f"Tool{i % 5}", "input": {}},
            ]))
        return _write_transcript(tmp_path, messages)

    def test_sentinel_allows_stop_when_fresh(self, tmp_path):
        """If sentinel exists and is fresh (< 300s), triage should allow stop."""
        proj = tmp_path / "proj"
        staging_dir = proj / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        sentinel = staging_dir / ".triage-handled"
        sentinel.write_text(str(time.time()), encoding="utf-8")

        transcript_path = self._make_blocking_transcript(tmp_path)
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        # Write config
        claude_dir = proj / ".claude" / "memory"
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        assert exit_code == 0
        # No blocking output - sentinel caused early return
        assert captured_out.getvalue().strip() == ""

    def test_sentinel_ignored_when_stale(self, tmp_path):
        """If sentinel exists but is stale (> 300s), triage should proceed normally."""
        proj = tmp_path / "proj"
        staging_dir = proj / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        sentinel = staging_dir / ".triage-handled"
        # Write sentinel with old timestamp and set mtime to 10 minutes ago
        sentinel.write_text(str(time.time() - 600), encoding="utf-8")
        old_time = time.time() - 600
        os.utime(str(sentinel), (old_time, old_time))

        transcript_path = self._make_blocking_transcript(tmp_path)
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        claude_dir = proj / ".claude" / "memory"
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        assert exit_code == 0
        stdout_text = captured_out.getvalue().strip()
        # With stale sentinel, triage should proceed and may block
        if stdout_text:
            response = json.loads(stdout_text)
            assert response["decision"] == "block"

    def test_sentinel_created_when_blocking(self, tmp_path):
        """When triage blocks, sentinel file should be created."""
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )

        transcript_path = self._make_blocking_transcript(tmp_path)
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        sentinel = proj / ".claude" / "memory" / ".staging" / ".triage-handled"
        stdout_text = captured_out.getvalue().strip()
        if stdout_text:
            # If triage blocked, sentinel should exist
            assert sentinel.exists(), "Sentinel should be created when triage blocks"
            content = sentinel.read_text(encoding="utf-8")
            # Content should be a timestamp
            float(content)  # Should not raise

    def test_sentinel_missing_dir_handled_gracefully(self, tmp_path):
        """When .staging/ doesn't exist, sentinel check should not crash."""
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        # No .staging/ directory - sentinel check should handle gracefully

        transcript_path = self._make_blocking_transcript(tmp_path)
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        # Should not crash, should proceed normally
        assert exit_code == 0

    def test_sentinel_not_created_when_allowing(self, tmp_path):
        """Sentinel should NOT be created when triage allows the stop (no results)."""
        messages = [
            _user_msg("Hi"),
            _assistant_msg([{"type": "text", "text": "Hello!"}]),
        ]
        transcript_path = _write_transcript(tmp_path, messages)

        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        sentinel = proj / ".claude" / "memory" / ".staging" / ".triage-handled"
        assert not sentinel.exists(), (
            "Sentinel should not be created when triage allows the stop"
        )

    def test_sentinel_idempotency_sequential_calls(self, tmp_path):
        """Two sequential _run_triage() calls: first blocks, second is suppressed by sentinel."""
        transcript_path = self._make_blocking_transcript(tmp_path)

        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        # First call: should block and create sentinel
        captured_out1 = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out1), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        first_output = captured_out1.getvalue().strip()
        assert first_output != "", "First call should produce blocking output"
        response1 = json.loads(first_output)
        assert response1["decision"] == "block"

        # Second call with same input: sentinel should suppress it
        captured_out2 = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out2), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        second_output = captured_out2.getvalue().strip()
        assert second_output == "", (
            "Second call should be suppressed by sentinel idempotency"
        )

    def test_sentinel_uses_flag_ttl_constant(self, tmp_path):
        """Sentinel TTL should use the FLAG_TTL_SECONDS constant (300s)."""
        # Verify the constant value matches expected
        assert FLAG_TTL_SECONDS == 300, (
            f"FLAG_TTL_SECONDS should be 300, got {FLAG_TTL_SECONDS}"
        )

        proj = tmp_path / "proj"
        staging_dir = proj / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        sentinel = staging_dir / ".triage-handled"

        # Sentinel at exactly TTL - 1 second should still be fresh
        sentinel.write_text(str(time.time()), encoding="utf-8")
        just_under_ttl = time.time() - (FLAG_TTL_SECONDS - 1)
        os.utime(str(sentinel), (just_under_ttl, just_under_ttl))

        transcript_path = self._make_blocking_transcript(tmp_path)
        claude_dir = proj / ".claude" / "memory"
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            _run_triage()

        # Just under TTL should still be fresh -> suppressed
        assert captured_out.getvalue().strip() == "", (
            "Sentinel at TTL-1s should still be considered fresh"
        )


# ---------------------------------------------------------------------------
# build_triage_data() helper tests
# ---------------------------------------------------------------------------


class TestBuildTriageData:
    """Tests for the build_triage_data() helper function."""

    def test_build_triage_data_basic_structure(self):
        """build_triage_data() returns correct top-level keys."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]
        context_paths = {"decision": "/tmp/context-decision.txt"}
        parallel_config = _deep_copy_parallel_defaults()

        data = build_triage_data(results, context_paths, parallel_config)

        assert "categories" in data
        assert "parallel_config" in data
        assert len(data["categories"]) == 1
        cat = data["categories"][0]
        assert cat["category"] == "decision"
        assert cat["score"] == 0.72
        assert cat["context_file"] == "/tmp/context-decision.txt"

    def test_build_triage_data_includes_descriptions(self):
        """build_triage_data() includes descriptions when provided."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["test"]},
            {"category": "RUNBOOK", "score": 0.55, "snippets": ["test"]},
        ]
        context_paths = {}
        parallel_config = _deep_copy_parallel_defaults()
        cat_descs = {
            "decision": "Architectural choices",
            "runbook": "Debugging procedures",
        }

        data = build_triage_data(results, context_paths, parallel_config,
                                 category_descriptions=cat_descs)

        cats = {c["category"]: c for c in data["categories"]}
        assert cats["decision"]["description"] == "Architectural choices"
        assert cats["runbook"]["description"] == "Debugging procedures"

    def test_build_triage_data_no_description_when_absent(self):
        """build_triage_data() omits description when not provided."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["test"]},
        ]
        data = build_triage_data(results, {}, _deep_copy_parallel_defaults())
        assert "description" not in data["categories"][0]

    def test_build_triage_data_parallel_config_defaults(self):
        """build_triage_data() uses defaults for missing parallel config keys."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["test"]},
        ]
        # Pass a partial parallel config
        data = build_triage_data(results, {}, {"enabled": False})

        pc = data["parallel_config"]
        assert pc["enabled"] is False
        # Missing keys should fall back to defaults
        assert "category_models" in pc
        assert "verification_model" in pc
        assert "default_model" in pc

    def test_build_triage_data_no_context_path(self):
        """build_triage_data() omits context_file when no path exists."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["test"]},
        ]
        data = build_triage_data(results, {}, _deep_copy_parallel_defaults())
        assert "context_file" not in data["categories"][0]

    def test_build_triage_data_json_serializable(self):
        """build_triage_data() output is JSON-serializable."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["test"]},
            {"category": "SESSION_SUMMARY", "score": 0.85, "snippets": ["5 tool uses"]},
        ]
        cat_descs = {"decision": "Choices", "session_summary": "Summary"}
        data = build_triage_data(
            results, {"decision": "/tmp/ctx.txt"}, _deep_copy_parallel_defaults(),
            category_descriptions=cat_descs,
        )
        # Must not raise
        serialized = json.dumps(data, indent=2)
        roundtripped = json.loads(serialized)
        assert roundtripped == data


# ---------------------------------------------------------------------------
# format_block_message() with triage_data_path tests
# ---------------------------------------------------------------------------


class TestFormatBlockMessageTriageDataPath:
    """Tests for file-based vs inline triage_data output."""

    def test_format_block_message_with_triage_data_path(self):
        """When triage_data_path is provided, output <triage_data_file> tag."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]
        parallel_config = _deep_copy_parallel_defaults()
        path = "/home/user/.claude/memory/.staging/triage-data.json"

        message = format_block_message(
            results, {}, parallel_config,
            triage_data_path=path,
        )

        assert "<triage_data_file>" in message
        assert path in message
        assert "</triage_data_file>" in message
        # Must NOT contain inline triage_data
        assert "<triage_data>" not in message
        assert "</triage_data>" not in message.replace("</triage_data_file>", "")
        # Human-readable part should still be present
        assert "memories before stopping" in message

    def test_format_block_message_without_triage_data_path(self):
        """When triage_data_path is None, output inline <triage_data>."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]
        parallel_config = _deep_copy_parallel_defaults()

        message = format_block_message(
            results, {}, parallel_config,
            triage_data_path=None,
        )

        assert "<triage_data>" in message
        assert "</triage_data>" in message
        assert "<triage_data_file>" not in message
        # Verify the inline JSON is valid
        start = message.index("<triage_data>") + len("<triage_data>")
        end = message.index("</triage_data>")
        triage_json = json.loads(message[start:end])
        assert "categories" in triage_json
        assert "parallel_config" in triage_json

    def test_format_block_message_default_is_inline(self):
        """Default (no triage_data_path kwarg) falls back to inline."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided"]},
        ]
        parallel_config = _deep_copy_parallel_defaults()

        message = format_block_message(results, {}, parallel_config)

        assert "<triage_data>" in message
        assert "<triage_data_file>" not in message

    def test_format_block_message_file_path_with_descriptions(self):
        """File-based output with descriptions: descriptions in human part only."""
        results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]
        parallel_config = _deep_copy_parallel_defaults()
        cat_descs = {"decision": "Architectural choices"}
        path = "/tmp/triage-data.json"

        message = format_block_message(
            results, {}, parallel_config,
            category_descriptions=cat_descs,
            triage_data_path=path,
        )

        assert "<triage_data_file>" in message
        # Human-readable part should still include description
        file_tag_start = message.index("<triage_data_file>")
        human_part = message[:file_tag_start]
        assert "Architectural choices" in human_part


# ---------------------------------------------------------------------------
# _run_triage() triage-data.json file output tests
# ---------------------------------------------------------------------------


class TestRunTriageWritesTriageDataFile:
    """Tests that _run_triage() writes triage-data.json and uses file reference."""

    def _make_blocking_transcript(self, tmp_path):
        """Create a transcript that triggers DECISION category."""
        messages = [
            {"type": "user", "message": {"role": "user", "content":
                "We decided to use PostgreSQL because of JSONB support. "
                "We chose PostgreSQL over MySQL because of better JSON handling. "
                "We selected this approach due to performance reasons."}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Understood, recording the decision."}
            ]}},
        ]
        transcript_path = str(tmp_path / "transcript.jsonl")
        with open(transcript_path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")
        return transcript_path

    def test_triage_data_file_written(self, tmp_path):
        """_run_triage() writes triage-data.json to staging directory."""
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        transcript_path = self._make_blocking_transcript(tmp_path)

        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        # Mock run_triage to guarantee a blocking result regardless of transcript
        forced_results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.run_triage", return_value=forced_results):
            exit_code = _run_triage()

        assert exit_code == 0

        stdout_text = captured_out.getvalue().strip()
        assert stdout_text, "Expected blocking output but got empty stdout"
        response = json.loads(stdout_text)
        assert response["decision"] == "block"

        # Check that triage-data.json was written
        triage_data_path = proj / ".claude" / "memory" / ".staging" / "triage-data.json"
        assert triage_data_path.exists(), "triage-data.json should exist"

        # Verify it's valid JSON with expected structure
        triage_data = json.loads(triage_data_path.read_text(encoding="utf-8"))
        assert "categories" in triage_data
        assert "parallel_config" in triage_data

        # Verify the reason references the file
        reason = response["reason"]
        assert "<triage_data_file>" in reason
        assert str(triage_data_path) in reason

    def test_triage_data_file_fallback_on_write_error(self, tmp_path):
        """If triage-data.json write fails, falls back to inline <triage_data>."""
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        transcript_path = self._make_blocking_transcript(tmp_path)

        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        # Mock run_triage to guarantee a blocking result
        forced_results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]

        captured_out = io.StringIO()
        # Mock os.open to fail only for triage-data.json.*.tmp writes
        original_os_open = os.open
        def mock_os_open(path, flags, mode=0o777):
            if isinstance(path, str) and "triage-data.json." in path and path.endswith(".tmp"):
                raise OSError("Simulated write failure")
            return original_os_open(path, flags, mode)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.run_triage", return_value=forced_results), \
             mock.patch("memory_triage.os.open", side_effect=mock_os_open):
            exit_code = _run_triage()

        assert exit_code == 0

        stdout_text = captured_out.getvalue().strip()
        assert stdout_text, "Expected blocking output but got empty stdout"
        response = json.loads(stdout_text)
        assert response["decision"] == "block"
        reason = response["reason"]
        # Should fall back to inline triage_data
        assert "<triage_data>" in reason
        assert "<triage_data_file>" not in reason

    def test_triage_data_file_fallback_on_replace_error(self, tmp_path):
        """If os.replace() fails after write, falls back to inline <triage_data>."""
        proj = tmp_path / "proj"
        claude_dir = proj / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        (claude_dir / "memory-config.json").write_text(
            json.dumps({"triage": {"enabled": True}}), encoding="utf-8"
        )
        transcript_path = self._make_blocking_transcript(tmp_path)

        hook_input = json.dumps({
            "transcript_path": transcript_path,
            "cwd": str(proj),
        })

        forced_results = [
            {"category": "DECISION", "score": 0.72, "snippets": ["decided to use PG"]},
        ]

        captured_out = io.StringIO()
        original_replace = os.replace
        def mock_replace(src, dst):
            if isinstance(dst, str) and "triage-data.json" in dst and ".tmp" not in dst:
                raise OSError("Simulated replace failure")
            return original_replace(src, dst)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.run_triage", return_value=forced_results), \
             mock.patch("memory_triage.os.replace", side_effect=mock_replace):
            exit_code = _run_triage()

        assert exit_code == 0

        stdout_text = captured_out.getvalue().strip()
        assert stdout_text, "Expected blocking output but got empty stdout"
        response = json.loads(stdout_text)
        assert response["decision"] == "block"
        reason = response["reason"]
        # Should fall back to inline triage_data
        assert "<triage_data>" in reason
        assert "<triage_data_file>" not in reason
