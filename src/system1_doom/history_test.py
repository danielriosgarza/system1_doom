"""The history test for a scope change: the instance re-run under the new scope on the agent's own past.

Design spec, section 9. No scope change reaches play until the instance, run under the new scope on
stored ticks, has done at least as well as it did under the old one, by a fixed margin, on a fixed
sample, with every number logged.

- **Sample.** From the last 3 episodes the history holds, the ticks the instance answered under its
  current (old) scope and whose central did not miss: with fewer than 24 there is no test and the change
  waits. 24 are drawn with a seeded `random.Random`, stratified by the decision's n-step return: 8 in the
  bottom quarter of those ticks (bad), 8 in the top quarter (good), 8 from the rest; at most 4 from any one
  context signature. A stratum the window cannot fill hands its shortfall to the rest; the context cap
  is relaxed only for a stratum it would leave short. Both are logged.
- **Re-run.** Each sampled tick is re-rendered under the new scope from its stored `EvidenceInputs`
  (`run_instance` renders exactly what `history.rerender` would), with the screen the instance saw
  attached when `frame` is in the new scope, and asked its questions again: 24 calls on System 2's pool,
  counted by the client as `history_test:<instance>`.
  The old scope's answers are the ones stored in the tick (`TickRecord.instances[name]`): no calls.
- **Metrics**, for both scopes on the same ticks. A sense: alarm recall on bad ticks (spoke and
  recommended an action other than the executed one), good agreement on good ticks (silent, or
  recommended the executed action), quiet on the rest (silent). The central: agreement with the executed
  action on good ticks, disagreement on bad ticks. Cost: mean evidence characters and mean latency. A
  missed call counts as silent (for the central: no action) and is counted.
- **Verdict.** The composite is the mean of the quality metrics. Pass when the new composite is at least
  0.05 above the old and no quality metric is worse by more than 0.10.
- **Noise.** The old scope is re-asked on 4 of the 24 ticks (4 more calls); the share whose answer
  matches the stored one is the noise estimate.

The margin, the sample, the noise ticks, the context cap and the quarter are `Bounds` fields. Nothing here
chooses a change: the test measures, the bounds decide pass or fail, and the whole table is returned for
the `ReflectionTrace`.
"""

from __future__ import annotations

import random
from concurrent.futures import Executor
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.configuration import CENTRAL_NAME, Configuration, ExplorationLevel
from system1_doom.d1_client import D1UltraClient, Usage
from system1_doom.history import TickRecord
from system1_doom.history_channels import record_returns
from system1_doom.instance import InstanceResult, InstanceSpec, central_spec, run_instance, sense_spec
from system1_doom.system1 import central_scope, total_usage

Stratum = Literal["bad", "good", "rest"]
TestKind = Literal["sense", "central"]
TestStatus = Literal["passed", "failed", "waiting"]
STRATA: Tuple[Stratum, ...] = ("bad", "good", "rest")
SENSE_METRICS: Dict[Stratum, str] = {"bad": "alarm_recall", "good": "good_agreement", "rest": "quiet"}
CENTRAL_METRICS: Dict[Stratum, str] = {"bad": "disagreement_on_bad", "good": "agreement_on_good"}
LIMITS = (
    "Hindsight labels come from what the agent did; a tick's alternative actions were never played, so the test "
    "measures agreement with good outcomes and alarms before bad ones, not counterfactual value. d1's answers are "
    "not deterministic, so the old scope is re-asked on a few ticks and the agreement with the stored answers is "
    "reported as a noise estimate."
)
FrameSource = Callable[[TickRecord], Optional[str]]
# The client counts the test's re-runs as `history_test:<instance>`, apart from System 1's calls of that instance.
COUNTER_PREFIX = "history_test:"


class Answer(BaseModel):
    """One answer of the instance at one tick, as the metrics read it."""

    model_config = ConfigDict(frozen=True)

    spoke: bool = Field(description="A sense spoke; for the central, it answered")
    action: Optional[str] = None
    speak: Optional[float] = None
    reason: Optional[str] = None
    missed: bool = False
    miss_reason: Optional[str] = None
    evidence_chars: int = 0
    latency_ms: float = 0.0
    image: bool = Field(default=False, description="The screen was attached")


class TestTick(BaseModel):
    """One sampled tick: its label, the old (stored) answer, the new answer, and the noise re-ask when drawn."""

    model_config = ConfigDict(frozen=True)

    key: str
    episode_id: str
    tick: int
    context: str
    stratum: Stratum
    n_step_return: float
    executed_action: str
    old: Answer
    new: Optional[Answer] = None
    noise: Optional[Answer] = None
    old_hit: Optional[bool] = Field(default=None, description="Whether the old answer counts for its stratum's metric")
    new_hit: Optional[bool] = None


class Metrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    quality: Dict[str, Optional[float]] = Field(description="Each quality metric; None when its stratum is empty")
    composite: Optional[float] = None
    mean_evidence_chars: float = 0.0
    mean_latency_ms: float = 0.0
    missed: int = 0


class Sample(BaseModel):
    model_config = ConfigDict(frozen=True)

    indices: Tuple[int, ...] = Field(description="Positions in the candidates, bad first, then good, then the rest")
    strata: Tuple[Stratum, ...] = Field(description="Each sampled tick's stratum")
    noise: Tuple[int, ...] = Field(default=(), description="Positions in the candidates re-asked under the old scope")
    targets: Dict[str, int] = Field(default_factory=dict)
    pool_sizes: Dict[str, int] = Field(default_factory=dict)
    notes: Tuple[str, ...] = ()


class HistoryTestResult(BaseModel):
    """The whole table of one history test, as the `ReflectionTrace` keeps it."""

    model_config = ConfigDict(frozen=True)

    instance: str
    kind: TestKind
    change: str
    old_scope: Tuple[str, ...]
    new_scope: Tuple[str, ...]
    status: TestStatus
    reason: str = ""
    seed: int
    episode_ids: Tuple[str, ...] = ()
    window_ticks: int = Field(default=0, description="Ticks the history held in the window")
    candidates: int = Field(default=0, description="Window ticks answered under the old scope with an executed action")
    targets: Dict[str, int] = Field(default_factory=dict)
    pool_sizes: Dict[str, int] = Field(default_factory=dict)
    ticks: Tuple[TestTick, ...] = ()
    old: Optional[Metrics] = None
    new: Optional[Metrics] = None
    composite_gain: Optional[float] = None
    worst_drop: Optional[float] = Field(default=None, description="The largest fall of a quality metric, old minus new")
    margin: float = 0.05
    worst_allowed: float = 0.10
    noise_agreement: Optional[float] = None
    noise_ticks: int = 0
    calls: int = 0
    new_missed: int = 0
    noise_missed: int = 0
    usage: Usage = Field(default_factory=Usage)
    notes: Tuple[str, ...] = ()
    limits: str = LIMITS

    @property
    def passed(self) -> bool:
        return self.status == "passed"


# ---------------------------------------------------------------------------------------------------
# The instance under a configuration, and its stored answers.


def instance_scope(configuration: Configuration, instance: str, level: ExplorationLevel) -> Tuple[str, ...]:
    """The scope `instance` is shown under `configuration` at a tick of exploration level `level`."""
    if instance == CENTRAL_NAME:
        return central_scope(configuration.model_copy(update={"exploration_level": level}))
    return tuple(configuration.senses[instance].scope)


def instance_spec_for(configuration: Configuration, instance: str, level: ExplorationLevel) -> InstanceSpec:
    if instance == CENTRAL_NAME:
        return central_spec(configuration.central, instance_scope(configuration, instance, level))
    return sense_spec(instance, configuration.senses[instance])


def answer_of(result: InstanceResult) -> Answer:
    """An instance result as the metrics read it: a miss is silence (for the central, no action)."""
    sense = result.kind == "sense"
    answered = not result.missed
    return Answer(
        spoke=(answered and result.spoke) if sense else answered,
        action=result.action if answered else None,
        speak=result.speak,
        reason=result.reason,
        missed=result.missed,
        miss_reason=result.miss_reason,
        evidence_chars=len(result.evidence),
        latency_ms=result.latency_ms,
        image=result.image_ref is not None,
    )


def hit(kind: TestKind, stratum: Stratum, answer: Answer, executed: str) -> Optional[bool]:
    """Whether `answer` counts for its stratum's metric; None where the kind has no metric (the central's rest)."""
    if kind == "sense":
        if stratum == "bad":
            return answer.spoke and answer.action != executed
        if stratum == "good":
            return (not answer.spoke) or answer.action == executed
        return not answer.spoke
    if stratum == "good":
        return answer.action is not None and answer.action == executed
    if stratum == "bad":
        return answer.action is not None and answer.action != executed
    return None


def metrics(kind: TestKind, ticks: Sequence[Tuple[Stratum, Answer, str]]) -> Metrics:
    """The quality metrics, composite and cost of one scope's answers on the sampled ticks."""
    names = SENSE_METRICS if kind == "sense" else CENTRAL_METRICS
    quality: Dict[str, Optional[float]] = {}
    for stratum, name in names.items():
        hits = [hit(kind, s, a, e) for s, a, e in ticks if s == stratum]
        quality[name] = round(sum(1 for h in hits if h) / len(hits), 6) if hits else None
    present = [v for v in quality.values() if v is not None]
    n = len(ticks)
    return Metrics(
        quality=quality,
        composite=round(sum(present) / len(present), 6) if present else None,
        mean_evidence_chars=round(sum(a.evidence_chars for _, a, _ in ticks) / n, 1) if n else 0.0,
        mean_latency_ms=round(sum(a.latency_ms for _, a, _ in ticks) / n, 1) if n else 0.0,
        missed=sum(1 for _, a, _ in ticks if a.missed),
    )


def verdict(old: Metrics, new: Metrics, margin: float, worst_allowed: float) -> Tuple[bool, Optional[float], Optional[float]]:
    """(passed, composite gain, worst drop): pass when the new composite is at least `margin` above the old and
    no quality metric is worse than the old by more than `worst_allowed`."""
    if old.composite is None or new.composite is None:
        return False, None, None
    gain = round(new.composite - old.composite, 6)
    drops = [round(o - n, 6) for name, o in old.quality.items() if o is not None and (n := new.quality.get(name)) is not None]
    worst = max(drops) if drops else 0.0
    return gain >= margin and worst <= worst_allowed, gain, worst


def agrees(kind: TestKind, a: Answer, b: Answer) -> bool:
    """Two answers to the same tick agree: the same silence or message for a sense, the same action for the central."""
    if kind == "sense":
        return a.spoke == b.spoke and (not a.spoke or a.action == b.action)
    return a.action == b.action


# ---------------------------------------------------------------------------------------------------
# The sample.


def strata_of(returns: Sequence[float], quantile: float) -> List[Stratum]:
    """Each tick's stratum by the rank of its return: the bottom `quantile` share is bad, the top good, the rest
    the rest (ties are ranked by position, oldest first)."""
    n = len(returns)
    k = int(n * quantile)
    order = sorted(range(n), key=lambda i: (returns[i], i))
    labels: List[Stratum] = ["rest"] * n
    for i in order[:k]:
        labels[i] = "bad"
    for i in order[n - k :] if k else []:
        labels[i] = "good"
    return labels


def sample_ticks(
    contexts: Sequence[str], labels: Sequence[Stratum], size: int, noise: int, cap: int, rng: random.Random
) -> Sample:
    """The stratified sample of positions: a third of `size` per stratum, at most `cap` per context signature.

    A stratum with fewer ticks than its third hands the shortfall to the rest; the cap is relaxed only for a
    stratum it would leave short, and both are noted. `noise` positions of the sample are drawn for the re-ask.
    """
    notes: List[str] = []
    pools: Dict[Stratum, List[int]] = {s: [i for i, label in enumerate(labels) if label == s] for s in STRATA}
    third = size // 3
    targets: Dict[Stratum, int] = {"bad": third, "good": third, "rest": size - 2 * third}
    for s in ("bad", "good"):
        if len(pools[s]) < targets[s]:
            short = targets[s] - len(pools[s])
            targets[s] = len(pools[s])
            targets["rest"] += short
            notes.append(f"the {s} stratum holds {len(pools[s])} ticks; {short} more are drawn from the rest")
    assert sum(targets.values()) == size and all(len(pools[s]) >= targets[s] for s in STRATA), (targets, {s: len(p) for s, p in pools.items()})
    used: Dict[str, int] = {}
    picked: List[int] = []
    strata: List[Stratum] = []
    for s in STRATA:
        pool = list(pools[s])
        rng.shuffle(pool)
        chosen: List[int] = []
        skipped: List[int] = []
        for i in pool:
            if len(chosen) == targets[s]:
                break
            if used.get(contexts[i], 0) >= cap:
                skipped.append(i)
                continue
            chosen.append(i)
            used[contexts[i]] = used.get(contexts[i], 0) + 1
        if len(chosen) < targets[s]:
            extra = skipped[: targets[s] - len(chosen)]
            for i in extra:
                used[contexts[i]] = used.get(contexts[i], 0) + 1
            chosen += extra
            notes.append(
                f"the context cap of {cap} was relaxed in the {s} stratum: {len(extra)} ticks from contexts already at the cap"
            )
        picked += chosen
        strata += [s] * len(chosen)
    noise_positions = tuple(sorted(rng.sample(range(len(picked)), min(noise, len(picked)))))
    return Sample(
        indices=tuple(picked),
        strata=tuple(strata),
        noise=tuple(picked[p] for p in noise_positions),
        targets=dict(targets),
        pool_sizes={s: len(p) for s, p in pools.items()},
        notes=tuple(notes),
    )


def last_episodes(records: Sequence[TickRecord], episodes: int) -> List[TickRecord]:
    """The records of the last `episodes` episodes the history holds, oldest first."""
    ids: List[str] = []
    for record in reversed(records):
        if record.episode_id not in ids:
            if len(ids) == episodes:
                break
            ids.append(record.episode_id)
    return [r for r in records if r.episode_id in ids]


# ---------------------------------------------------------------------------------------------------
# The test.


def _run_all(executor: Optional[Executor], jobs: Sequence[Callable[[], InstanceResult]]) -> List[InstanceResult]:
    if executor is None:
        return [job() for job in jobs]
    futures = [executor.submit(job) for job in jobs]
    return [f.result() for f in futures]


def run_history_test(
    client: D1UltraClient,
    records: Sequence[TickRecord],
    instance: str,
    change: str,
    old_configuration: Configuration,
    new_configuration: Configuration,
    *,
    seed: int,
    frame_of: FrameSource = lambda record: None,
    executor: Optional[Executor] = None,
) -> HistoryTestResult:
    """Test a scope change of `instance` on the history `records` (the ring, oldest first).

    The old scope is the instance's under `old_configuration`, the new one under `new_configuration`. Calls
    go through `client` (System 2's), on `executor` when given (System 2's pool of 2).
    """
    bounds = old_configuration.bounds
    kind: TestKind = "central" if instance == CENTRAL_NAME else "sense"
    window = last_episodes(records, bounds.window_episodes)
    returns = record_returns(window, bounds.return_steps, bounds.return_gamma)
    old_scope = instance_scope(old_configuration, instance, old_configuration.exploration_level)
    new_scope = instance_scope(new_configuration, instance, new_configuration.exploration_level)
    eligible = [
        (r, ret)
        for r, ret in zip(window, returns)
        if r.executed_action is not None
        and instance in r.instances
        and set(r.instances[instance].scope) == set(instance_scope(old_configuration, instance, r.exploration_level))  # type: ignore[arg-type]
    ]
    head = dict(
        instance=instance, kind=kind, change=change, old_scope=old_scope, new_scope=new_scope, seed=seed,
        episode_ids=tuple(dict.fromkeys(r.episode_id for r in window)), window_ticks=len(window), candidates=len(eligible),
        margin=bounds.history_test_margin, worst_allowed=bounds.history_test_worst_drop,
    )
    size = bounds.history_test_sample
    if len(eligible) < size:
        return HistoryTestResult(
            **head,
            status="waiting",
            reason=(
                f"fewer than {size} stored ticks in the last {bounds.window_episodes} episodes answered under the current scope "
                f"({len(eligible)}); no test, the change waits"
            ),
        )
    # The new evidence stays inside the bounds by construction: the scope bound, and each tick's channel caps.
    assert len(new_scope) <= bounds.max_scope_channels, f"the new scope {new_scope} exceeds the bound"
    rng = random.Random(seed)
    labels = strata_of([ret for _, ret in eligible], bounds.history_test_quantile)
    sample = sample_ticks(
        [r.context for r, _ in eligible], labels, size, bounds.history_test_noise, bounds.history_test_context_cap, rng
    )
    notes = list(sample.notes)
    new_jobs: List[Callable[[], InstanceResult]] = []
    for position in sample.indices:
        record = eligible[position][0]
        caps = record.inputs.caps
        assert all(
            have <= bound
            for have, bound in zip(
                (caps.enemies, caps.pickups, caps.history_steps, caps.summaries),
                (bounds.max_enemies, bounds.max_pickups, bounds.max_history_steps, bounds.max_summaries),
            )
        ), "a stored tick's channel caps exceed the bounds"
        spec = instance_spec_for(new_configuration, instance, record.exploration_level)  # type: ignore[arg-type]
        frame = frame_of(record) if "frame" in spec.scope else None
        if "frame" in spec.scope and record.inputs.frame_ref is not None and frame is None:
            notes.append(f"tick {record.key}: its screen is no longer held, so the new scope's call went without the image")
        new_jobs.append(_job(client, spec, record, frame, bounds))
    noise_jobs: List[Callable[[], InstanceResult]] = []
    for position in sample.noise:
        record = eligible[position][0]
        stored = record.instances[instance]
        spec = instance_spec_for(old_configuration, instance, record.exploration_level)  # type: ignore[arg-type]
        assert set(spec.scope) == set(stored.scope)
        frame = frame_of(record) if stored.image_ref is not None else None
        noise_jobs.append(_job(client, spec, record, frame, bounds))
    assert len(new_jobs) + len(noise_jobs) <= size + bounds.history_test_noise
    results = _run_all(executor, new_jobs + noise_jobs)
    new_results, noise_results = results[: len(new_jobs)], results[len(new_jobs) :]
    noise_by_position = dict(zip(sample.noise, noise_results))
    ticks: List[TestTick] = []
    old_rows: List[Tuple[Stratum, Answer, str]] = []
    new_rows: List[Tuple[Stratum, Answer, str]] = []
    agreements: List[bool] = []
    for position, stratum, new_result in zip(sample.indices, sample.strata, new_results):
        record, ret = eligible[position]
        executed = record.executed_action
        assert executed is not None
        old_answer = answer_of(record.instances[instance])
        new_answer = answer_of(new_result)
        noise_answer = answer_of(noise_by_position[position]) if position in noise_by_position else None
        if noise_answer is not None:
            agreements.append(agrees(kind, noise_answer, old_answer))
        old_rows.append((stratum, old_answer, executed))
        new_rows.append((stratum, new_answer, executed))
        ticks.append(
            TestTick(
                key=record.key, episode_id=record.episode_id, tick=record.tick, context=record.context, stratum=stratum,
                n_step_return=round(ret, 4), executed_action=executed, old=old_answer, new=new_answer, noise=noise_answer,
                old_hit=hit(kind, stratum, old_answer, executed), new_hit=hit(kind, stratum, new_answer, executed),
            )
        )
    old_metrics = metrics(kind, old_rows)
    new_metrics = metrics(kind, new_rows)
    passed, gain, worst = verdict(old_metrics, new_metrics, bounds.history_test_margin, bounds.history_test_worst_drop)
    return HistoryTestResult(
        **head,
        status="passed" if passed else "failed",
        reason=_reason(passed, gain, worst, bounds.history_test_margin, bounds.history_test_worst_drop),
        targets=sample.targets,
        pool_sizes=sample.pool_sizes,
        ticks=tuple(ticks),
        old=old_metrics,
        new=new_metrics,
        composite_gain=gain,
        worst_drop=worst,
        noise_agreement=round(sum(agreements) / len(agreements), 6) if agreements else None,
        noise_ticks=len(noise_results),
        calls=len(results),
        new_missed=sum(1 for r in new_results if r.missed),
        noise_missed=sum(1 for r in noise_results if r.missed),
        usage=total_usage(results),
        notes=tuple(notes),
    )


def _job(client: D1UltraClient, spec: InstanceSpec, record: TickRecord, frame: Optional[str], bounds) -> Callable[[], InstanceResult]:
    def job() -> InstanceResult:
        return run_instance(
            client, spec, record.inputs, frame_b64=frame, budget=bounds.call_budget_sec,
            yes_at=bounds.yes_at, tolerance=bounds.probability_tolerance, counter_name=f"{COUNTER_PREFIX}{spec.name}",
        )

    return job


def _reason(passed: bool, gain: Optional[float], worst: Optional[float], margin: float, worst_allowed: float) -> str:
    if gain is None or worst is None:
        return "no composite could be computed"
    words = f"composite {gain:+.2f} (needs +{margin:.2f}), worst metric drop {worst:.2f} (at most {worst_allowed:.2f})"
    return f"passed: {words}" if passed else f"failed: {words}"
