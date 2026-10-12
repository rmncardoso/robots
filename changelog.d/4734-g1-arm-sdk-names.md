### Fixed: the G1 names its arm topic and FSM ids as Unitree does, cites the issue that tracks its tools, and says which verbs ask for approval

Four kinds of name in `strands_robots/drivers/g1.py`, `strands_robots/drivers/unitree/` and
`strands_robots/tools/g1/` pointed a reader at something that does not exist or means something
else, and the Unitree hardware page promised an approval step most of its verbs do not have.
Behaviour is unchanged apart from strings; the one FSM set that moves, `WALK_FSMS`, has its own
entry.

- **The arm topic.** The package spelled it `rt/armsdk` in eight places. Unitree's arm SDK
  examples publish `rt/arm_sdk` (`unitree_sdk2_python`,
  `example/g1/high_level/g1_arm5_sdk_dds_example.py`); the spelling without the underscore matches
  the G1 message for response 7400 in Unitree's C++ SDK, whose H2 header spells the same
  message `rt/arm_sdk`. The docstrings now name `rt/arm_sdk`, and the three that said a gesture
  goes out on that topic say what the `ExecuteAction` gesture call is: a request to the SDK's arm
  action service.
- **Response 7400.** `ERR_CODES[7400]` read "rt/armsdk topic is occupied", pinned as the SDK's
  text. The Python SDK carries no text for the code, so a caller only ever receives the integer.
  The entry now reads "rt/arm_sdk topic is occupied - an action is executing", the cause Unitree's
  arm action page gives (https://support.unitree.com/home/en/G1_developer/arm_action_interface).
- **FSM 500.** Three of the four descriptions of `HANDSHAKE_FSMS` and `WALK_FSMS` called 500
  "sitting", and the fourth labelled the set "arm-SDK, sit, sit-down". Unitree's SDK enters 500 from
  `LocoClient.Start()` and sits with FSM 3 (`LocoClient.Sit()`), and its FSM table
  (https://support.unitree.com/home/en/G1_developer/sport_services_interface) names 500 regular
  locomotion, 501 the same with the 3-DoF waist and 801 walk-run locomotion. That label was why
  `WALK_FSMS` left 500 out; it now admits 500, which has its own entry.
- **#358.** Twenty-seven lines cited `#358` as the G1 tools tracker, in refusal envelopes,
  docstrings and comments. Here #358 is a merged pull request about zenoh mock isolation, and
  #2928 is the issue opened for the tools port once that was noticed. The `refs` clauses under
  `tools/g1/` cite #2928 now, and the driver-layer prose that deferred to "later, issue #358" for
  tools that have since landed names those tools instead.
- **#354, #356 and #361.** Twelve more lines carried three more numbers from the same tracker: the
  driver (#354), a point-cloud view (#356) and the write path with its control loop (#361), which
  landed here as #2757, #2767 and #2779. Here each is another merged pull request about the mesh,
  and that tracker is not one a reader of this repository can open, so the lines now name what
  they meant. Four are the `g1_send_action` and `g1_run_policy` refusals, which keep pointing at
  the driver method for the shape. Two of the reworded sentences were also out of date:
  `DDSPublisher.close` said the driver held no publisher yet, and `_build_zero_torque_lowcmd` said
  `G1Driver.stop` used it, when `stop` reaches it only through the control loop it halts.
- **Approval on `docs/learn/hardware/unitree.md`.** The page said the `g1_*` motion verbs execute
  and that "each motion pauses for your approval". Only `use_unitree` asks: no other module under
  `tools/g1/` reaches `gate_motion`. The thirteen `g1_actions` verbs call methods `G1Driver` does
  not define, so against the shipped driver each returns its live-handle refusal, and every `g1_*`
  verb but the four reference tables takes a live driver no model can send. The page now says that,
  and its sketch hands the agent `use_unitree` alone. The edit is word-neutral, so the site budget
  is unchanged.

Pinned by two new tests (five cells) in `tests/drivers/test_g1_handshake_fsms_docstring_names_the_topic_it_gates.py`
(no module in the package spells the topic `rt/armsdk`; none of the four descriptions of the FSM
sets calls an id in them a sitting mode, one cell per description), which replace the cell that
pinned the old 7400 text, and by `tests/tools/g1/test_g1_sources_cite_the_tools_port_issue.py`
(no G1 source cites #358; none cites #354, #356 or #361). Each fails on `03b9cfd1` and passes after
this change.
