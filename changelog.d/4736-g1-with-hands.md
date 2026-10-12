### Added: `unitree_g1_with_hands` - the G1 model that has the hands the catalog advertised

`unitree_g1` was described as "29-DOF + dexterous hands", but the model it loads
(`g1.xml`) has no finger joint at all: its body tree ends at the wrists, as
`changelog.d/2899-humanoid-camera-mount-recipe.md` measured while documenting a
camera mount. The `joints: 29` figure beside the claim is the hand-less count, so
the entry contradicted itself, and a reader who sized an action vector from the
description got 29 keys and no fingers.

The hands are in a second model in the same upstream directory,
`g1_with_hands.xml`: the same 29 body joints plus seven per hand - three thumb,
two middle and two index hinges - for 43 actuated joints, each driven by one
actuator. It now has its own registry entry, so `Robot("unitree_g1_with_hands")`
(or `Robot("g1_with_hands")`) spawns it and `robot_action_keys` reports the
fourteen hand joints; `unitree_g1`'s description no longer promises them.

Nothing is vendored. Both entries name one `robot_descriptions` module, whose
`PACKAGE_PATH` is the directory holding both models, so the second arrives
through the resolver already in the tree as one more symlink into the same cached
description - no copied asset, and no new download path.

The entry's asset cache dir cannot be the upstream directory's name, because no
two entries may share one, so the viewer manifest carries the row that maps it
back to the menagerie path - the same table `aliengo` and `unitree_h1_2` already
use - and both G1s now stream from one URL at one pinned ref. A catalog card with
no thumbnail yet also stops claiming the robot has no simulation asset: a
thumbnail comes from a render sweep rather than from the build, so a robot added
between two sweeps has an asset and no picture of it.
