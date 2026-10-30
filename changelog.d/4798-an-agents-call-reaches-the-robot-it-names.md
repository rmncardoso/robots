### Fixed: an agent's call reaches the robot it names, and its run is the robot's one task

A tool is named `robot_<id>` and a hardware `Robot`'s id defaults to its registry name, so a simulated and a
hardware so101, or two so101s on two buses, were both `robot_so101`, and strands kept only the last of two tools of
one name: an `act` meant for the simulated arm wrote to the hardware bus. A second tool of the same name is now
refused when the `Agent` is built; give one of the robots an `id=`. An agent's `run` now goes through `Robot.start`
and waits for its end, so two `run` calls of one model message no longer drive one bus at once: the second is
refused with "already has a running task; call stop() first", `describe()` shows the run, and `robot.stop()` ends
it. `start` no longer lets two threads that call it at the same moment both start a run.
