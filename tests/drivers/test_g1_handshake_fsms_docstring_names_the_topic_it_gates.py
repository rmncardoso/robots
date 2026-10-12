"""Regression: the FSM-set docstrings do not name a topic ``send_action`` does not write.

Two docstrings in this driver claimed :data:`HANDSHAKE_FSMS` gates writes to
``rt/armsdk``:

* ``strands_robots/drivers/unitree/_common.py`` on the ``HANDSHAKE_FSMS`` constant
  itself: "so :meth:`~strands_robots.drivers.g1.G1Driver.send_action` checks
  membership before writing ``rt/armsdk``".
* ``strands_robots/drivers/g1.py`` on ``_check_motion_gates``: ":data:`HANDSHAKE_FSMS`
  covers arm-SDK writes (``rt/armsdk``)".

Neither is what the shipped driver does.  Since #2767 landed (2026-08-24)
``G1Driver.send_action`` publishes on ``rt/lowcmd`` -- ``_TOPIC_LOWCMD`` is
`"rt/lowcmd"` and ``_pubs.publish(_TOPIC_LOWCMD, LowCmd_, cmd)`` is the one
write site.  The control loop wired by #2779 writes the same topic on every
step and on stop.  The reader following ``HANDSHAKE_FSMS`` from either docstring
was pointed at a topic string this file does not appear in and could not confirm
by grep, and the two mentions of the real topic in the same module
(``send_action``'s own docstring at line 635 and its scope classification at
line 657) already say "``rt/lowcmd``" -- so the module contradicted itself.

The confusion is worth naming: the arm-SDK-*shape* (the client that talks
:data:`HANDSHAKE_FSMS` at the FSM level) and the arm-SDK-*topic* are not the
same thing.  ``HANDSHAKE_FSMS`` is a set of FSM ids on the motion-switcher rail;
the G1 driver's write for that shape lands on ``rt/lowcmd`` today, and nothing
in this package writes the arm-SDK topic yet.

## The names, too

The quotes above spell the topic ``rt/armsdk``, as the package did in eight
places.  Unitree's arm SDK examples publish ``rt/arm_sdk``
(``unitree_sdk2_python``, ``example/g1/high_level/g1_arm5_sdk_dds_example.py``);
the spelling without the underscore is the G1 message for response 7400 in the
C++ SDK, whose H2 header spells the same message with it.
:data:`~strands_robots.drivers.unitree._common.ERR_CODES` carried it because its
table was ported from ``cagataycali/neon-the-g1``'s ``tools/_g1_common.py``
(#2739).  That text was pinned here as the SDK's, but the Python SDK carries no
text for the code at all - a caller receives only the integer - so nothing reads
the vendor's spelling back, and a reader who grepped a capture or the examples
for it found no topic.  The entry now names ``rt/arm_sdk`` and adds the cause
Unitree's arm action page gives, that an action is executing.

The same descriptions called FSM 500 sitting, which is how :data:`WALK_FSMS`
explained leaving it out.  Unitree's SDK enters 500 from ``LocoClient.Start()``
and sits with FSM 3 (``LocoClient.Sit()``), and its FSM table names 500 regular
locomotion, 501 the same with the 3-DoF waist and 801 walk-run locomotion.

## Scope

The topic rule grades the two named docstrings only: where either names the
arm-SDK topic, in either spelling, in the context of a currently-gated write,
``rt/lowcmd`` must appear too.  A docstring that names the arm-SDK topic
alongside ``rt/lowcmd`` (naming future work explicitly) satisfies it; naming
only the arm-SDK topic does not.  The two name tests reach further on purpose:
no module in the package may spell the topic ``rt/armsdk``, and none of the four
descriptions of the FSM sets may call an id in them a sitting mode.

## Fires on the defect, passes on the fix

Both topic cells fail on ``main @ 5ded625b`` (where ``rt/armsdk`` is the only
topic named beside :data:`HANDSHAKE_FSMS`) and pass after the fix (where
``rt/lowcmd`` is named as today's write and the arm-SDK topic is optional
context).  Both name tests fail on ``main @ 03b9cfd1``, in all five of their
cells (eight ``rt/armsdk`` spellings, and a sit word in all four descriptions),
and pass after the rename.
The two premise cells fail vacuously if a future refactor renames the constant
or the write topic, at which point the pin has to move with it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

import strands_robots
from strands_robots.drivers.unitree import _common

_PACKAGE_DIR = Path(strands_robots.__file__).resolve().parent

#: The arm-SDK topic as Unitree's examples publish it, and the spelling this
#: package carried before.  A topic cell that looked for only one of them would
#: pass vacuously once the docstrings used the other.
_ARM_TOPIC = "rt/arm_sdk"
_ARM_TOPIC_WITHOUT_UNDERSCORE = "rt/armsdk"

#: A word that calls a mode sitting.  "sits" is left out on purpose: the gate
#: docstrings use it as a verb ("the live FSM id sits outside the set").
_SIT_WORD = re.compile(r"\bsit(?:ting)?\b|\bsit-down\b", re.IGNORECASE)


def _read(rel: str) -> str:
    return (_PACKAGE_DIR / rel).read_text(encoding="utf-8")


def _hash_colon_block_above(constant: str) -> str:
    """The ``#:``-prefixed docstring above ``constant`` in ``_common``.

    Sphinx renders ``#:`` lines that precede a module-level assignment as the
    docstring for the assigned name, so the reader who follows the constant
    sees exactly this block.  The scan collects the contiguous run of ``#:``
    lines immediately above the assignment.
    """
    lines = _read("drivers/unitree/_common.py").splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"{constant}:"):
            # Walk backwards to the top of the contiguous ``#:`` block.
            top = idx
            while top > 0 and lines[top - 1].lstrip().startswith("#:"):
                top -= 1
            return "\n".join(lines[top:idx])
    raise AssertionError(f"{constant} assignment not found in _common.py")


def _function_docstring(rel: str, name: str) -> str:
    """The docstring on the function ``name`` in the module at ``rel``.

    Extracted textually so the test does not have to import ``G1Driver`` (which
    binds a DDS interface at construction time).  The scan captures from the
    ``def`` line to the closing ``\"\"\"`` that follows the first ``\"\"\"``
    opening on a later line.
    """
    match = re.search(
        rf'def {re.escape(name)}\(.*?\n\s+"""(.*?)"""',
        _read(rel),
        flags=re.DOTALL,
    )
    assert match is not None, f"{name} docstring not found in {rel}"
    return match.group(1)


def _names_the_arm_topic(doc: str) -> bool:
    return _ARM_TOPIC in doc or _ARM_TOPIC_WITHOUT_UNDERSCORE in doc


#: Every place the package describes the FSM sets in prose: the two ``#:``
#: blocks a reader reaches from the constants, the gate that tests them, and
#: the agent tool that lists them.
_FSM_SET_DESCRIPTIONS: dict[str, Callable[[], str]] = {
    "HANDSHAKE_FSMS": lambda: _hash_colon_block_above("HANDSHAKE_FSMS"),
    "WALK_FSMS": lambda: _hash_colon_block_above("WALK_FSMS"),
    "G1Driver._check_motion_gates": lambda: _function_docstring("drivers/g1.py", "_check_motion_gates"),
    "g1_motion_gates": lambda: _function_docstring("tools/g1/g1_reference.py", "g1_motion_gates"),
}


# ---------------------------------------------------------------------------
# Premise cells -- exist so a rename can never make the defect cells vacuous.
# ---------------------------------------------------------------------------


def test_premise_handshake_fsms_still_declared_in_the_transport() -> None:
    """The constant this file grades is at the location it grades."""
    assert isinstance(_common.HANDSHAKE_FSMS, frozenset)
    assert _common.HANDSHAKE_FSMS == frozenset({500, 501, 801})


def test_premise_send_action_writes_rt_lowcmd() -> None:
    """The topic the docstrings must name is the one the driver writes.

    Read out of the module source (not out of an import that would touch the
    SDK).  If ``_TOPIC_LOWCMD`` moves or is renamed, this cell fires before the
    defect cell it supports so a reader is not left grading the wrong site.
    """
    text = _read("drivers/g1.py")
    assert '_TOPIC_LOWCMD = "rt/lowcmd"' in text
    # And the one write site in ``send_action`` reads that constant.
    assert "_pubs.publish(_TOPIC_LOWCMD, LowCmd_, cmd)" in text


# ---------------------------------------------------------------------------
# Defect cells -- both fire on main, both pass after the fix.
# ---------------------------------------------------------------------------


def test_handshake_fsms_docstring_does_not_name_a_topic_send_action_does_not_write() -> None:
    """The ``HANDSHAKE_FSMS`` docstring in ``_common`` cites ``rt/lowcmd`` where it names a topic.

    The defect was a docstring that said :meth:`send_action` writes ``rt/armsdk``.
    The fix does not have to strip every mention of the arm-SDK topic - it may
    legitimately distinguish today (``rt/lowcmd``) from future work
    (``rt/arm_sdk``) - but a docstring that names the arm-SDK topic without
    also naming ``rt/lowcmd`` in the same block is naming only the wrong topic.
    The rule is *not* "must never name the arm-SDK topic"; it is "if the reader
    is told a topic name in the ``send_action`` neighbourhood, ``rt/lowcmd``
    must be one of them."
    """
    doc = _hash_colon_block_above("HANDSHAKE_FSMS")
    if "send_action" not in doc:
        return  # the docstring may have been rewritten to omit send_action entirely
    if _names_the_arm_topic(doc):
        assert "rt/lowcmd" in doc, (
            "HANDSHAKE_FSMS docstring names the arm-SDK topic in a send_action context "
            "without also naming rt/lowcmd; the shipped driver writes rt/lowcmd (#2767) "
            "and the reader must be told which one send_action writes today."
        )


def test_check_motion_gates_docstring_does_not_conflate_the_arm_shape_with_the_armsdk_topic() -> None:
    """The ``_check_motion_gates`` docstring must not tie ``HANDSHAKE_FSMS`` to the arm-SDK topic alone.

    The original phrasing was ":data:`HANDSHAKE_FSMS` covers arm-SDK writes
    (``rt/armsdk``)".  ``HANDSHAKE_FSMS`` gates the FSM shape, and the write
    that shape produces today lands on ``rt/lowcmd``; the arm-SDK topic is
    future work for the ``g1_tools`` client.  A docstring naming the arm-SDK
    topic without also naming ``rt/lowcmd`` reads as an authoritative
    statement of what ``send_action`` does today, which is wrong.
    """
    doc = _function_docstring("drivers/g1.py", "_check_motion_gates")
    if _names_the_arm_topic(doc):
        assert "rt/lowcmd" in doc, (
            "_check_motion_gates docstring names the arm-SDK topic without naming rt/lowcmd; "
            "the driver's arm write goes to rt/lowcmd today (#2767) and the reader "
            "must be able to see that from this docstring."
        )


# ---------------------------------------------------------------------------
# Name cells -- the topic and the FSM ids are named the way Unitree names them.
# ---------------------------------------------------------------------------


def test_no_module_in_the_package_spells_the_arm_topic_without_its_underscore() -> None:
    """Unitree's examples publish ``rt/arm_sdk``, so that is the name a reader must find here."""
    modules = sorted(_PACKAGE_DIR.rglob("*.py"))
    assert _PACKAGE_DIR / "drivers" / "unitree" / "_common.py" in modules, "the scan is not reading this package"
    offenders = [
        f"{path.relative_to(_PACKAGE_DIR)}:{number}"
        for path in modules
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _ARM_TOPIC_WITHOUT_UNDERSCORE in line
    ]
    assert not offenders, (
        f"spell the arm SDK topic {_ARM_TOPIC!r}, as Unitree's examples publish it; "
        f"{_ARM_TOPIC_WITHOUT_UNDERSCORE!r} appears only in the C++ SDK's G1 message for response 7400: {offenders}"
    )


@pytest.mark.parametrize("described", sorted(_FSM_SET_DESCRIPTIONS))
def test_no_description_of_the_fsm_sets_calls_an_id_in_them_a_sitting_mode(described: str) -> None:
    """None of 500, 501 or 801 is a sitting mode, so no description of the sets may call one that.

    Unitree's FSM table names 500 regular locomotion, 501 the same with the
    3-DoF waist and 801 walk-run locomotion; sitting is FSM 3, which neither
    set holds.
    """
    doc = _FSM_SET_DESCRIPTIONS[described]()
    assert doc.strip(), f"the {described} description is empty; re-point this cell at the prose that describes the set"
    found = _SIT_WORD.findall(doc)
    assert not found, (
        f"the {described} description calls an FSM id in the sets a sitting mode ({found}); Unitree's "
        "FSM table names 500 regular locomotion, 501 the same with the 3-DoF waist and 801 walk-run "
        "locomotion, and sitting is FSM 3"
    )
