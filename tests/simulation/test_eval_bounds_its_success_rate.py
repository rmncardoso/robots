"""An evaluation's success rate is reported with bounds, not as a bare point.

``success_rate`` is a count over however many episodes ran, and the payload gave a
reader no way to tell how much of it is the count: 4 of 5 and 400 of 500 both print
as 80%, and only the second has settled anything. So two checkpoints at "the same
rate" were routinely compared on a difference the run was too short to show - the
same gap ``pass_hat_k`` closes for repeated attempts, which is why both now travel in
the same payload.

Two intervals are reported, because the distance between them is a fact about the run
rather than a matter of taste:

* **Wilson** (the score interval) is what the textbook ``p +/- z*sqrt(p(1-p)/n)`` form
  should have been. That form's width collapses to zero at ``p`` of 0 or 1 - a policy
  that failed all five attempts would publish 0% with no uncertainty whatever - and
  its bounds leave ``[0, 1]`` for most of the episode counts an evaluation runs.
* **Clopper-Pearson** inverts the binomial tail directly, so it invokes no normal
  approximation and holds at least its nominal coverage for every ``p``. Wherever
  both ends are interior it is the wider of the two; at 0/n and n/n that reverses
  once ``n`` passes 45, and both facts are pinned below, because "the conservative
  one" is not a property either interval has outright.

The arithmetic is graded here by the equation each interval solves, not against a
table, so a cell cannot pass by agreeing with the code it checks: a Wilson bound is
where the score statistic reaches ``z``, and a Clopper-Pearson bound is where the
binomial tail reaches ``alpha / 2`` - re-derived per cell from :func:`math.comb` and
:class:`fractions.Fraction`, which share no code with the ``lgamma`` sum under test.
The 0/n, 1/n and n/n ends have closed forms, and those are checked against the closed
form itself. Each sweep over ``_COUNTS`` runs inside one cell and names the offending
pair, rather than multiplying into a parametrised grid.

No paired test (McNemar's and friends) is added: both surfaces evaluate one policy per
call, so a paired statistic would have no caller here, and code with no caller is
refused (``AGENTS.md`` convention 10).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from fractions import Fraction

import pytest

from strands_robots.simulation.policy_runner import (
    _CI_CONFIDENCE,
    CooperativeStop,
    _binomial_tail_at_least,
    clopper_pearson_interval,
    success_interval,
    wilson_interval,
)

#: The coverage both intervals carry, as the tail mass outside them. Read from the
#: module under test so no cell can pass against a level nobody reports.
_ALPHA = 1.0 - _CI_CONFIDENCE

#: The 97.5% standard normal quantile, spelled out here rather than imported: a cell
#: that read the same constant as the code could not catch a wrong one.
_Z_97_5 = 1.959963984540054

#: Episode counts the sweeping cells run over. Weighted to small ``n`` on purpose -
#: that is where an approximation is worst, and where an evaluation actually lives.
_SIZES = (1, 2, 3, 5, 8, 13, 20, 50)

#: Every ``(n, successes)`` pair over those counts, the degenerate ends included.
_COUNTS = tuple((n, c) for n in _SIZES for c in range(n + 1))

#: A one-joint arm, so an evaluated episode costs a handful of cheap steps. What is
#: under test is the arithmetic over a rollout, not the rollout.
_PROBE_XML = """
<mujoco model="success_interval_probe">
  <worldbody>
    <body name="base" pos="0 0 0">
      <joint name="j1" type="hinge" axis="0 0 1" range="-3 3"/>
      <geom name="link1" type="capsule" fromto="0 0 0 0 0 0.2" size="0.02"/>
    </body>
  </worldbody>
  <actuator>
    <position name="a1" joint="j1" kp="10"/>
  </actuator>
</mujoco>
"""

#: Steps an evaluated episode is allowed.
_MAX_STEPS = 4


def _exact_tail_at_least(k: int, n: int, p: float) -> float:
    """``P(X >= k)`` for ``Binomial(n, p)``, summed in exact rationals.

    An independent re-derivation of what ``_binomial_tail_at_least`` computes with
    logarithms, so a cell comparing the two grades the sum instead of restating it.
    ``Fraction(p)`` is the float exactly, and rationals cancel nothing, so the only
    error left is the ``float()`` at the end.
    """
    q = Fraction(p)
    return float(sum(math.comb(n, i) * q**i * (1 - q) ** (n - i) for i in range(k, n + 1)))


class TestTheWilsonBoundIsWhereTheScoreTestTurns:
    """Graded by the equation the interval solves, not by a remembered table.

    Both bounds satisfy ``(p_hat - p)**2 == z**2 * p * (1 - p) / n``: the score
    statistic reaches ``z`` exactly there. A hand-rolled quadratic is easy to get
    subtly wrong - a dropped 2 in the continuity term, ``n`` where ``n**2`` belongs -
    and every such slip survives a monotonicity or a containment check.
    """

    def test_each_interior_bound_reaches_the_quantile(self) -> None:
        for n, c in _COUNTS:
            p_hat = c / n
            for bound in wilson_interval(n, c):
                if bound in (0.0, 1.0):
                    continue  # clamped: the unclamped root is that endpoint itself
                score = abs(p_hat - bound) * math.sqrt(n / (bound * (1.0 - bound)))
                assert score == pytest.approx(_Z_97_5, rel=1e-9), (
                    f"the {c}/{n} bound {bound} sits at score {score}, not at the 95% quantile"
                )

    def test_it_stays_inside_the_unit_interval(self) -> None:
        for n, c in _COUNTS:
            low, high = wilson_interval(n, c)
            assert 0.0 <= low <= high <= 1.0, f"{c}/{n} reports bounds outside [0, 1]: {(low, high)}"

    def test_it_contains_the_rate_it_bounds(self) -> None:
        for n, c in _COUNTS:
            low, high = wilson_interval(n, c)
            assert low <= c / n <= high, f"{c}/{n} reports an interval excluding its own rate: {(low, high)}"

    def test_the_degenerate_ends_are_taken_from_the_count_not_the_arithmetic(self) -> None:
        """``centre`` and ``half`` are equal at 0/n, so their difference is noise.

        Computed, the low bound came out as ``5.6e-17`` at 0/3 - a nonzero floor
        under a run that never succeeded, which a caller comparing it against another
        run's exact ``0.0`` would read as a difference. The score equation puts the
        root at exactly 0 there, and at exactly 1 at the other end.
        """
        for n in _SIZES:
            assert wilson_interval(n, 0)[0] == 0.0, f"0 of {n} reports a floor above zero"
            assert wilson_interval(n, n)[1] == 1.0, f"{n} of {n} reports a ceiling below one"

    def test_no_successes_still_has_a_width(self) -> None:
        """The defect that rules the textbook interval out, at the end it fails on.

        ``p +/- z*sqrt(p(1-p)/n)`` is ``0 +/- 0`` here, so a policy that failed every
        attempt would publish 0% as a settled fact.
        """
        low, high = wilson_interval(5, 0)
        assert low == 0.0, "a rate of zero cannot be bounded below zero"
        assert high == pytest.approx(0.4345, abs=1e-4), (
            f"0 of 5 attempts bounds the rate at {high}, so five failures are read as near-certainty"
        )

    def test_every_success_still_has_a_width(self) -> None:
        low, high = wilson_interval(5, 5)
        assert high == 1.0, "a rate of one cannot be bounded above one"
        assert low == pytest.approx(0.5655, abs=1e-4), (
            f"5 of 5 attempts bounds the rate at {low}, so five successes are read as near-certainty"
        )

    def test_more_attempts_at_the_same_rate_narrows_it(self) -> None:
        widths = []
        for n in (5, 20, 100, 500):
            low, high = wilson_interval(n, n * 4 // 5)
            widths.append(high - low)
        assert widths == sorted(widths, reverse=True), f"width does not fall as 80% is measured longer: {widths}"

    def test_no_completed_attempt_is_the_whole_range(self) -> None:
        """Nothing was measured, so every rate is still possible - and that is what it says."""
        assert wilson_interval(0, 0) == (0.0, 1.0)


class TestTheClopperPearsonBoundIsWhereTheBinomialTailTurns:
    """Graded by inverting the tail in exact rationals, independently of the solver."""

    def test_the_low_bound_puts_the_observed_count_at_the_tail(self) -> None:
        for n, c in _COUNTS:
            low = clopper_pearson_interval(n, c)[0]
            if c == 0:
                assert low == 0.0, "no successes leaves no lower tail to invert, so the bound is the endpoint"
                continue
            tail = _exact_tail_at_least(c, n, low)
            assert tail == pytest.approx(_ALPHA / 2.0, rel=1e-6), (
                f"at the {c}/{n} low bound {low}, P(X >= {c}) is {tail} rather than {_ALPHA / 2.0}"
            )

    def test_the_high_bound_puts_the_observed_count_at_the_other_tail(self) -> None:
        for n, c in _COUNTS:
            high = clopper_pearson_interval(n, c)[1]
            if c == n:
                assert high == 1.0, "every attempt succeeding leaves no upper tail to invert"
                continue
            tail = 1.0 - _exact_tail_at_least(c + 1, n, high)
            assert tail == pytest.approx(_ALPHA / 2.0, rel=1e-6), (
                f"at the {c}/{n} high bound {high}, P(X <= {c}) is {tail} rather than {_ALPHA / 2.0}"
            )

    def test_no_successes_matches_the_closed_form(self) -> None:
        """At 0/n the interval is ``[0, 1 - (alpha/2) ** (1/n)]`` with nothing to solve."""
        for n in (1, 5, 10, 37):
            low, high = clopper_pearson_interval(n, 0)
            assert low == 0.0
            assert high == pytest.approx(1.0 - (_ALPHA / 2.0) ** (1.0 / n), abs=1e-12), (
                f"0 of {n} disagrees with the closed form"
            )

    def test_every_success_matches_the_closed_form(self) -> None:
        """At n/n it is the mirror, ``[(alpha/2) ** (1/n), 1]``."""
        for n in (1, 5, 10, 37):
            low, high = clopper_pearson_interval(n, n)
            assert high == 1.0
            assert low == pytest.approx((_ALPHA / 2.0) ** (1.0 / n), abs=1e-12), (
                f"{n} of {n} disagrees with the closed form"
            )

    def test_one_success_matches_the_closed_form(self) -> None:
        """At 1/n the low bound is ``1 - (1 - alpha/2) ** (1/n)``, the only other one."""
        for n in (1, 5, 10, 37):
            low = clopper_pearson_interval(n, 1)[0]
            assert low == pytest.approx(1.0 - (1.0 - _ALPHA / 2.0) ** (1.0 / n), abs=1e-12), (
                f"1 of {n} disagrees with the closed form"
            )

    def test_it_is_the_wider_of_the_two_at_every_swept_interior_count(self) -> None:
        """Where the pair's distance is the cost of the normal approximation.

        Width, not containment, is the claim: over these counts the exact interval
        also contains the score one, but that is not a theorem - from 1/97 on, the
        exact high bound at 1/n sits a hair below the score one, correctly.
        """
        for n, c in _COUNTS:
            if c in (0, n):
                continue  # one end is an endpoint, not a tail: see the cell below
            exact_low, exact_high = clopper_pearson_interval(n, c)
            score_low, score_high = wilson_interval(n, c)
            assert exact_high - exact_low > score_high - score_low, (
                f"at {c}/{n} the exact interval {(exact_low, exact_high)} is narrower than the score "
                f"interval {(score_low, score_high)}"
            )

    def test_at_one_outcome_only_the_wider_interval_changes_hands(self) -> None:
        """Pinned because "the conservative one" is the tempting shortcut, and wrong.

        At 0/n and n/n the exact interval has a single open end, and the score
        interval's reaches further than it does from n=46 up. So neither interval can
        be reported as the outer bound of the other, which is the reason the payload
        carries both rather than picking one.
        """
        for n, wider in ((20, "exact"), (45, "exact"), (46, "score"), (500, "score")):
            exact_high = clopper_pearson_interval(n, 0)[1]
            score_high = wilson_interval(n, 0)[1]
            assert ("exact" if exact_high > score_high else "score") == wider, (
                f"at 0/{n} the {wider} interval no longer reaches further: exact {exact_high}, score {score_high}"
            )
            # Both intervals are symmetric under c -> n - c, so the n/n end mirrors it.
            exact_low = clopper_pearson_interval(n, n)[0]
            score_low = wilson_interval(n, n)[0]
            assert ("exact" if exact_low < score_low else "score") == wider, (
                f"at {n}/{n} the ends disagree with the 0/{n} ones: exact {exact_low}, score {score_low}"
            )

    def test_no_completed_attempt_is_the_whole_range(self) -> None:
        assert clopper_pearson_interval(0, 0) == (0.0, 1.0)


class TestTheTailSumSurvivesALongRun:
    """Why the tail is summed through ``lgamma`` rather than through ``math.comb``."""

    def test_the_comb_form_it_replaces_overflows(self) -> None:
        """Pinned, because the motive for the slower-looking sum is invisible otherwise.

        Where it starts, too: at 1,029 trials the largest coefficient still converts to
        a float, and at 1,030 ``comb(1030, 515)`` is already past the largest float.
        """
        assert 0.0 < math.comb(1029, 514) * 0.5**514 * 0.5**515 < 1.0
        with pytest.raises(OverflowError):
            _ = math.comb(1030, 515) * 0.5**515 * 0.5**515

    def test_a_long_run_is_still_bounded(self) -> None:
        low, high = clopper_pearson_interval(5000, 2500)
        assert 0.0 < low < 0.5 < high < 1.0, f"5000 attempts report nonsense bounds: {(low, high)}"
        assert _binomial_tail_at_least(2500, 5000, 0.5) == pytest.approx(
            _exact_tail_at_least(2500, 5000, 0.5), rel=1e-9
        )


class TestThePayloadShape:
    """What an agent reads: JSON-safe values, the level named, and nothing invented."""

    def test_it_carries_both_intervals_and_the_level(self) -> None:
        """A regression pin on the whole dict; the cells above grade the values."""
        assert success_interval(5, 4) == {
            "confidence": _CI_CONFIDENCE,
            "wilson_low": 0.3755,
            "wilson_high": 0.9638,
            "clopper_pearson_low": 0.2836,
            "clopper_pearson_high": 0.9949,
        }

    def test_the_level_is_named_so_the_bounds_read_alone(self) -> None:
        """A pair of numbers with no coverage attached says nothing a reader can act on."""
        assert success_interval(5, 4)["confidence"] == _CI_CONFIDENCE

    def test_no_completed_attempt_reports_nothing(self) -> None:
        """Empty rather than ``[0, 1]``.

        There is no rate to bound, and a vacuous interval beside a ``success_rate`` of
        ``0.0`` reads as a measured one. The rule ``pass_hat_k`` follows there too.
        """
        assert success_interval(0, 0) == {}

    def test_it_survives_a_json_round_trip(self) -> None:
        payload = success_interval(7, 3)
        assert json.loads(json.dumps(payload)) == payload

    def test_every_bound_agrees_with_the_interval_it_came_from(self) -> None:
        payload = success_interval(13, 8)
        assert (payload["wilson_low"], payload["wilson_high"]) == tuple(round(b, 4) for b in wilson_interval(13, 8))
        assert (payload["clopper_pearson_low"], payload["clopper_pearson_high"]) == tuple(
            round(b, 4) for b in clopper_pearson_interval(13, 8)
        )


#: Counts no success rate can be read from, each beside the refusal it earns. A float or
#: ``True`` is refused even when it holds a whole value: a count is an integer, and the
#: shared guard the package's other counts go through says so in the same words.
_UNREADABLE_COUNTS = (
    ((5, 6), "n_success must be at most n_completed (5), got 6."),
    ((0, 1), "n_success must be at most n_completed (0), got 1."),
    ((5, -1), "n_success must be a non-negative integer, got -1."),
    ((-1, 0), "n_completed must be a non-negative integer, got -1."),
    ((5, 2.0), "n_success must be a non-negative integer, got 2.0."),
    ((5.0, 2), "n_completed must be a non-negative integer, got 5.0."),
    ((5, True), "n_success must be a non-negative integer, got True."),
)


class TestCountsNoRateCanBeReadFromAreRefused:
    """``0 <= n_success <= n_completed``, as integers, or a ``ValueError`` naming the count.

    Unchecked, the arithmetic answered instead: 6 of 5 raised a bare ``math domain
    error`` from Wilson's square root and came back from Clopper-Pearson as ``(1.0,
    1.0)``, and -1 completed read as a run that measured nothing. The ends the domain
    keeps - 0 of 0, 0 of n and n of n - are the ones the sweeps above already run on.
    """

    def test_each_public_function_refuses_them_by_name(self) -> None:
        for function in (wilson_interval, clopper_pearson_interval, success_interval):
            for counts, reason in _UNREADABLE_COUNTS:
                try:
                    answer = function(*counts)
                except ValueError as refusal:
                    assert str(refusal) == f"{function.__name__}: {reason}", (
                        f"{function.__name__}{counts} is refused as {str(refusal)!r}"
                    )
                else:
                    pytest.fail(f"{function.__name__}{counts} answered {answer!r} for counts no rate has")


@pytest.fixture
def sim():
    pytest.importorskip("mujoco")
    from strands_robots.simulation.mujoco.simulation import Simulation

    engine = Simulation(tool_name="success_interval_probe", mesh=False)
    yield engine
    engine.destroy()


@pytest.fixture
def arm(tmp_path, sim) -> str:
    """A world holding the probe arm, shared by both rollout surfaces."""
    sim.create_world()
    robot_xml = tmp_path / "probe.xml"
    robot_xml.write_text(_PROBE_XML)
    sim.add_robot("arm1", urdf_path=str(robot_xml))
    return "arm1"


@pytest.fixture
def scoring_task(tmp_path, sim, arm) -> str:
    """A benchmark that scores every step and never succeeds, registered from a file."""
    spec_path = tmp_path / "interval_probe.json"
    spec_path.write_text(
        json.dumps(
            {
                "name": "interval-probe",
                "default_robot": arm,
                "supported_robots": [],
                "max_steps": _MAX_STEPS,
                "dense_reward": [{"predicate": "constant", "value": 0.25}],
            }
        )
    )
    result = sim.register_benchmark_from_file("interval-probe", str(spec_path))
    assert result.get("status") != "error", result
    return "interval-probe"


class _SucceedsForTheFirstAttempts:
    """A ``success_fn`` that approves the first ``budget`` calls it receives.

    ``eval_policy`` asks once at reset, for ``episodes_successful_at_reset``, and then
    after every step, ending the episode as soon as the criterion holds. So a success
    spends two approvals, and a budget of 2 makes the first attempt succeed and the
    rest fail. That buys a chosen split without depending on the probe's physics,
    which is what keeps a failure here attributable to the arithmetic rather than to
    the scene.
    """

    def __init__(self, budget: int) -> None:
        self.budget = budget

    def __call__(self, observation: dict) -> bool:
        if self.budget > 0:
            self.budget -= 1
            return True
        return False


def _metrics(result: dict) -> dict:
    assert result.get("status") != "error", result
    return next(c["json"] for c in result["content"] if "json" in c)


class TestEvalPolicyReportsTheInterval:
    """The ``success_fn`` route, where the rate is a count and nothing else."""

    def _evaluated(
        self, sim, robot: str, *, n_episodes: int, budget: int, on_frame: Callable[..., None] | None = None
    ) -> dict:
        return _metrics(
            sim.eval_policy(
                robot_name=robot,
                policy_provider="mock",
                n_episodes=n_episodes,
                max_steps=_MAX_STEPS,
                success_fn=_SucceedsForTheFirstAttempts(budget),
                on_frame=on_frame,
                seed=0,
            )
        )

    def test_a_measured_evaluation_reports_it(self, sim, arm) -> None:
        metrics = self._evaluated(sim, arm, n_episodes=5, budget=2)
        assert metrics["success_measured"] is True, "the probe measured nothing, so nothing is owed"
        assert "success_rate_ci" in metrics, (
            f"an evaluation of {metrics['episodes_completed']} attempts reports "
            f"success_rate={metrics['success_rate']} with no bounds on it"
        )

    def test_the_bounds_agree_with_the_payloads_own_counts(self, sim, arm) -> None:
        """Graded against the helper applied to the counts reported beside them.

        Independent of how many attempts the criterion happened to end, so the cell
        pins the wiring rather than the probe.
        """
        metrics = self._evaluated(sim, arm, n_episodes=5, budget=2)
        completed, successes = metrics["episodes_completed"], metrics["n_success"]
        assert 0 < successes < completed, f"{successes}/{completed} is degenerate, so a 0-or-1 interval would pass"
        assert metrics["success_rate_ci"] == success_interval(completed, successes)

    def test_the_interval_brackets_the_rate_it_qualifies(self, sim, arm) -> None:
        metrics = self._evaluated(sim, arm, n_episodes=5, budget=2)
        bounds = metrics["success_rate_ci"]
        assert bounds["wilson_low"] <= metrics["success_rate"] <= bounds["wilson_high"]
        assert bounds["clopper_pearson_low"] <= metrics["success_rate"] <= bounds["clopper_pearson_high"]

    def test_an_unmeasured_evaluation_reports_nothing(self, sim, arm) -> None:
        """No criterion means no bounds, for the reason there is no rate either.

        Without a ``success_fn`` every attempt counts as a failure for a reason
        unrelated to the policy, so an interval around that hard ``0.0`` would qualify
        a number that measured nothing - the gate ``pass_hat_k`` already sits behind.
        """
        metrics = _metrics(
            sim.eval_policy(robot_name=arm, policy_provider="mock", n_episodes=3, max_steps=_MAX_STEPS, seed=0)
        )
        assert metrics["success_measured"] is False
        assert "success_rate_ci" not in metrics
        assert "pass_hat_k" not in metrics, "the two keys no longer share a gate"

    def test_a_run_stopped_before_any_episode_completed_reports_no_bounds(self, sim, arm) -> None:
        """Measured, and still nothing to bound: the other gate, reached through a rollout.

        ``on_frame`` stops the run at its first applied step, so a criterion is in force
        and no episode completed. The key is then empty rather than ``[0, 1]``, the shape
        ``pass_hat_k`` takes there too.
        """

        def stop_at_once(step: int, observation: dict, action: dict) -> None:
            raise CooperativeStop("stopped before the first episode completed")

        metrics = self._evaluated(sim, arm, n_episodes=3, budget=0, on_frame=stop_at_once)
        assert (metrics["success_measured"], metrics["episodes_completed"]) == (True, 0), metrics
        assert metrics["success_rate_ci"] == {}
        assert metrics["pass_hat_k"] == {}, "the two keys no longer share a gate"

    def test_the_payload_survives_json(self, sim, arm) -> None:
        metrics = self._evaluated(sim, arm, n_episodes=3, budget=1)
        assert json.loads(json.dumps(metrics))["success_rate_ci"] == metrics["success_rate_ci"]


class TestEvaluateBenchmarkReportsTheInterval:
    """The other rollout surface, where a success criterion is always in force."""

    def test_it_reports_bounds_beside_the_rate(self, sim, scoring_task) -> None:
        metrics = _metrics(sim.evaluate_benchmark(scoring_task, policy_provider="mock", n_episodes=3, seed=0))
        completed, successes = metrics["episodes_completed"], metrics["n_success"]
        assert completed > 0, "no attempt completed, so the interval is vacuous by construction"
        assert metrics["success_rate_ci"] == success_interval(completed, successes)

    def test_a_run_of_failures_is_not_reported_as_settled(self, sim, scoring_task) -> None:
        """The probe never succeeds, which is the end the textbook interval loses.

        A zero rate with no width is what invites "this policy does not work" after
        three attempts; the bound says how little three attempts settled.
        """
        metrics = _metrics(sim.evaluate_benchmark(scoring_task, policy_provider="mock", n_episodes=3, seed=0))
        assert metrics["success_rate"] == 0.0, "the probe succeeded, so this cell no longer covers the zero end"
        bounds = metrics["success_rate_ci"]
        assert bounds["wilson_low"] == 0.0
        assert bounds["wilson_high"] > 0.3, f"3 failures bounded the rate at {bounds['wilson_high']}"
        assert bounds["clopper_pearson_high"] > bounds["wilson_high"]

    def test_the_payload_survives_json(self, sim, scoring_task) -> None:
        metrics = _metrics(sim.evaluate_benchmark(scoring_task, policy_provider="mock", n_episodes=2, seed=0))
        assert json.loads(json.dumps(metrics))["success_rate_ci"] == metrics["success_rate_ci"]
