### Added: `apply_force` and `raycast` on the Isaac backend

The last two consumer-ranked entries from the action-parity census. Both were
absent entirely, so the MuJoCo-portable disturbance-and-sensing recipes had no
Isaac half.

**`apply_force(body_name, force=None, torque=None, point=None)`** keeps the
MuJoCo contract: the wrench is **latched** - applied on every physics step until
the next call for that body replaces it, `force=[0,0,0]` stops one body,
`reset()` clears all, and a `point` folds its lever-arm torque into the latch at
call time. PhysX's own `apply_force_at_pos` acts for ONE step (measured: a
single call accelerated a resting cube for one tick and stopped), so the step
loop replays the latch each tick, applying the force at the body's current
position. Vectors are validated on the shared `coerce_pose_vector` domain
(booleans, non-finite elements and wrong lengths refused); an unknown or static
body is refused by name. A latch whose replay fails (deleted prim) is dropped
with one ERROR naming the body - replaying a failing wrench every tick floods
the log, and keeping a latch that no longer acts is a silent lie.

Two things the GPU verification settled that no document said:

* **`omni.physx.apply_torque` spins a body opposite to the right-handed world
  torque it is handed** on isaacsim 6.0.1 - +0.3 z gave wz = -0.458 rad/s and
  -0.3 z gave wz = +0.538, a clean mirror measured from rest in both
  directions. The flip is applied once, at the boundary to the binding that
  disagrees, so this backend's `apply_force` is right-handed world-frame like
  MuJoCo's.
* The latch demonstrably accelerates across step batches (successive
  15-step displacements 0.074 m then 0.209 m under a constant 8 N), and after
  `force=[0,0,0]` friction brings the cube to rest - no hidden latch.

**`raycast(origin, direction, exclude_body=-1, include_static=True)`** reports
the MuJoCo payload (`hit`, `distance`, `geom_id`, `geom_name`, `hit_point`) plus
`collision_path`. `geom_id` is always `None`: PhysX addresses colliders by prim
path, not compiled-model id, and inventing a number would invite cross-backend
comparisons of ids that mean nothing. `exclude_body` exists for signature
parity and accepts only its `-1` default - it is a MuJoCo body id, and silently
ignoring another value would report the very body the caller asked to skip -
refused with that explanation. `include_static=False` re-casts past hits whose
prim carries no `UsdPhysics.RigidBodyAPI` (bounded at 16 hops), so a clearance
check sees the movable scene only.

GPU-verified 12/12 on `nvcr.io/nvidia/isaac-sim:6.0.1` (A10G), including the ray
distance matching the geometric value to sub-millimeter (1.8800 m vs 1.88) and
`include_static=False` over bare ground answering "no hit". 23 unit tests over
the domains, the latch bookkeeping, the per-tick replay, and the raycast
translation with the static-hop.
