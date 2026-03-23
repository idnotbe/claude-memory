"""Config default regression tests.

Guards against accidental reversion of architecture simplification config defaults:
- verification_enabled must be false (performance: skip Phase 1.5 by default)
- architecture.simplified_flow must be true (enable v6 3-phase flow by default)
"""

import json
from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).parent.parent / "assets" / "memory-config.default.json"


@pytest.fixture
def default_config():
    """Load the default config JSON."""
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class TestArchitectureSimplificationDefaults:
    """Regression guards for architecture simplification config values."""

    def test_verification_enabled_is_false(self, default_config):
        """verification_enabled must default to false (Phase 1.5 VERIFY is optional)."""
        parallel = default_config.get("triage", {}).get("parallel", {})
        assert parallel.get("verification_enabled") is False, (
            "triage.parallel.verification_enabled must default to false. "
            "Verification is optional for performance; enable per-project via config."
        )

    def test_simplified_flow_is_true(self, default_config):
        """architecture.simplified_flow must default to true (v6 3-phase flow)."""
        arch = default_config.get("architecture", {})
        assert arch.get("simplified_flow") is True, (
            "architecture.simplified_flow must default to true. "
            "This enables the v6 3-phase flow. Set to false for v5 fallback."
        )

    def test_architecture_key_exists(self, default_config):
        """architecture section must exist in default config."""
        assert "architecture" in default_config, (
            "Missing 'architecture' key in default config. "
            "Required for simplified_flow feature flag."
        )

    def test_config_file_is_valid_json(self):
        """Default config file must be valid JSON."""
        content = CONFIG_PATH.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_verification_model_still_sonnet(self, default_config):
        """verification_model should remain sonnet for when verification is enabled."""
        parallel = default_config.get("triage", {}).get("parallel", {})
        assert parallel.get("verification_model") == "sonnet"

    def test_parallel_enabled_still_true(self, default_config):
        """parallel.enabled should remain true (Phase 1 drafting is always parallel)."""
        parallel = default_config.get("triage", {}).get("parallel", {})
        assert parallel.get("enabled") is True
