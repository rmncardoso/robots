"""Regression: the G1 sources cite the issue that tracks the tools port, not a merged mesh test fix.

The G1 tools were ported from ``cagataycali/neon-the-g1`` against a tracker the
port's prose called "issue #358", and 27 lines of the driver layer and the tools
package carried that number: refusal envelopes an agent reads (``g1_set_fsm``,
``g1_wave_hand_loco``, the reference verbs' ``Refs ...`` suffix), module
docstrings and comments.  In this repository #358 is "test(mesh): fix flaky
test_session_config", a merged pull request about zenoh mock isolation, so every
one of those references sent the reader to an unrelated change.  #2928 is the
issue opened for the port's design once that was noticed - its own text calls
the #358 reference dangling - and the tools package already cited it.  A tracker
reference in a refusal is a remedy, so the refusals now name #2928; the
driver-layer prose that deferred to "later, issue #358" for tools that have since
landed names the tools instead.

The rule is the number, read over the files where it lived.  It is narrow on
purpose: ``tests/test_deferral_strings_do_not_cite_a_landed_change.py`` grades
bare deferrals against the whole merged history, and an owner-qualified
``strands-labs/robots#358`` in a "refs" clause is neither bare nor a deferral, so
that rule could not see these.  Fails on ``main @ 03b9cfd1`` (27 lines in 11
files) and passes after the change.
"""

from __future__ import annotations

import re
from pathlib import Path

import strands_robots

_PACKAGE_DIR = Path(strands_robots.__file__).resolve().parent

#: The driver, its Unitree transport and the agent tools: every file the number lived in.
_G1_SOURCES = sorted(
    [
        _PACKAGE_DIR / "drivers" / "g1.py",
        *(_PACKAGE_DIR / "drivers" / "unitree").glob("*.py"),
        *(_PACKAGE_DIR / "tools" / "g1").glob("*.py"),
    ]
)

#: ``#358`` as a whole number, bare or owner-qualified.
_DEAD_TRACKER = re.compile(r"(?<![0-9])#358(?![0-9])")

#: The issue that tracks the tools port: the remedy the rule names.
_TOOLS_PORT_ISSUE = "strands-labs/robots#2928"


def test_the_scan_reads_the_files_the_number_lived_in() -> None:
    """A moved package would leave the rule below grading nothing."""
    names = {path.relative_to(_PACKAGE_DIR).as_posix() for path in _G1_SOURCES}
    lived_in = {"drivers/g1.py", "drivers/unitree/_common.py", "tools/g1/g1_actions.py", "tools/g1/g1_reference.py"}
    assert lived_in <= names, f"the scan misses {sorted(lived_in - names)}"


def test_no_g1_source_cites_358() -> None:
    """#358 is a merged mesh test fix here; the tools port is tracked in #2928."""
    offenders = [
        f"{path.relative_to(_PACKAGE_DIR)}:{number}"
        for path in _G1_SOURCES
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _DEAD_TRACKER.search(line)
    ]
    assert not offenders, (
        "strands-labs/robots#358 is a merged pull request about zenoh mock isolation; cite "
        f"{_TOOLS_PORT_ISSUE}, the issue that tracks the G1 tools port, or name what is missing: {offenders}"
    )
