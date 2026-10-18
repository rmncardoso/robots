"""A hardware Robot's twin shares Simulation.default() with simulated bodies, and it never pushes them."""

import pytest
from test_drivers import FakeLowState, FakeSub, make_driver

from strands_robots import Description, Robot
from strands_robots.robot.drivers.unitree import UnitreeDriver


def _real_g1(msg):
    return Robot("g1", driver=UnitreeDriver(Description.load("g1"), port="fake", subscriber=FakeSub(msg)))


def _touching(world, rid):
    """The robots (or "world", the floor) that ``rid``'s bodies touch right now."""
    out = set()
    for c in world.contacts():
        a, b = c.body_a.split("/")[0], c.body_b.split("/")[0]
        if rid in (a, b):
            out.add(b if a == rid else a)
    return out


@pytest.mark.parametrize("arm_first", [True, False], ids=["arm_first", "real_first"])
def test_a_twin_never_pushes_a_simulated_arm_off_its_targets(arm_first):
    # both stand on the so101 spawn point and every observe() places the twin there; #4749's headline is arm first
    arm = Robot("so101") if arm_first else None
    real = Robot("so101", driver=make_driver()[0], id="arm_real")
    arm = arm or Robot("so101")
    worst = 0.0
    for k in range(100):  # the sim arm sweeps for 50 ticks, then holds; the real arm idles, observed every tick
        s = min(1.0, k / 50)
        target = {"shoulder_pan": 1.2 * s, "shoulder_lift": -1.0 * s, "elbow_flex": 0.8 * s}
        obs = arm.act(target)
        real.observe()
        if k >= 60:
            worst = max(worst, *(abs(obs[j] - v) for j, v in target.items()))
    assert worst < 0.05  # dev: 1.013 rad arm first, 2.959 rad real first
    assert _touching(arm.sim, real.twin.id) <= {"world"}
    real.close()


def test_a_twin_rests_on_the_floor_and_touches_nothing_else():
    # a floating twin still needs the floor: with no collisions at all a G1 twin falls through it
    sim_g1 = Robot("g1")  # a simulated G1 standing where the real G1's twin spawns
    real = _real_g1(FakeLowState())
    twin, touched = real.twin, set()
    for _ in range(50):  # 1 s of world time; nobody observes the real G1, so the twin's base is simulated
        sim_g1.act(sim_g1.observe().joints)
        touched |= _touching(twin.sim, twin.id)
    assert touched == {"world"} and twin.pose.position[2] > 0.05  # dev: it touches the sim G1 and itself too
    real.close()
