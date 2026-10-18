"""A replay rebuilds the units its dataset was recorded in: LeRobot's norm mode per joint, never the registry's guess.

The parquet reader is LeRobot's (``tests/recording`` runs it end to end); here one recorded row stands in for it,
so the required check exercises what a replay does with ``meta/units.json`` on the repo's fake Feetech bus.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from test_drivers import make_driver

from strands_robots import Description, Policy, Robot
from strands_robots.policy import dataset
from strands_robots.recording.features import units_meta
from strands_robots.robot.drivers import feetech as ft
from strands_robots.units import lerobot_units

DEG = {"*": "degrees", "gripper": "range_0_100"}
ROW = [45.0] * 5 + [50.0]  # 45 degrees on every arm joint, the gripper half open


class Degrees:
    """What a LeRobot checkpoint run with norm=DEG declares, without loading one."""

    def units_for(self, description):
        return lerobot_units(description, DEG)

    def act(self, obs, *, instruction=None):
        return np.array(ROW)

    def reset(self):
        pass


def _arm():
    driver, serial = make_driver()
    arm = Robot("so101", driver=driver, twin=False)
    serial.frames.clear()
    return arm, serial


def _goals(policy):
    """The Goal_Position counts one step of ``policy`` writes to a hardware so101 on the fake bus."""
    arm, serial = _arm()
    try:
        arm.run(policy, steps=1)
    finally:
        arm.close()
    at = slice(ft.REG_GOAL_POSITION, ft.REG_GOAL_POSITION + 2)
    return [int.from_bytes(serial.regs[i][at], "little") for i in sorted(serial.regs)]


def _units_json(norm, *, modes=True):
    d = Description.load("so101")
    said = units_meta(lerobot_units(d, norm), d)
    for j in said["joints"].values():
        if not modes:
            j.pop("mode", None)  # a units.json written before it named the modes: the scheme and the ranges only
    return said


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """A dataset directory with ``meta/info.json``, and ``meta/units.json`` when given; its one row is ``ROW``."""
    monkeypatch.setattr(dataset, "_episode_actions", lambda root, episode: np.array([ROW]))
    keys = Description.load("so101").action_keys

    def make(name, units_json):
        (tmp_path / name / "meta").mkdir(parents=True)
        info = {"fps": 30, "features": {"action": {"names": [f"{k}.pos" for k in keys]}}}
        (tmp_path / name / "meta" / "info.json").write_text(json.dumps(info))
        if units_json is not None:
            (tmp_path / name / "meta" / "units.json").write_text(json.dumps(units_json))
        return str(tmp_path / name)

    return make


def test_units_json_names_the_norm_mode_of_every_joint():
    keys = Description.load("so101").action_keys
    said = _units_json(DEG)
    modes = {k: j.get("mode") for k, j in said["joints"].items()}
    assert modes == {f"{k}.pos": "range_0_100" if k == "gripper" else "degrees" for k in keys}
    assert units_meta(None, Description.load("so101")) == {"units": "rad", "joints": {}}  # radians have no modes


def test_a_degrees_recording_replays_on_a_real_arm_at_the_counts_the_run_wrote(recorded):
    direct = _goals(Degrees())
    replayed = _goals(Policy(recorded("deg", _units_json(DEG))))
    print(f"[measured] Goal_Position counts: the degrees run {direct}, its replay {replayed}")
    assert replayed == direct
