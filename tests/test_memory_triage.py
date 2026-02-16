"""Tests for memory_triage.py -- Stop hook triage with category descriptions.

Tests the category description feature: descriptions loaded from config
are passed through to context files and triage_data JSON output.
"""

import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_triage import (
    load_config,
    write_context_files,
    format_block_message,
    DEFAULT_THRESHOLDS,
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
