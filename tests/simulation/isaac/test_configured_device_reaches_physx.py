"""The configured CUDA device reaches PhysX, and what is reported is what it resolved.

``IsaacConfig.device`` defaults to ``"cuda:0"`` and its ``__post_init__`` refuses
anything that does not start with ``cuda`` - "Isaac Sim requires a CUDA device".
``create_world`` then built the world without passing it:

    World(stage_units_in_meters=1.0, physics_dt=dt, rendering_dt=...)

``World``'s own ``device`` default is ``None``, which resolves to ``"cpu"``. So
PhysX solved on the CPU for every caller of this backend, while ``get_state``,
``create_world``'s own result, ``replicate``'s message, the init log line and
``__repr__`` all echoed ``cuda:0`` - the configured value, never the resolved
one. Nothing compared the two, which is why a backend selected specifically for
GPU physics could run entirely on the CPU without a single report saying so.

Measured end to end through ``IsaacSimulation`` on an A10G under Isaac Sim 6.0.1
- 40 cuboids, 300 ``step()`` calls after a 30-step warmup, one container per arm
so the ``World`` singleton is not reused. Same code path both ways:

    main       reported cuda:0   physics_context 'cpu'      gpu=False    9.9 steps/s
    with fix   reported cuda:0   physics_context 'cuda:0'   gpu=True   112.3 steps/s

11.3x, on the one property Isaac is chosen over MuJoCo for, and note that the
reported device is identical in both rows - that is the defect, not a footnote.
The gap widens with scene size, because GPU physics amortizes its fixed cost over
more bodies.

Two halves are pinned here, and the second is what stops a silent recurrence:
the device is forwarded, and every report resolves it from the physics context
rather than echoing the request. ``device_requested`` is reported beside it so a
divergence is legible instead of invisible.

Nothing here needs Isaac Sim: a fake ``isaacsim`` tree records the kwargs
``World`` was constructed with and what its physics context reports.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from strands_robots.simulation.isaac import simulation as isaac_simulation
from strands_robots.simulation.isaac.config import IsaacConfig
from strands_robots.simulation.isaac.simulation import IsaacSimulation


def _resolver():
    """Imported inside the tests, not at module scope, so this file's *behavioural*
    assertions still collect and run against a tree where the resolver does not
    exist yet. A module-scope import turns every test in the file into one
    collection error, which proves the symbol is new and says nothing about
    whether the device was forwarded - the thing actually under test."""
    from strands_robots.simulation.isaac.simulation import _resolved_physics_device

    return _resolved_physics_device


class _PhysicsContext:
    """Reports a device the way ``PhysicsContext`` does, from what World resolved."""

    def __init__(self, device: str | None) -> None:
        # None is what a real World resolves to "cpu" for; the fake mirrors that
        # so the omitted-argument case is reproduced rather than asserted about.
        self.device = device if device is not None else "cpu"

    def set_gravity(self, magnitude: object) -> None:
        return None


class _FakeScene:
    def add_default_ground_plane(self) -> None:
        return None


class _FakeWorld:
    """Stands in for ``isaacsim.core.api.World``, recording its own kwargs."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        type(self).last_kwargs = dict(kwargs)
        self.physics_context = _PhysicsContext(kwargs.get("device"))
        self.scene = _FakeScene()

    def get_physics_context(self) -> _PhysicsContext:
        return self.physics_context

    def reset(self) -> None:
        return None


@pytest.fixture()
def fake_isaacsim(monkeypatch):
    """Fake ``isaacsim`` tree covering every import ``create_world`` performs."""
    monkeypatch.setattr(isaac_simulation, "_SIMULATION_APP", None)
    monkeypatch.setattr(isaac_simulation, "_SIMULATION_APP_LAUNCH", None)
    _FakeWorld.last_kwargs = {}
    mods = {}
    for name in ("isaacsim", "isaacsim.core", "isaacsim.core.api"):
        module = types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, module)
        mods[name] = module
    mods["isaacsim"].SimulationApp = lambda launch=None: types.SimpleNamespace(launch=launch)
    mods["isaacsim"].core = mods["isaacsim.core"]
    mods["isaacsim.core"].api = mods["isaacsim.core.api"]
    mods["isaacsim.core.api"].World = _FakeWorld
    return mods


class TestTheDeviceIsForwardedToWorld:
    """The fix itself: omitting the argument is what put PhysX on the CPU."""

    def test_world_is_constructed_with_the_configured_device(self, fake_isaacsim) -> None:
        sim = IsaacSimulation(config=IsaacConfig(device="cuda:0"))

        assert sim.create_world()["status"] == "success"

        assert _FakeWorld.last_kwargs.get("device") == "cuda:0"

    def test_a_second_gpu_is_honoured_rather_than_collapsed_to_zero(self, fake_isaacsim) -> None:
        """The multi-GPU case, which is the one a caller can observe directly."""
        sim = IsaacSimulation(config=IsaacConfig(device="cuda:1"))

        assert sim.create_world()["status"] == "success"

        assert _FakeWorld.last_kwargs.get("device") == "cuda:1"

    def test_the_argument_is_present_at_all(self, fake_isaacsim) -> None:
        """The precise pre-fix shape: the key was absent, not wrong. A test
        asserting only ``!= "cpu"`` would have passed on the broken code, because
        the broken code never named a device for anything to disagree with."""
        sim = IsaacSimulation(config=IsaacConfig(device="cuda:0"))
        sim.create_world()

        assert "device" in _FakeWorld.last_kwargs


class TestWhatIsReportedIsWhatResolved:
    """The half that makes a recurrence visible instead of benchmark-only."""

    def test_create_world_reports_the_resolved_device(self, fake_isaacsim) -> None:
        sim = IsaacSimulation(config=IsaacConfig(device="cuda:0"))

        result = sim.create_world()

        assert result["content"][0]["json"]["device"] == "cuda:0"
        assert result["content"][0]["json"]["device_requested"] == "cuda:0"

    def test_get_state_reports_both(self, fake_isaacsim) -> None:
        sim = IsaacSimulation(config=IsaacConfig(device="cuda:0"))
        sim.create_world()

        state = sim.get_state()["content"][0]["json"]

        assert state["device"] == "cuda:0"
        assert state["device_requested"] == "cuda:0"

    def test_a_divergence_is_legible(self, fake_isaacsim, monkeypatch) -> None:
        """The whole point. With the physics context reporting cpu against a
        cuda request, the two fields must disagree - that is the signal the
        pre-fix code could not emit, because it read one value twice."""
        sim = IsaacSimulation(config=IsaacConfig(device="cuda:0"))
        sim.create_world()
        sim._world.physics_context.device = "cpu"  # what the pre-fix world resolved

        state = sim.get_state()["content"][0]["json"]

        assert state["device"] == "cpu"
        assert state["device_requested"] == "cuda:0"
        assert state["device"] != state["device_requested"]


class TestTheResolverNeverRaises:
    """It feeds status reads, so it answers None instead of failing."""

    def test_no_world_answers_none(self) -> None:
        assert _resolver()(None) is None

    def test_a_world_without_a_physics_context_answers_none(self) -> None:
        assert _resolver()(types.SimpleNamespace()) is None

    def test_a_physics_context_without_a_device_answers_none(self) -> None:
        world = types.SimpleNamespace(get_physics_context=lambda: types.SimpleNamespace())

        assert _resolver()(world) is None

    def test_a_raising_physics_context_answers_none(self) -> None:
        def _raise() -> Any:
            raise RuntimeError("physics not initialized")

        assert _resolver()(types.SimpleNamespace(get_physics_context=_raise)) is None

    def test_a_resolved_device_is_returned_as_a_string(self) -> None:
        world = types.SimpleNamespace(get_physics_context=lambda: types.SimpleNamespace(device="cuda:0"))

        assert _resolver()(world) == "cuda:0"

    def test_it_is_a_module_level_function_not_a_method(self) -> None:
        """Two of its three callers reach it with a ``types.SimpleNamespace``
        standing in for ``self`` - the ``replicate`` suites call the unbound
        method with a stub - so a method raised ``AttributeError`` there for a
        reporting concern. Pinned because moving it onto the class is the
        natural-looking refactor and it fails only in those suites."""
        assert not hasattr(IsaacSimulation, "_resolved_physics_device")
        assert callable(_resolver())


class TestTheConfigStillRefusesANonCudaDevice:
    """The control: this fix forwards the value, it does not widen the domain."""

    @pytest.mark.parametrize("device", ["cpu", "mps", "", "gpu:0"])
    def test_a_non_cuda_device_is_refused_by_the_config(self, device: str) -> None:
        with pytest.raises(ValueError, match="requires a CUDA device"):
            IsaacConfig(device=device)

    @pytest.mark.parametrize("device", ["cuda", "cuda:0", "cuda:1", "cuda:7"])
    def test_a_cuda_device_is_accepted(self, device: str) -> None:
        assert IsaacConfig(device=device).device == device
