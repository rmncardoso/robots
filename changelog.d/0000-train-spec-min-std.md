### Added: `TrainSpec.min_std` refuses a dataset whose control columns barely move

`MEAN_STD` normalization divides by `std + 1e-8`, so an `action` or
`observation.state` column whose aggregate spread is a thousandth of its unit
scales whatever deviation remains by a thousand, and the policy's input layer
sees values far outside the range it was fitted for. Nothing fails: the run
trains to completion, reports success, and only the checkpoint's behaviour says
the dataset was unusable.

`TrainSpec.min_std` (also `train_policy(min_std=...)`) is the smallest aggregate
`std` a run accepts. When it is set, `LerobotTrainer.validate` reads the
dataset's `meta/stats.json` - the aggregate stats lerobot's own `load_stats`
feeds to normalization - and refuses the run with the number of columns below
it, the first six by name, and the three remedies. It is a refusal, not a
floor: nothing in the dataset or in normalization changes. An absent,
unreadable or non-object `meta/stats.json` (a Hub dataset with no local cache)
leaves the question open, and image features are not graded.

Opt-in, and `None` by default, because a joint held still on purpose produces
the same statistic. The value's domain is a new shared field-scoped gate,
`Trainer._min_std_problems` (positive and finite: `0` or a negative is a
threshold no column falls below, and no comparison with a non-finite one grades
a column honestly - `inf` would call every column flat, `nan` and `-inf` none),
so the `sagemaker` provider, which forwards the field to its container, refuses
a bad value before submission rather than inside the job.
