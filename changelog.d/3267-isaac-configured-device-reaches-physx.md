### Fixed: the Isaac backend ran PhysX on the CPU while reporting `cuda:0`

`IsaacConfig.device` defaults to `"cuda:0"`, and its `__post_init__` refuses
anything that does not start with `cuda` - *"Isaac Sim requires a CUDA device"*.
`create_world` then built the world without passing it:

```python
World(stage_units_in_meters=1.0, physics_dt=dt, rendering_dt=...)
```

`World`'s own `device` default is `None`, which resolves to `"cpu"`. So the
configured device was validated, stored, and never applied: **PhysX solved on the
CPU for every caller of this backend.**

Measured end to end through `IsaacSimulation` itself on an A10G under Isaac Sim
6.0.1 - `IsaacConfig(device="cuda:0")`, 40 cuboids via `add_object`, 300 `step()`
calls after a 30-step warmup, one container per arm so the `World` singleton is
not reused. Same code path in both; the only difference is the forwarded
argument:

| | `main` (pre-fix) | with the fix |
|---|---|---|
| `create_world` reports `device` | `'cuda:0'` | `'cuda:0'` |
| `get_state` reports `device` | `'cuda:0'` | `'cuda:0'` |
| **`physics_context.device`** | **`'cpu'`** | `'cuda:0'` |
| **`use_gpu_pipeline`** | **`False`** | `True` |
| 300 steps | 30.16 s | 2.67 s |
| throughput | **9.9 steps/s** | **112.3 steps/s** |

**11.3x**, on the one property this backend is selected over MuJoCo for. The gap
widens with scene size, because GPU physics amortizes its fixed cost over more
bodies - so the larger the scene, the more the omission cost. (A narrower
`World`-only A/B, which pays per-step rendering both ways, shows 10.2 against
55.9 steps/s; the full-backend figure above is the one a caller experiences.)

The first three rows are the defect in one image: both reporting surfaces said
`cuda:0` while PhysX was solving on the CPU. That is what let it survive. Five
surfaces named the device - `create_world`'s result, `get_state`, `replicate`'s
message, the init log line and `__repr__` - and every one echoed
`self._config.device`, the value that had been *requested*. Nothing read what
PhysX resolved, so there was no field in which the two could disagree, and a
completely CPU-bound run looked correct everywhere a user would check. The only
visible symptom was that it was slow, which reads as "Isaac is heavyweight"
rather than as a defect.

Two halves, and the second is what stops a silent recurrence:

* `device=self._config.device` is forwarded to `World`.
* The reports resolve the device from the live physics context, with the
  requested value beside it as `device_requested`. A future divergence is then
  legible in `get_state` instead of only in a benchmark.

`_resolved_physics_device()` answers `None` rather than raising when there is no
world yet or the runtime does not expose the attribute, because it feeds status
reads and a status read must not be the thing that fails. It is a module-level
function rather than a method on purpose: two of its three callers are reached
with a `types.SimpleNamespace` standing in for `self` - the `replicate` suites
call the unbound method with a stub - so a method raised `AttributeError` there
for a reporting concern. That is pinned, because moving it onto the class is the
natural-looking refactor and it fails only in those two suites.

The init log line now reads `device_requested=`, since no world exists at
construction time and the physics context cannot yet be asked what it chose.

The config's CUDA-only domain is unchanged and pinned as a control: this
forwards the value, it does not widen what is accepted.
