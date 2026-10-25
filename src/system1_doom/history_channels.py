"""History channels: what System 2's instances are shown, rendered as plain text from the history.

Design spec, section 8. System 2's evidence is System 1's history, shown over three windows at once: the
last 20 decisions, the last 100, and the last 3 episodes, as the history holds them (fewer when there are
fewer), so a short-lived problem and a long trend both have a view. Every channel reads one
`HistoryInputs`, built once per cycle from the history ring, the configuration, the strategy archive and
System 2's own record (its change log, the trial in flight, cooling, recent tests and verdicts).

| Channel | What it renders |
| --- | --- |
| `h_outcomes` | per window: decisions, reward, kills, deaths, damage taken, stalls, missed ticks |
| `h_sense:<name>` | per window: spoke, followed, paid off, overruled, calibration, misses; the scope, what it could add and drop |
| `h_central` | per window: followed the strongest message, picks that paid off, ties, misses; the scope, what it could add and drop |
| `h_actions` | per window: each action's count and mean return; actions never executed; admitted macros and their record |
| `h_strategy` | the archive, and per window the decisions under each strategy with their mean return |
| `h_exploration` | the level; per window: the share of less-tried actions taken, drawn picks, the progress trend |
| `h_config` | the configuration version, the change log, the trial in flight, cooling per instance |
| `h_tests` | recent history tests and trial verdicts |
| `messages` | System 2's central only: the reflectors' proposals this cycle |

"Paid off" is the decision's n-step return (`relevance.decision_returns`, n 8, discount 0.9 by the bounds)
being positive, computed per episode over the stored ticks. Rendering is deterministic: one renderer per
channel, each under a `[name]` header, in the fixed order of `HISTORY_CHANNELS`, like `evidence.py`.
Nothing here ranks or scores a change or an action: lists follow the menu's, the archive's or the
configuration's own order.
"""

from __future__ import annotations

from functools import partial
from itertools import groupby
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.configuration import CENTRAL_NAME, SENSE_NAMES, Bounds, Configuration, reason_words
from system1_doom.evidence import StrategyLine
from system1_doom.history import TickRecord
from system1_doom.reflectors import COOLING_KEYS, SYSTEM2_KEY, Proposal, addable, droppable, scope_of
from system1_doom.relevance import decision_returns

WINDOW_NAMES: Tuple[str, ...] = ("recent", "long", "episodes")
HISTORY_CHANNELS: Tuple[str, ...] = (
    "messages",
    "h_outcomes",
    *(f"h_sense:{name}" for name in SENSE_NAMES),
    "h_central",
    "h_actions",
    "h_strategy",
    "h_exploration",
    "h_config",
    "h_tests",
)
CHANGE_LOG_SHOWN = 6
TESTS_SHOWN = 4


# ---------------------------------------------------------------------------------------------------
# System 2's own record, as the channels show it (system2.py keeps and saves it).


class ChangeLogEntry(BaseModel):
    """One configuration version: what changed, who changed it, and what became of it."""

    model_config = ConfigDict(frozen=True)

    version: int
    change: str = Field(description="A change id, 'revert:<change id>', or what changed when System 2 did not make it")
    by: str = Field(description="system 2, revert, safety revert, revert with no verdict, slow path, or outside System 2")
    cycle_id: Optional[str] = None
    decision: int = Field(default=0, description="System 2's decision count when the version took effect")
    status: str = Field(default="applied", description="trial, kept, reverted, or applied")


class TrialStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    cycle_id: str
    change: str
    version: int
    observed: int
    of: int


class HistoryTestSummary(BaseModel):
    """One history test as `h_tests` lists it."""

    model_config = ConfigDict(frozen=True)

    cycle_id: str
    change: str
    status: str = Field(description="passed, failed, or waiting")
    old_composite: Optional[float] = None
    new_composite: Optional[float] = None
    noise_agreement: Optional[float] = None
    note: str = ""


class VerdictSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    cycle_id: str
    change: str
    version: int
    verdict: str = Field(description="keep or revert")
    by: str = Field(description="the trial judge, the safety bound, or no verdict")


class System2Status(BaseModel):
    """What `h_config` and `h_tests` render of System 2's own record."""

    model_config = ConfigDict(frozen=True)

    decisions: int = 0
    cooling_left: Dict[str, int] = Field(default_factory=dict, description="Cooling key -> decisions left")
    change_log: Tuple[ChangeLogEntry, ...] = ()
    trial: Optional[TrialStatus] = None
    pending: Optional[str] = Field(default=None, description="A change queued or asked for, not yet in play")
    tests: Tuple[HistoryTestSummary, ...] = ()
    verdicts: Tuple[VerdictSummary, ...] = ()


# ---------------------------------------------------------------------------------------------------
# Windows and returns.


class Window(BaseModel):
    """One of the three windows, as the history held it."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="recent, long or episodes")
    label: str = Field(description="How the channels name it")
    wanted: int = Field(description="Decisions (recent, long) or episodes (episodes) the window asks for")
    decisions: int
    episode_ids: Tuple[str, ...] = ()
    first: Optional[str] = Field(default=None, description="The first record's key, <episode id>:<tick>")
    last: Optional[str] = None

    def held(self) -> str:
        """The label with what the history held when it held fewer than the window asks for."""
        if self.name == "episodes":
            n = len(self.episode_ids)
            short = f"only {n} held, " if n < self.wanted else ""
            return f"{self.label} ({short}{self.decisions} decision{'' if self.decisions == 1 else 's'})"
        return self.label if self.decisions >= self.wanted else f"{self.label} (only {self.decisions} held)"


def record_returns(records: Sequence[TickRecord], steps: int, gamma: float) -> List[float]:
    """Each record's n-step return, computed over its own episode's stored ticks, in record order."""
    out: List[float] = []
    for _, group in groupby(records, key=lambda r: r.episode_id):
        episode = list(group)
        out.extend(decision_returns([r.reward for r in episode], steps, gamma))
    return out


def window_indices(records: Sequence[TickRecord], bounds: Bounds) -> List[Tuple[Window, Tuple[int, ...]]]:
    """The three windows over `records` (oldest first), each with the indices of its records."""
    n = len(records)

    def window(name: str, label: str, wanted: int, idx: Sequence[int]) -> Tuple[Window, Tuple[int, ...]]:
        ids: List[str] = []
        for i in idx:
            if records[i].episode_id not in ids:
                ids.append(records[i].episode_id)
        return (
            Window(
                name=name, label=label, wanted=wanted, decisions=len(idx), episode_ids=tuple(ids),
                first=records[idx[0]].key if idx else None, last=records[idx[-1]].key if idx else None,
            ),
            tuple(idx),
        )

    recent = list(range(max(0, n - bounds.window_recent), n))
    long = list(range(max(0, n - bounds.window_long), n))
    episodes: List[str] = []
    for record in reversed(records):
        if record.episode_id not in episodes:
            if len(episodes) == bounds.window_episodes:
                break
            episodes.append(record.episode_id)
    by_episode = [i for i, r in enumerate(records) if r.episode_id in episodes]
    return [
        window("recent", f"last {bounds.window_recent} decisions", bounds.window_recent, recent),
        window("long", f"last {bounds.window_long} decisions", bounds.window_long, long),
        window("episodes", f"last {bounds.window_episodes} episodes", bounds.window_episodes, by_episode),
    ]


class HistoryInputs(BaseModel):
    """Everything any history channel renders from, for one System 2 cycle."""

    model_config = ConfigDict(frozen=True)

    records: Tuple[TickRecord, ...] = Field(description="The records the windows cover, oldest first")
    returns: Tuple[float, ...] = Field(description="Each record's n-step return, per episode")
    windows: Tuple[Window, ...]
    indices: Tuple[Tuple[int, ...], ...] = Field(description="Each window's record indices")
    configuration: Configuration
    archive: Tuple[StrategyLine, ...] = ()
    status: System2Status = Field(default_factory=System2Status)
    proposals: Tuple[Proposal, ...] = ()

    def window_records(self) -> List[Tuple[Window, List[int]]]:
        return [(w, list(idx)) for w, idx in zip(self.windows, self.indices)]

    def union(self) -> List[int]:
        """Every index any window covers, in record order."""
        return sorted({i for idx in self.indices for i in idx})

    def paid(self, i: int) -> bool:
        return self.returns[i] > 0.0


def history_inputs(
    ring: Sequence[TickRecord],
    configuration: Configuration,
    *,
    archive: Sequence[StrategyLine] = (),
    status: Optional[System2Status] = None,
    proposals: Sequence[Proposal] = (),
) -> HistoryInputs:
    """The inputs of one cycle: the windows over the ring, the returns, and System 2's own record."""
    bounds = configuration.bounds
    full = window_indices(ring, bounds)
    covered = sorted({i for _, idx in full for i in idx})
    records = [ring[i] for i in covered]
    position = {old: new for new, old in enumerate(covered)}
    windows = [w for w, _ in full]
    indices = tuple(tuple(position[i] for i in idx) for _, idx in full)
    return HistoryInputs(
        records=tuple(records),
        returns=tuple(record_returns(records, bounds.return_steps, bounds.return_gamma)),
        windows=tuple(windows),
        indices=indices,
        configuration=configuration,
        archive=tuple(archive),
        status=status or System2Status(),
        proposals=tuple(proposals),
    )


# ---------------------------------------------------------------------------------------------------
# Small deterministic phrases.


def _num(value: float, places: int = 0) -> str:
    text = f"{value:.{places}f}"
    return text[1:] if text.startswith("-") and float(text) == 0.0 else text


def _signed(value: float) -> str:
    text = f"{value:+.2f}"
    return "+0.00" if text == "-0.00" else text


def _mean(total: float, n: int, thin: int) -> str:
    """A mean, shown with its count when the count is under the thin-record bound, as relevance does."""
    if n == 0:
        return "n/a"
    mean = f"{total / n:.2f}"
    return mean if n >= thin else f"{mean} over {n} tick{'' if n == 1 else 's'}"


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole}" + (f" ({part / whole:.2f})" if whole else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _no_history(inp: HistoryInputs) -> Optional[List[str]]:
    return ["no decision is stored yet"] if not inp.records else None


def _scope_lines(inp: HistoryInputs, instance: str) -> List[str]:
    configuration = inp.configuration
    scope = scope_of(configuration, instance)
    bound = configuration.bounds.max_scope_channels
    add = addable(configuration, instance)
    drop = droppable(configuration, instance)
    note = "; novelty is added while the level is explore and there is room" if instance == CENTRAL_NAME else ""
    if len(scope) >= bound:
        could_add = f"could add: nothing while the scope holds {bound} channels, the bound"
    else:
        could_add = f"could add: {', '.join(add)}" if add else "could add: nothing"
    return [
        f"scope now ({len(scope)} of {bound} channels): {', '.join(scope)}{note}",
        could_add,
        f"could drop: {', '.join(drop)}" if drop else "could drop: nothing (menu stays)",
    ]


PAID_OFF = "paid off: the decision's {n}-step return (discount {g}) was positive"


def _paid_off(inp: HistoryInputs) -> str:
    b = inp.configuration.bounds
    return PAID_OFF.format(n=b.return_steps, g=f"{b.return_gamma:g}")


# ---------------------------------------------------------------------------------------------------
# One renderer per channel. Each returns the body lines under the channel's header.


def _h_outcomes(inp: HistoryInputs) -> List[str]:
    empty = _no_history(inp)
    if empty:
        return empty
    lines = ["what play produced, per window:"]
    for window, idx in inp.window_records():
        records = [inp.records[i] for i in idx]
        kills = sum(r.outcome.kills_delta for r in records if r.outcome is not None)
        deaths = sum(1 for r in records if r.outcome is not None and r.outcome.died)
        damage = sum(r.outcome.damage_taken for r in records if r.outcome is not None)
        lines.append(
            f"- {window.held()}: decisions {len(records)}, reward {_num(sum(r.reward for r in records), 1)}, "
            f"kills {_num(kills)}, deaths {deaths}, damage taken {_num(damage)}, "
            f"stalls {sum(1 for r in records if r.stalled)}, "
            f"missed ticks {sum(1 for r in records if r.executed_action is None)}"
        )
    return lines


def _sense_window(inp: HistoryInputs, sense: str, idx: Sequence[int]) -> str:
    spoke = followed = followed_paid = overruled = overruled_paid = 0
    paid_sum = unpaid_sum = 0.0
    paid_n = unpaid_n = 0
    missed = 0
    for i in idx:
        record = inp.records[i]
        result = record.instances.get(sense)
        if result is not None and result.missed:
            missed += 1
        if record.executed_action is None:
            continue
        message = next((m for m in record.messages if m.sense == sense), None)
        if message is None:
            continue
        spoke += 1
        paid = inp.paid(i)
        if message.action == record.executed_action:
            followed += 1
            followed_paid += 1 if paid else 0
        else:
            overruled += 1
            overruled_paid += 1 if paid else 0
        if paid:
            paid_sum, paid_n = paid_sum + message.strength, paid_n + 1
        else:
            unpaid_sum, unpaid_n = unpaid_sum + message.strength, unpaid_n + 1
    thin = inp.configuration.bounds.thin_record
    return (
        f"spoke {spoke}, followed {followed}, paid off {followed_paid} of {followed}; "
        f"overruled {overruled}, the chosen action paid off {overruled_paid} of {overruled}; "
        f"mean strength {_mean(paid_sum, paid_n, thin)} when it paid off, {_mean(unpaid_sum, unpaid_n, thin)} when not; "
        f"missed {missed} of {len(idx)} calls"
    )


def _h_sense(inp: HistoryInputs, sense: str) -> List[str]:
    concern = inp.configuration.senses[sense].concern
    lines = [f"the {sense} sense (concern: {concern}), on decisions the central did not miss; {_paid_off(inp)}:"]
    if not inp.records:
        lines.append("- no decision is stored yet")
    for window, idx in inp.window_records():
        if inp.records:
            lines.append(f"- {window.held()}: {_sense_window(inp, sense, idx)}")
    return lines + _scope_lines(inp, sense)


def _h_central(inp: HistoryInputs) -> List[str]:
    lines = [f"the central action chooser (concern: {inp.configuration.central.concern}); {_paid_off(inp)}:"]
    if not inp.records:
        lines.append("- no decision is stored yet")
    for window, idx in inp.window_records():
        if not inp.records:
            break
        missed = picked = paid = ties = with_message = followed_strongest = 0
        for i in idx:
            record = inp.records[i]
            if record.pick.tie:
                ties += 1
            if record.executed_action is None:
                missed += 1
                continue
            picked += 1
            paid += 1 if inp.paid(i) else 0
            if record.messages:
                with_message += 1
                strongest = max(record.messages, key=lambda m: m.strength)  # the first in sense order on a tie
                followed_strongest += 1 if strongest.action == record.executed_action else 0
        lines.append(
            f"- {window.held()}: {len(idx)} decisions, {missed} missed; followed the strongest message on "
            f"{followed_strongest} of {with_message} decisions with a message; picks that paid off {paid} of {picked}; "
            f"ties {ties}"
        )
    return lines + _scope_lines(inp, CENTRAL_NAME)


def _menu_order(inp: HistoryInputs, idx: Sequence[int]) -> List[str]:
    order: List[str] = []
    for i in idx:
        for aid in inp.records[i].inputs.menu_ids():
            if aid not in order:
                order.append(aid)
    return order


def _action_counts(inp: HistoryInputs, idx: Sequence[int]) -> Dict[str, Tuple[int, float]]:
    counts: Dict[str, Tuple[int, float]] = {}
    for i in idx:
        aid = inp.records[i].executed_action
        if aid is None:
            continue
        n, total = counts.get(aid, (0, 0.0))
        counts[aid] = (n + 1, total + inp.returns[i])
    return counts


def _h_actions(inp: HistoryInputs) -> List[str]:
    empty = _no_history(inp)
    if empty:
        return empty
    b = inp.configuration.bounds
    lines = [f"each action executed, per window: times executed and mean {b.return_steps}-step return (discount {b.return_gamma:g}):"]
    every = inp.union()
    order = _menu_order(inp, every)
    for window, idx in inp.window_records():
        counts = _action_counts(inp, idx)
        listed = [f"{aid} {counts[aid][0]} (mean {_signed(counts[aid][1] / counts[aid][0])})" for aid in order if aid in counts]
        lines.append(f"- {window.held()}: {', '.join(listed) if listed else 'no action executed'}")
    executed = _action_counts(inp, every)
    never = [aid for aid in order if aid not in executed]
    lines.append(f"on the menu but never executed in these windows: {', '.join(never) if never else 'none'}")
    macros = inp.configuration.admitted_macros
    if not macros:
        lines.append("admitted macros: none")
        return lines
    lines.append("admitted macros, over these windows:")
    for macro in macros:
        legal = sum(1 for i in every if macro.id in inp.records[i].inputs.menu_ids())
        n, total = executed.get(macro.id, (0, 0.0))
        record = f"executed {n} times, mean return {_signed(total / n)}" if n else "never executed"
        lines.append(f"- {macro.id}: {macro.description}; legal on {legal} decisions, {record}")
    return lines


def _h_strategy(inp: HistoryInputs) -> List[str]:
    active = inp.configuration.active_strategy
    lines = [f"strategies (active: {active}):" if inp.archive else f"no strategy archived (active: {active})"]
    for s in inp.archive:
        mark = " (active)" if s.strategy_id == active else ""
        lines.append(
            f"- {s.strategy_id}{mark}: {', '.join(s.action_sequence)}; reward {_num(s.observed_reward, 2)}, "
            f"success {_num(s.success_rate, 2)}, used {s.usage_count} times"
        )
    if not inp.records:
        lines.append("no decision is stored yet")
        return lines
    b = inp.configuration.bounds
    lines.append(f"decisions under each strategy, per window (count, mean {b.return_steps}-step return):")
    for window, idx in inp.window_records():
        tally: Dict[str, Tuple[int, float]] = {}
        for i in idx:
            sid = inp.records[i].active_strategy
            n, total = tally.get(sid, (0, 0.0))
            tally[sid] = (n + 1, total + inp.returns[i])
        listed = [f"{sid} {n} (mean {_signed(total / n)})" for sid, (n, total) in tally.items()]
        lines.append(f"- {window.held()}: {', '.join(listed)}")
    return lines


def _less_tried(record: TickRecord) -> bool:
    """The executed action had been taken fewer times in that situation than the menu's average."""
    if record.executed_action is None:
        return False
    counts = [record.inputs.novelty.get(aid, 0) for aid in record.inputs.menu_ids()]
    if not counts:
        return False
    return record.inputs.novelty.get(record.executed_action, 0) < sum(counts) / len(counts)


def _h_exploration(inp: HistoryInputs) -> List[str]:
    level = inp.configuration.exploration_level
    meaning = {
        "exploit": "the action the chooser gives the highest probability is executed",
        "explore": "the executed action is drawn from the chooser's probabilities",
    }[level]
    lines = [f"level now: {level} ({meaning})"]
    if not inp.records:
        lines.append("no decision is stored yet")
        return lines
    lines.append(
        "per window: decisions that took a less-tried action (taken fewer times in that situation than the menu's "
        "average so far), picks drawn under explore, and the progress trend (reward, displacement and new cells per decision):"
    )
    for window, idx in inp.window_records():
        records = [inp.records[i] for i in idx]
        n = len(records)
        less = sum(1 for r in records if _less_tried(r))
        drawn = sum(1 for r in records if r.pick.kind == "drawn")
        reward = sum(r.reward for r in records) / n if n else 0.0
        moved = sum(r.outcome.displacement for r in records if r.outcome is not None) / n if n else 0.0
        cells = sum(r.outcome.new_cells for r in records if r.outcome is not None) / n if n else 0.0
        lines.append(
            f"- {window.held()}: less-tried {_share(less, n)}; drawn {drawn}; reward per decision {_num(reward, 2)}; "
            f"displacement per decision {_num(moved, 1)}; new cells per decision {_num(cells, 2)}"
        )
    return lines


def _cooling_phrase(key: str, left: int) -> str:
    who = "System 2 as a whole (menu, strategy, level)" if key == SYSTEM2_KEY else key
    return f"{who} {'ready' if left <= 0 else _plural(left, 'decision') + ' left'}"


def _h_config(inp: HistoryInputs) -> List[str]:
    status = inp.status
    lines = [f"configuration version {inp.configuration.version}"]
    if status.change_log:
        shown = status.change_log[-CHANGE_LOG_SHOWN:]
        lines.append(f"changes (latest last, the last {len(shown)} of {len(status.change_log)}):")
        for e in shown:
            cycle = f", cycle {e.cycle_id}" if e.cycle_id else ""
            lines.append(f"- version {e.version}: {e.change} by {e.by}{cycle}; {e.status}")
    else:
        lines.append("no change made yet")
    trial = status.trial
    lines.append(
        f"trial in flight: {trial.change} (version {trial.version}), observed {trial.observed} of {trial.of} decisions"
        if trial
        else "trial in flight: none"
    )
    lines.append(f"change pending: {status.pending}" if status.pending else "change pending: none")
    lines.append("cooling: " + "; ".join(_cooling_phrase(k, status.cooling_left.get(k, 0)) for k in COOLING_KEYS))
    return lines


def _composite(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _h_tests(inp: HistoryInputs) -> List[str]:
    status = inp.status
    lines: List[str] = []
    if status.tests:
        lines.append("recent history tests (latest last):")
        for t in status.tests[-TESTS_SHOWN:]:
            if t.status == "waiting":
                lines.append(f"- cycle {t.cycle_id}, {t.change}: waiting, {t.note}")
                continue
            noise = "" if t.noise_agreement is None else f"; noise agreement {t.noise_agreement:.2f}"
            lines.append(
                f"- cycle {t.cycle_id}, {t.change}: composite {_composite(t.old_composite)} old, "
                f"{_composite(t.new_composite)} new; {t.status}{noise}"
            )
    else:
        lines.append("no history test yet")
    if status.verdicts:
        lines.append("recent trial verdicts (latest last):")
        for v in status.verdicts[-TESTS_SHOWN:]:
            how = "with no verdict (the trial judge never answered)" if v.by == "no verdict" else f"by {v.by}"
            lines.append(f"- {v.change} (version {v.version}): {v.verdict}, {how}")
    else:
        lines.append("no trial judged yet")
    return lines


def _messages(inp: HistoryInputs) -> List[str]:
    if not inp.proposals:
        return ["no reflector proposed a change this cycle."]
    return ["the reflectors' proposals this cycle:"] + [
        f"- {p.title} proposes {p.change} ({p.description}), strength {p.strength:.2f}, reason {reason_words(p.reason)}."
        for p in inp.proposals
    ]


RENDERERS: Dict[str, Callable[[HistoryInputs], List[str]]] = {
    "messages": _messages,
    "h_outcomes": _h_outcomes,
    **{f"h_sense:{name}": partial(_h_sense, sense=name) for name in SENSE_NAMES},
    "h_central": _h_central,
    "h_actions": _h_actions,
    "h_strategy": _h_strategy,
    "h_exploration": _h_exploration,
    "h_config": _h_config,
    "h_tests": _h_tests,
}
assert tuple(RENDERERS) == HISTORY_CHANNELS, "one renderer per history channel, in channel order"


def render_history_channel(inputs: HistoryInputs, channel: str) -> str:
    """One history channel: its header line and its body."""
    return "\n".join([f"[{channel}]"] + RENDERERS[channel](inputs))


def render_history_scope(inputs: HistoryInputs, scope: Sequence[str]) -> str:
    """The text an instance with this history scope is shown: its channels only, in channel order."""
    unknown = [c for c in scope if c not in RENDERERS]
    if unknown:
        raise ValueError(f"unknown history channel(s) {unknown}")
    return "\n\n".join(render_history_channel(inputs, c) for c in HISTORY_CHANNELS if c in scope)
