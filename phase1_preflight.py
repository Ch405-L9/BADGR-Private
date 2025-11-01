"""Phase 1: Setup & Pre‑Flight

This module performs the initial setup and pre‑flight checks required
before the remainder of the lead generation audit pipeline can be run.

It validates the Python interpreter version, checks that critical
dependencies meet minimum version requirements, ensures that required
environment variables are present, and creates the directory
structure used by subsequent phases. The results of these checks are
recorded and returned to the caller. Additionally, human‑readable
logs are emitted in the standardized ``[Component] action=result
detail=value`` format described in the build protocol.

Usage
-----
The primary entry point is :func:`run_preflight`. When invoked as a
script, this function will execute immediately and write its result
to standard output. To integrate with the overall pipeline, import
``run_preflight`` and call it from the state machine.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class PreflightResult:
    """Structured result describing the outcome of the preflight checks."""

    passed: bool
    errors: List[str] = field(default_factory=list)
    missing_env: List[str] = field(default_factory=list)
    version_issues: List[str] = field(default_factory=list)
    created_dirs: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        """Return a serializable representation of the result."""
        return {
            "passed": self.passed,
            "errors": self.errors,
            "missing_env": self.missing_env,
            "version_issues": self.version_issues,
            "created_dirs": self.created_dirs,
        }


def _load_version_matrix() -> Dict[str, object]:
    """Load the version matrix from the package directory.

    The version matrix defines minimum and recommended versions for
    Python and various dependencies. If the file cannot be read or
    parsed, a RuntimeError is raised.
    """
    here = Path(__file__).resolve().parent
    matrix_path = here / ".." / "version_matrix.json"
    matrix_path = matrix_path.resolve()
    if not matrix_path.exists():
        raise RuntimeError(f"version_matrix.json not found at {matrix_path}")
    try:
        with open(matrix_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Failed to load version matrix: {exc}") from exc


def _check_python_version(matrix: Dict[str, object]) -> Tuple[bool, List[str]]:
    """Ensure the running Python interpreter meets the minimum version.

    Returns a tuple where the first element indicates success and the
    second is a list of human‑readable issues.
    """
    issues: List[str] = []
    py_req = matrix.get("python", {})
    min_version = py_req.get("min")
    if min_version is not None:
        current = sys.version_info
        # Parse minimal version as major.minor[.patch]
        parts = tuple(int(part) for part in str(min_version).split("."))
        if current < parts:
            issues.append(
                f"Python {'.'.join(map(str, current[:3]))} is below required {min_version}"
            )
    return (not issues, issues)


def _check_dependencies(matrix: Dict[str, object]) -> Tuple[bool, List[str]]:
    """Check that critical dependencies meet the specified versions.

    For critical dependencies, if the installed version is missing or
    older than the required minimum, a descriptive issue is added to
    the returned list.
    """
    import importlib.metadata

    issues: List[str] = []
    deps: Dict[str, Dict[str, str]] = matrix.get("deps", {})
    for package_name, constraints in deps.items():
        min_req = constraints.get("critical") or constraints.get("optional")
        if min_req is None:
            continue
        # Remove comparison operators, keep version
        # e.g. ">=2.0" -> "2.0"
        version_str = min_req.lstrip("<>=!")
        try:
            installed_version = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            issues.append(f"Package '{package_name}' is not installed")
            continue
        from packaging.version import Version

        if Version(installed_version) < Version(version_str):
            issues.append(
                f"{package_name} {installed_version} is below required {version_str}"
            )
    return (not issues, issues)


def _check_environment_vars(required_keys: List[str]) -> Tuple[bool, List[str]]:
    """Verify that required environment variables are present and non‑empty."""
    missing = [key for key in required_keys if not os.getenv(key)]
    return (not missing, missing)


def _ensure_directories(directories: List[Path]) -> List[str]:
    """Create the given directories if they do not already exist.

    Returns a list of directory names that were created.
    """
    created: List[str] = []
    for d in directories:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))
    return created


def run_preflight(*, emit_logs: bool = True) -> PreflightResult:
    """Run setup and pre‑flight checks.

    Parameters
    ----------
    emit_logs: bool
        If true, emit human‑readable logs to standard output. Disable
        when invoking from tests to avoid cluttering the output.

    Returns
    -------
    PreflightResult
        A structured result describing the outcome of the preflight checks.
    """
    matrix = _load_version_matrix()

    # Check Python version
    ok_py, py_issues = _check_python_version(matrix)
    # Check dependencies
    ok_deps, deps_issues = _check_dependencies(matrix)
    # Check environment variables
    required_env = ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"]
    ok_env, missing_env = _check_environment_vars(required_env)
    # Ensure directory structure
    base_path = Path.cwd() / "outputs"
    dirs_to_create = [
        base_path / "csv",
        base_path / "sqlite",
        Path.cwd() / "configs",
    ]
    created_dirs = _ensure_directories(dirs_to_create)

    # Prepare result
    passed = ok_py and ok_deps and ok_env
    result = PreflightResult(
        passed=passed,
        errors=[],
        missing_env=missing_env,
        version_issues=py_issues + deps_issues,
        created_dirs=created_dirs,
    )

    if emit_logs:
        # Emit standardized logs
        component = "Setup"
        # Python version check log
        py_status = "pass" if ok_py else "fail"
        py_detail = (
            "no issues"
            if ok_py
            else "; ".join(py_issues)
        )
        print(f"[{component}] version_check={py_status} detail={py_detail}")
        # Dependency check
        deps_status = "pass" if ok_deps else "fail"
        deps_detail = (
            "no issues"
            if ok_deps
            else "; ".join(deps_issues)
        )
        print(f"[{component}] dependency_check={deps_status} detail={deps_detail}")
        # Environment variable check
        env_status = "pass" if ok_env else "fail"
        env_detail = (
            "all present"
            if ok_env
            else f"missing: {', '.join(missing_env)}"
        )
        print(f"[{component}] env_check={env_status} detail={env_detail}")
        # Directory creation log
        if created_dirs:
            print(
                f"[{component}] directory_setup=created detail={', '.join(created_dirs)}"
            )
        else:
            print(f"[{component}] directory_setup=skip detail=already exists")
        # Final status
        status_str = "passed" if passed else "failed"
        print(
            f"[Status] phase=1 step=preflight status={status_str}"
        )
        print("[STANDBY]")

    return result


if __name__ == "__main__":
    # When executed directly, run the preflight and exit with a
    # non‑zero status code if checks fail. This allows integration into
    # shell scripts that can bail on failure.
    res = run_preflight()
    if not res.passed:
        sys.exit(1)