### Fixed: the Isaac backend refuses to step a scene PhysX's tensor view no longer covers

PhysX builds its tensor simulation view at `world.reset()`, and adding or
deleting a physics-body prim afterwards invalidates it. Stepping that stale view
advanced the clock and simulated nothing, while every envelope reported success:

```python
sim.create_world()
sim.add_robot("arm", urdf_path="arm.urdf")
sim.add_object(name="cube", shape="cuboid", position=[0.4, 0.0, 0.6], size=[0.05] * 3)
sim.step(90)
# before: {"status": "success", ... "Stepped 90x ... 33 steps/sec"}
#         - the cube never left 0.600 m, and the arm's get_observation() went 2 keys -> 0
# after:  {"status": "error", ... "the scene changed since the last reset() ... Call reset() first"}
```

Measured on `nvcr.io/nvidia/isaac-sim:6.0.1` (A10G), the invalidation had three
consequences and every one of them was silent. The body never moved, though
`step` reported a rate for the steps it claimed to have taken: a cube spawned at
`z=0.600` was still at `z=0.600` afterwards, and fell to `z=0.025` once the same
`step` ran after a `reset()`. An already-working robot's `get_observation()` went
empty - 2 keys to 0 on a 2-joint URDF arm, and back to 2 after the reset. And
after a `remove_object`, the observation stopped degrading and started *raising*
- `SingleArticulation.get_joint_positions` throws a bare `Exception` ("Failed to
get DOF positions from backend") straight out of a method the `SimEngine` ABC
documents as returning a dict, which the narrow handler downstream cannot catch
without widening to `except Exception`.

The observation half was measured on a URDF robot on purpose. The three
procedural builders (`so100`, `panda`, `unitree_g1`) leave their
`_RobotState.articulation` as `None` and report 0 observation keys at every point
in the lifecycle, reset or no reset, so neither the drop nor the raise is
observable on one. That is a separate defect and is not addressed here.

`reset()` repairs all three, so the scene was always one call away from correct
and nothing said so. `add_object` and `remove_object` now mark the scene, `step`
refuses while the mark stands and names the remedy, and `get_observation` answers
empty - its documented degraded mode - with a WARNING rather than raising.

Which mutations invalidate the view was measured rather than assumed:
`add_camera`, `remove_camera`, `move_object`, `add_robot` and `remove_robot` each
left that arm reporting both its keys, so none of them marks the scene. A gate
that fired on those would refuse `step` over a view that is perfectly live.

`load_scene` is the one path that repairs the view *without* a reset - it rebuilds
through `SimulationManager.initialize_physics()` and `world.play()`, deliberately
not `world.reset()`, because a full reset re-applies every registered prim's
default state and was measured to explode an already-posed articulation into
non-finite PhysX bounds (#1802). It clears the mark where that rebuild lands, so
a scene load still steps. A reload that removes prior objects and realizes none
skips the rebuild and stays marked, which is the honest verdict: those removals
invalidated the view with nothing behind them.

The refusal is Isaac-only and changes no cross-backend contract. MuJoCo needs no
equivalent - its `step` reads the compiled model directly - and the shared
step-count and lock-hold domains are unchanged, since the gate is inert until a
body mutation marks the scene and sits behind the existing "No world created" and
"World not initialized" refusals.

**A failed `add_object` marks the scene stale too.** Only the success path set the
flag, and the failure path is stale by the same mechanism - which that handler's own
comment already states: `_construct_shape_prim` stops the timeline, clearing the
physics sim view, *before* constructing a dynamic prim. By the time the handler runs
the view is already invalid whether the construction went on to succeed or to raise.

So a failed `add_object` left `step()` willing to advance, and the clock moved over a
scene PhysX was no longer simulating while every robot's `get_observation` came back
empty - the exact degradation the flag was added to refuse. To a caller it read as a
transient add failure followed by a sim that had quietly stopped simulating: no
exception, a plausible error envelope, and then empty observations attributed to
whatever ran next.

Pinned across all six exception types the handler names, and by a drift guard that
derives from the source: any `return` below the `_construct_shape_prim` call which
does not have the flag set on the way is a new instance of this bug. There were two
such returns when only one was covered.
