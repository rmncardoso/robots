### Added: an evaluation reports bounds on its success rate, not just the rate

`eval_policy` and `evaluate_benchmark` now carry `success_rate_ci` in the `json`
block: `confidence` (0.95) plus `wilson_low` / `wilson_high` and
`clopper_pearson_low` / `clopper_pearson_high`, rounded to 4 decimals like
`success_rate`. The text block prints the Clopper-Pearson pair beside the rate, as
`Success: 4/5 (80.0%, 95% CI 28-99%)`; it is the pair to gate on, since its
coverage is guaranteed. The key is gated as `pass_hat_k` is - absent from
`eval_policy`'s payload when no success criterion was in force, and empty when no
episode completed - and the text prints no bounds in either case. The new
`wilson_interval`, `clopper_pearson_interval` and `success_interval` functions in
`strands_robots.simulation.policy_runner` use the standard library only, and raise
`ValueError` unless both counts are integers with `0 <= n_success <= n_completed`.
