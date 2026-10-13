"""A networked robot (G1, Go2, UR, Spot...) is added from the Devices sheet by its address.

``port`` is polymorphic across drivers: a servo bus takes a ``/dev`` path on this machine, a
networked robot takes where it is on the network. The dashboard held every robot to the serial
rule, so ``unitree_g1`` was listed as real-capable and could not be spawned: an IP was refused
as "not a path under /dev/", and the sheet offered only a serial picker and a lerobot
calibration id. :func:`~strands_robots.drivers.port_kind` is the fact the sheet and the
refusals now branch on.

A driver that joins a DDS domain (G1, Go2) takes ``domain_id`` the same way it takes
``network_interface``: read off the spawn request, refused before a process exists unless the
driver declares it and it names a domain, and forwarded to ``Robot`` by the spawner, so a spawn
that names none still binds the driver's own default, domain 0. A camera change respawns the
child and hands the new one both again; it used to come back on the driver's defaults, ``eth0``
and domain 0.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import strands_robots
from strands_robots.dashboard import device_manager, routes_devices, routes_mesh
from strands_robots.dashboard.device_manager import DeviceManager, validate_port
from strands_robots.drivers import port_kind
from strands_robots.utils import dds_domain_id_error
from tests.test_dds_domain_id_domain import UNUSABLE_DOMAINS

APP_JS = Path(device_manager.__file__).parent / "static" / "app.js"


@pytest.mark.parametrize(
    ("robot", "kind"),
    [("so101", "serial"), ("koch", "serial"), ("unitree_g1", "address"), ("ur5e", "address"), ("spot", "address")],
)
def test_port_kind_says_what_port_names_for_each_driver(robot: str, kind: str) -> None:
    assert port_kind(robot) == kind


@pytest.mark.parametrize(
    ("port", "kind", "ok"),
    [
        ("/dev/ttyACM0", "serial", True),
        ("192.168.123.161", "serial", False),
        ("192.168.123.161", "address", True),
        ("ur5e.local:30004", "address", True),
        ("[fe80::1]", "address", True),
        ("radio://0/80/2M", "address", True),
        ("-oProxyCommand=x", "address", False),
        ("host/../etc", "address", False),
        ("10.0.0.1 ; rm", "address", False),
        ("/dev/../etc/passwd", "address", False),  # a /dev path is a bus, whatever the robot
    ],
)
def test_a_port_is_judged_by_the_shape_its_driver_reads(port: str, kind: str, ok: bool) -> None:
    assert (validate_port(port, kind) is None) is ok


class _Proc:
    pid = 4242
    stdout = None

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        """A respawn stops the child first; this one runs nothing to stop."""

    def wait(self, timeout: float | None = None) -> int:
        return 0


@pytest.fixture
def dm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[DeviceManager, list[dict[str, Any]], list[str]]:
    calls: list[dict[str, Any]] = []
    probed: list[str] = []

    def popen(argv: list[str], **_: Any) -> _Proc:
        calls.append(json.loads(argv[-1]))
        return _Proc()

    def bus_holders(port: str, **_: Any) -> list[Any]:
        probed.append(port)
        return []

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(device_manager, "_drain", lambda *a, **k: None)
    monkeypatch.setattr(device_manager.bus_claim, "bus_holders", bus_holders)
    monkeypatch.setattr(device_manager.camera_liveness, "stamp_device_names", lambda cams, roster: cams)
    monkeypatch.setattr(DeviceManager, "_roster_for_stamp", lambda self: [])
    monkeypatch.setenv("STRANDS_MESH_AUTH_MODE", "mtls")
    monkeypatch.delenv("STRANDS_MESH_LOCAL_DEV", raising=False)
    return DeviceManager(profiles_path=str(tmp_path / "profiles.json")), calls, probed


@pytest.mark.parametrize(
    ("robot", "kwargs", "spawned"),
    [
        ("unitree_g1", {"port": "192.168.123.161", "network_interface": "enp3s0"}, True),
        ("unitree_g1", {}, True),  # the G1 driver binds a NIC; its address is optional
        ("ur5e", {"port": "192.168.1.10"}, True),
        ("so101", {}, False),  # a servo bus still needs its port
        ("so101", {"port": "/dev/ttyACM0", "network_interface": "eth0"}, False),
        ("ur5e", {"port": "192.168.1.10", "network_interface": "eth0"}, False),  # UR takes no NIC
        ("unitree_g1", {"network_interface": "-eth0"}, False),
        ("unitree_g1", {"network_interface": "enp3s0", "domain_id": 7}, True),
        ("unitree_go2", {"port": "192.168.123.161", "domain_id": 7}, True),
        ("ur5e", {"port": "ur5e.local:30004", "domain_id": 7}, False),  # UR joins no DDS domain
    ],
)
def test_spawn_takes_a_networked_robot_by_address(
    dm: tuple[DeviceManager, list[dict[str, Any]], list[str]], robot: str, kwargs: dict[str, Any], spawned: bool
) -> None:
    manager, calls, probed = dm
    out = manager.spawn(robot, "real", peer_id="peer", remember=False, **kwargs)
    assert ("error" not in out) is spawned, out
    if spawned:
        assert calls[0]["port"] == kwargs.get("port")
        assert calls[0].get("network_interface") == kwargs.get("network_interface")
        assert calls[0].get("domain_id") == kwargs.get("domain_id")
        assert probed == [], "an address is not a serial bus: lsof must not be asked about it"


@pytest.mark.parametrize("value", [v for v in UNUSABLE_DOMAINS if v is not None], ids=repr)
def test_a_domain_no_bus_can_bind_is_refused_before_a_process_exists(
    dm: tuple[DeviceManager, list[dict[str, Any]], list[str]], value: Any
) -> None:
    """``None`` is the absent field, the driver's default; every other unusable value is refused
    in the shared words, by a dashboard that has not yet started the child that would die on it."""
    manager, calls, _ = dm

    out = manager.spawn("unitree_g1", "real", peer_id="peer", remember=False, domain_id=value)

    assert out == {"error": dds_domain_id_error(value, "domain_id", "spawn")}
    assert calls == []


class _SpawnerStopped(Exception):
    """Raised in place of the spawned robot, so the script ends before its keep-alive loop."""


def _driver_the_spawner_builds(cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    """Run ``_SPAWNER``'s real-mode branch on ``cfg``; answer the driver ``Robot`` builds from it.

    The stand-in hands every argument to the real factory except the mesh, which would open a
    session, so the keywords the driver receives are the ones the script forwards.
    """
    built: list[Any] = []
    factory = strands_robots.Robot

    def robot(*args: Any, mesh: bool, peer_id: str, **kwargs: Any) -> Any:
        built.append(factory(*args, **kwargs))
        raise _SpawnerStopped

    monkeypatch.setattr(strands_robots, "Robot", robot)
    monkeypatch.setattr(sys, "argv", ["spawner", json.dumps(cfg)])
    with pytest.raises(_SpawnerStopped):
        exec(compile(device_manager._SPAWNER, "<spawner>", "exec"), {"__name__": "__main__"})
    return built[0]


def _status_domain(driver: Any) -> Any:
    """The domain a driver reports it will bind, read off its public status."""
    return asyncio.run(driver.get_status())["content"][0]["json"]["domain_id"]


@pytest.mark.parametrize("robot", ["unitree_g1", "unitree_go2"])
def test_a_spawn_that_names_a_domain_builds_its_driver_on_that_domain(
    dm: tuple[DeviceManager, list[dict[str, Any]], list[str]], monkeypatch: pytest.MonkeyPatch, robot: str
) -> None:
    manager, calls, _ = dm
    assert "error" not in manager.spawn(robot, "real", peer_id="peer", remember=False, domain_id=7)

    assert _status_domain(_driver_the_spawner_builds(calls[0], monkeypatch)) == 7


def test_a_spawn_that_names_no_domain_still_builds_its_driver_on_domain_0(
    dm: tuple[DeviceManager, list[dict[str, Any]], list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default stays the driver's: the spawner forwards no domain it was not given."""
    manager, calls, _ = dm
    assert "error" not in manager.spawn("unitree_g1", "real", peer_id="peer", remember=False, network_interface="eth0")

    assert "domain_id" not in calls[0]
    assert _status_domain(_driver_the_spawner_builds(calls[0], monkeypatch)) == 0


@pytest.mark.parametrize(
    ("robot", "where"),
    [("unitree_g1", {}), ("unitree_go2", {"port": "192.168.123.161"})],
    ids=["unitree_g1", "unitree_go2"],
)
def test_a_camera_change_respawns_the_robot_on_the_interface_and_domain_it_had(
    dm: tuple[DeviceManager, list[dict[str, Any]], list[str]],
    monkeypatch: pytest.MonkeyPatch,
    robot: str,
    where: dict[str, Any],
) -> None:
    """``reconfigure_cameras`` stops the child and spawns it again with everything but the cameras."""
    manager, calls, _ = dm
    # The respawn lists this machine's cameras and serial boards; the stand-ins list none.
    monkeypatch.setattr(DeviceManager, "_camera_names", lambda self, refresh=False: [])
    monkeypatch.setattr(device_manager, "scan_serial_ports", lambda: [])
    bus: dict[str, Any] = {"network_interface": "enp3s0", "domain_id": 7}
    cameras = {"front": {"index_or_path": 0}}
    assert "error" not in manager.spawn(robot, "real", peer_id="peer", remember=False, cameras=cameras, **bus, **where)

    out = manager.reconfigure_cameras("peer", None)

    assert out.get("reconfigured") is True, out
    respawned = calls[-1]
    assert respawned["cameras"] is None
    assert {k: respawned.get(k) for k in bus} == bus
    assert _status_domain(_driver_the_spawner_builds(respawned, monkeypatch)) == 7


class _SpawnRecorder(DeviceManager):
    """A DeviceManager whose spawn records, by parameter name, what it was handed, and starts nothing."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(profiles_path=str(tmp_path / "profiles.json"))
        self.handed: list[dict[str, Any]] = []

    def spawn(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        bound = inspect.signature(DeviceManager.spawn).bind(self, *args, **kwargs)
        bound.apply_defaults()
        self.handed.append(dict(bound.arguments))
        return {"peer_id": bound.arguments["peer_id"], "pid": 1, "mode": bound.arguments["mode"]}


def test_the_spawn_route_hands_domain_id_from_the_body_to_the_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``POST /devices/spawn`` reads ``domain_id`` off the request body, as it reads ``network_interface``."""
    monkeypatch.setattr(routes_devices.env_install, "spawn_preflight", lambda *a, **k: None)
    manager = _SpawnRecorder(tmp_path)
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(devices=manager, bridge=None)))
    body = {"robot_name": "unitree_g1", "mode": "real", "network_interface": "enp3s0", "domain_id": 7}

    asyncio.run(routes_devices.spawn(request, body, {}))

    (handed,) = manager.handed
    assert (handed["network_interface"], handed["domain_id"]) == ("enp3s0", 7)


def test_the_spawn_form_is_told_which_transport_each_robot_uses() -> None:
    rows = {r["name"]: r for r in asyncio.run(routes_mesh.registry({}))["robots"]}
    assert rows["unitree_g1"]["real_transport"] == {
        "port_kind": "address",
        "network_interface": True,
        "domain_id": True,
    }
    assert rows["so101"]["real_transport"] == {"port_kind": "serial", "network_interface": False, "domain_id": False}
    # A native driver the entry does not declare still builds it for real.
    assert rows["ur5e"]["real_transport"] == {"port_kind": "address", "network_interface": False, "domain_id": False}
    # Each keyword is read off the driver on its own: the T1 joins a DDS domain but binds no NIC.
    assert rows["booster_t1"]["real_transport"] == {
        "port_kind": "address",
        "network_interface": False,
        "domain_id": True,
    }
    app_js = APP_JS.read_text(encoding="utf-8")
    assert "real_transport" in app_js and "network_interface" in app_js, "static/app.js was not rebuilt"
