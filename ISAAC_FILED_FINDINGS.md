# Isaac backend: 13 defects found but not fixed in this series

Each was surfaced by an adversarial audit, survived unanimous verification by
independent reviewers, and was then **re-validated against upstream `main` at
`b0a8fcea`** — the Isaac backend is untouched by the 29 commits that landed after
the audit, so all 13 still reproduce. None is intended: for each, no test pins the
current behaviour, no comment or changelog states a reason, and no `AGENTS.md` rule
endorses it.

They are **left out of this series deliberately**. It claims to make the Isaac
backend work and to stop it reporting things it has not done; these are separate
repairs with their own risk surfaces. `send-action-lock` in particular means
introducing marshalling on a hot path, which deserves its own PR and its own GPU
verification rather than riding along in a 23-branch change.

Five sibling findings *were* fixed here, because they were defects in code this
series adds or completions of a fix it starts: the `get_contacts` cache surviving a
clock rewind, `remove_object` leaking a latched wrench, a failed `add_object` not
marking the scene stale, and `__repr__` / `physics_dt` still echoing a request.

---

## 1. `remove-robot-prim` — high

**What is wrong**

Accurate as far as the prim/articulation go, with three refinements. (1) The leftover is
bounded by `destroy()`, not permanent: `destroy` issues
`omni.usd.get_context().new_stage()` (simulation.py:1772-1775), so the stale prim dies
with the stage - the defect window is remove_robot -> destroy, and the docstring's
"delegated to destroy" is technically true via the wholesale stage swap, not via
`_prim_registry` (remove_robot deletes the path from that registry at 4196-4198, so the
per-prim teardown accounting it points at no longer knows about the prim, and
`destroy`'s `num_prims_released` under-reports by one). (2) Within that window the body
is orphaned rather than merely "still simulating": PhysX keeps it in the scene so it
collides, holds its last drive targets and falls under gravity, while
`list_robots`/`get_observation`/`send_action` all treat it as gone and its
`_action_controllers` entry has been dropped. (3) "Collides with the leftover prim path"
is right in the USD sense but does not raise: robots are never registered with
`world.scene.add()` (only objects are, 3125/4078), so there is no scene name-uniqueness
error. A re-add of the same name recomputes the identical `{stage_path}/Robots/{name}`
(2498), is not refused (`name in self._robots` is false, 2485), and `_load_usd_robot`'s
`add_reference_to_stage` (7712) finds a valid prim already there - so with a different
asset two references compose under one prim (two articulation roots), and with the same
asset the re-added robot inherits the stale prim's drifted transform/joint state
(`set_world_pose` is skipped for `position=[0,0,0]`, 7736). Reach also differs by
branch: on origin/main the registry-name path went through the procedural builder that
created no prims at all (/tmp/isaac_main.py:1862-1875), so only explicit
`usd_path=`/`urdf_path=` adds were affected; on `compose/rebased` every `add_robot`
creates a real prim, so every robot is now exposed.

**Evidence**

Code, current tree: strands_robots/simulation/isaac/simulation.py:4152-4207
(`remove_robot`) touches only Python state - it prunes `_prim_registry` (4196-4198),
does `del self._robots[name]` (4199), pops `_action_controllers` (4202) and returns
`"Robot '<name>' removed."`. It never references `self._world` and never imports/uses
`delete_prim`, which the sibling verb `remove_camera` does use for exactly this purpose
at 6908-6919 (`from isaacsim.core.utils.prims import delete_prim;
delete_prim(prim_path)`), and `remove_object` deletes via
`self._world.scene.remove_object(name)` at 4246-4248. `remove_robot` is byte-identical
to `git show origin/main:strands_robots/simulation/isaac/simulation.py` (verified by
extracting the method from both: identical, 2842 chars), so it is upstream code,
unchanged by our branches, and none of the moved pieces touch it
(`strands_robots/utils.py` diff 90a6efc6..origin/main only edits `positive_count_error`/
`non_negative_count_error`/`declared_count`/`validation_split_error` docstrings+domains,
not `registered`/`entity_name_error`; the two new AGENTS.md rules are about text-IO
encoding and child-stream decoding).  Demonstrated on the current tree (/tmp/srenv,
/tmp/demo_remove_robot.py, unbound-method-on-a-stub idiom from
tests/simulation/isaac/test_removing_a_robot_prunes_at_the_prim_path_boundary.py:71-110,
with `_load_usd_robot` replaced by a recorder that mimics `add_reference_to_stage`'s
define-or-add-reference semantics and a `MagicMock` world):   add_robot #1 -> success,
prim `/World/Robots/arm`, stage {'/World/Robots/arm': ['/assets/panda.usd']}
remove_robot -> success "Robot 'arm' removed."; world.mock_calls == []  (zero
stage/scene calls)   stage AFTER remove -> {'/World/Robots/arm': ['/assets/panda.usd']};
`_robots` == [], `list_robots()` == []   add_robot #2 ("arm", different asset) ->
success, same prim path, stage {'/World/Robots/arm': ['/assets/panda.usd',
'/assets/so100.usd']} The zero-world-call result is corroborated by the repo's own test
double: tests/simulation/isaac/test_delta_eef_controller.py:365-370 drives a real
`IsaacSimulation` whose `_world` is `_FakeWorld` (line 240-242, it has only `step`, no
`scene`) and `remove_robot` still returns success - it would have hit AttributeError if
it deleted anything.  Corroborating measurement already in the file:
simulation.py:1134-1137 records that `add_camera`, `remove_camera`, `move_object`,
`add_robot` and `remove_robot` each left a live arm reporting both joint keys, so they
do NOT set `_physics_view_stale`, while `remove_object` (4265-4269) does - i.e. a
measured confirmation that `remove_robot` removes nothing PhysX holds.
simulation.py:2098-2103 then tells callers in the `step` refusal text that
"add_object/remove_object are the mutations that require [a reset]; add_camera,
move_object, add_robot and remove_robot do not", so stepping continues over the orphaned
articulation without complaint.  Intent: no test pins the no-deletion behaviour (the
only dedicated regression file,
tests/simulation/isaac/test_removing_a_robot_prunes_at_the_prim_path_boundary.py, grades
only `_prim_registry` scoping; `grep -rn delete_prim tests/` has one hit, an unrelated
stub); no changelog.d fragment mentions it; no AGENTS.md rule endorses it. The only
documentation is the docstring at 4155-4158, and it frames the state as unfinished
("delegated to destroy / world teardown in Phase 1; only the in-Python registry is
updated here") while its two sibling verbs carry explicit "Phase 2 wiring (#14)" notes
saying the prim really is gone (4212-4217, 6875-6878). docs/simulation/isaac.md:272-278
advertises `remove_robot` as part of "the same SimEngine shape as the MuJoCo backend",
and the MuJoCo `remove_robot` docstring
(strands_robots/simulation/mujoco/simulation.py:2401-2405) names this exact defect as
one it already fixed: "Previously remove_robot only popped the Python-side dict entry
... That blocked re-adding a robot with the same name ... and left stale bodies in the
physics loop."

**Suggested fix**

Mirror `remove_camera`: inside the existing lock, before dropping bookkeeping, import
`delete_prim` (`isaacsim.core.utils.prims` with the `omni.isaac.core.utils.prims`
fallback) and delete the robot's subtree - `robot.actual_prim_path` as well as
`prim_path` when they differ (the URDF importer can land elsewhere, 7910/2700) - wrapped
in the same narrow `(RuntimeError, ValueError, OSError, AttributeError, TypeError,
ImportError)` clause that returns the error envelope and leaves state retry-friendly.
Then set `self._physics_view_stale = True` as `remove_object` does (4265-4269), since
deleting a prim PhysX holds invalidates the tensor view, and update the two places that
assert the opposite: the `step` refusal text at 2098-2103 and the measurement comment at
1134-1137.

*Scope: upstream-main · verifier confidence: high*

---

## 2. `send-action-lock` — high

**What is wrong**

Accurate as stated, with two refinements. (1) The missing guard is not only the "no pump
-> block forever" case: with `run_pump_forever` engaged, `send_action` also fails to
marshal (measured: `_main_jobs` stays empty and world.step runs on the worker), so it
drives kit off the owning thread while holding `self._lock` and starves the pump that
would service it - whereas `step()` in the same state marshals. (2) The "blocks forever"
consequence is the repo's own documented premise about `world.step()` off-thread
(simulation.py:8244), not something measurable here (no Isaac Sim / GPU); what is
measured is the unguarded off-thread kit call under a held lock and the asymmetry with
`step`. Bonus, same lines, same acquisition: the substep loop never got the
`_STEPS_PER_BATCH` release + boundary re-check that `step` has (1 lock acquisition for
`n_substeps=100_001`), and it does not honour the `_physics_view_stale` refusal `step`
makes.

**Evidence**

Reproduces on the current tree (branch compose/rebased, merge 31aec6f1 over origin/main
b0a8fcea).  CODE: /Users/ruicard/projects/new-strands/strands-
robots/strands_robots/simulation/isaac/simulation.py:5117 takes `with self._lock:` and
the same single acquisition still covers the substep loop at :5243 ->
`self._world.step(render=...)` at :5254. An AST scan of every `world.step` call site in
the file: `step` (:2147) ends in `return self._marshal_main_thread_affine("step",
_step_impl)`; `run_multi_policy` (:5788) has `if not self._on_main_thread() and not
self._pump_running: return {"status": "error", ...}` at :5638; `send_action`
(:5050-5277) has NO `_on_main_thread` / `_pump_running` / `_marshal_main_thread_affine`
/ `run_on_main` reference anywhere in its 227 lines. `step`'s docstring carries a
"Concurrency: main-thread affine" section (:2062); `send_action`'s docstring has none.
MEASURED on a skeleton engine (IsaacSimulation.__new__, `_main_tid` = main thread, world
stub recording the calling thread; /tmp/demo_send_action_thread.py,
/tmp/demo_lock_hold.py under /tmp/srenv): - no pump, worker thread: `send_action({...},
n_substeps=3)` -> `{"status": "success", ...}`, world.step called on
['WORKER','WORKER','WORKER'], `_step_count`=3. `step(3)` on the identical engine ->
RuntimeError "...called from a worker thread with no main-thread pump...". - pump
running (`_pump_running=True`), worker thread: `send_action` still ran world.step on the
worker; `_main_jobs` queue size 0, i.e. it never marshals. - deadlock shape: with
world.step blocking off-MAIN (the behaviour `_marshal_main_thread_affine`'s own
docstring at :8244 states - "they block **forever** waiting for a pump the worker thread
can never run"), the worker sat inside world.step and the MAIN thread could not acquire
`engine._lock` within 1s, so the pump that would have to service kit is itself starved.
- two further asymmetries in the same lines: `send_action(n_substeps=100_001)` = 1 lock
acquisition for 100_001 ticks, vs `step(100_001)` = 102 acquisitions
(`_STEPS_PER_BATCH`=1000), i.e. the #1871/#1869 batch-release + re-check contract pinned
by tests/simulation/test_step_lock_hold_across_backends.py was never applied to this
loop; and `_physics_view_stale=True` -> `step` errors, `send_action` reports success
having ticked the stale tensor view.  UPSTREAM vs OURS: an AST diff of `send_action`
between `git show origin/main:...` (upstream lines 3827-4045) and the working tree
(5050-5277) differs by exactly two added code lines - `if getattr(self,
"_applied_wrenches", None): self._reapply_wrenches()` inside the substep loop (our
apply_force work). The single `with self._lock:` and the unguarded
`self._world.step(...)` are upstream's, unchanged; our two lines merely inherit the same
off-thread context. The n_substeps domain guard was already upstream.  NOT INTENDED:
tests/simulation/isaac/test_isaac_backend.py:610-650 pins the worker-thread contract for
`reset` and `step` only (raise without a pump, marshal to main with one); no test
anywhere exercises `send_action` off the owning thread. changelog.d/3270-isaac-queued-
joint-write-needs-a-pump.md asserts the opposite of the current code - "every other
main-thread-affine surface either routes through `_marshal_main_thread_affine` or checks
`_pump_running` directly" - and tests/simulation/test_step_lock_hold_across_backends.py
names the deployment shape outright: "a web UI serves `get_observation` / `send_action`
on worker threads". Reachable through a documented path: Isaac's `run_policy` (:5361,
`return super().run_policy(...)` at :5463) delegates to PolicyRunner.run, which calls
`sim.send_action(...)` per control step
(strands_robots/simulation/policy_runner.py:1748) with no guard, so the #1896 agent-on-
a-worker-thread shape marshals `reset` correctly and then steps kit from the worker. The
two AGENTS.md rules added in 90a6efc6..b0a8fcea (utf-8 on disk I/O, `errors="replace"`
on child streams) and the two new graders are unrelated; strands_robots/utils.py's
change does not touch this (its `positive_whole_number_error` guard ran fine in the
repro). TeleopMixin is mixed into the MuJoCo engine only, so the teleop-thread variant
of this does not apply to Isaac.

**Suggested fix**

Give `send_action`'s apply-and-step body the same thread contract as `step`: either wrap
it in `self._marshal_main_thread_affine("send_action", _impl)`, or - matching
set_joint_positions/#3270 for a surface whose contract is the envelope throughout -
return an error dict when `not self._on_main_thread() and not self._pump_running` and
route through `run_on_main` when a pump is engaged. Whichever is chosen, declare
`_main_tid` on the class (as #3270 did for `_pump_running`) because a dozen isaac test
modules call `send_action` on `__new__` skeletons that never seed it, and the guard
would otherwise `AttributeError` inside itself; while there, batch the substep loop with
`_STEPS_PER_BATCH` plus the world re-check so a large `n_substeps` stops holding the
lock for the whole count.

*Scope: upstream-main · verifier confidence: high*

---

## 3. `timestep-not-stored` — high

**What is wrong**

Substantively correct, with three refinements. (1) It is ONE defect with ONE fix site
and five stale readers, so the three findings that describe it should collapse:
create_world validates the effective dt and builds `World(physics_dt=dt)` but never
makes `dt` the engine's live dt, so `physics_timestep()` (simulation.py:4859) and all
four `_sim_time` accumulators (:2148, :5255, :5789, :6521) keep reading
`self._config.physics_dt`. (2) create_world's OWN report is right —
`world_info["physics_dt"]` (:1601) and the success text echo the override — so the
divergence is between create_world's report and every LATER report:
`physics_timestep()`, `get_state`'s `sim_time`, and each recorded frame's `sim_time`
(recording.py:626). Measured, `create_world(timestep=0.005)` on a default config then
`step(100)` reports t=0.8333 s for 0.5 s of physics (1.667x), and PolicyRunner at 20 Hz
derives 6 substeps where 10 are needed — each action gets 30 ms of physics instead of 50
ms, the same class of failure the physics_timestep override was added for in #1812. (3)
"ungraded" holds specifically on the override path: with `timestep=None` the config
value IS graded by create_world, but when an override is supplied only the argument is
graded, and `IsaacConfig.__post_init__` uses a bare `physics_dt <= 0` test — so
`IsaacConfig(physics_dt=nan)` plus `create_world(timestep=0.005)` returns success on a
healthy world and then reports nan sim time forever. The defect is entirely upstream
(`origin/main` b0a8fcea has the identical lines); our Isaac branches inherit it and add
no new instance.

**Evidence**

CODE (current tree, branch compose/rebased):
strands_robots/simulation/isaac/simulation.py:1434 resolves `effective_timestep`, :1436
grades it, :1516 `dt = timestep if timestep is not None else self._config.physics_dt`,
:1565 `World(physics_dt=dt)`. `dt` is never written back — no assignment to
`self._config` / `physics_dt` exists anywhere after `__init__` (`grep -n
"dataclasses.replace"` yields only :1037/:1070/:1090/:1092, all inside `__init__`). The
five readers that keep the stale config value: `physics_timestep()` :4859 (`return
float(self._config.physics_dt)`) and four `_sim_time` accumulators — :2148 (`step`),
:5255 (`send_action` substeps), :5789 (multi-robot lockstep, via `physics_dt` snapshot
taken at :5733), :6521 (camera warmup). `_sim_time` is what `get_state` reports (:2187)
and what every recorded frame carries
(strands_robots/simulation/isaac/recording.py:626). `IsaacConfig` is a plain mutable
`@dataclass` (config.py:197-274), so nothing prevents the write-back.  DEMONSTRATED
(venv /tmp/srenv, no GPU; driver at /tmp/demo_dt.py + /tmp/demo_dt2.py, reusing the
fake-`World` idiom from
tests/simulation/isaac/test_failed_create_world_clears_the_singleton.py; nothing in the
repo touched):   config.physics_dt before create_world : 0.008333 (1/120)
create_world(timestep=0.005) status   : success   World() was built with physics_dt
: 0.005   config.physics_dt AFTER create_world  : 0.008333   <-- override never lands
physics_timestep()                    : 0.008333   after step(100): world.step()
ticks=100, true simulated time 0.5 s,     _sim_time = 0.8333 s, get_state text "State:
t=0.8333s, step=100" (1.667x over)   substeps PolicyRunner derives at 20 Hz: 6   (the
world needs 10) Ungraded-value corollary, also measured:
`IsaacConfig(physics_dt=float("nan"))` constructs (config.py:316 is a bare `<= 0` test),
and with an override supplied create_world grades only the argument, so
`create_world(timestep=0.005)` returns success on a good world while
`physics_timestep()` -> nan and `_sim_time` -> nan after 10 usable steps ("State:
t=nans, step=10"). Control: with `IsaacConfig(physics_dt=0.005)` and no override,
physics_timestep()=0.005 and 100 steps give _sim_time=0.5 — the divergence needs the
override.  WHERE: pre-existing upstream. `git show
origin/main:strands_robots/simulation/isaac/simulation.py` has the identical shape — dt
local at main:1187, `World(physics_dt=dt)` at main:1193, `physics_timestep` at
main:3636, accumulators at main:1600/4023/4412/5061 — and `git diff origin/main --
.../isaac/simulation.py | grep -E "^[-+].*(effective_timestep|dt = timestep|def
physics_timestep|_sim_time \+=|_config.physics_dt)"` returns nothing: our 2083-line
addition to that file does not touch a single one of these lines.  NOT INTENDED: no test
pins it. The only Isaac `create_world(timestep=...)` tests are
test_failed_create_world_clears_the_singleton.py:196-201 (asserts the *World kwargs*,
and its module docstring line 20-22 complains about exactly this class of bug:
"world_info is built from the config and the arguments and never read back off the
world"); tests/simulation/isaac/test_delta_eef_controller.py:446-448 pins
physics_timestep() only from the constructor path.
tests/simulation/test_timestep_domain_across_surfaces.py's `_config.physics_dt`
assertions (:697, :705) are about the `default_timestep=` constructor shortcut, not the
override. No comment/docstring states the override is deliberately transient —
create_world's own docstring (:1356) says only "Override physics_dt from config", and
physics_timestep's docstring (:4852) asserts "Isaac's World steps at
IsaacConfig.physics_dt", which the override falsifies. Changelog fragments 2248-create-
world-timestep-domain-across-backends.md and 3290-isaac-legacy-timestep-domain.md cover
the *domain*, never the write-back. AGENTS.md:2225 cuts the other way, treating a
dropped dt as a bug: "dropping `defualt_timestep=0.001` left the physics integrating at
the 2 ms default under `status="success"`". MuJoCo/Newton have no such gap because their
`physics_timestep()` reads `self._world.timestep` (mujoco/simulation.py:809,
newton/simulation.py:1288), which `create_world` writes.  UPSTREAM-DRIFT CHECK: the
29-commit `strands_robots/utils.py` change is docs plus a count domain — `git diff
90a6efc6..b0a8fcea -- strands_robots/utils.py | grep -iE "def |timestep"` is empty, so
no shared helper this finding depends on moved. The new whole-tree graders in that range
(test_env_vars_the_package_reads_are_documented.py, test_on_disk_text_io_states_utf8.py,
test_shared_domain_family_counts_match_their_lists.py,
test_declared_*_count_has_one_owner.py) touch env-var docs, file-encoding literals and
shared-domain family counts — none constrains this fix.

**Suggested fix**

In create_world, after the effective dt is validated, make it the engine's live dt:
either `self._config = dataclasses.replace(self._config, physics_dt=float(dt))` (the
constructor already folds the legacy `default_timestep=` shortcut into the field exactly
this way at simulation.py:1070), or store `self._physics_dt = float(dt)` and have
`physics_timestep()` plus the four `_sim_time` accumulators read that instead of
`self._config.physics_dt`. Prefer reading it back off the live world
(`world.get_physics_context().get_physics_dt()` / `world.get_physics_dt()`) where
available, since the World singleton can keep an earlier call's dt. Additionally grade
`self._config.physics_dt` even when an override is supplied — or stop letting a nan
field construct — so an ungraded config dt cannot reach the clock through the override
path; pin with a test asserting `physics_timestep()` and `_sim_time` after
`create_world(timestep=X); step(n)` equal `X` and `n*X`.

*Scope: upstream-main · verifier confidence: high*

---

## 4. `add-robot-reports-requested-pos` — medium

**What is wrong**

Isaac's `add_robot` echoes the requested (or defaulted `[0, 0, 0]`) position back as the
robot's placement in both success payloads and never measures the articulation, so the
reported number can name a place the robot is not. On this backend the divergence is NOT
produced by a collision or terrain adjustment (Isaac refuses `terrain=` at :1388 and no
physics step runs inside `add_robot`); it is produced by the asset's own authored root
pose. Guaranteed case: when `position` is omitted or is the origin - the default, and
the shape of the common `add_robot("unitree_go2")` registry call -
`_load_usd_robot`/`_load_urdf_robot` skip `set_world_pose` altogether (:7736, :7962), so
a model authored standing lands at its authored height (Go2 base z=0.445, JVRC pelvis
z=1.4) and the result says `[0, 0, 0]`; the same engine's
`get_observation()["base_pos"]` then reports the real height. Additional case, likely
but not verifiable without Isaac Sim: for a non-zero position the write goes to the
reference-root prim, so any base-link offset inside the asset composes on top the same
way MuJoCo's root `pos` composes with the attach frame.

**Evidence**

CODE (working tree, compose/rebased): strands_robots/simulation/isaac/simulation.py:2497
sets `pos = [0.0, 0.0, 0.0] if position is None else position`, and both success
payloads echo it verbatim - :2651 (USD/MJCF branch, `"position": pos`) and :2729 (URDF
branch). Nothing between the loader call and the return reads a pose:
`articulation.get_world_pose()` appears at :4428 (get_observation's floating-base read),
:6422 (camera), :8753/:8882 (get_body_state) - never in add_robot. Worse, both loaders
SKIP the pose write when the position is the origin: :7736 (`_load_usd_robot`, comment
"The USD's authored pose is the default; only call set_world_pose when the caller
actually wanted a non-default placement") and :7962 (`_load_urdf_robot`, "Same skip-
origin shortcut"). So on the default call the robot keeps the asset's authored standing
height and the report says [0,0,0].  DEMONSTRATED (/tmp/demo_isaac_add_robot_pos.py,
/tmp/srenv; skeleton engine via IsaacSimulation.__new__ per
tests/simulation/isaac/test_mjcf_floating_base_is_recorded.py, legged MJCF whose root
body is authored at z=0.8 - the Go2/JVRC shape):   add_robot(position=None)         ->
json["position"]=[0.0,0.0,0.0]  base actually [0,0,0.8]  set_world_pose calls=0,
get_world_pose calls by add_robot=0; get_observation["base_pos"]=[0,0,0.8]
add_robot(position=[0,0,0])      -> same   add_robot(position=[0,0,0.4])    ->
json["position"]=[0.0,0.0,0.4]  base actually [0,0,1.2];
get_observation["base_pos"]=[0,0,1.2] i.e. the one engine reports two different
placements for the same robot, and the add_robot number is the one a fixed-base caller
has no second source for (base_* keys are emitted only for a free base, :4427).  THE
PROJECT ALREADY RULED ON THIS - the opposite way. MuJoCo's add_robot reports the
MEASURED root pose via `_describe_robot_placement`
(strands_robots/simulation/mujoco/simulation.py:2288-2314, docstring opens
"``add_robot`` used to echo the requested ``position`` back as the robot's placement...
that names a place the robot is not"), pinned by
tests/simulation/mujoco/test_add_robot_reports_the_placement_it_compiled.py ("30 of the
55 single-root robots in the built-in registry declare a non-zero root pos") and
documented for the whole world-building surface at docs/simulation/world-
building.md:129-132: "add_robot reports the *measured* world position of the robot's
root body and names the request and the model's offset beside it whenever they differ".
Same MJCF run through the MuJoCo backend in my script prints `Position: [0.0, 0.0, 1.2]
(position=[0.0, 0.0, 0.4] + model root offset [0.0, 0.0, 0.8])`. So not intended: no
Isaac test asserts the payload's "position" (grepped tests/simulation/isaac/), no
changelog.d fragment or docstring defends the echo, and the shared doc promises the
measured value.  PROVENANCE: `git show origin/main:...isaac/simulation.py` has the same
echo at its lines 1945 and 2010 and the same skip-origin guards at 6040/6264 ->
upstream. Our branch keeps both, adds a third echo site (the MJCF-derived `payload` dict
at :2651), and materially widens the blast radius: upstream's registry-name path created
no prims at all, whereas our MJCF->USD path now really loads the 64 registry MJCF robots
- exactly the corpus with non-zero authored root offsets. Hence where=both.  UPSTREAM
MOVEMENT DOES NOT TOUCH IT: `git diff 90a6efc6..b0a8fcea -- strands_robots/utils.py` is
docstring-only around the numeric domains; `coerce_pose_vector`
(strands_robots/utils.py:2311) still returns (list[float]|None, err|None) with None
meaning "omitted", which is what :2497 relies on. The two new AGENTS.md rules are UTF-8
on-disk text IO and `errors="replace"` on child streams; the new whole-tree graders are
the matching ones - none bear on placement reporting.

**Suggested fix**

Mirror MuJoCo's `_describe_robot_placement`: after the loader returns, best-effort
`articulation.get_world_pose()[0]` (the read already used at :4428) and report THAT as
`payload["position"]`, naming the request and the offset beside it in the text whenever
they differ; when the articulation is None or the read raises, keep the request but say
it is the requested placement rather than a measurement. Reporting measured also makes
the skip-origin shortcut honest, so that optimisation can stay.

*Scope: both · verifier confidence: high*

---

## 5. `converge-render-clock` — medium

**What is wrong**

Precise version, in three parts:  1) TRUE and upstream: `_converge_render`
(simulation.py:9144-9159) calls `self._world.step(render=True)` n times, which advances
PhysX by n * physics_dt while `_sim_time` and `_step_count` stay frozen. Reached on the
default idle-preview path (`pump` -> `_converge_render(_idle_converge=4)`, once per
`_idle_render_period=1.0` s), so reported `sim_time`/`step_count` understate the physics
that actually ran by ~4 s per idle minute. Byte-identical to origin/main apart from a
lock snapshot, and undocumented anywhere.  2) TRUE and ours: the latched wrench is not
replayed on those ticks, so a latched force is absent while gravity still acts - a
partial integration, not a paused one (demonstrated: cube z-velocity -0.654 instead of
+0.679 over 4 ticks under a 20 N +z latch).  3) The claim's framing needs correcting on
two points. (a) The comment that "says it advances no time" is at
simulation.py:5249-5251 (mirrored in changelog.d/3262:75-80 and the test docstring at
test_apply_force_and_raycast.py:371, 425-426), and it is only true of the `_sim_time`
counter, not of physics; its real error is the label "render-only pump", which the
helper's own docstring at :9126 contradicts. (b) The wrench exclusion is NOT an
undocumented oversight - it is stated, reasoned ("or a latch would act on ticks the
clock never saw") and pinned by an AST grader, so any fix must not simply add
`_reapply_wrenches` to `_converge_render` or that grader fails. The residual defect is
that the exclusion is reasoned from a false premise: excluding the latch does not stop
the unclocked physics, it only makes those ticks force-free. The same mislabel applies
to `_refresh_all_render_products` on its `world.step(render=True)` fallback path
(:9120-9121), though its primary `app.update()` path really is render-only.

**Evidence**

Reproduced on the current tree (branch `compose/rebased`, HEAD 31aec6f1, upstream
b0a8fcea merged in).  CODE FACTS - /Users/ruicard/projects/new-strands/strands-
robots/strands_robots/simulation/isaac/simulation.py:9144-9159 - `_converge_render`
loops `max(1,n)` times and ends each iteration with `self._world.step(render=True)`. No
`_sim_time` / `_step_count` increment, no `_reapply_wrenches`. - Same file:9126 - the
helper's OWN docstring states "``world.step(render=True)`` advances physics every tick,
so a kinematic arm keeps drifting (gravity / settling)". :9102 says the render-only
alternative is `SimulationApp.update()` which "does NOT advance physics". So inside this
module `world.step(render=True)` unambiguously advances physics. - Same file:5245-5251
(ours) - "Every tick that advances ``_sim_time`` replays; a render-only pump
(``_converge_render``, ``_refresh_all_render_products``) does not, because it advances
no time." Calling `_converge_render` a "render-only pump" that "advances no time"
contradicts :9126. - Contrast the clocked shape at :2145-2149 and :5252-5256: replay,
`world.step`, `_sim_time += physics_dt`, `_step_count += 1`. - Reach: :8097 `pump()`
calls `_converge_render(self._idle_converge)`; `_idle_converge` default 4 (:1220),
`_idle_render_period` default 1.0 s (:1226), and `run_pump_forever` (:8193-8199) renders
on that period. So ~1 min of idle preview runs ~240 physics ticks (~4.0 s at physics_dt
1/60) that reported `sim_time` (:2187, :1617) never counts.  DEMONSTRATION (skeleton
engine via `IsaacSimulation.__new__`, /tmp/srenv, fake world modelling PhysX's one-tick
force contract): `_converge_render(4)` with `_applied_wrenches = {"cube": force
[0,0,20]}` -> physics ticks 0->4, `_sim_time` 0.0->0.0, `_step_count` 0->0,
`_reapply_wrenches` 0 calls, cube z-velocity 0.0 -> -0.654 (gravity only). The same 4
ticks in `step()`'s clocked shape -> `_sim_time` 0.06667, `_step_count` 4, 4 replays,
z-velocity +0.6793. Gravity acts on those ticks; the latch does not.  WHERE - `git show
origin/main:strands_robots/simulation/isaac/simulation.py` has `_converge_render` at
line 7314; an AST diff of the function shows the ONLY worktree change is the `with
self._lock: robots_snapshot = ...` registry snapshot. The physics-off-the-clock body is
upstream verbatim. - The "advances no time" comment, `_reapply_wrenches`, and the
exclusion are ours only (absent from the origin/main file).  INTENDED? - The exclusion
IS stated and pinned: changelog.d/3262-isaac-apply-force-and-raycast.md:75-80 and
tests/simulation/isaac/test_apply_force_and_raycast.py:367-428, whose
`test_a_render_only_pump_does_not_replay` derives from the AST that a method containing
`_world.step` but not `_sim_time` must NOT contain `_reapply_wrenches`. An AST scan of
both modules gives: step/_step_impl/send_action/run_multi_policy/_apply_all_and_step/_wa
rmup_camera/_primitive_tick = advances+replays; `_converge_render` and
`_refresh_all_render_products` = neither. - But the stated justification's premise is
false: it asserts these helpers advance no time / are render-only, when
`_converge_render` unconditionally steps physics. Nothing documents "physics advances
here while the clock is frozen and the latch is absent" as a deliberate accepted state -
`git grep converge_render origin/main -- docs changelog.d AGENTS.md README.md` returns
nothing, and the two AGENTS.md rules added in 90a6efc6..b0a8fcea are about text
encodings, unrelated. `strands_robots/utils.py`'s change and the new whole-tree graders
do not touch this.

**Suggested fix**

Make the helper live up to its label: drive the DLSS convergence ticks with the render-
only surface `_refresh_all_render_products` already prefers (`SimulationApp.update()`,
falling back to `world.render()` rather than `world.step`), so no physics advances,
"advances no time" becomes true, and both the clock desync and the latch question
disappear - the pose re-assert loop then also stops fighting drift it caused itself. If
a physics tick turns out to be required for the re-asserted pose to reach the renderer
(needs GPU verification), the alternative is to treat these as ordinary ticks: replay
the latch and increment `_sim_time`/`_step_count`, which also satisfies the AST grader
(a method that advances and replays is legal) - but that makes reported `sim_time`
depend on preview cadence, so prefer the render-only route. Either way, correct
simulation.py:5249-5251, changelog.d/3262-isaac-apply-force-and-raycast.md:75-80 and the
test docstrings at tests/simulation/isaac/test_apply_force_and_raycast.py:371/425-426 so
they no longer call a physics-stepping helper "render-only".

*Scope: both · verifier confidence: high*

---

## 6. `describe-add-camera-order` — medium

**What is wrong**

The claim holds, with two refinements. (1) The mismatch is exactly a rotation of the
4th-6th parameters: describe() advertises width, height, fov where the method declares
fov, width, height - the first three (name, position, target) and their defaults are
correct, and describe()'s `name='default'` correctly reflects Isaac's optional-name
signature (MuJoCo/Newton require name). (2) describe() additionally omits `parent_body`,
which the method does accept and answers with a structured "not supported on the Isaac
backend" error (:6691); the docstring at :6631-6639 argues a caller following
/policies/camera-naming must be told which backend mounts a wrist cam, so the omission
suppresses precisely the discovery signal that text calls for. The wrong side is
describe(), not the signature: the signature's fov-before-width/height order is
documented at :6614-6616 as deliberate cross-backend positional parity and matches
MuJoCo (:3936-3944) and Newton (:1364-1372). Impact is confined to positional callers -
keyword calls are unaffected - and is loud-but-misleading for typical resolutions
(width>=180 trips the fov interval guard) yet fully silent for small square resolutions
(width<180 is accepted as a field of view).

**Evidence**

DESCRIBE STRING (working tree, compose/rebased @ 31aec6f1):
strands_robots/simulation/isaac/simulation.py:9226-9230 advertises "(name='default',
position=None, target=None, width=None, height=None, fov=60.0) -> dict  # register an
RTX camera ...".  ACTUAL SIGNATURE:
strands_robots/simulation/isaac/simulation.py:6571-6579 -> (self, name='default',
position=None, target=None, fov=60.0, width=None, height=None, parent_body=None).
Verified by introspection, not by eye: on a skeleton engine (IsaacSimulation.__new__ +
hand-seeded _cameras/_world_created/_lock/_robots/_objects), describe() returns the
string above while inspect.signature(IsaacSimulation.add_camera) yields
['name','position','target','fov','width','height','parent_body'] -> advertised order !=
real order (differs from position 4 on), and 'parent_body' is advertised nowhere.
DEMONSTRATED CONSEQUENCE: sig.bind(eng, "cam", [1,2,3], [0,0,0], 640, 480, 60.0) - i.e.
exactly the describe()-advertised order - binds {'fov': 640, 'width': 480, 'height':
60.0}. The shared guards then make this mis-bind either loud-but-misleading or silent:
camera_fov_error("add_camera","fov",640) -> "'fov' must be in the open interval (0, 180)
degrees, got 640." (a complaint about fov for a caller who never passed an fov), while
width values below 180 pass silently - camera_fov_error(...,128) -> None and
positive_count_error(128,"width","add_camera") -> None, so add_camera("wrist", pos, tgt,
128, 128) builds a 128-DEGREE lens at the IsaacConfig default resolution with no error
at all.  NOT INTENDED: the docstring at
strands_robots/simulation/isaac/simulation.py:6614-6616 states the signature order is
the deliberate side - "fov : float / Horizontal field of view in degrees. Default 60.0.
Declared in the same position as on the MuJoCo and Newton backends, so a positional call
is read the same way on all three." describe() contradicts that sentence. No test pins
the string (no tests/*.py matches 'methods' dict or a describe/add_camera signature
grader; the three isaac tests calling describe() - test_motion_primitives.py,
test_move_to_ik.py, test_dataset_recording.py - assert on other keys), no changelog.d/
fragment covers it, and AGENTS.md has no rule endorsing an abbreviated describe() order
(its nearest rule, line 1840 "Forward all advertised kwargs", cuts the other way).
Newton's describe() already gets it right -
strands_robots/simulation/newton/simulation.py:2496 advertises "(name: str,
position=None, target=None, fov=60.0, width=640, height=480, parent_body=None)" matching
its signature at :1364-1372.  WHERE: upstream. `git show
origin/main:.../isaac/simulation.py` carries the identical broken string at :7408-7412
and the identical correct signature at :5111-5119; `git diff origin/main --
strands_robots/simulation/isaac/simulation.py | grep -c 'add_camera"'` = 0, so our
branches never touched it. `git log -L 9226,9231` attributes it to upstream commit
aa3cfe01 (feat(sim/isaac): IsaacRecordingMixin, PR #1552), and `git merge-base --is-
ancestor aa3cfe01 origin/main` confirms it is upstream.  UPSTREAM MOVEMENT DOES NOT
INVALIDATE: strands_robots/utils.py's changed helpers are the guards that make the mis-
bind reachable (camera_fov_error at utils.py:2711, positive_count_error at
utils.py:1060) and both still behave as measured above; the 14 new whole-tree graders in
90a6efc6..b0a8fcea (test_merge_blockers.py,
test_env_vars_the_package_reads_are_documented.py,
test_shared_domain_family_counts_match_their_lists.py, etc.) none grade describe()
advertised signatures.

**Suggested fix**

Rewrite the describe() entry at strands_robots/simulation/isaac/simulation.py:9226-9230
to mirror the real signature, following Newton's already-correct wording at
newton/simulation.py:2496: "(name='default', position=None, target=None, fov=60.0,
width=None, height=None, parent_body=None) -> dict  # register an RTX camera (rendered
frames ride get_observation and recordings); parent_body is refused on this backend -
use MuJoCo/Newton for a mounted wrist cam". Since nothing currently grades this, pair it
with a whole-tree grader that parses each describe()["methods"] signature string and
asserts its parameter names and order are a prefix of inspect.signature of the same-
named method on every SimEngine backend - that closes the class rather than this one
instance.

*Scope: upstream-main · verifier confidence: high*

---

## 7. `destroy-discards-camera-recording` — medium

**What is wrong**

destroy() drops a running camera recording (simulation.py:1791) with no warning, six
lines above a dataset-recording sibling that warns for the identical situation and
documents why ("so the data loss is visible"). Two refinements to the original wording:
(a) the gap is six lines, not three; (b) the loss is not merely invisible, it is
avoidable — the comment's premise that the buffers "reference RTX frames that are
meaningless after the stage tears down" is false, since on_frame stores plain host-side
uint8 numpy copies, and encode_clip successfully wrote an mp4 from the discarded buffers
after destroy(). The follow-up stop_cameras_recording() returns status="success" with
"Was not recording cameras.", so the caller gets a clean success envelope and cannot
distinguish "nothing to flush" from "your clip was thrown away".

**Evidence**

Reproduced on the current tree (branch compose/rebased, HEAD 31aec6f1, merged onto
b0a8fcea).  Code: strands_robots/simulation/isaac/simulation.py:1789-1803 —
`self._cams_rec_state = None` at :1791 under the comment "Drop any in-flight recorder
state (buffers reference RTX frames that are meaningless after the stage tears down)",
with no guard and no log; the dataset sibling at :1797-1802 logs a WARNING for the same
situation and its comment at :1796 states the project's value outright ("warn when a
session was still open so the data loss is visible"). stop_cameras_recording at
:7153-7156 returns `{"status": "success", ... "Was not recording cameras."}` once the
handle is gone.  Demonstrated (/tmp/demo_destroy_cams.py, skeleton engine via
IsaacSimulation.__new__ in /tmp/srenv, MUJOCO_GL=cgl): with a running `_cams_rec_state`
holding 60 captured frames AND an open dataset session, destroy() logged exactly one
warning — the dataset one — then `_cams_rec_state is None`, 60 frames gone, and
stop_cameras_recording() returned status=success "Was not recording cameras.".  The
stated justification is factually wrong: on_frame stores host-side copies
(`np.ascontiguousarray(arr[..., :3].astype(np.uint8))`, simulation.py:7106), nothing
stage-bound. Holding a reference to the discarded buffers and calling `encode_clip(held,
..., fps=30)` after destroy() wrote a valid 3344-byte mp4 — the frames destroy() threw
away were still fully flushable.  where=upstream-main: `git show
origin/main:strands_robots/simulation/isaac/simulation.py` carries the identical block
at lines 1353-1367; a diff of destroy() upstream-vs-worktree shows our branch only
appends the per-world registry clears after :1803 and does not touch this line.  Not
intended: no test pins the silence
(tests/simulation/isaac/test_destroy_clears_the_state_that_outlives_a_world.py and
test_dataset_recording.py:180 assert only that state is cleared, no caplog on this
path); changelog.d/3273-... covers the added registry clears only; nothing in AGENTS.md
endorses it, and two rules cut the other way ("Schema-only tests miss silent data loss",
AGENTS.md:1850; "Silent drops are bugs masquerading as features", :2225). The MuJoCo
sibling is explicit that deregistering without flushing "discarded exactly the frames
that message promised were still available" (mujoco/rendering.py:2540-2554). Reachable
path: `with IsaacSimulation(...)` → __exit__ → cleanup() (:9296) → destroy().

**Suggested fix**

Mirror the dataset sibling at simulation.py:1792-1803: before nulling, check `if (st :=
self._cams_rec_state) and st.get("running")`. Because the buffers are host memory,
prefer flushing — set `running = False` and run the same encode path
stop_cameras_recording uses so the mp4 lands — and log a WARNING naming the tag, cameras
and frame counts either way; at minimum warn ("destroy() called while a camera recording
was active; N buffered frames for <cameras> are discarded. Call stop_cameras_recording()
first."). Keep it inside the existing lock and guard with getattr so the
__del__/skeleton-engine path cannot raise, and correct the misleading comment at
:1789-1790.

*Scope: upstream-main · verifier confidence: high*

---

## 8. `fov-horizontal` — medium

**What is wrong**

The claim holds, with three refinements. (1) Isaac reads fov as horizontal because it
derives the focal length from the camera's *horizontal* aperture (`focal = h_aperture /
(2*tan(fov/2))`), which by USD's definition makes hFOV == fov; MuJoCo reads it as
vertical via MJCF `fovy` (vertical because the injected camera declares no `sensorsize`)
and Newton reads it as vertical by docstring and by `fy = 0.5*h/tan(fov/2)`. (2) The
divergence is not a fixed offset but scales with aspect ratio: it vanishes for a square
image, and its *direction* flips — at 640x480 Isaac is 33% zoomed in (vFOV 46.83 vs
60.00 deg, fx 554.26 vs 415.69 px), while for a portrait camera (h > w) Isaac is
correspondingly wider vertically. (3) "Silently" is right about the cross-backend
contract but not about Isaac's own docstring: Isaac does say "Horizontal field of view
in degrees" at simulation.py:6614. That is a description of the implementation, not a
documented rationale for diverging — the same docstring claims all three backends read
the call the same way, and the shared validator Isaac delegates its fov domain to
(strands_robots/utils.py:2714) documents the parameter as vertical. So it is disclosed
in one place and contradicted in two, which is why intended=false rather than a
documented-and-reasoned choice.

**Evidence**

Reproduced end-to-end on the current tree (venv /tmp/srenv, MUJOCO_GL=cgl, script
/tmp/fov_demo.py): a skeleton IsaacSimulation.__new__ engine with a stub
`isaacsim.sensors.camera.Camera` (returning the USD-default 20.955 mm horizontal
aperture) driven through the real public `add_camera(name="cam", position=[2,2,2],
target=None, fov=60.0, width=640, height=480)` returns `status=success` with
`json.focal_length_mm = 18.147562336302915`. By USD's own definition (hFOV =
2*atan(hAperture/(2*focal))) that is hFOV = 60.00 deg exactly, fx = 554.26 px, vFOV =
46.83 deg. The live MuJoCo backend in the same run (`MuJoCoSimEngine.create_world` +
`add_camera(..., fov=60.0, 640, 480)` + `get_camera_params`) returns K with fx = fy =
415.69 px, i.e. vFOV = 60.00 deg / hFOV = 75.18 deg. Newton's own formula
(strands_robots/simulation/newton/simulation.py:1799 `fy = 0.5 * h /
tan(radians(fov)/2)`) gives the identical 415.69 px. Same call, same pixels requested:
fx differs by exactly the aspect ratio, 554.26/415.69 = 1.3333.  Code paths: Isaac
strands_robots/simulation/isaac/simulation.py:6613-6619 ("fov : float / Horizontal field
of view in degrees") and :7272-7290 (comment "Map FOV (deg, horizontal) to focal
length"; `focal_length_mm = horizontal_aperture_mm / (2.0 *
math.tan(math.radians(fov_deg) / 2.0))`, with the comment at :7283 stating the intent
"fx = width / (2*tan(fov/2))"). MuJoCo
strands_robots/simulation/mujoco/simulation.py:4115 passes `fov=fov` into the spec
builder, which writes it as MJCF `fovy`
(strands_robots/simulation/mujoco/spec_builder.py:845 `"fovy": float(cam.fov)`) —
vertical, since the injected camera declares no `sensorsize`; its intrinsics path
confirms it (strands_robots/simulation/mujoco/rendering.py:1614-1615 `fy =
0.5*h/tan(deg2rad(fovy)/2)`, `fx = fy`). Newton
strands_robots/simulation/newton/simulation.py:1425 ("fov: Vertical field of view in
degrees"), :1702, :1771, :1799.  Which convention the docs/shared contract state:
`add_camera` is on no ABC (AGENTS.md rule 19, lines 235-258, says so explicitly), so the
only shared statement is the validator all three delegate to —
strands_robots/utils.py:2714: "A camera's **vertical** field of view must be a finite
angle in the open interval (0, 180) degrees". Repo-wide grep for "(horizontal|vertical)
field of view|FOV" finds exactly one horizontal claim (Isaac's docstring) against five
vertical ones (utils.py:2714, newton:1425/1702/1771, mujoco/rendering.py). No doc page
states an axis at all (docs/simulation/isaac.md:411-413 claims only that the accepted
*input domain* matches across backends, not the meaning).  Not intended: no test pins
the axis or the focal-length value.
tests/simulation/isaac/test_add_camera_numeric_validation.py only pins refusals (fov=0 /
180 / nan). tests/simulation/test_backend_shared_parameter_order.py pins parameter
*order* and the docs pages, and its "TestOnePositionalCallMeansOneThingEverywhere" name
notwithstanding it compares only `inspect.signature(...).bind` arguments, never
semantics. There is no changelog.d fragment for a horizontal reading;
changelog.d/2781-backend-shared-parameter-order.md and AGENTS.md rule 19 argue the
opposite way ("the caller found out from the pixels" is this exact failure class).
Isaac's docstring even asserts parity two lines below the divergence: ":6614-6616
Declared in the same position as on the MuJoCo and Newton backends, so a positional call
is read the same way on all three."  Upstream, not ours: `git show
origin/main:strands_robots/simulation/isaac/simulation.py` carries the identical text at
lines 5154-5158 and the identical formula at 5829; `git diff origin/main --
strands_robots/simulation/isaac/simulation.py | grep '^[-+].*fov'` is empty, so our
2083-line diff on that file touches no fov line. New utils.py work did not disturb it:
camera_fov_error is a domain guard only (returns None for any fov in (0,180)) and its
docstring already said "vertical" — that wording is now the shared contract Isaac
contradicts.

**Suggested fix**

In `_create_camera_prim`, scale the derived focal length by the aspect ratio so the
value is read as the vertical FOV like the siblings: `focal_length_mm =
horizontal_aperture_mm * (0.5 * height) / (width * tan(radians(fov_deg)/2))` (i.e. the
current expression times `height/width` — 18.1476 -> 13.6107 mm at 640x480, giving fx =
fy = 415.69 px and vFOV = 60 deg, matching the measured MuJoCo/Newton value), and change
the docstring at :6613-6619 plus the comments at :7272-7283 from horizontal to vertical,
citing `camera_fov_error`'s wording. Worth pinning with a cross-backend grader that
compares the *derived intrinsics* at a non-square resolution, since the existing order
grader only binds signatures. Adjacent agent-visible surface to fix in the same change:
`IsaacSimulation.describe()` at simulation.py:9226-9229 still advertises the pre-fix
order `add_camera(name, position, target, width, height, fov)`, which the order grader
does not cover (upstream too, at origin/main:7409-7410).

*Scope: upstream-main · verifier confidence: high*

---

## 9. `physics-dt-order-comparison` — medium

**What is wrong**

`IsaacConfig.__post_init__` (config.py:315-321) grades both dt fields with a bare `if
self.<field> <= 0: raise` instead of a shared domain, so `nan` (`nan <= 0` is False),
`inf`, `True` and `10**400` are all accepted and stored, while `str`/`None` raise a bare
`TypeError` out of the comparison naming neither the field nor a remedy. Two refinements
to the original claim: (a) only `True` slips through of the two booleans — `False` is
refused as `0`, and `10**400` and the `TypeError` shapes were omitted; (b) physics_dt
does NOT reach the engine ungraded — `create_world` grades the effective dt on
`SimEngine._validate_timestep` (simulation.py:1436), as does the legacy
`default_timestep` spelling (simulation.py:1067), so for physics_dt the defect is a
divergence between two owners of one field: construction accepts a value the world
builder then refuses, and the failure is deferred from the call that got it wrong to a
later one. `rendering_dt` is the genuinely ungraded half — it occurs exactly twice in
`IsaacSimulation`, forwarded to `World(rendering_dt=...)` (simulation.py:1566) and
echoed into the `create_world` success payload (simulation.py:1602), with no guard on
either path, so a `nan` rendering timestep is both installed in the world and reported
back under `status="success"`.

**Evidence**

GUARD IS PRESENT AND UPSTREAM. `strands_robots/simulation/isaac/config.py:315-321` holds
the two bare comparisons verbatim. `git show origin/main:.../config.py` has them
identically at lines 318-324, and `git show 90a6efc6:.../config.py` at 319/323 —
unchanged across the whole 29-commit range. `git diff origin/main -- .../config.py` is a
3-line deletion (the `enable_rtx_sensors` field only), so none of this is ours.
DEMONSTRATED (venv /tmp/srenv, `IsaacConfig(**{field: val})` for both fields): ACCEPTED
`nan` (stored nan), `inf`, `True`, and `10**400`; refused `False`, `0`, `-1`, `-inf`;
`'1/120'` and `None` raise `TypeError: '<=' not supported between instances of 'str' and
'int'` — out of the comparison itself, naming neither field nor remedy.  PHYSICS_DT HAS
A BACKSTOP (the claim's one inaccuracy). Driven on a skeleton (`IsaacSimulation.__new__`
+ hand-seeded `_config`): `IsaacConfig(physics_dt=nan)` constructs, then
`create_world()` returns `{"status": "error"}` → "create_world: physics_dt must be a
finite positive number, got nan." — `simulation.py:1436` grades the effective dt on
`SimEngine._validate_timestep` (`simulation/base.py:2151`), and `simulation.py:1067`
grades the legacy `default_timestep` spelling on the same domain.  RENDERING_DT HAS
NONE. `rendering_dt` occurs exactly twice in `IsaacSimulation` (measured via
`inspect.getsource` + regex): forwarded to `World(rendering_dt=...)` at
`simulation.py:1566`, and echoed into the `create_world` success snapshot at
`simulation.py:1602`. No grading anywhere.  NOT INTENDED, BUT PINNED.
`changelog.d/2248-create-world-timestep-domain-across-backends.md` names this exact gap
as a liability: "`IsaacConfig.__post_init__` tests `physics_dt <= 0` - a bare
comparison, so `IsaacConfig(physics_dt=float("nan"))` constructs and `create_world()` is
the only thing between it and a world built on a dt no integrator can advance by." Same
framing at `tests/simulation/test_timestep_domain_across_surfaces.py:60-71` and in class
`TestTheConfigGuardCannotSeeEveryUnusableDefault` (line 483-493). That is a documented
weakness with no reason offered for keeping it — but
`test_isaac_config_admits_a_default_create_world_then_refuses` (line 495-507) does
assert `IsaacConfig(physics_dt=nan/inf/True)` constructs, so a fix breaks it.  NEW
UPSTREAM MATERIAL DOES NOT INVALIDATE. The two new AGENTS.md rules (`git diff
90a6efc6..origin/main -- AGENTS.md`) are about text-IO encoding and child-stream
decoding — unrelated. The new grader
`tests/test_shared_domain_family_counts_match_their_lists.py` only checks docstrings
matching `for <count> families`; `positive_finite_number_error.__doc__` states no family
count and has zero top-level `* ` bullets (measured), so adding a call site does not
trip it. `tests/simulation/isaac/test_isaac_backend.py:149-160` matches only on the
field name, so both candidate fixes keep it green. Ran `pytest
tests/test_shared_domain_family_counts_match_their_lists.py
tests/simulation/isaac/test_isaac_backend.py -k "dt or family or count"` → 7 passed.

**Suggested fix**

Grade both fields in `__post_init__` on `SimEngine._validate_timestep`
(simulation/base.py:2151) — the domain `create_world` already applies to this exact
field — raising `err["content"][0]["text"]` as `ValueError`, exactly the precedent
`IsaacSimulation.__init__` sets at simulation.py:1067-1069 for the legacy spelling, so
the two owners of one dt reach one verdict. `positive_finite_number_error`
(utils.py:689) is the alternative; its message form is current and verified
("IsaacConfig: physics_dt must be > 0, got nan.") and it additionally catches `10**400`,
which `_validate_timestep` lets raise `OverflowError` (measured) — but it is not the
domain the world builder applies, so it would leave a narrower residual divergence.
Either keeps the two floor tests at tests/simulation/isaac/test_isaac_backend.py:149-160
green. The fix must also rewrite
`tests/simulation/test_timestep_domain_across_surfaces.py:495-507` plus the class and
module docstrings at lines 60-71 and 483-493, which assert the config constructs on
nan/inf/True; their "load-bearing rather than defensive" rationale for create_world's
check survives on Newton alone, whose `__init__` still stores `default_timestep` raw.

*Scope: upstream-main · verifier confidence: high*

---

## 10. `posture-flags-truthy` — medium

**What is wrong**

Accurate, with three refinements. (a) The "reports the caller's spelling while writing
the opposite" half is specific to set_object_kinematic (simulation.py:8682, :8699),
which interpolates the raw flag; set_object_collision renders its report from the same
truthiness (:8725, :8736), so its message agrees with the write and disagrees only with
what the caller asked for. (b) The inversion is not limited to truthy opt-out spellings:
falsy non-booleans (None, 0.0, [], "") take the dynamic / collider-off branch without
ever being a declared spelling of it, which is the other half of the AGENTS.md rule. (c)
Reachability is direct/agent callers of these public envelope-returning methods only —
no in-repo config, CLI or tool path feeds them a string, and both in-repo callers
(examples/so101_curobo/collector.py:453 and :470) pass a real bool — so this is a
public-surface domain hole rather than a live mis-posture on an existing code path,
which caps the practical severity at medium.

**Evidence**

Reproduces byte-for-byte on the current tree. (1) The code:
strands_robots/simulation/isaac/simulation.py:8681 `fn(bool(kinematic))`, :8682 reports
`f"'{name}' kinematic={kinematic}."` (raw flag), :8696 `attr.Set(bool(kinematic))` with
the same raw interpolation at :8699; strands_robots/simulation/isaac/simulation.py:8724
`obj.handle.set_collision_enabled(bool(enabled))`, :8725/:8736 `'on' if enabled else
'off'`. Neither method calls boolean_flag_error. (2) Demonstrated on a skeleton engine
(IsaacSimulation.__new__ + hand-seeded _objects with a recording handle, /tmp/srenv):
kinematic='false'/'no'/'off'/'0' -> status=success, handle received True, message
`'crate' kinematic=false.` — the report states the caller's spelling while the write is
the opposite posture; the same spellings on set_object_collision -> handle received
True, message `'crate' collision on.` (report agrees with the write, contradicts the
request). Falsy non-booleans (None, 0.0, []) silently take the dynamic / collider-off
branch. boolean_flag_error refuses all eight values I tried. (3) The helper is unchanged
by the upstream +92/-27: AST source-segment sha256 of boolean_flag_error is 4ee3f35ed53f
and is_boolean d260c42a5ff7 at 90a6efc6, b0a8fcea and HEAD alike
(strands_robots/utils.py:3038, :3087 `if is_boolean(value)`); the upstream diff touches
only positive_count_error / non_negative_count_error / declared_count /
validation_split_error. (4) `where`: both method bodies are byte-identical (hashes
eaa4b0467f92 and 8ad123c58ef1) at 90a6efc6, origin/main and the working tree — upstream
code our branch merely carries, only relocated 6889->8655. (5) Not intended:
AGENTS.md:2016-2085 ("Posture flags are checked, never read by truthiness") mandates the
opposite, and the same file already obeys it at simulation.py:2458 for add_robot's
`fix_base` (and :4758 for raycast's `include_static`). No test pins the behaviour — the
only test callers are
tests/simulation/test_unhashable_entity_name_is_reported.py:358-359, both passing True —
no changelog.d fragment mentions it, and neither posture-flag grader lists these methods
or exempts them. The two new upstream graders
(tests/test_on_disk_text_io_states_utf8.py,
tests/test_child_stream_decode_substitutes.py) and the two new AGENTS.md rules
(AGENTS.md:2256-2258) are about text encoding and child-process stream decoding —
unrelated.

**Suggested fix**

In each method, after the registry_entry miss check and before any write, add the guard
the same file already uses for fix_base: `if (err := boolean_flag_error(kinematic,
"kinematic", "set_object_kinematic")) is not None: return {"status": "error", "content":
[{"text": err}]}` (and `enabled`/"set_object_collision"), then normalise once with
`kinematic = bool(kinematic)` so both the wrapper path and the USD fallback report the
checked boolean rather than the caller's spelling. boolean_flag_error is already
imported at simulation.py:53, and no existing test passes a non-boolean, so nothing
regresses.

*Scope: upstream-main · verifier confidence: high*

---

## 11. `headless-not-flag-domain` — low

**What is wrong**

The claim holds but understates the defect on two axes. (a) The disagreement is not
limited to spellings `STRANDS_ISAAC_HEADLESS` refuses: the four off-spellings it
*accepts and resolves to False* (`0`/`false`/`no`/`off`) actively invert through the
kwarg door — env `off` yields `headless=False` (windowed) while `headless="off"` is read
as True (headless) — so two doors to one field give opposite answers on a vocabulary
both understand. The falsy non-bools (`0`, `None`, `""`, `[]`) invert the other way,
launching a window on a display-less runner, which is the outcome `_env_switch`'s own
docstring says the variable exists to prevent. (b) The value is not merely "read by
truthiness": it is forwarded unnormalized into the SimulationApp launch dict
(simulation.py:618) and echoed raw into the `"headless"` key of the `create_world()` and
`get_state()` JSON payloads, where a `nan` renders as the invalid JSON token `NaN` —
while the sibling `ground_plane` echo one line away is `bool(...)`-coerced. Also worth
scoping: `headless` is one of three ungraded `bool` fields in this dataclass.
`ground_plane` is the same defect (read by truthiness at simulation.py:1576, and
`create_world`'s own `ground_plane: bool = True` argument at simulation.py:1344 is
ungraded too, the exact facade/forwardee asymmetry AGENTS.md:2050-2062 names); `verbose`
has no consumer in the backend at all, so it is cosmetic. Severity low is right for
`headless` alone, but the honest unit of fix is the dataclass's flag fields, not one
field.

**Evidence**

REPRODUCED on the current tree (compose/rebased, HEAD 31aec6f1).
`IsaacConfig.__post_init__` (/Users/ruicard/projects/new-strands/strands-
robots/strands_robots/simulation/isaac/config.py:317-372) grades `render_mode`,
`device`, `num_envs`, `physics_dt`, `rendering_dt`, `camera_width`, `camera_height` and
`stage_path`, and grades none of the three `bool` fields (`headless` config.py:275,
`ground_plane` :278, `verbose` :281). `strands_robots.utils.boolean_flag_error`
(utils.py:3038) is the shared domain for exactly this shape and is never called from
this module (`grep boolean_flag_error strands_robots/simulation/isaac/` hits only
simulation.py:2458 `fix_base` and :4758 `include_static`).  Measured in /tmp/srenv
against the working tree:   ENV  STRANDS_ISAAC_HEADLESS=maybe -> ValueError (refused by
`_env_switch`, config.py:39-89)   kwarg headless='maybe' -> stored 'maybe', truthiness
True, boolean_flag_error would refuse   Same silent acceptance for
'false','off','0','no','' , None, 0, 1, 2.7, [], nan.   The two doors disagree on a
vocabulary BOTH understand:     ENV   STRANDS_ISAAC_HEADLESS=off -> headless is False
(windowed)     kwarg headless='off'             -> headless == 'off', read as True
(headless)  The unvalidated value is spent, not just stored. simulation.py:1503 passes
`headless=self._config.headless` into `_create_simulation_app`, which does
`merged["headless"] = headless` (simulation.py:618) with no normalization, so the
string/None/nan reaches SimulationApp's launch config verbatim. It is also echoed raw
into two JSON payloads documented as bool: `world_info["headless"]` (simulation.py:1612)
and `get_state()`'s `"headless"` (simulation.py:2196). Driven on a skeleton engine
(`IsaacSimulation.__new__` + seeded attrs):
`get_state()["content"][0]["json"]["headless"]` returned `'off'`, `None`, and `nan` —
the last serializing as the non-standard JSON token `NaN`. The neighbouring
`ground_plane` echo IS coerced (`bool(...)`, simulation.py:1604), so `headless` is the
one field echoed raw.  NOT INTENDED.
tests/simulation/isaac/test_isaac_env_switch_domain.py:300-304 pins the behaviour, but
as a deferral, not an endorsement: the test is
`test_the_headless_field_itself_is_not_type_checked`, its docstring says "That is the
argument domain rather than the environment vocabulary, and it is a separate change",
and it lives in class `TestNeighbouringSurfacesStayOutOfScope` whose docstring reads
"Boundary pins. Replace rather than delete these if the scope moves."
AGENTS.md:2014-2085 ("Posture flags are checked, never read by truthiness") condemns
precisely this shape, including the facade/forwardee asymmetry. changelog.d/2064-isaac-
env-switch-vocabulary.md covers only the env vocabulary and says nothing about the
field's type. Verified 3 pinning tests pass as written on this tree.  WHERE = upstream.
`git diff origin/main -- strands_robots/simulation/isaac/config.py` is 3 deleted lines
only (the `enable_rtx_sensors` field and its doc bullet); the `headless` field, its
docstring and all of `__post_init__` are byte-identical to origin/main:b0a8fcea.  THE
THREE INVALIDATION VECTORS DO NOT BITE. (1) utils.py moved +65/-27 in
90a6efc6..b0a8fcea, but `boolean_flag_error` and `is_boolean` are AST-identical at
90a6efc6, b0a8fcea and HEAD (checked by unparsing each rev). (2) The two new whole-tree
graders are tests/test_shared_domain_family_counts_match_their_lists.py — scoped to the
four "for N families" numeric-domain docstrings, explicitly not `boolean_flag_error` —
and tests/test_env_vars_the_package_reads_are_documented.py, which only requires that a
STRANDS_* read be documented and is untouched by grading a field. (3) AGENTS.md gained
no new section in that range (no added `###` headings); the posture-flag rule that
condemns this predates it.

**Suggested fix**

In `IsaacConfig.__post_init__`, grade each bool field against the shared domain as the
caller supplied it — `if (err := boolean_flag_error(self.headless, "headless",
type(self).__name__)) is not None: raise ValueError(err)` — placed before the
`STRANDS_ISAAC_HEADLESS` override so a bad kwarg is refused whether or not the env
happens to mask it, and extended to `ground_plane` (plus `create_world`'s own
`ground_plane` argument, which is read by truthiness independently). Then replace, not
delete, tests/simulation/isaac/test_isaac_env_switch_domain.py::TestNeighbouringSurfaces
StayOutOfScope::test_the_headless_field_itself_is_not_type_checked with a domain test
parametrized over `boolean_flag_error` itself, per that class's own docstring and the
AGENTS.md convention for these pins, and add a changelog.d fragment.

*Scope: upstream-main · verifier confidence: high*

---

## 12. `pump-docstring` — low

**What is wrong**

Accurate, and understated. `_frame_cache` has no reader in the tree (nor does its
sibling `_joint_cache`) — the only non-test accesses are pump's two writes and destroy's
clear. But the docstring at strands_robots/simulation/isaac/simulation.py:8060-8068
misstates the threading contract in three ways, not one: (1) the frame cache it says
callers read has no readers — `get_observation` calls `cam.handle.get_rgba()` and
`articulation.get_joint_positions()` inline on the calling worker thread; (2) neither
`get_observation` nor `send_action` enqueues anything — the file's only `_action_q`
producer is `set_joint_positions`, which since #3270 refuses when no pump is running;
(3) pump is therefore not "the single place that actually advances the sim" —
`send_action` calls `self._world.step()` on whatever thread invoked it. The actual
mechanism is `_marshal_main_thread_affine` / `run_on_main`, which is what the reference
UI uses, explicitly in preference to the action queue. The nearby comment at :8129-8131
("the capture already published its frames to the cache") is false for the same reason.
Severity is a notch above cosmetic: `_pump_cameras` defaults True, so every idle pump
tick spends one RTX readback per camera writing a dict nothing reads. All of it is
upstream and unchanged by our branch, which only added the registry snapshots plus two
artifacts (a destroy comment and a test) that inherit the false premise.

**Evidence**

READER SEARCH (the Note's question): `_frame_cache` has no reader anywhere in the
package. An AST scan over every `*.py` in the tree finds exactly four non-test
`Attribute` nodes for the two caches, and every one is a write or a clear: -
`strands_robots/simulation/isaac/simulation.py:1210-1211` — the two `Store` inits. -
`simulation.py:8125` and `:8142` — `Load` of the attribute only as the base of a
`Subscript` whose ctx is `Store` (i.e. `self._joint_cache[rname] = ...`,
`self._frame_cache[cname] = img`). - `simulation.py:1834-1837` — `destroy()` clears both
via a `getattr(self, name).clear()` loop. No dynamic access exists either: no
`self.__dict__` / `vars(self)` use in `strands_robots/simulation/isaac/*.py`, and no
string `"_frame_cache"` outside that clear-loop tuple. The only other loads in the whole
tree are asserts in
`tests/simulation/isaac/test_pump_survives_a_concurrent_registry_mutation.py:304-328`
and `test_destroy_clears_the_state_that_outlives_a_world.py:54-55`.  DEMONSTRATED
(skeleton engine, /tmp/srenv, no Isaac): seeded `_frame_cache={"cam": SENTINEL}` and
`_joint_cache={"arm": {"j0": 1.23}}` as if a pump had just refreshed them, then called
`get_observation("arm")` from a thread named `worker-1`. Result: `get_rgba called from:
['worker-1']`, `frame came from cache? False`, `frame came from live handle? True`,
`joint value served from _joint_cache? False`. So the exact call the docstring says
"reads cached frames" instead does the RTX readback inline on the worker thread — the
deadlock-prone path the docstring claims is avoided.  THE DOCSTRING IS WRONG IN THREE
PARTS, NOT ONE (`simulation.py:8060-8068`). A per-method keyword scan: `send_action`
(5050-5277) contains `self._world.step` and `get_rgba` and zero `_action_q` references —
it advances physics inline on the calling thread, so pump is not "the single place that
actually advances the sim". `get_observation` (4277-4491) contains `get_rgba` and no
queue. The sole `_action_q` producer in the file is `set_joint_positions` (`:8475`),
which since #3270 refuses outright when `_pump_running` is False. The real main-thread-
affinity mechanism is `_marshal_main_thread_affine` / `run_on_main` / `_main_jobs`
(`:8240-8270`), and `get_frame`'s docstring (`:6287-6289`) states it: "use `run_on_main`
from worker threads".  THE REFERENCE UI DELIBERATELY DOES NOT USE THE DOCUMENTED DESIGN.
`examples/so101_curobo/controller.py:273-281` submits whole jobs through `run_on_main`
"instead of round-tripping every frame through the action queue (slow + deadlock-prone
for long plans)", and its `render()` (`:315-325`) calls `sim.get_observation(...)` from
the Gradio worker thread — i.e. the live path, not the cache.  AN ADJACENT COMMENT IS
FALSE FOR THE SAME REASON. `simulation.py:8129-8131` says "When actions ran, the capture
already published its frames to the cache". `grep frame_cache
strands_robots/simulation/isaac/recording.py` → no match; nothing in the recording path
writes `_frame_cache`.  NOT COSMETIC. `_pump_cameras` defaults to True (`:1213`), so on
every idle `run_pump_forever` tick pump performs one `_grab_frame` RTX readback per
camera into a dict nothing reads, and keeps a full frame per camera alive until
`destroy`. The two population tests pass on this tree (`pytest -k cache
tests/simulation/isaac/test_pump_survives_a_concurrent_registry_mutation.py` → 2
passed), confirming the writes are live.  WHERE. Byte-identical upstream. `git show
origin/main:.../simulation.py` has the same docstring at `:6362-6370`, the same inits at
`:903-904`, and the same two writes at `:6408` / `:6422`, with no reader and (on main)
not even the destroy-clear. An AST diff of `pump` between `origin/main` and the worktree
shows our branch added only the two registry snapshots (#3268) — it did not touch the
docstring. Our branch does add two derivative artifacts built on the false premise: the
`destroy` comment at `:1827-1828` ("a full RTX frame and a joint snapshot from the old
stage, readable as if current" — nothing can read it), and
`test_the_frame_cache_is_populated_on_the_idle_path`, which pins a write to a reader-
less cache.  INTENDED: no. `AGENTS.md:1838` is a rule against exactly this — "**Match
docstrings to semantics** - If the docstring says 'single-shot' but the code is
'latched', one of them must change." Nothing pins the docstring's text, and no
`changelog.d/` fragment reasons for the divergence. The opposite:
`changelog.d/3268-isaac-pump-snapshots-the-registries.md:5-10` and
`tests/simulation/isaac/test_pump_survives_a_concurrent_registry_mutation.py:5-10` both
block-quote this docstring as the authority for "concurrent access is the *designed*
usage", so the stale text has already propagated into two artifacts. I also checked the
29-commit upstream move for invalidators: the `AGENTS.md` additions in
`90a6efc6..b0a8fcea` are two text-encoding rules (utf-8 on disk I/O, `errors="replace"`
on child streams) and the new graders are a mesh-decoder and driver/policy domain
graders — none touch docstring accuracy or this backend.

**Suggested fix**

Pick one direction and make the other side match, per AGENTS.md:1838. Cheapest: delete
`_frame_cache`, `_joint_cache`, `_pump_cameras` and pump's steps 3-4, drop them from
destroy's clear-loop and the two tests, and rewrite the docstring to state the contract
that actually exists — `reset`/`step` refuse off-thread via
`_marshal_main_thread_affine`, worker threads marshal whole jobs through `run_on_main`,
`set_joint_positions` is the one queued surface and it errors without a pump — while
fixing the false ":8129-8131" capture-publishes comment. Alternative, if a lock-free
off-thread preview is genuinely wanted: add the reader the docstring promises, i.e. have
`get_observation` serve `_frame_cache`/`_joint_cache` when `not self._on_main_thread()`
and fall through to the live handles on the owning thread.

*Scope: upstream-main · verifier confidence: high*

---

## 13. `record-converge-unused` — low

**What is wrong**

Accurate, with two refinements. (1) The knob is parsed and stored exactly once and read
nowhere in the package, tests, or examples — statically or dynamically. The comment's
"both knobs are env-tunable" is true only of `_idle_converge`, which the sole
`_converge_render` call site (the idle branch of `pump`, simulation.py:8097) reads;
`SO101_RECORD_CONVERGE` is silently inert, and since `_env_int` falls back in silence
there is no warning either. (2) "the documented env var" overstates it: the variable
appears in no README or docs page — unlike the sibling
`STRANDS_ISAAC_CAMERA_WARMUP_STEPS`, which has a README row (README.md:1261) — so what
the code breaks is the in-comment promise plus the explicit runbook-compatibility claim
("the same names the retired example used so existing operator runbooks keep working"):
an operator carrying `SO101_RECORD_CONVERGE=12` forward from the retired example gets no
convergence ticks and no diagnostic. Related and worth noting for the fix: the recording
capture path (`run_policy` / `run_multi_policy` / `start_cameras_recording`) never calls
`_converge_render` at all — it only renders on the last substep
(simulation.py:5238-5256) — so the pump's own comment at simulation.py:8090-8095
("worker actions ... include the recording capture, which does its OWN _converge_render
+ grab") also has no in-tree caller backing it.

**Evidence**

Static proof: `strands_robots/simulation/isaac/simulation.py:1219` is the ONLY
occurrence of `_record_converge` or `SO101_RECORD_CONVERGE` anywhere in the repo (grep
over all non-.git files: 1 hit). An AST walk over 4033 .py files (package + tests +
examples) gives `_record_converge`: STORE=[simulation.py:1219], LOAD=[] — zero reads —
while its three sibling knobs all have loads: `_idle_converge` STORE 1220 / LOAD 8097,
`_idle_render_period` STORE 1226 / LOAD 8194, `_camera_warmup_steps` STORE 1235 / LOAD
6841-6842. No dynamic access either: the same walk found no string literal
`"_record_converge"`/`"record_converge"`, and no `getattr`/`vars(self)`/`__dict__` route
reaches it. `_converge_render` has exactly one call site in the whole package,
`simulation.py:8097`, and it passes `self._idle_converge`.  Runtime demo (/tmp/srenv,
MUJOCO_GL=cgl, skeleton engine via `IsaacSimulation.__new__` per the idiom in
`tests/simulation/isaac/test_pump_survives_a_concurrent_registry_mutation.py:89`): with
`SO101_RECORD_CONVERGE=999 SO101_IDLE_CONVERGE=3`, class-level property traps counting
reads of both attributes, then `pump(render=True)` on an idle tick and on a tick with a
queued action → `_converge_render` called with [3]; read counts `{_record_converge: 0,
_idle_converge: 1}`. The env value 999 is parsed (`_env_int("SO101_RECORD_CONVERGE", 6)`
→ 999) and then goes nowhere.  Not intended: `AGENTS.md:95` rule 10 is "**No dead code**
- if it's not called and not part of base class, delete it". No test references the knob
(`tests/simulation/isaac/test_idle_render_period_is_a_finite_span.py:213` pins only
`SO101_IDLE_CONVERGE`), no `changelog.d/` fragment mentions it, and no docstring or
comment gives a reason for it being unread — the comment at `simulation.py:1214-1218`
asserts the opposite ("both knobs are env-tunable ... the same names the retired example
used so existing operator runbooks keep working").  Unchanged by the 29 upstream
commits: `git show origin/main:.../simulation.py` carries the identical assignment at
line 912 and the identical 5-line comment block (byte-identical comparison: True), with
the same single `_converge_render(self._idle_converge)` call site — so upstream is dead
too and this is inherited, not ours. The new whole-tree grader
`tests/test_env_vars_the_package_reads_are_documented.py` does not touch the verdict:
`OWN_PREFIX = "STRANDS_"` (line 74), so `SO101_*` is out of its population; it passes
18/18 on this tree.

**Suggested fix**

Two legitimate directions, and AGENTS.md:1133 explicitly warns that an unused symbol is
often a missing call site rather than dead code — decide which before deleting. Either
wire it up, calling `self._converge_render(self._record_converge)` before the frame grab
in the capture path the DLSS-ghost note at simulation.py:8037-8043 describes (which
today converges nowhere), or apply rule 10 and delete the attribute, reword the comment
at simulation.py:1214-1218 to claim env-tunability only for `_idle_converge`, and drop
the stale "does its OWN _converge_render" clause at simulation.py:8091. If it is kept,
it should also get a README env-table row beside `STRANDS_ISAAC_CAMERA_WARMUP_STEPS`;
note the SO101_* prefix escapes the new grader, so nothing would catch that omission
automatically.

*Scope: upstream-main · verifier confidence: high*

---
