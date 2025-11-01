"""Unit tests for the preflight phase using the standard unittest framework."""

import importlib.metadata
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from leadgen_audit.phase1_preflight import run_preflight


class TestPreflight(unittest.TestCase):
    def test_preflight_passes_with_required_env(self) -> None:
        """Preflight should pass when required environment variables are set and dependencies are satisfied.

        In the test environment some critical dependencies (e.g. playwright)
        are not installed, which would cause the preflight to fail. To
        isolate environment variable checking, we patch the version matrix
        loader to only require packages that are present. This demonstrates
        that the preflight passes if there are no missing dependencies and
        the required environment variables are set.
        """
        # Define a minimal version matrix that only requires pydantic (which
        # is available in the test environment).
        minimal_matrix = {
            "python": {"min": "3.8"},
            "deps": {"pydantic": {"critical": ">=2.0"}},
        }
        with patch(
            "leadgen_audit.phase1_preflight._load_version_matrix", return_value=minimal_matrix
        ), patch.dict(
            os.environ,
            {"GOOGLE_API_KEY": "dummy", "GOOGLE_CSE_ID": "dummy"},
            clear=False,
        ):
            result = run_preflight(emit_logs=False)
        self.assertTrue(result.passed)
        self.assertEqual(result.missing_env, [])
        self.assertFalse(result.version_issues)

    def test_preflight_fails_without_env(self) -> None:
        """Preflight should fail if required environment variables are missing.

        As with the previous test, we patch the version matrix to avoid
        dependency failures. Only missing environment variables should
        cause the failure.
        """
        minimal_matrix = {
            "python": {"min": "3.8"},
            "deps": {"pydantic": {"critical": ">=2.0"}},
        }
        with patch(
            "leadgen_audit.phase1_preflight._load_version_matrix", return_value=minimal_matrix
        ):
            # Remove keys if present and ensure they are absent inside the context
            env_backup = os.environ.copy()
            for key in ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"]:
                os.environ.pop(key, None)
            try:
                result = run_preflight(emit_logs=False)
            finally:
                os.environ.update(env_backup)
        self.assertFalse(result.passed)
        self.assertCountEqual(result.missing_env, ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"])

    def test_preflight_detects_missing_dependency(self) -> None:
        """Simulate a missing dependency by patching importlib.metadata.version."""
        original_version_fn = importlib.metadata.version

        def fake_version(pkg_name: str) -> str:
            if pkg_name == "pydantic":
                raise importlib.metadata.PackageNotFoundError(pkg_name)
            return original_version_fn(pkg_name)

        minimal_matrix = {
            "python": {"min": "3.8"},
            "deps": {"pydantic": {"critical": ">=2.0"}},
        }
        with patch(
            "leadgen_audit.phase1_preflight._load_version_matrix", return_value=minimal_matrix
        ), patch.dict(
            os.environ,
            {"GOOGLE_API_KEY": "dummy", "GOOGLE_CSE_ID": "dummy"},
            clear=False,
        ), patch(
            "importlib.metadata.version", fake_version
        ):
            result = run_preflight(emit_logs=False)
        self.assertFalse(result.passed)
        self.assertTrue(any("pydantic" in issue for issue in result.version_issues))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()