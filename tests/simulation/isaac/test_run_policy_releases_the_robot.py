"""``run_policy`` lowers ``policy_running``, so the motion primitives come back.

``policy_running`` is Isaac's busy guard: ``move_to``, ``rotate_wrist`` and
``set_gripper`` all refuse while it is set, because a primitive and the policy loop
would race on the articulation's PD targets. The guard is right to exist. What was
wrong is that on the ``run_policy`` path nothing ever lowered it.

The flag is raised as a side effect of the recording hook -
``IsaacRecordingMixin._make_run_policy_hook`` sets ``robot.policy_running = True``,
and reaches that line whenever a world exists (its early return is on
``_recording_state() is None``, which is keyed on ``_world_created``, not on
whether recording is active). The shared ``SimEngine.run_policy`` never mentions
the flag at all. So the only Isaac path that lowered it was ``run_multi_policy``,
in its own ``finally``:

| path | raises it | lowers it (before) |
| --- | --- | --- |
| ``run_policy`` (shared) | yes, via the hook it installs | **no** |
| ``start_policy`` -> ``run_policy`` | yes | **no** |
| ``run_multi_policy`` (Isaac's own) | yes | yes |
| ``eval_policy`` -> ``PolicyRunner.evaluate`` | no | n/a |

After one ``run_policy`` the flag stayed up forever, so every later primitive on
that robot was refused with a message whose advice could never come true::

    Cannot 'move_to' on 'arm' while its policy is running [...] Wait for the
    rollout to finish (Isaac policy loops clear the flag on exit).

The rollout *had* finished. The parenthetical was a promise only
``run_multi_policy`` kept, and the only recovery was to remove and re-add the
robot. The MuJoCo backend has had the ``finally`` all along, in ``_drive_rollout``,
which is the shape this mirrors.

Scope. ``start_policy`` is covered without its own override, because the shared
implementation ends in ``return self.run_policy(...)``. ``eval_policy`` is
deliberately NOT covered: it drives ``PolicyRunner.evaluate``, which never touches
the flag on *either* backend, so it is a shared question rather than an Isaac
defect, and it is pinned as out of scope below rather than fixed quietly.
"""

from __future__ import annotations

import inspect
import threading
import types
from typing import Any

import numpy as np
import pytest

pytest.importorskip("strands_robots.simulation.isaac")

from strands_robots.simulation.base import SimEngine  # noqa: E402
from strands_robots.simulation.isaac.config import IsaacConfig  # noqa: E402
from strands_robots.simulation.isaac.simulation import IsaacSimulation, _RobotState  # noqa: E402


class _Articulation:
    dof_names = ["j0", "j1"]

    def get_joint_positions(self) -> Any:
        return np.zeros(2, dtype=np.float32)


def _engine(robots: tuple[str, ...] = ("arm",)) -> Any:
    engine = IsaacSimulation.__new__(IsaacSimulation)
    engine._lock = threading.RLock()
    engine._config = IsaacConfig()
    engine._world = types.SimpleNamespace()
    engine._world_created = True
    engine._robots = {
        name: _RobotState(
            name=name,
            prim_path=f"/World/Robots/{name}",
            joint_names=["j0", "j1"],
            articulation=_Articulation(),
        )
        for name in robots
    }
    engine._objects = {}
    engine._cameras = {}
    engine._prim_registry = []
    engine._action_controllers = {}
    engine._replicated = False
    engine._recording_state_dict = {}
    engine._main_tid = threading.get_ident()
    engine._pump_running = False
    return engine


@pytest.fixture
def base_returns(monkeypatch) -> list[dict[str, Any]]:
    """Stand in for the 549-line shared rollout: this pins the release, not the loop."""
    calls: list[dict[str, Any]] = []

    def _fake(self: Any, robot_name: Any = None, **kwargs: Any) -> dict[str, Any]:
        calls.append({"robot_name": robot_name, **kwargs})
        return {"status": "success", "content": [{"text": "rollout done"}]}

    monkeypatch.setattr(SimEngine, "run_policy", _fake)
    return calls


class TestTheFlagIsLoweredWhateverTheRolloutDid:
    def test_a_completed_rollout_releases_the_robot(self, base_returns: Any) -> None:
        engine = _engine()
        robot = engine._robots["arm"]
        robot.policy_running = True  # what the recording hook leaves set

        assert engine.run_policy("arm")["status"] == "success"

        assert robot.policy_running is False

    def test_a_raising_rollout_releases_the_robot(self, monkeypatch) -> None:
        """The ``finally`` is the point: a rollout that dies must not brick the robot."""

        def _boom(self: Any, robot_name: Any = None, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("kit session torn down")

        monkeypatch.setattr(SimEngine, "run_policy", _boom)
        engine = _engine()
        robot = engine._robots["arm"]
        robot.policy_running = True

        with pytest.raises(RuntimeError, match="kit session torn down"):
            engine.run_policy("arm")

        assert robot.policy_running is False

    def test_the_base_result_is_returned_unchanged(self, base_returns: Any) -> None:
        """The override adds cleanup and nothing else - it must not reshape a verdict."""
        engine = _engine()

        result = engine.run_policy("arm", duration=1.0)

        assert result == {"status": "success", "content": [{"text": "rollout done"}]}
        # Every parameter is forwarded explicitly (see the signature test below),
        # so the base sees the full set; what matters is that the caller's value
        # arrives and the robot is named.
        assert len(base_returns) == 1
        assert base_returns[0]["robot_name"] == "arm"
        assert base_returns[0]["duration"] == 1.0

    def test_kwargs_reach_the_base_verbatim(self, base_returns: Any) -> None:
        engine = _engine()

        engine.run_policy("arm", instruction="pick the cube", n_steps=7, seed=3)

        assert base_returns[0]["instruction"] == "pick the cube"
        assert base_returns[0]["n_steps"] == 7
        assert base_returns[0]["seed"] == 3


class TestTheRobotReleasedIsTheOneTheRolloutResolved:
    def test_robot_name_none_releases_the_only_robot(self, base_returns: Any) -> None:
        """``None`` is the documented spelling for "the only robot", and it is that
        robot the flag was raised on - so it is that robot that must be released."""
        engine = _engine()
        robot = engine._robots["arm"]
        robot.policy_running = True

        engine.run_policy(None)

        assert robot.policy_running is False

    def test_a_sibling_robot_is_untouched(self, base_returns: Any) -> None:
        """Releasing everything would clear a flag another rollout legitimately holds."""
        engine = _engine(("arm", "other"))
        engine._robots["arm"].policy_running = True
        engine._robots["other"].policy_running = True

        engine.run_policy("arm")

        assert engine._robots["arm"].policy_running is False
        assert engine._robots["other"].policy_running is True

    def test_an_unresolvable_name_does_not_raise_from_cleanup(self, base_returns: Any) -> None:
        """With two robots ``None`` cannot resolve, and the base call's own verdict
        must survive: a raise from cleanup would replace it."""
        engine = _engine(("arm", "other"))

        result = engine.run_policy(None)

        assert result["status"] == "success"

    def test_an_unknown_name_does_not_raise_from_cleanup(self, base_returns: Any) -> None:
        engine = _engine()

        result = engine.run_policy("nonexistent")

        assert result["status"] == "success"


class TestThePrimitivesComeBack:
    """The consequence, read through the guard the primitives actually call."""

    def test_a_primitive_is_refused_while_the_flag_is_up(self) -> None:
        engine = _engine()
        engine._robots["arm"].policy_running = True

        _name, _robot, err = engine._primitive_resolve_robot("move_to", "arm")

        assert err is not None
        assert "while its policy is running" in err["content"][0]["text"]

    def test_a_primitive_is_allowed_after_the_rollout(self, base_returns: Any) -> None:
        """Before the fix this was the permanent state: rollout over, primitive
        refused, and the refusal advising a wait that would never end."""
        engine = _engine()
        engine._robots["arm"].policy_running = True

        engine.run_policy("arm")
        _name, _robot, err = engine._primitive_resolve_robot("move_to", "arm")

        assert err is None, err


class TestTheOverrideExistsForTheReasonStated:
    def test_isaac_overrides_run_policy(self) -> None:
        assert IsaacSimulation.run_policy is not SimEngine.run_policy

    def test_it_delegates_rather_than_reimplementing(self) -> None:
        """A 549-line rollout must not be forked to add a ``finally``."""
        src = inspect.getsource(IsaacSimulation.run_policy)
        base_src = inspect.getsource(SimEngine.run_policy)
        assert "super().run_policy(" in src
        assert "finally:" in src
        # Measured against the shared implementation rather than a magic number:
        # the point is that the 500-plus-line rollout is NOT forked to add a
        # ``finally``. A signature this wide makes the wrapper long on its own, so
        # an absolute threshold would either be meaningless or need bumping every
        # time the shared parameter list grows.
        assert len(src.splitlines()) < len(base_src.splitlines()) / 2, (
            "this should be a thin wrapper, not a second rollout"
        )

    def test_start_policy_is_covered_without_its_own_override(self) -> None:
        """The shared ``start_policy`` ends in ``return self.run_policy(...)``, so
        the worker it submits reaches this override's ``finally`` too. If that
        stops being true, ``start_policy`` silently loses the release."""
        assert IsaacSimulation.start_policy is SimEngine.start_policy
        assert "self.run_policy(" in inspect.getsource(SimEngine.start_policy)

    def test_the_shared_rollout_still_does_not_manage_the_flag(self) -> None:
        """Premise. If the shared implementation ever starts lowering the flag
        itself, this override becomes redundant and should go, rather than both
        doing it."""
        assert "policy_running" not in inspect.getsource(SimEngine.run_policy)

    def test_the_signature_is_the_shared_one_and_not_a_kwargs_sink(self) -> None:
        """A ``**kwargs`` sink here is a correctness bug, not a style choice.

        It accepts EVERY keyword, so ``run_policy(instrction="pick")`` binds
        silently instead of raising ``TypeError`` and the typo surfaces as a
        rollout that ignored the instruction. It also disables a repository-wide
        grader: ``tests/test_docs_python_examples_are_callable.py`` reads a
        candidate's accepted keywords off its signature and treats a sink as
        "accepts anything", so with one here a planted bad keyword in the
        documentation can no longer be reported - which is exactly how an
        interim version of this override was caught.
        """
        base = inspect.signature(SimEngine.run_policy).parameters
        own = inspect.signature(IsaacSimulation.run_policy).parameters

        assert not any(p.kind is p.VAR_KEYWORD for p in own.values()), (
            "run_policy must not absorb keywords into **kwargs"
        )
        assert list(own) == list(base), "the override must expose the shared parameter list"
        assert all(own[n].default == base[n].default for n in base if n != "self"), (
            "a default that differs from the shared one would silently change behaviour"
        )

    def test_a_misspelled_keyword_is_refused(self) -> None:
        """The consequence the explicit signature buys back."""
        engine = _engine()

        with pytest.raises(TypeError):
            engine.run_policy("arm", instrction="pick the cube")

    def test_run_multi_policy_still_lowers_it_itself(self) -> None:
        """The one Isaac path that always did. Left alone deliberately: it drives
        several robots and releases each, which this single-robot override cannot
        express."""
        assert "policy_running = False" in inspect.getsource(IsaacSimulation.run_multi_policy)


class TestEvalPolicyIsOutOfScope:
    """Pinned so the boundary is deliberate rather than an oversight.

    ``eval_policy`` drives ``PolicyRunner.evaluate``, which touches the flag on
    neither backend - so a primitive is *not* refused during an eval on MuJoCo
    either. That makes it a shared question about the eval path rather than an
    Isaac release defect, and it is not fixed here.
    """

    def test_eval_policy_is_shared_by_both_backends(self) -> None:
        from strands_robots.simulation.mujoco.simulation import MuJoCoSimEngine

        assert IsaacSimulation.eval_policy is SimEngine.eval_policy
        assert MuJoCoSimEngine.eval_policy is SimEngine.eval_policy

    def test_the_eval_path_does_not_reach_run_policy(self) -> None:
        src = inspect.getsource(SimEngine.eval_policy)
        body = src.split('"""')[2] if src.count('"""') >= 2 else src
        assert "self.run_policy(" not in body
        assert "PolicyRunner" in src
