"""The Unitree bus binds one validated DDS domain per process.

``ChannelFactoryInitialize(domain_id, network_interface)`` takes a domain
beside the interface, and this stack passed the literal ``0``: a bus that is
not on that domain - a simulator, or a bench rig deliberately kept off the
robots' domain - had no keyword to name it. ``ensure_dds``, both halves of the
DDS engine, the G1 and Go2 drivers and ``use_unitree`` now take ``domain_id``,
defaulting to ``0``, so a caller that names nothing binds exactly what it bound
before.

Three properties make the keyword worth having rather than merely present, and
each has a class below:

* the value a caller names is the value the SDK is called with, through every
  surface that opens the bus;
* a second, *different* domain in one process is refused, for the reason a
  second interface is - ``ChannelFactory.Init`` short-circuits on its
  ``__initialized`` flag, so the later domain never reaches the SDK and the
  endpoints built after it would sit on the first domain, reading topics
  nobody publishes there;
* a value that cannot name a domain is refused by the *shared* domain rule
  (:func:`~strands_robots.utils.dds_domain_id_error`), whose tables this module
  imports from :mod:`tests.test_dds_domain_id_domain` rather than restating: a
  domain the telemetry bridges refuse and this bus accepts is a robot
  publishing where nothing subscribes. The guard runs ahead of the lazy SDK
  import, so the refusal is about the value rather than about the install, and
  that placement is asserted directly.

No cell binds a real factory: the bind is a process-wide side effect with no
``Shutdown`` in ``unitree_sdk2py``, so every cell that reaches the SDK drives a
fake ``unitree_sdk2py.core.channel`` and the recorded state is cleared around
all of them.
"""

from __future__ import annotations

import asyncio
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import strands_robots.tools.g1.use_unitree as uu
from strands_robots.drivers.g1 import G1Driver
from strands_robots.drivers.go2 import Go2Driver
from strands_robots.drivers.unitree._common import ensure_dds, reset_dds_state
from strands_robots.drivers.unitree._dds_engine import DDSPublisher, DDSSubscriberSet
from strands_robots.utils import MAX_DDS_DOMAIN_ID, dds_domain_id_error
from tests._blocked_module import blocked
from tests.test_dds_domain_id_domain import UNUSABLE_DOMAINS, USABLE_DOMAINS

#: The attribute ``ChannelFactory`` publishes "the bus is up" on. Spelled here
#: rather than read from the package so the fake is an independent statement of
#: what the SDK does; its sibling module grades the spelling against the
#: installed SDK.
_SDK_BOUND_ATTR = "_ChannelFactory__initialized"

#: Both halves of the engine: each opens the bus through ``ensure_dds``, so
#: each owes the caller the same answer about a domain.
ENGINES: tuple[type[Any], ...] = (DDSSubscriberSet, DDSPublisher)

#: Both Unitree drivers: each hands its own interface and domain to both
#: engine halves.
DRIVERS: tuple[type[Any], ...] = (G1Driver, Go2Driver)


def _class_name(cls: type[Any]) -> str:
    """Name a parametrized class cell after the class, not its ``repr``."""
    return cls.__name__


class _ReadOnlyClient:
    """A stand-in SDK client exposing one read, so no approval gate runs."""

    def GetFsmId(self) -> tuple[int, int]:  # the SDK's own spelling
        """Answer the SDK's ``(code, fsm_id)`` pair without a robot."""
        return (0, 801)


@pytest.fixture(autouse=True)
def _clean_dds_state() -> Iterator[None]:
    """Clear the recorded bind around every cell.

    The record is module state with no SDK-side reset, so a cell that left a
    domain recorded would decide the verdict of the next one.
    """
    reset_dds_state()
    yield
    reset_dds_state()


@pytest.fixture
def bus_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    """Install a fake SDK channel module; answer its ``(domain, interface)`` log.

    The fake reports an unbound factory - the state a fresh process is in - and
    records every ``ChannelFactoryInitialize`` call, which is how a cell reads
    what the SDK was actually asked to bind.
    """
    calls: list[tuple[int, str]] = []
    channel = types.ModuleType("unitree_sdk2py.core.channel")
    factory = type("ChannelFactory", (), {_SDK_BOUND_ATTR: False})

    def channel_factory_initialize(domain_id: int, network_interface: str) -> None:
        calls.append((domain_id, network_interface))
        setattr(factory, _SDK_BOUND_ATTR, True)

    channel.ChannelFactory = factory  # type: ignore[attr-defined]
    channel.ChannelFactoryInitialize = channel_factory_initialize  # type: ignore[attr-defined]
    core = types.ModuleType("unitree_sdk2py.core")
    core.channel = channel  # type: ignore[attr-defined]
    root = types.ModuleType("unitree_sdk2py")
    root.core = core  # type: ignore[attr-defined]
    for name, module in (
        ("unitree_sdk2py", root),
        ("unitree_sdk2py.core", core),
        ("unitree_sdk2py.core.channel", channel),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return calls


# =========================================================================
# The value a caller names is the value the SDK is asked to bind.          #
# =========================================================================


class TestTheDomainACallerNamesIsTheDomainBound:
    """Every surface that opens the bus carries the caller's domain to it."""

    def test_naming_no_domain_binds_domain_zero_as_before(self, bus_calls: list[tuple[int, str]]) -> None:
        """The default is the call every existing caller already made."""
        assert ensure_dds("eth0") is None

        assert bus_calls == [(0, "eth0")]

    @pytest.mark.parametrize("value", USABLE_DOMAINS, ids=repr)
    def test_a_domain_the_shared_table_accepts_reaches_the_sdk(
        self, value: int, bus_calls: list[tuple[int, str]]
    ) -> None:
        """Every facet of one usable value: it is accepted, it is the argument
        the SDK is called with, and asking again for the same pair is the
        idempotent no-op rather than a second bind."""
        assert ensure_dds("eth0", value) is None
        assert bus_calls == [(value, "eth0")]

        assert ensure_dds("eth0", value) is None

        assert bus_calls == [(value, "eth0")]

    @pytest.mark.parametrize("engine", ENGINES, ids=_class_name)
    def test_an_engine_hands_its_domain_to_the_bind(self, engine: type[Any], bus_calls: list[tuple[int, str]]) -> None:
        """Readers and writers are built on one bus, so both carry the domain."""
        assert engine("eth0", domain_id=7).start() is None

        assert bus_calls == [(7, "eth0")]

    @pytest.mark.parametrize("driver_cls", DRIVERS, ids=_class_name)
    def test_a_driver_binds_the_domain_it_was_built_with(
        self, driver_cls: type[Any], bus_calls: list[tuple[int, str]]
    ) -> None:
        """``connect_eagerly`` gets no further than the bind under the fake SDK,
        which carries no IDL - and the bind is the step under test."""
        driver = driver_cls(port="192.168.123.161", network_interface="eth0", domain_id=7)

        driver.connect_eagerly()

        assert bus_calls == [(7, "eth0")]

    @pytest.mark.parametrize("driver_cls", DRIVERS, ids=_class_name)
    def test_a_driver_reports_the_domain_it_will_bind(self, driver_cls: type[Any]) -> None:
        """The status envelope already names the interface; a domain a caller
        cannot read back is a setting they cannot check before a robot moves."""
        status = asyncio.run(driver_cls(domain_id=11).get_status())

        assert status["content"][0]["json"]["domain_id"] == 11

    def test_use_unitree_forwards_the_domain_it_was_given(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The raw escape hatch reaches the same bus, so it names the same pair."""
        monkeypatch.setenv("STRANDS_MESH_AUDIT_DIR", str(tmp_path / "audit"))
        asked: list[tuple[str, int]] = []
        monkeypatch.setattr(uu, "ensure_dds", lambda iface, domain_id=0: asked.append((iface, domain_id)))
        monkeypatch.setattr(uu, "_CLIENTS", {"loco": _ReadOnlyClient()})

        uu.use_unitree("loco", "GetFsmId", {}, domain_id=9)

        assert asked == [("eth0", 9)]


# =========================================================================
# One bind per process: the second domain is refused, not silently joined. #
# =========================================================================


class TestASecondDifferentDomainIsRefused:
    """The SDK's re-init is a silent no-op, so the refusal has to be ours."""

    def test_the_refusal_names_the_bound_domain_and_the_one_asked_for(self, bus_calls: list[tuple[int, str]]) -> None:
        """A caller with two domains needs to know which one is up."""
        assert ensure_dds("eth0", 7) is None

        err = ensure_dds("eth0", 9)

        assert err is not None
        assert "domain 7" in err
        assert "domain 9" in err
        assert bus_calls == [(7, "eth0")], "the second domain reached the SDK, which binds nothing"
        assert ensure_dds("eth0", 7) is None, "the record no longer describes the bind"

    def test_a_caller_that_names_no_domain_is_refused_against_a_bound_one(
        self, bus_calls: list[tuple[int, str]]
    ) -> None:
        """The default is a named domain and not "whichever is up": a verb that
        omits the keyword on a bus already bound to another domain is told so,
        rather than attaching its endpoints to a domain nobody chose for it."""
        assert ensure_dds("eth0", 7) is None

        err = ensure_dds("eth0")

        assert err is not None
        assert "domain 7" in err
        assert "domain 0" in err
        assert bus_calls == [(7, "eth0")]

    def test_the_interface_refusal_is_unchanged_on_the_bound_domain(self, bus_calls: list[tuple[int, str]]) -> None:
        """One reason at a time: a NIC mismatch keeps its own wording."""
        assert ensure_dds("eth0", 7) is None

        err = ensure_dds("wlan0", 7)

        assert err is not None
        assert "interface 'eth0'" in err
        assert "wlan0" in err


# =========================================================================
# The shared domain rule, applied before the bus is touched.               #
# =========================================================================


class TestAnUnusableDomainIsRefusedBeforeTheBus:
    """Every surface answers an unusable value with the shared refusal."""

    @pytest.mark.parametrize("value", UNUSABLE_DOMAINS, ids=repr)
    def test_a_value_that_cannot_name_a_domain_binds_nothing_anywhere(
        self, value: Any, bus_calls: list[tuple[int, str]]
    ) -> None:
        """Every facet of one unusable value, in the order the harm would land:
        the shared refusal word for word, no call to the SDK, every other
        surface refusing it too - ``use_unitree`` as a failed call carrying
        that refusal - and nothing recorded, so the next caller still binds."""
        refusal = dds_domain_id_error(value, "domain_id", "ensure_dds")
        assert ensure_dds("eth0", value) == refusal
        assert bus_calls == []

        for engine in ENGINES:
            with pytest.raises(ValueError, match="invalid domain_id"):
                engine("eth0", domain_id=value)
        for driver_cls in DRIVERS:
            with pytest.raises(ValueError, match="invalid domain_id"):
                driver_cls(domain_id=value)
        result = uu.use_unitree("loco", "GetFsmId", {}, domain_id=value)
        assert result["status"] == "error"
        assert result["content"][0]["json"]["message"] == f"loco.GetFsmId failed: {refusal}"

        assert ensure_dds("eth0") is None
        assert bus_calls == [(0, "eth0")]

    @pytest.mark.parametrize("value", UNUSABLE_DOMAINS, ids=repr)
    def test_the_same_refusal_arrives_without_the_vendor_sdk(self, value: Any) -> None:
        """The guard sits ahead of the lazy import, so the caller is told about
        the value they passed rather than about an install they may not need to
        fix - the placement the shared domain asks of every surface."""
        with blocked("unitree_sdk2py"):
            assert ensure_dds("eth0", value) == dds_domain_id_error(value, "domain_id", "ensure_dds")

    def test_the_refusal_states_the_range_the_rtps_port_map_fixes(self, bus_calls: list[tuple[int, str]]) -> None:
        """The first id whose discovery ports overflow is named, not just rejected."""
        err = ensure_dds("eth0", MAX_DDS_DOMAIN_ID + 1)

        assert err is not None
        assert f"expected 0-{MAX_DDS_DOMAIN_ID}" in err
        assert bus_calls == []
