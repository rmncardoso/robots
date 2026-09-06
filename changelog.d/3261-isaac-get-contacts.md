### Added: `get_contacts` on the Isaac backend

The method was the `SimEngine` raising stub - which is what made
`eval_policy(success_fn="contact")` unmeasurable on Isaac and every `contact_*`
predicate answer `False` on a backend that simulates contacts perfectly well.
With this override in place, the contact-success resolver's structural check
admits Isaac automatically, and `describe()` starts advertising the capability
through the conditional gate - both keyed on the override existing, no second
edit anywhere.

The mechanism, measured on `isaacsim` 6.0.1 before any code was written: a
`PhysxContactReportAPI` applied to a prim **before** the reset that builds the
physics view produces per-pair headers with per-point
`position`/`separation`/`impulse` - and one applied mid-simulation produces
nothing, 0 headers over every later step. So enrollment lives in `add_object`
(threshold 0: the question is "touching?", not "hit hard?"), and a pair is
reported when either actor is enrolled - object<->ground and object<->robot (a
grasp) are covered without touching robot prims. The handle-level contact APIs
were measured as a dead end (they raise without a constructor-time contact
view).

Records arrive in the exact shape the MuJoCo backend emits and the predicate DSL
reads - `geom1`/`geom2` (the registered object name where the actor is a
registered object, else the path leaf), `dist`, `pos`, `active` - plus
`impulse`. Two semantics were settled by measurement rather than assumption:

* **`active` requires a nonzero impulse.** PhysX reports a speculative pair
  inside the contact offset as `CONTACT_PERSIST` at a plainly positive
  separation: a cube resting on *another cube* reported a "persisting" pair with
  the ground plane **0.12 m below it**. Event-type-only `active` answers
  "touching" for bodies visibly apart - the exact proximity-for-touch
  substitution MuJoCo's `active` flag (solver `exclude == 0`) exists to prevent,
  and `contact_between(top_cube, ground)` would have answered `True`. A resting
  contact's impulse is small but decisively nonzero (~3e-3 N*s measured); a
  speculative pair's is zero.
* **The report is cached per step.** PhysX hands the events once per fetch, so
  a second `get_contacts` call without an intervening `step` would read an
  empty report and answer "No contacts." for a cube still resting on the
  ground. The translated result is cached against `_step_count`.

GPU-verified 11/11 on `nvcr.io/nvidia/isaac-sim:6.0.1` (A10G): a resting cube
reports its ground pair, a stacked pair reports cube<->cube, the speculative
pair is inactive while both real pairs carry force, `contact_any` /
`contact_between` answer correctly on the live engine through the shared DSL,
the same-step cache serves the populated answer, and contacts persist across
steps at rest. The translation from the raw report is a pure function with its
own unit tests, including the per-header data-offset walk (an offset bug hands
pair B pair A's contact points).
