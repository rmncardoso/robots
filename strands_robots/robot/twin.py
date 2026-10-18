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
    places the twin's joints AT the measurement, so it shows the real pose with no step.
    """
    twin = robot.twin
    if twin is not None and twin.sim is not None:
        with twin.sim.lock:
            if measured:
                with contextlib.suppress(NotImplementedError):  # an engine that cannot place joints: command only
                    twin.sim.backend.set_joints(twin.id, targets)
            twin.body.write(targets)
        if step:
            twin.sim.control_step()
