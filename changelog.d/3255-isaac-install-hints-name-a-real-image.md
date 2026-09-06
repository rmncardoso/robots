### Fixed: the Isaac Sim install hint named a docker image that does not exist

`ISAAC_SIM_DOCKER_IMAGE` was `nvcr.io/nvidia/isaac-sim:6.0`, and NVIDIA publishes
no `major.minor` tag for that image. Measured against the registry with
`docker manifest inspect`:

```
isaac-sim:6.0     -> no such manifest
isaac-sim:latest  -> no such manifest
isaac-sim:6.0.0   -> exists
isaac-sim:6.0.1   -> exists
isaac-sim:5.0.0   -> exists
isaac-sim:4.5.0   -> exists
```

What made this worse than a stale line in a document is *where* that constant is
read. It is the single source the **recovery instructions** are composed from:
`IsaacSimulation.is_available()` returns it in the hint it gives when the runtime
is absent, and `create_world()` names it in the structured error it returns for the
same reason. So the one message a user sees when they have no Isaac Sim installed
told them to pull an image that cannot be pulled.

Now pinned to `6.0.1`, the tag this backend is verified against on an A10G, and
pinned by a test that grades the property a registry lookup would confirm - a
resolvable tag carries all three version components - so it needs no network call
and fails on the exact value that shipped. The two pre-existing tests over this
constant assert only that it appears *in* those messages, which a wrong tag
satisfies perfectly.

### Docs: the Isaac page no longer promises three things the backend does not do

* **`create_simulation("isaac")` does not raise when Isaac Sim is missing.** The
  page claimed it "raises a `ValueError` whose message carries the exact install
  hint", then said in the next sentence that backend discovery is lazy - which is
  what is implemented, what `tests/simulation/test_factory.py` pins, and why
  nothing raises: no runtime is imported until you build a world. The page now
  describes the real path (construction succeeds; `create_world()` returns the
  structured error; `is_available()` is the eager check that needs no world) and
  notes the deliberate contrast with Newton, which *does* raise `ImportError` from
  `create_simulation("newton")` because it imports its runtime to construct.
* **Replicator synthetic data** - "ground-truth depth, segmentation, and bounding
  boxes" - is not implemented; there is no Replicator code in the package. The
  bullet now names the RTX metric depth `get_frame` does return.
* **`enable_rtx_sensors`** was a documented `IsaacConfig` field that nothing read,
  so `enable_rtx_sensors=False` silently left RTX sensors enabled. Removed from
  both the config and the table: `IsaacConfig` refuses unknown keywords with a
  `TypeError` naming the argument, so a caller who passes it now gets told, rather
  than having it accepted and ignored.

### Docs: the pip install route runs physics but produces no RTX pixels

Measured on an AWS `g5.2xlarge` (A10G, an RT-core GPU): a pip-wheel install boots
`SimulationApp`, steps physics and reports success, and every RTX camera read comes
back empty - while the same script under `nvcr.io/nvidia/isaac-sim:6.0.1` on the
same instance returns real frames. It reproduces in *pure Isaac Sim* with no
`strands-robots` code in the process, which isolates it to the install route rather
than to the GPU, the driver, or this backend.

Nothing raises, which is what makes it expensive: `render()` degrades to a blank
frame by contract, so a rollout recording video writes an all-black MP4 and reports
success. The page now says so where the pip route is offered, and the install block
lists Docker first.
