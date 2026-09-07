### Fixed: an Isaac `run_policy` no longer leaves the robot permanently busy

`policy_running` is Isaac's busy guard: `move_to`, `rotate_wrist` and `set_gripper`
all refuse while it is set, because a primitive and the policy loop would race on
the articulation's PD targets. The guard is right to exist. On the `run_policy`
path, nothing ever lowered it.

The flag is raised as a side effect of the recording hook -
`IsaacRecordingMixin._make_run_policy_hook` sets it, and reaches that line whenever
a world exists (its early return is keyed on `_world_created`, not on whether
recording is active). The shared `SimEngine.run_policy` never mentions the flag at
all. So the only Isaac path that lowered it was `run_multi_policy`, in its own
`finally`:

| path | raises it | lowers it (before) |
|---|---|---|
| `run_policy` (shared) | yes, via the hook it installs | **no** |
| `start_policy` -> `run_policy` | yes | **no** |
| `run_multi_policy` (Isaac's own) | yes | yes |
| `eval_policy` -> `PolicyRunner.evaluate` | no | n/a |

After one `run_policy` the flag stayed up for the life of the robot, so every later
primitive was refused with a message whose advice could never come true:

```
Cannot 'move_to' on 'arm' while its policy is running - a primitive and the policy
loop would race on the articulation's PD targets. Wait for the rollout to finish
(Isaac policy loops clear the flag on exit).
```

The rollout *had* finished. The parenthetical was a promise only `run_multi_policy`
kept, so the advice named a wait that would never end, and the only recovery was to
remove and re-add the robot.

`run_policy` now delegates the whole rollout to `SimEngine.run_policy` and lowers
the flag in a `finally`, so a rollout that ends for any reason - completion, a
cooperative stop, or a raise - leaves the robot idle. That is the shape the MuJoCo
backend's `_drive_rollout` has had all along, and for the same reason.

It releases the robot the rollout **resolved**, not the argument: `robot_name=None`
is the documented spelling for "the only robot", and that is the robot the flag was
raised on. A resolution that cannot succeed (no robots, or several) is swallowed, so
a refusal from the base call is never replaced by a raise from cleanup.

`start_policy` is covered without its own override, because the shared
implementation ends in `return self.run_policy(...)`. `eval_policy` is deliberately
**not** covered: it drives `PolicyRunner.evaluate`, which touches the flag on
neither backend, so a primitive is not refused during an eval on MuJoCo either.
That makes it a shared question about the eval path rather than an Isaac release
defect, and it is pinned as out of scope rather than fixed quietly.
