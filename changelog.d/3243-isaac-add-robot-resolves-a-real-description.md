### Fixed: the Isaac backend's `add_robot` loads a real robot instead of reporting one

`add_robot(name)` with no asset path took a "procedural" branch whose comment read
"Build procedurally via USD API" and which made no USD call at all. It read joint
names off a hardcoded dataclass, registered a prim path for a prim it never
created, and returned success:

```python
sim.create_world()
sim.add_robot("so100")
# before: {"status": "success", ... "Robot 'so100' added (procedural: so100,
#          6 joints: ['shoulder_pan', 'shoulder_lift', 'elbow_flex', ...])"}
#         - 0 prims under /World/Robots/so100, articulation None before AND after
#           reset(), get_observation() == {} for the whole lifecycle
# after:  {"status": "success", ... "Robot 'so100' added (MJCF: .../trs_so_arm100/
#          scene.xml -> USD: ..., 6 joints)"}
#         - a live articulation, and get_observation() returns 6 keys
```

Measured on `nvcr.io/nvidia/isaac-sim:6.0.1` (A10G), `_RobotState.articulation`
was `None` both before and after `world.reset()`, no prim existed at the
registered path, and `get_observation()` was empty at every point in the
lifecycle. That was the documented headline example
(`sim.add_robot("so100")  # procedural; no asset files needed`).

**It was also wrong as metadata**, which is the half a caller could have checked
without a GPU. For the same robot name the MuJoCo backend reports a different
vocabulary, and for `panda` a different count:

| robot | the deleted table | MuJoCo, real asset |
|---|---|---|
| `so100` | 6: `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper` | 6: `Rotation, Pitch, Elbow, Wrist_Pitch, Wrist_Roll, Jaw` |
| `panda` | **7**: `panda_joint1..panda_joint7` | **9**: `joint1..joint7, finger_joint1, finger_joint2` |

So the parity these docs promise - "the joint-name and observation contract
matches the MuJoCo backend, [so] policies and observation mappings transfer
unchanged between backends" - was false before any physics was involved.

Both halves are answered by loading the description MuJoCo loads. `add_robot` now
resolves the robot name (or `data_config=`) through
`strands_robots.simulation.model_registry.resolve_model`, the same resolver the
MuJoCo backend's `add_robot` uses, so one name means one file on both backends and
the vocabularies cannot drift. Measured on the same runtime, this reproduces
MuJoCo's names exactly: 9 of 9 for `panda`, 6 of 6 for `so100`, with a wired
articulation and a non-empty observation.

### Added: the Isaac backend imports MJCF

`add_robot(mjcf_path=...)` was refused outright, on the stated grounds that the
Isaac backend "has no MJCF robot importer". That was an assertion this repository
made in three places and measured in none. Isaac Sim 6.0.1 registers
`isaacsim.asset.importer.mjcf`, exposing `MJCFImporter` / `MJCFImporterConfig`
alongside the `MJCFCreateAsset` Kit command:

```
extensions: ['isaacsim.asset.importer.mjcf', 'isaacsim.asset.importer.mjcf.ui']
commands:   ['MJCFCreateAsset', 'MJCFCreateImportConfig']
```

The new `strands_robots.simulation.isaac.mjcf_assets` converts an MJCF to USD
through it, cached content-addressed under
`$STRANDS_BASE_DIR/asset_cache/usd_robots/`, and the result is loaded by the
existing native USD path - so a name, an MJCF, a URDF and a USD all converge on
one proven loader rather than each growing its own.

The cache key covers the description **and every file its directory holds**. An
MJCF is not self-contained: Menagerie's `scene.xml` is a handful of lines that
`<include>` the robot body and reference a `meshdir` of STLs, and the geometry
PhysX simulates lives in those, so a key over the named file alone would serve a
stale conversion after any change that did not touch it. Two vendor behaviours are
handled rather than assumed, both measured: `usd_path` is an output *directory
root* (the importer writes `<root>/<stem>/<stem>.usda` and returns that path), and
with no destination it writes beside the source - which fails with `Read-only file
system` for every description this package resolves, since those live in a shared
`robot_descriptions` checkout.

`fix_base` defaults to `None`, the vendor default, which honours whatever the
description says. That is the only choice that keeps a floating-base robot
floating: every shipped quadruped and humanoid declares its base with
`<freejoint>`, and `True` would bolt such a robot to the ground while reporting
success.

### Removed: the three hardcoded Isaac "procedural builders"

`_build_so100`, `_build_panda`, `_build_unitree_g1` and the
`get_procedural_robot` / `list_procedural_robots` lookup are deleted. Beyond
describing no real robot, the data could not have been authored into a working
articulation: `JointDef` carries no joint anchor frame (which is what a USD
revolute joint is defined by), `BodyDef.position` meant parent-relative from the
loaders but cumulative world-frame in those tables, `JointDef.axis` is a free
vector where `UsdPhysics` takes an X/Y/Z token and `panda_joint4`'s `(0,-1,0)` is
unrepresentable as one, `stiffness` was `0.0` on every joint so nothing would have
held a pose, and six `unitree_g1` bodies declared `mass=0.0`.

`ProceduralRobot`, `BodyDef`, `JointDef` and `_validate_kinematic_tree` stay -
they are the return type and shared guard of `load_urdf` / `load_mjcf` /
`load_usd`, which are unaffected.

### Fixed: two asset paths are refused rather than silently ranked

With `mjcf_path` live alongside `urdf_path` and `usd_path`, a call naming two was
newly ambiguous, and the `elif` chain would have dropped the loser with nothing
said. `add_robot` now refuses the combination and quotes every path it was given.

### Changed: the unresolvable-model message has one owner

`MuJoCoSimEngine._unknown_model_msg`'s three-way diagnosis - a typo (with close
matches over the sim-loadable registry), a hardware-only registry entry, or an
asset that is simply not downloaded - moved to
`strands_robots.simulation.base.unknown_model_msg` now that the Isaac backend
resolves names too. The MuJoCo method delegates and its text is byte-identical; a
second inline copy is how two backends come to diagnose one registry differently.
The one backend-specific sentence, the discovery hint, is a parameter.
