#!/usr/bin/env python3
"""
scripts/check_github_laws.py

Lightweight verification that the repo encodes the LAWS and required artifacts.
Fail-fast on missing critical files or missing manifest keys referenced by governance.

Exits with:
 - 0 if checks pass
 - 2 if checks fail (CI will see non-zero and mark job failed)
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.txt"        # if using manifest.txt
MANIFEST_YAML = ROOT / "configs" / "manifest.yaml"
ROBOTS = ROOT / "robots_guard.py"
SHN_STAMP = ROOT / "outputs" / "shn_stamp.json"
REQUIRED_TESTS = [ROOT / "tests" / "test_discover.py", ROOT / "tests" / "test_integration_discover.py"]

errors = []

# -----------------------
# Fundamental checks
# -----------------------
def check_manifest():
    path = None
    if MANIFEST.exists():
        path = MANIFEST
    elif MANIFEST_YAML.exists():
        path = MANIFEST_YAML
    else:
        errors.append("Missing manifest (manifest.txt or configs/manifest.yaml).")
        return

    text = path.read_text(encoding="utf-8")
    # lightweight check: ensure the key law names are present
    checks = [
        "Respect robots.txt", "No private/login-wall scraping",
        "Enforce rate limiting", "GDPR/CCPA", "Mobile-first", "Self-evaluation", "Legitimate Interest"
    ]
    missing = [c for c in checks if c not in text]
    if missing:
        errors.append(f"Manifest at {path} missing governance keywords: {missing}")

def check_robots_guard():
    if not ROBOTS.exists():
        errors.append("Missing robots_guard.py — required to enforce robots.txt checks in CI/scan.")

def check_tests():
    missing = [str(p) for p in REQUIRED_TESTS if not p.exists()]
    if missing:
        errors.append(f"Required tests missing: {missing}")

def check_env_files():
    env_path = ROOT / ".env"
    if env_path.exists():
        txt = env_path.read_text(errors="ignore")
        suspicious = any(k in txt for k in ["GOOGLE_API_KEY", "GOOGLE_CSE_ID", "AWS_ACCESS_KEY", "AKIA"])
        if suspicious:
            errors.append(".env contains credential-like values. Do NOT commit secrets to repo.")

# -----------------------
# New LAWS checks (sm/lg, README, venv notice)
# -----------------------
def check_shn_handoffs():
    """Require either a small or full SHN handoff stamp in outputs/"""
    sm = ROOT / "outputs" / "shn_small.json"
    lg = ROOT / "outputs" / "shn_full.json"
    if not sm.exists() and not lg.exists():
        errors.append("Missing SHN handoff: outputs/shn_small.json (sm) or outputs/shn_full.json (lg) required for LAWS compliance.")

def check_shn_stamp():
    """Optional traceability stamp used elsewhere; warn if not present."""
    if not SHN_STAMP.exists():
        # make this an error to enforce traceability; change to warning if you prefer
        errors.append("Missing outputs/shn_stamp.json (traceability SHN stamp). Add outputs/shn_stamp.json during release or as part of prepush.")

def check_readme_and_manifest_updates():
    readme = any((ROOT / fn).exists() for fn in ("README.md", "README.rst"))
    manifest = any((ROOT / fn).exists() for fn in ("manifest.txt", "configs/manifest.yaml"))
    if not readme:
        errors.append("README missing: LAWS require README update describing AI-behavior and LAWS.")
    if not manifest:
        errors.append("Manifest missing: configs/manifest.yaml or manifest.txt required.")

def check_venv_notice():
    """Print informational message for CI logs about venv state."""
    if (ROOT / ".venv").exists() or (ROOT / "venv").exists() or (ROOT / "env").exists():
        print("INFO: a virtual environment is present in repo root; CI should activate it for local-like runs.")
    else:
        print("INFO: no virtual environment detected in repository root; tests/scripts may run outside venv in CI.")

# -----------------------
# Utility / sanity checks
# -----------------------
def quick_secret_scan():
    patterns = [
        "AIza[A-Za-z0-9_-]{35}",  # common Google API key pattern
        "AKIA[A-Z0-9]{16}",      # AWS access key id
        "BEGIN RSA PRIVATE KEY",
        "PRIVATE_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_CSE_ID"
    ]
    # Use git grep if present
    try:
        out = os.popen("git rev-parse --is-inside-work-tree 2>/dev/null && git grep -nE \"{}\" -- :/ || true".format("|".join(patterns))).read().strip()
        if out:
            errors.append("Potential secret-like strings found in committed files:\n" + out)
    except Exception:
        # best-effort; ignore failures here
        pass

# -----------------------
# main
# -----------------------
def main():
    print("=== RUNNING CHECK_GITHUB_LAWS ===")
    check_manifest()
    check_robots_guard()
    check_tests()
    check_env_files()

    # New LAWS enforcement
    check_shn_handoffs()
    check_shn_stamp()
    check_readme_and_manifest_updates()
    check_venv_notice()

    # Useful sanity check for secrets
    quick_secret_scan()

    if errors:
        print("\n=== ENFORCE-LAWS CHECK FAILED ===")
        for e in errors:
            print("- " + e)
        # choose non-zero code to fail CI (2 used above in examples)
        sys.exit(2)

    print("\n=== ENFORCE-LAWS CHECK PASSED ===")
    sys.exit(0)

if __name__ == "__main__":
    main()
