"""``pump()`` snapshots the registries it walks, so a worker thread may mutate them.

``pump`` is the main-thread half of this backend's threading contract, and its own
docstring states the other half:

    A web UI calls ``get_observation``/``send_action`` from worker threads where
    Isaac's renderer / physics deadlock. Those calls instead enqueue actions and
    read cached frames; this pump (run on the owning main thread) is the single
    place that actually advances the sim and renders the cameras.

So concurrent access is the designed usage rather than an edge case - and
``add_robot``, ``remove_robot``, ``add_camera`` and ``destroy`` all mutate
``_robots`` / ``_cameras`` under ``self._lock``. ``pump`` walked those dicts
**live and unlocked**, so an agent adding a robot from a worker thread while the
pump ran raised

    RuntimeError: dictionary changed size during iteration

measured on 6 of 6 trials with 200 robots and a worker adding 60 more mid-walk.

Two things make it worse than a lost tick. The exception comes from the ``for``
statement's own call to the iterator, which sits **outside** the per-item
``try``/``except (RuntimeError, ...)`` in the body - so the handler that looks
like it covers this cannot see it. And it lands on the **main** thread, which is
the thread that owns Kit and runs the pump loop, so it takes the application down
rather than degrading one frame.

The fix copies each registry under the lock and iterates the copy. The lock is
held only for the copy, deliberately not across the body: the joint read and the
frame grab both reach into Kit, and holding it across them would serialize the
pump against every tool call for the length of a render.

Nothing here needs Isaac Sim - the articulation and camera handles are stand-ins.
What is exercised is the real ``pump``.
"""

from __future__ import annotations

import queue
import threading
import types
from typing import Any

import pytest

pytest.importorskip("strands_robots.simulation.isaac")

from strands_robots.simulation.isaac.simulation import IsaacSimulation  # noqa: E402

#: Enough robots that a worker mutating partway through lands inside the walk.
_ROBOT_COUNT = 200


class _SlowArticulation:
    """Reads slowly enough that a concurrent mutation lands mid-iteration."""

    def __init__(self, delay: float = 0.002) -> None:
        self._delay = delay

    def get_joint_positions(self) -> list[float]:
        import time

        time.sleep(self._delay)
        return [0.0]


class _Camera:
    def __init__(self) -> None:
        self.handle = object()


def _engine(*, cameras: bool = False) -> Any:
    """A skeleton engine holding exactly what ``pump`` touches."""
    engine = IsaacSimulation.__new__(IsaacSimulation)
    engine._lock = threading.RLock()
    engine._world_created = True
    engine._world = types.SimpleNamespace()
    engine._action_q = queue.Queue()
    engine._robots = {}
    engine._cameras = {}
    engine._joint_cache = {}
    engine._frame_cache = {}
    engine._pump_cameras = cameras
    engine._idle_converge = 1
    engine._converge_render = lambda n: None
    engine._grab_frame = lambda name, handle: None
    for i in range(_ROBOT_COUNT):
        engine._robots[f"r{i}"] = types.SimpleNamespace(articulation=_SlowArticulation(), joint_names=["j"])
        if cameras:
            engine._cameras[f"c{i}"] = _Camera()
    return engine


def _mutate_after(engine: Any, attr: str, make, *, delay: float = 0.01) -> threading.Thread:
    """Add entries to ``attr`` from another thread, once the walk has started."""

    def _run() -> None:
        import time

        time.sleep(delay)
        registry = getattr(engine, attr)
        for i in range(_ROBOT_COUNT, _ROBOT_COUNT + 60):
            registry[f"new{i}"] = make()

    thread = threading.Thread(target=_run)
    thread.start()
    return thread


class TestAWorkerMayAddARobotMidPump:
    """The measured crash: 6/6 before, 0/6 after."""

    @pytest.mark.parametrize("trial", range(6))
    def test_pump_does_not_raise(self, trial: int) -> None:
        engine = _engine()
        thread = _mutate_after(
            engine,
            "_robots",
            lambda: types.SimpleNamespace(articulation=_SlowArticulation(), joint_names=["j"]),
        )
        try:
            engine.pump(render=False)
        finally:
            thread.join()

    def test_a_removal_mid_pump_does_not_raise(self) -> None:
        """Removal is the other direction and the one ``remove_robot`` performs."""
        engine = _engine()

        def _remove() -> None:
            import time

            time.sleep(0.01)
            for i in range(_ROBOT_COUNT // 2):
                engine._robots.pop(f"r{i}", None)

        thread = threading.Thread(target=_remove)
        thread.start()
        try:
            engine.pump(render=False)
        finally:
            thread.join()


class TestAWorkerMayAddACameraMidPump:
    """The second walk, which is reached only on the idle render path."""

    @pytest.mark.parametrize("trial", range(4))
    def test_pump_does_not_raise(self, trial: int) -> None:
        engine = _engine(cameras=True)
        thread = _mutate_after(engine, "_cameras", _Camera)
        try:
            engine.pump(render=True)
        finally:
            thread.join()


class TestThePumpStillDoesItsWork:
    """Controls. A snapshot that walked nothing would pass every test above."""

    def test_the_joint_cache_is_populated(self) -> None:
        engine = _engine()

        engine.pump(render=False)

        assert len(engine._joint_cache) == _ROBOT_COUNT
        assert engine._joint_cache["r0"] == {"j": 0.0}

    def test_the_frame_cache_is_populated_on_the_idle_path(self) -> None:
        engine = _engine(cameras=True)
        engine._grab_frame = lambda name, handle: f"frame-{name}"

        engine.pump(render=True)

        assert len(engine._frame_cache) == _ROBOT_COUNT
        assert engine._frame_cache["c0"] == "frame-c0"

    def test_a_robot_added_mid_pump_is_picked_up_on_the_next_tick(self) -> None:
        """A snapshot is a point-in-time read, so the new robot is served by the
        following tick rather than dropped. Pinned so the fix cannot be mistaken
        for one that silently forgets late arrivals."""
        engine = _engine()
        engine.pump(render=False)
        engine._robots["late"] = types.SimpleNamespace(articulation=_SlowArticulation(), joint_names=["j"])

        assert "late" not in engine._joint_cache

        engine.pump(render=False)

        assert "late" in engine._joint_cache

    def test_the_lock_is_not_held_across_the_body(self) -> None:
        """Holding it across the joint read would serialize the pump against
        every tool call for the length of a render. Observed from inside the
        walk, on the thread the articulation read runs on."""
        engine = _engine()
        held: list[bool] = []

        def _probe() -> bool:
            """Whether the lock is currently held, asked from another thread.

            An RLock is re-entrant for its owner, so the main thread could take
            it again even while holding it - the question is only answerable from
            a thread that does not own it. Acquire and release happen in that
            same thread: releasing an RLock from a thread that does not own it
            raises RuntimeError, and pump's per-item handler would swallow it,
            leaving this assertion silently unevaluated.
            """
            got: list[bool] = []

            def _try() -> None:
                acquired = engine._lock.acquire(blocking=False)
                got.append(acquired)
                if acquired:
                    engine._lock.release()

            thread = threading.Thread(target=_try)
            thread.start()
            thread.join()
            return not got[0]

        class _Observing:
            def get_joint_positions(self) -> list[float]:
                held.append(_probe())
                return [0.0]

        engine._robots = {"only": types.SimpleNamespace(articulation=_Observing(), joint_names=["j"])}

        engine.pump(render=False)

        assert held == [False], "the lock was held while the articulation was read"
