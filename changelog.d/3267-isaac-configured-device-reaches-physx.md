### Fixed: the Isaac backend reported `cuda:0` while PhysX solved on the CPU

`IsaacConfig.device` defaults to `"cuda:0"`, and its `__post_init__` refuses
anything that does not start with `cuda` - *"Isaac Sim requires a CUDA device"*.
`create_world` builds the world without passing it, and `World`'s own `device`
default is `None`, which resolves to `"cpu"`.

So the backend runs PhysX on the CPU. That is expensive - measured through
`IsaacSimulation` on an A10G under Isaac Sim 6.0.1, 40 cuboids, 300 `step()`
calls after a 30-step warmup, one container per arm:

| | as shipped | with `device="cuda:0"` |
|---|---|---|
| `physics_context.device` | `'cpu'` | `'cuda:0'` |
| `use_gpu_pipeline` | `False` | `True` |
| throughput | **9.9 steps/s** | **112.3 steps/s** |

**What this changes is the reporting, not the device.** Forwarding the device is
the obvious one-line change. It does not work, and the reason is worth recording:

```
no device arg     gpu_pipeline=False   add_robot -> success
device="cuda:0"   gpu_pipeline=True    add_robot -> CUDA error: an illegal
    memory access was encountered   (omni.physx.tensors GpuArticulationView.cpp:631)
```

Same A10G, same tree, only the argument differing. PhysX's GPU pipeline
**pre-sizes its tensor buffers at `world.reset()`**, and `create_world` resets
immediately - sizing them for a stage holding a ground plane and *zero*
articulations. The first `add_robot` then initializes an articulation into a view
with no room for it. Nothing recovers in-process: the illegal access poisons the
CUDA context, so the next `add_object` fails too.

Neither available ordering avoids it. Adding while the sim is stopped instead
fails with `'NoneType' object has no attribute 'create_articulation'` - stopped,
there is no view to add into. Making the GPU pipeline usable needs Isaac Lab's
pattern, where the whole scene is built *before* the first reset, and that is
incompatible with this backend's incremental contract, where an agent calls
`create_world` and then `add_robot` one tool call at a time. That is a feature,
not the repair of a wrong answer, so it is left undone and written down - with the
measurement and the failing call site attached to the code, so the next reader
does not rediscover it on a GPU.

**The defect this fixes is that none of it was visible.** Five surfaces named the
device - `create_world`'s result, `get_state`, `replicate`'s message, the init log
line and `__repr__` - and every one echoed `self._config.device`, the value that
had been *requested*. Nothing read what PhysX resolved, so there was no field in
which the two could disagree: a wholly CPU-bound run reported `device=cuda:0`
everywhere a user would look, and the only symptom was being slow, which reads as
"Isaac is heavyweight" rather than as a defect.

`get_state` and `create_world` now report `device` as the device PhysX **resolved**
and `device_requested` as the one the config asked for. On current hardware they
disagree, and that disagreement is the finding:

```python
sim.get_state()["content"][0]["json"]
# {..., "device": "cpu", "device_requested": "cuda:0", ...}
```

The init log line reads `device_requested=` rather than `device=`, since no world
exists at construction time and the physics context cannot yet be asked.

`_resolved_physics_device()` answers `None` rather than raising when there is no
world or the runtime does not expose the attribute, because it feeds status reads
and a status read must not be the thing that fails. It is a module-level function
on purpose: two of its three callers are reached with a `types.SimpleNamespace`
standing in for `self` - the `replicate` suites call the unbound method with a stub
- so a method raised `AttributeError` there for a reporting concern. Pinned,
because moving it onto the class is the natural-looking refactor and it fails only
in those suites.

The config's CUDA-only domain is unchanged and pinned as a control. So is the
absence of the `device` kwarg at the `World` call, with the reason - a bare
omission reads as an oversight and invites the one-line "fix" that breaks
`add_robot`.
