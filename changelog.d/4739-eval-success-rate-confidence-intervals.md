### Added: an evaluation reports bounds on its success rate, not just the rate

`success_rate` is a count over however many episodes ran, and the payload gave a
reader no way to tell how much of it is the count. 4 of 5 and 400 of 500 both print
as 80%; the first is consistent with anything from 38% to 96% and the second only
with 76% to 83%. So two checkpoints "at the same rate" were routinely compared on a
difference the run was too short to show - the gap `pass_hat_k` closes for repeated
attempts, left open for the rate itself.

`eval_policy` and `evaluate_benchmark` now carry `success_rate_ci` in the `json`
block: `confidence` (0.95) plus `wilson_low` / `wilson_high` and
`clopper_pearson_low` / `clopper_pearson_high`, each rounded to 4 decimals like
`success_rate` and `pass_hat_k`.

**Why two intervals.** The textbook `p +/- z*sqrt(p(1-p)/n)` form is unusable here:
its width collapses to zero at `p` of 0 or 1, so a policy that failed all five
attempts would publish 0% with no uncertainty whatever, and near 0/n and n/n its
bounds leave `[0, 1]`. The Wilson score interval fixes
both and still says something at the ends (0 of 5 bounds the rate at 43.4%).
Clopper-Pearson inverts the binomial tail instead, so it needs no normal
approximation and holds at least its nominal coverage for every `p`, where Wilson's
true coverage dips below the level it claims. The distance between them is what the
approximation costs: at 4 of 5 it is 38-96% against 28-99%. Neither is the outer
bound of the other, which is why the payload carries both rather than picking one -
the exact interval is the wider wherever both ends are interior, and at 0/n and n/n
the score interval's single open end reaches further from n=46 up (0 of 50 bounds the
rate at 7.135% by the score interval and 7.112% by the exact one).

Standard library only: no SciPy, and no new dependency for either. The binomial tail
is summed through `math.lgamma` rather than `math.comb`, because `comb(n, i) * p**i`
raises `OverflowError` from 1,030 trials up (`comb(1030, 515)` is already past the
largest float) - the coefficient leaves float range while the product it belongs to
stays a probability in `[0, 1]`. Each exact bound is then found by bisection on a
tail that is monotone in `p`, so the root is unique.

Both degenerate ends are taken from the count rather than from the arithmetic.
`centre` and `half` are equal at 0/n, and subtracting them left `5.6e-17` (at 0/3)
as `wilson_interval`'s floor under a run that never succeeded - a nonzero floor that
a caller comparing it against another run's exact `0.0` would read as a difference.
The payload's 4-decimal rounding hid it; the function's own return value did not.

Gated exactly as `pass_hat_k` is: absent from `eval_policy`'s payload when no success
criterion was in force, since an interval around a hard `0.0` would qualify a number
that measured nothing, and empty rather than `[0, 1]` when no episode completed.
`evaluate_benchmark` always measures success, so it reports the key unconditionally.
No paired test (McNemar's and friends) is included: both surfaces evaluate one policy
per call, so a paired statistic would have no caller.

`learn/simulation/predicates-and-rollouts.md` names the key in its payload list and
says what to read it for, 45 words; the `_SITE_BUDGET` ceiling is raised by 43 to pay
for them (2 spare words were already under it), with the two intervals' contrast
and the arithmetic left in `PolicyRunner.evaluate`'s `Returns:` block, which is where
a caller reads a payload key.

Pinned by `tests/simulation/test_eval_bounds_its_success_rate.py`, which grades the
arithmetic by the equation each interval solves rather than against a table, so a
cell cannot pass by agreeing with the code it checks. A Wilson bound is asserted to
sit where the score statistic reaches `z`; a Clopper-Pearson bound where the binomial
tail reaches `alpha / 2`, re-derived per cell in exact rationals from `math.comb` and
`fractions.Fraction`, which share no code with the `lgamma` sum under test. The 0/n,
1/n and n/n ends are checked against their closed forms. Six property cells each
sweep the same 110 `(n, successes)` pairs inside one cell and name the offending
pair, rather than multiplying into a parametrised grid. Those sweeps are what found
the `5.6e-17` floor and the n=46 crossover above; both are now pinned.
