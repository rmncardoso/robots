"""A Feetech arm's calibration file is the one ``Robot(id=)`` names: LeRobot's ``--robot.id``.

Every bus here is the suite's ``FakeSerial``.
"""

from __future__ import annotations

import json
import warnings

import pytest
from test_drivers import CAL, FakeSerial

from strands_robots import Robot
from strands_robots.robot.drivers import feetech as ft
from strands_robots.robot.drivers.feetech import driver as ftd

OTHER = {name: dict(joint, range_min=1124, range_max=3172) for name, joint in CAL.items()}  # another arm's file


def on_disk(tmp_path, monkeypatch, files):
    """LeRobot's calibration root is tmp_path, holding ``files`` (path under ``robots/`` -> calibration)."""
    monkeypatch.setenv("HF_LEROBOT_CALIBRATION", str(tmp_path))
    for where, cal in files.items():
        p = tmp_path / "robots" / where
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cal))
    return tmp_path / "robots"


@pytest.mark.parametrize(
    "robot_id, files, loads",
    [
        ("my_arm", {"so_follower/my_arm.json": CAL, "so_follower/other_arm.json": OTHER}, "so_follower/my_arm.json"),
        ("my_arm", {"so101_follower/my_arm.json": CAL, "so101_follower/b.json": OTHER}, "so101_follower/my_arm.json"),
        (None, {"so_follower/my_arm.json": CAL}, "so_follower/my_arm.json"),  # no id: the only file, as before
    ],
    ids=["two-arms", "the-so101_follower-directory", "no-id"],
)
def test_robot_id_is_the_lerobot_id_that_names_the_arms_calibration_file(tmp_path, monkeypatch, robot_id, files, loads):
    robots = on_disk(tmp_path, monkeypatch, files)
    monkeypatch.setattr(ftd, "FeetechBus", lambda port, baud: ft.FeetechBus(port, serial=FakeSerial()))
    real = Robot("so101", port="/dev/fake", id=robot_id, twin=False)
    assert real.body.calibration_source == str(robots / loads)
    real.close()


@pytest.mark.parametrize(
    "files",
    [
        {"so_follower/my_awesome_follower_arm.json": CAL},  # LeRobot's tutorial id, the only file: dev loaded it
        {"so_follower/other_arm.json": OTHER, "so101_follower/b.json": OTHER},
        {},  # nothing on disk: nothing to name
    ],
    ids=["lerobots-tutorial-id", "a-file-in-each-directory", "nothing-on-disk"],
)
def test_an_id_without_a_file_of_its_own_loads_none_and_warns_naming_the_files_there(tmp_path, monkeypatch, files):
    robots = on_disk(tmp_path, monkeypatch, files)
    monkeypatch.setattr(ftd, "FeetechBus", lambda port, baud: ft.FeetechBus(port, serial=FakeSerial()))
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        real = Robot("so101", port="/dev/fake", id="left", twin=False)
    said = [str(w.message) for w in seen if "no calibration file for id 'left'" in str(w.message)]
    assert real.body.calibration_source is None  # never another arm's file, even the only one there
    assert len(said) == (1 if files else 0) and all(str(robots / f) in said[0] for f in files)
    real.close()
