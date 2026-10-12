"""The two Unitree G1 models compile to the shapes ``robots.json`` declares.

The registry-side companion (``tests/registry``) grades both entries' fields
from ``robots.json`` and ``docs/hooks/`` alone. It cannot compile either asset:
that directory's conftest repoints ``STRANDS_ASSETS_DIR`` at a per-test temp
dir for host isolation, so no downloaded asset is ever visible there. These
cells live here so the declared figures are checked against the models that
supply them.

The joint names and the body count are stated once, in the registry-side
module, and imported here - so there is one statement of each and this file
grades it, rather than two copies that agree until one is edited.

The premise is graded too, not only the new entry. ``unitree_g1`` dropped
"dexterous hands" from its description because ``g1.xml`` has no finger joint;
if an upstream revision ever gives it one, the wording should come back and
:meth:`TestTheHandLessModelHasNoHandJoint.test_the_body_tree_ends_at_the_wrists`
is what says so.

Neither asset is downloaded here. Fetching one would clone an external
repository during a test run and turn a host with no network into a failure
rather than a skip, so the search paths are read directly and every cell skips
when the asset is absent - which is the case on a clean CI checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.registry.test_g1_with_hands_declares_its_asset_shape import (
    BODY_JOINTS,
    FLOATING_BASE_JOINTS,
    HAND_JOINTS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROBOTS_JSON = REPO_ROOT / "strands_robots" / "registry" / "robots.json"


def _entry(name: str) -> dict:
    return json.loads(ROBOTS_JSON.read_text(encoding="utf-8"))["robots"][name]


def _asset_file(name: str, key: str = "model_xml") -> Path:
    """Return a declared asset file present on disk, or skip.

    Reads the search paths rather than calling
    :func:`~strands_robots.assets.manager.resolve_model_path`, which downloads a
    missing asset. A test that fetches a third-party repository fails on a host
    with no network instead of skipping, and does it once per cell.
    """
    from strands_robots.utils import get_search_paths

    asset = _entry(name)["asset"]
    present = next(
        (candidate for root in get_search_paths() if (candidate := Path(root) / asset["dir"] / asset[key]).exists()),
        None,
    )
    if present is None:
        pytest.skip(f"{name} {key} is not downloaded, so the compiled shape cannot be read")
    return present


def _joints(name: str):  # noqa: ANN202 - the mujoco module and its model, like the sibling asset suites
    """``(mujoco, model, joint names)`` for one entry's declared model."""
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(str(_asset_file(name)))
    names = [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(model.njnt)]
    return mujoco, model, names


class TestTheHandLessModelHasNoHandJoint:
    """Why ``unitree_g1`` no longer says "dexterous hands"."""

    def test_the_body_tree_ends_at_the_wrists(self) -> None:
        """Not one joint of :data:`HAND_JOINTS`, nor any other finger joint, is in ``g1.xml``."""
        _, model, names = _joints("unitree_g1")
        assert model.njnt - FLOATING_BASE_JOINTS == BODY_JOINTS == _entry("unitree_g1")["joints"]
        fingers = [n for n in names if any(part in n for part in ("hand", "thumb", "index", "middle"))]
        assert fingers == [], f"g1.xml grew finger joints: {fingers}"


class TestTheWithHandsModelCarriesTheDeclaredHands:
    """The new entry's figures, re-derived from the model they describe."""

    def test_the_hands_are_the_only_joints_the_other_model_lacks(self) -> None:
        """The two models differ by exactly :data:`HAND_JOINTS`, in that order."""
        _, _, names = _joints("unitree_g1_with_hands")
        _, _, hand_less = _joints("unitree_g1")
        assert tuple(n for n in names if n not in set(hand_less)) == HAND_JOINTS
        assert [n for n in hand_less if n not in set(names)] == [], "the body joints are shared, not renamed"

    def test_the_declared_count_is_the_models_joint_total_without_the_base(self) -> None:
        """``joints: 43`` is the model's ``njnt`` less its floating base (#4147)."""
        _, model, _ = _joints("unitree_g1_with_hands")
        assert model.njnt - FLOATING_BASE_JOINTS == _entry("unitree_g1_with_hands")["joints"]

    def test_every_hand_joint_is_driven_by_one_actuator(self) -> None:
        """A policy can command the fingers, which is the reason to load this model."""
        mujoco, model, _ = _joints("unitree_g1_with_hands")
        driven = {
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, int(model.actuator_trnid[i, 0]))
            for i in range(model.nu)
        }
        assert set(HAND_JOINTS) <= driven
        assert model.njnt == model.nu + FLOATING_BASE_JOINTS

    def test_the_scene_wrapper_loads_the_same_body(self) -> None:
        """``scene_with_hands.xml`` is what ``add_robot`` compiles, so it must hold the hands too."""
        mujoco = pytest.importorskip("mujoco")
        scene = mujoco.MjModel.from_xml_path(str(_asset_file("unitree_g1_with_hands", "scene_xml")))
        names = {mujoco.mj_id2name(scene, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(scene.njnt)}
        assert set(HAND_JOINTS) <= names
