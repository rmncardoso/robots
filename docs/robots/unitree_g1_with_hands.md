---
title: unitree_g1_with_hands
description: "Unitree G1 Humanoid with hands (43-DOF: 29 body + 7 per hand)"
---

<!-- generated: docs/hooks/robot_pages.py -->

# Unitree G1 Humanoid with hands (43-DOF: 29 body + 7 per hand)

{{robot_chips:unitree_g1_with_hands}}

<robot-viewer name="unitree_g1_with_hands"></robot-viewer>

```python
from strands_robots import Robot

robot = Robot("unitree_g1_with_hands")
print(robot.robot_action_keys("unitree_g1_with_hands"))
robot.cleanup()
```

Walk it with a whole-body controller ([wbc](../learn/policies/wbc.md)) or a trained gait ([rl](../learn/policies/rl.md)).

Aliases: `g1_with_hands`.

## Policies verified on this robot

No checkpoint verified on this robot yet. Record one: [Record](../learn/data/record.md), then [train](../learn/training/lerobot.md) and run it with `run_policy`.

Model: [google-deepmind/mujoco_menagerie/unitree_g1](https://github.com/google-deepmind/mujoco_menagerie/tree/c96a32d28fb5da84da38c1da4d749e7a13212855/unitree_g1), scene `scene_with_hands.xml`.
