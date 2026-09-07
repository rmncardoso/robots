"""In-container smoke test: the Isaac backend end to end on a cloud GPU.

Runs inside nvcr.io/nvidia/isaac-sim:6.0.1 with this repository mounted at
/sr (see run_smoke.sh). Exercises the surface a first user reaches for, and a
slice of everything this backend has been verified to actually do - physics
that integrates, an articulated robot from a bare URDF, contacts, a ray, a
latched force, domain randomization, and a rendered RTX frame with real
pixels - failing loudly on the first thing that is not real.

Isaac Sim has a known atexit segfault that exits 134 AFTER successful work,
so this script reports its verdict and leaves through os._exit.
"""

import os
import sys
import traceback

os.environ.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")

ARM_URDF = """<?xml version="1.0"?>
<robot name="smoke_arm">
  <link name="base_link">
    <inertial><mass value="4.0"/><inertia ixx="0.04" ixy="0" ixz="0" iyy="0.04" iyz="0" izz="0.04"/></inertial>
    <visual><geometry><box size="0.15 0.15 0.1"/></geometry></visual>
    <collision><geometry><box size="0.15 0.15 0.1"/></geometry></collision>
  </link>
  <link name="l1">
    <inertial><origin xyz="0 0 0.14"/><mass value="0.5"/><inertia ixx="0.01" ixy="0" ixz="0" iyy="0.01" iyz="0" izz="0.01"/></inertial>
    <visual><origin xyz="0 0 0.14"/><geometry><box size="0.04 0.04 0.22"/></geometry></visual>
    <collision><origin xyz="0 0 0.14"/><geometry><box size="0.04 0.04 0.22"/></geometry></collision>
  </link>
  <joint name="j1" type="revolute">
    <parent link="base_link"/><child link="l1"/>
    <origin xyz="0 0 0.05"/><axis xyz="0 1 0"/>
    <limit lower="-2.0" upper="2.0" effort="80" velocity="10"/>
  </joint>
</robot>
"""

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}", flush=True)


def main() -> None:
    import numpy as np

    from strands_robots.simulation import create_simulation

    sim = create_simulation("isaac", headless=True, render_mode="rtx_realtime")
    check("create_world", sim.create_world()["status"] == "success")

    with open("/tmp/smoke_arm.urdf", "w", encoding="utf-8") as fh:
        fh.write(ARM_URDF)
    r = sim.add_robot("arm", urdf_path="/tmp/smoke_arm.urdf")
    check("add_robot from a bare URDF", r["status"] == "success", str(r)[:120])

    r = sim.add_object(name="cube", shape="cuboid", position=[0.5, 0.0, 0.6], size=[0.1] * 3, mass=0.4)
    check("add_object", r["status"] == "success")
    sim.add_camera("cam", position=[1.6, 0.0, 0.8], target=[0.2, 0.0, 0.2])

    # The scene changed since the last reset, so the tensor view must be
    # rebuilt before stepping - the backend refuses otherwise, by design.
    check("reset", sim.reset()["status"] == "success")

    z0 = None
    st = sim.get_body_state("cube")
    for block in st.get("content", []):
        if "json" in block and block["json"].get("position"):
            z0 = float(block["json"]["position"][2])
    check("physics: the cube starts where it was spawned", z0 is not None and z0 > 0.5, f"z={z0}")

    check("step", sim.step(120)["status"] == "success")
    z1 = None
    st = sim.get_body_state("cube")
    for block in st.get("content", []):
        if "json" in block and block["json"].get("position"):
            z1 = float(block["json"]["position"][2])
    check("physics: the cube actually FELL", z1 is not None and z0 is not None and z1 < z0 - 0.3, f"z {z0} -> {z1}")

    obs = sim.get_observation()
    check("observation: joint position + velocity keys", "j1" in obs and "j1.vel" in obs, str(sorted(obs))[:100])

    r = sim.get_contacts()
    contacts = next((b["json"]["contacts"] for b in r["content"] if "json" in b), [])
    check("get_contacts: the resting cube touches something", any(c["active"] for c in contacts), f"{len(contacts)} pairs")

    r = sim.raycast([0.5, 0.0, 2.0], [0.0, 0.0, -1.0])
    payload = next((b["json"] for b in r["content"] if "json" in b), {})
    check("raycast hits the cube", payload.get("hit") is True and payload.get("geom_name") == "cube", str(payload)[:90])

    check("apply_force latches", sim.apply_force("cube", force=[6.0, 0.0, 0.0])["status"] == "success")
    sim.step(30)
    sim.apply_force("cube", force=[0.0, 0.0, 0.0])

    r = sim.randomize(randomize_colors=True, randomize_lighting=True, seed=7)
    check("randomize", r["status"] == "success", " ".join(b.get("text", "") for b in r["content"])[:80])

    sim.step(5)
    rgb, depth = sim.get_frame("cam")
    real_pixels = float(np.asarray(rgb).std()) > 1.0
    check("RTX frame carries real pixels", real_pixels, f"shape={np.asarray(rgb).shape} std={np.asarray(rgb).std():.1f}")
    check("RTX depth carries geometry", depth is not None and bool(np.isfinite(depth).any()))

    sim.destroy()


if __name__ == "__main__":
    code = 1
    try:
        main()
    except BaseException:
        traceback.print_exc()
    finally:
        passed = sum(1 for _, ok, _ in CHECKS if ok)
        print(f"\n=== SMOKE SUMMARY: {passed}/{len(CHECKS)} ===", flush=True)
        for name, ok, _ in CHECKS:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        code = 0 if CHECKS and passed == len(CHECKS) else 1
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
