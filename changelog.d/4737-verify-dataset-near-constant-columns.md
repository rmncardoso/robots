### Added: `verify-dataset` advises on a control column that barely moves, not only one that is zero

Check 6 proves a writer failed: an `action` or `observation.state` vector, or
one robot's block of it, that is identically zero across an episode is a
reading no sensor and no teleoperator produces. A column that moved by a
thousandth of its unit is a different finding, and nothing reported it - so a
recording whose joints were measured but barely actuated passed every check,
although lerobot's `MEAN_STD` normalization divides by `std + 1e-8` and scales
what deviation remains by a thousand.

`verify_dataset(root, min_std=...)` and `--min-std` now read `meta/stats.json`,
the dataset-wide stats normalization divides by, and name each control column
whose `std` there is below the threshold (default `1e-3`; `0` switches the
advice off), in one line per feature. The per-episode stats check 6 reads would
be the wrong evidence: a column held still within each episode and moved
between them has a healthy dataset-wide spread. The finding is advice, not a
verdict: it lands in the report's new `warnings` list, prints on a `!` line
below the problems, and leaves `ok`, `status` and the exit code alone, because a
joint held still on purpose produces the same reading. A zero column is named
like any other: check 6 calls one among moving columns (a gripper parked at
zero) a measurement and reports nothing, and a wholly zero vector, which check 6
fails, is also one advisory. An absent or unreadable `meta/stats.json`, or an
entry that is not a number, says nothing. `--no-check-stats` still switches off
check 6 alone.

`min_std` is this gate's third threshold and its only continuous one. It is read
as `min_std > 0`, the same shape that let a negative or non-finite `min_frames`
switch its check off silently, so a value outside its domain (a non-number or a
`bool`, `nan`, `inf`, an integer too large for a float, or a negative) is
reported as a problem and the dataset is not read. A NumPy scalar counts as a
number.
