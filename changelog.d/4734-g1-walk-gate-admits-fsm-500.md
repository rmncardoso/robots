### Fixed: the G1's locomotion gate admits FSM 500, the state `LocoClient.Start()` enters

`WALK_FSMS`, the set `G1Driver._check_motion_gates("loco")` tests, held 501 and 801 and left 500
out on the grounds that 500 was sitting. It is not: Unitree's `LocoClient.Start()` calls
`SetFsmId(500)`, its FSM table names 500 regular locomotion, and the SDK sits with FSM 3. So the
first locomotion verb wired to that gate would have refused the state `Start()` puts the robot in.
`WALK_FSMS` is now `{500, 501, 801}`, the same three ids as `HANDSHAKE_FSMS`.

No write changes behaviour: nothing calls the `loco` scope yet, and the arm and motion gates
already admitted 500. Two read-only verbs answer differently at FSM 500: `g1_get_state` reports
`admits_loco` as true, and `g1_motion_gates` lists 500 under `loco` and admits it there.

Pinned by a new cell in `tests/drivers/test_g1_driver.py`: with the motion switcher reporting 500,
the `loco`, `arm` and `motion` gates all admit, while FSM 3 and a pack under the floor still
refuse. It fails with 500 left out of the set, as do the cells beside it that state the set and
admit 500 for `loco`, and the `g1_get_state` cell at 500.
