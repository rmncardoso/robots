"""A hardware Robot's twin: the simulated body in the default world that mirrors what it measures and commands."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .robot import Robot


def make(real: Robot, name: str, position: Any, orientation: Any, keyframe: str | None) -> Robot:
    """``real``'s twin: a simulated body of its description in ``Simulation.default()``, whose ``twin_of`` is ``real``.

    Its scene entry is marked as a twin, so there it touches the floor and nothing else: it never pushes a simulated
    robot or object that stands where it spawns, and a floating twin still rests on the floor. The world's lock is
    held from the add to the rebuild that marks it, so a step in another thread never meets it unmarked.
    """
    from ..simulation import Simulation
    from .robot import Robot

    world = Simulation.default()
    with world.lock:
        twin = Robot(
            name, sim=world, position=position, orientation=orientation, keyframe=keyframe, id=f"{real.id}_twin"
        )
        twin.twin_of = real
        world.scene.robot(twin.id)._twin = True  # the backend builds a twin's geoms to touch the floor alone
        world._reload()
    return twin


def mirror(robot: Robot, targets: np.ndarray, *, step: bool = False, measured: bool = False) -> None:
    """Write ``targets`` to this robot's twin (if any), under the twin's world lock.

    ``step=True`` (what ``act`` passes) then advances the twin's world one control step, as a simulated
    ``act`` does; ``manual_time()`` still suppresses it. ``measured=True`` (what ``observe`` passes) also
    places the twin's joints AT the measurement, so it shows the measured joints with no step.

    A sample that is not finite is not mirrored (MuJoCo would reset the whole world on its next step), and a twin
    whose world closed, or that left it, is skipped: the real body goes on without its display.
    """
    twin = robot.twin
    sim = twin.sim if twin is not None else None  # read once: a world that closes sets it to None
    if twin is None or sim is None or not np.isfinite(targets).all():
        return
    with sim.lock:  # close() takes it too, so inside it the twin is either still in this world or gone
        if sim.robots.get(twin.id) is not twin:
            return
        if measured:
            with contextlib.suppress(NotImplementedError):  # an engine that cannot place joints: command only
                sim.backend.set_joints(twin.id, targets)
        twin.body.write(targets)
        if step:
            sim.control_step()
