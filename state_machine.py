"""Simple state machine for the LeadGen Audit pipeline.

This module manages progression through the eight phases defined in
the build protocol. State is persisted to a JSON file so that the
pipeline can resume after interruptions. Only phase 1 (preflight)
is implemented at present; placeholder stubs are provided for later
phases.

To run the first phase directly from the command line, execute this
module as a script::

    python -m leadgen_audit.state_machine

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from .phase1_preflight import run_preflight


STATE_FILE = Path("state.json")


def _load_state() -> Dict[str, object]:
    """Load the persistent state from disk or return a default state."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # Corrupted state file: start fresh
            pass
    return {
        "current_phase": 1,
        "status": "not_started",
    }


def _save_state(state: Dict[str, object]) -> None:
    """Persist the state to disk."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _handle_phase1(state: Dict[str, object]) -> None:
    """Execute phase 1 (preflight) and update the state accordingly."""
    result = run_preflight()
    state["status"] = "passed" if result.passed else "failed"
    state["phase1"] = result.as_dict()
    _save_state(state)


def run_next_phase(state: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Run the next phase based on the current state.

    The returned state reflects any updates made by the executed phase.
    """
    if state is None:
        state = _load_state()
    phase = state.get("current_phase", 1)
    if phase == 1:
        _handle_phase1(state)
        # Move to the next phase (discovery) regardless of pass/fail; it
        # will be up to the user to decide whether to proceed.
        state["current_phase"] = 2
    else:
        # Future phases would be handled here.
        pass
    _save_state(state)
    return state


def main() -> None:
    state = _load_state()
    run_next_phase(state)


if __name__ == "__main__":
    main()