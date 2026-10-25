"""System 2: d1-ultra instances over System 1's history that change the configuration, one trial at a time.

Design spec, sections 8 and 9. System 2 runs on its own thread with the controller's `slow_client` (a
pool of 2 calls) and never blocks a tick. The controller tells it about every tick (after the history
keeps it), every configuration that takes effect at a tick boundary, every slow-path proposal, and every
episode end.

A **cycle** starts when 20 new decisions have been made since the last one, or an episode has ended, and
no trial is in flight (a change queued, a macro asked for, or a revert waiting counts as one). At most one
cycle runs at a time:

1. the history channels are rendered once from the ring, over the three windows;
2. each of the nine reflectors' finite change menus is filtered by the bounds; a reflector whose menu the
   bounds leave without a change is not called (logged); the others are called on System 2's pool, each
   one call with `speak`, `change` and `reason`. A reflector that speaks (d1's own yes) for a change
   sends a proposal; a silent, missed or `keep` reflector sends nothing;
3. no proposal means no further call. Otherwise System 2's central is called once over `messages`,
   `h_config` and `h_outcomes`: "Choose the one configuration change to make now, or none.", its criteria
   the proposed changes the bounds still allow, and `none`. A tie goes to the first option, and is
   logged; a missed central means no change this cycle;
4. the chosen change: a scope change goes through the history test (`history_test.py`) and is queued only
   when it passes; `macro:<sense>` asks the slow path (`request_expansion`) with a description built from
   the reflector's reason and the sense's concern, and the admit instance decides; `retire`, `strategy`
   and `level` are queued. A queued configuration takes effect at the next tick boundary
   (`request_configuration`).

Every change that takes effect is a **trial**: it is observed for 60 decisions (across episodes if need
be), then the trial judge (one call, `verdict`: `keep` or `revert`) reads a before-and-during table:
reward and damage per decision, kills, deaths, missed ticks, the changed instance's paid-off rate, and
the history test's prediction. For a scope change, the safety bound reverts without asking when the
paid-off rate of the changed instance falls by more than 0.15 on at least 10 followed messages. A revert
restores the previous configuration exactly, with the version bumped (a reverted macro is retired, a
reverted retire re-admits). A missed judge extends the trial by 20 decisions and is asked again; after its
third miss (`judge_extensions_max`) the trial ends as `revert` with no verdict, because nothing stands in for
a missed verdict and the configuration before the change is the honest state to return to. After the
verdict the changed instance rests 60 decisions, or System 2 as a whole after a menu, strategy or level
change.

Code renders evidence, filters the finite set of changes by the bounds, runs the history test, applies
and reverts; nothing here ranks or chooses a change, and nothing stands in for a missed answer. Every
number is a `Bounds` field. Each cycle is a `ReflectionTrace`, each verdict a `TrialVerdictTrace`, and the
moments between are `System2Note`s, all in `reflections.jsonl`. System 2's own state (its decision count,
cooling, change log, recent tests and verdicts, the trial in flight) is saved to `system2.json` and
restored when the run starts from the configuration it was saved with; a revert or a change queued but
not yet in play is queued again then, and a macro request (whose slow worker died with the process) is
dropped.
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol, Sequence, Tuple, Union

from pydantic import BaseModel, Field, ValidationError

from system1_doom.admission import AdmissionDecisionResult
from system1_doom.configuration import CENTRAL_NAME, Configuration, reason_words
from system1_doom.d1_client import ChoiceQuestion, D1UltraClient, Usage
from system1_doom.evidence import StrategyLine
from system1_doom.history import HistoryStore, TickRecord
from system1_doom.history_channels import (
    ChangeLogEntry,
    HistoryTestSummary,
    System2Status,
    TrialStatus,
    VerdictSummary,
    history_inputs,
    render_history_scope,
)
from system1_doom.history_test import HistoryTestResult, run_history_test
from system1_doom.instance import InstanceResult, InstanceSpec, preamble, run_system2_instance
from system1_doom.logger import DecisionLogger
from system1_doom.reflection import (
    AppliedChange,
    ChangeKindName,
    CycleOutcome,
    CycleTrigger,
    NoteKind,
    ReflectionTrace,
    System2EpisodeSummary,
    System2Note,
    TrialBy,
    TrialRecord,
    TrialRow,
    TrialTable,
    TrialVerdictTrace,
    summarize,
)
from system1_doom.reflectors import (
    REFLECTORS,
    BoundsState,
    ChangeOption,
    ConfigDiff,
    Proposal,
    apply_change,
    blocked_by,
    change_menu,
    change_option,
    config_diff,
    filter_changes,
    offers_a_change,
    proposal_of,
    reflector_questions,
)
from system1_doom.relevance import decision_returns
from system1_doom.system1 import total_usage

SYSTEM2_FILE = "system2.json"
CONFIGURATION_FILE = "configuration.json"
STATE_VERSION = 1
NONE = "none"
TESTS_KEPT = 20
VERDICTS_KEPT = 20
CHANGE_LOG_KEPT = 50

CENTRAL_SPEC = InstanceSpec(
    name="system2_central",
    kind="system2_central",
    scope=("messages", "h_config", "h_outcomes"),
    concern="which one configuration change, if any, the agent makes now",
)
CENTRAL_QUESTION = "Choose the one configuration change to make now, or none."
NONE_DESCRIPTION = "make no configuration change this cycle"
JUDGE_SPEC = InstanceSpec(
    name="trial_judge",
    kind="judge",
    scope=("trial",),
    concern="whether a configuration change on trial has served the agent",
)
JUDGE_QUESTION = "Keep this configuration change, or revert it?"
VERDICT_CRITERIA: Dict[str, str] = {
    "keep": "keep the change: its configuration stays in play",
    "revert": "revert the change: the configuration before it is restored",
}
Record = Union[ReflectionTrace, TrialVerdictTrace, System2Note]


class System2Host(Protocol):
    """What System 2 needs from the controller."""

    configuration: Configuration
    history: HistoryStore
    logger: DecisionLogger
    slow_client: D1UltraClient
    episode_id: str

    def next_configuration(self) -> Configuration: ...

    def request_configuration(self, configuration: Configuration) -> None: ...

    def request_expansion(self, source: str, description: str) -> bool: ...

    def slow_path_available(self) -> bool: ...

    def archive_lines(self) -> List[StrategyLine]: ...


def fingerprint(configuration: Configuration) -> str:
    """A short hash of a configuration, whole: System 2's state is restored only onto the configuration it was saved with."""
    return hashlib.sha256(configuration.model_dump_json().encode("utf-8")).hexdigest()[:16]


def kind_of(option: ChangeOption) -> ChangeKindName:
    return "scope" if option.is_scope_change else option.kind  # type: ignore[return-value]


def macro_description(proposal: Proposal, sense: str, configuration: Configuration) -> str:
    """What the slow path is asked for: the sense's concern and the reflector's reason, in words."""
    concern = configuration.senses[sense].concern
    return (
        f"A new macro-action for the {sense} sense's problem: its concern is {concern}. The {proposal.title} asked "
        f"for it because of {reason_words(proposal.reason)}. Propose one bounded macro-action that would serve this concern."
    )


# ---------------------------------------------------------------------------------------------------
# System 2's state: what it keeps between cycles, and saves.


class TrialTick(BaseModel):
    """One decision a trial reads: what it produced, and what the changed instance did at it."""

    episode_id: str
    tick: int
    period: Literal["before", "during"]
    reward: float = 0.0
    damage: float = 0.0
    kills: float = 0.0
    died: bool = False
    missed: bool = False
    done: bool = False
    followed: bool = Field(default=False, description="Sense: its message was the executed action; central or none: a pick was executed")


def trial_tick(record: TickRecord, instance: Optional[str], period: Literal["before", "during"]) -> TrialTick:
    executed = record.executed_action
    if instance is None or instance == CENTRAL_NAME:
        followed = executed is not None
    else:
        message = next((m for m in record.messages if m.sense == instance), None)
        followed = executed is not None and message is not None and message.action == executed
    outcome = record.outcome
    return TrialTick(
        episode_id=record.episode_id,
        tick=record.tick,
        period=period,
        reward=record.reward,
        damage=outcome.damage_taken if outcome is not None else 0.0,
        kills=outcome.kills_delta if outcome is not None else 0.0,
        died=bool(outcome.died) if outcome is not None else False,
        missed=executed is None,
        done=record.done,
        followed=followed,
    )


class PendingChange(BaseModel):
    """A change System 2 set in motion that is not in play yet: queued, a macro asked for or admitted, or a revert."""

    cycle_id: str
    change: str
    kind: ChangeKindName
    stage: Literal["queued", "macro_requested", "macro_admitted", "revert"]
    instance: Optional[str] = None
    target: Optional[str] = Field(default=None, description="A macro request's sense")
    description: str = ""
    decision: int = Field(description="System 2's decision count when it was set in motion")
    version: Optional[int] = Field(default=None, description="The configuration version that will take effect (None for a macro request)")
    cooling_key: Optional[str] = None
    prediction: Optional[str] = None
    macro_id: Optional[str] = None
    safety: bool = False
    no_verdict: bool = Field(default=False, description="A revert because the trial judge never answered")
    restore: Optional[Configuration] = Field(default=None, description="A revert: the configuration it restores (before the version bump)")
    before: List[TrialTick] = Field(
        default_factory=list,
        description="A queued change: the decisions before it when it was queued, for a trial that starts after a restore",
    )


class TrialState(BaseModel):
    cycle_id: str
    change: str
    kind: ChangeKindName
    instance: Optional[str] = None
    description: str = ""
    detail: str = ""
    cooling_key: Optional[str] = None
    previous: Configuration = Field(description="The configuration before the change, restored exactly by a revert")
    version: int
    diff: ConfigDiff
    started_at: str
    started_decision: int
    started_episode: str
    started_tick: int = -1
    of: int = Field(description="Decisions to observe before the judge: the trial's length plus any extensions")
    before_wanted: int = Field(default=0, description="Decisions before the change the table compares with (the trial's length)")
    extensions: int = 0
    prediction: Optional[str] = None
    judge: List[InstanceResult] = Field(default_factory=list)
    ticks: List[TrialTick] = Field(default_factory=list)

    def during(self) -> int:
        return sum(1 for t in self.ticks if t.period == "during")


class System2State(BaseModel):
    state_version: int = STATE_VERSION
    fingerprint: str = ""
    configuration_version: int = 1
    decisions: int = 0
    last_cycle_decision: int = 0
    cycles: int = 0
    cooling: Dict[str, int] = Field(default_factory=dict)
    change_log: List[ChangeLogEntry] = Field(default_factory=list)
    tests: List[HistoryTestSummary] = Field(default_factory=list)
    verdicts: List[VerdictSummary] = Field(default_factory=list)
    trial: Optional[TrialState] = None
    pending: Optional[PendingChange] = None


# ---------------------------------------------------------------------------------------------------
# The trial table.


def trial_returns(ticks: Sequence[TrialTick], steps: int, gamma: float) -> List[Tuple[float, bool]]:
    """Each trial tick's n-step return (per episode, over the ticks held) and whether it is complete: its
    n rewards are all held, or its episode ended."""
    out: List[Tuple[float, bool]] = []
    groups = [list(g) for _, g in groupby(ticks, key=lambda t: t.episode_id)]
    for gi, group in enumerate(groups):
        returns = decision_returns([t.reward for t in group], steps, gamma)
        ended = group[-1].done or gi < len(groups) - 1
        for i, ret in enumerate(returns):
            out.append((ret, ended or i + steps <= len(group)))
    return out


def trial_rows(trial: TrialState, steps: int, gamma: float, complete_only: bool = False) -> Tuple[TrialRow, TrialRow]:
    returns = trial_returns(trial.ticks, steps, gamma)
    rows: Dict[str, TrialRow] = {}
    for period in ("before", "during"):
        picked = [(t, r) for t, r in zip(trial.ticks, returns) if t.period == period]
        n = len(picked)
        followed = [(t, r) for t, r in picked if t.followed and (r[1] or not complete_only)]
        paid = sum(1 for _, r in followed if r[0] > 0.0)
        rows[period] = TrialRow(
            decisions=n,
            reward_per_decision=round(sum(t.reward for t, _ in picked) / n, 4) if n else 0.0,
            damage_per_decision=round(sum(t.damage for t, _ in picked) / n, 4) if n else 0.0,
            kills=round(sum(t.kills for t, _ in picked), 4),
            deaths=sum(1 for t, _ in picked if t.died),
            missed_ticks=sum(1 for t, _ in picked if t.missed),
            followed=len(followed),
            paid_off=paid,
            paid_off_rate=round(paid / len(followed), 4) if followed else None,
        )
    return rows["before"], rows["during"]


def _who_followed(instance: Optional[str]) -> Tuple[str, str]:
    if instance is None:
        return "decisions executed (no single instance changed)", "decisions executed that paid off"
    if instance == CENTRAL_NAME:
        return "the central's picks", "the central's picks that paid off"
    return f"{instance}'s followed messages", f"{instance}'s followed messages that paid off"


def _rate(row: TrialRow) -> str:
    if not row.followed:
        return "0 of 0"
    return f"{row.paid_off} of {row.followed} ({row.paid_off_rate:.2f})"


def trial_table(trial: TrialState, steps: int, gamma: float) -> TrialTable:
    """The before-and-during table the trial judge reads, as plain text, with its numbers."""
    before, during = trial_rows(trial, steps, gamma)
    followed_label, paid_label = _who_followed(trial.instance)
    changes = "; ".join(trial.diff.changes) or "no visible change"
    held = f" (the history held only {before.decisions})" if before.decisions < trial.before_wanted else ""
    lines = [
        "[trial]",
        f"change on trial: {trial.change} ({trial.description})" + (f", {trial.detail}" if trial.detail else ""),
        f"configuration: version {trial.diff.new_version}, replacing version {trial.diff.old_version} ({changes})",
        f"the history test predicted: {trial.prediction}" if trial.prediction else "no history test: not a scope change",
        f"observed: {during.decisions} decisions under the change, against the {before.decisions} decisions before it{held}",
        f"paid off: the decision's {steps}-step return (discount {gamma:g}) was positive",
        "",
        "                     before | during",
        f"- decisions: {before.decisions} | {during.decisions}",
        f"- reward per decision: {before.reward_per_decision:.2f} | {during.reward_per_decision:.2f}",
        f"- damage per decision: {before.damage_per_decision:.2f} | {during.damage_per_decision:.2f}",
        f"- kills: {before.kills:g} | {during.kills:g}",
        f"- deaths: {before.deaths} | {during.deaths}",
        f"- missed ticks: {before.missed_ticks} | {during.missed_ticks}",
        f"- {followed_label}: {before.followed} | {during.followed}",
        f"- {paid_label}: {_rate(before)} | {_rate(during)}",
    ]
    return TrialTable(before=before, during=during, instance=trial.instance, prediction=trial.prediction, text="\n".join(lines))


def safety_breach(trial: TrialState, configuration: Configuration) -> Optional[str]:
    """Why the safety bound reverts a scope change without asking, or None. Only complete returns count."""
    if trial.kind != "scope":
        return None
    b = configuration.bounds
    before, during = trial_rows(trial, b.return_steps, b.return_gamma, complete_only=True)
    if (during.followed or 0) < b.safety_followed or before.paid_off_rate is None or during.paid_off_rate is None:
        return None
    drop = before.paid_off_rate - during.paid_off_rate
    if drop > b.safety_drop:
        return (
            f"{trial.instance}'s paid-off rate fell from {before.paid_off_rate:.2f} to {during.paid_off_rate:.2f} "
            f"on {during.followed} followed messages (more than {b.safety_drop:.2f} on at least {b.safety_followed})"
        )
    return None


def prediction_of(test: HistoryTestResult) -> Optional[str]:
    if test.old is None or test.new is None or test.old.composite is None or test.new.composite is None:
        return None
    return f"composite {test.old.composite:.2f} under the old scope, {test.new.composite:.2f} under the new; {test.reason}"


def test_summary(cycle_id: str, test: HistoryTestResult) -> HistoryTestSummary:
    return HistoryTestSummary(
        cycle_id=cycle_id,
        change=test.change,
        status=test.status,
        old_composite=test.old.composite if test.old is not None else None,
        new_composite=test.new.composite if test.new is not None else None,
        noise_agreement=test.noise_agreement,
        note=test.reason if test.status == "waiting" else "",
    )


# ---------------------------------------------------------------------------------------------------
# System 2.


class System2:
    """System 2's thread: cycles, trials and its own state, over a controller (`System2Host`)."""

    def __init__(self, host: System2Host, *, seed: int = 0, state_path: Optional[Union[str, Path]] = None) -> None:
        self.host = host
        self.seed = seed
        self.state_path = Path(state_path) if state_path is not None else None
        self.state = System2State()
        self.records: List[Record] = []
        self._listeners: List[Callable[[Record], None]] = []
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._dirty = False
        self._busy = False
        self._stop = False
        self._begun = False
        self._episode_end: Optional[str] = None
        bounds = host.configuration.bounds
        self._executor = ThreadPoolExecutor(max_workers=bounds.system2_pool, thread_name_prefix="system2-call")
        self._thread = threading.Thread(target=self._run, name="system2", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------------------------------------
    # Hooks: called by the controller, on its thread. Each is cheap and never calls d1.

    def begin(self) -> None:
        """Restore the saved state when it was saved with the configuration the run starts from (once)."""
        with self._lock:
            if self._begun:
                return
            self._begun = True
            configuration = self.host.configuration
            if self.state_path is None or not self.state_path.is_file():
                self.state = System2State(fingerprint=fingerprint(configuration), configuration_version=configuration.version)
                return
            try:
                saved = System2State.model_validate_json(self.state_path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError) as exc:
                self.state = System2State(fingerprint=fingerprint(configuration), configuration_version=configuration.version)
                self._note("fresh_start", f"{self.state_path.name} could not be read ({str(exc).splitlines()[0][:120]}); System 2 starts fresh")
                return
            if saved.fingerprint != fingerprint(configuration):
                self.state = System2State(fingerprint=fingerprint(configuration), configuration_version=configuration.version)
                self._note(
                    "fresh_start",
                    f"{self.state_path.name} was saved with configuration version {saved.configuration_version}, not the one this run "
                    f"starts from (version {configuration.version}); System 2 starts fresh",
                )
                return
            dropped = saved.pending
            saved.pending = None
            self.state = saved
            trial = f"; trial of {saved.trial.change} continues" if saved.trial else ""
            lost = ""
            again: Optional[Configuration] = None
            if dropped is not None and dropped.stage == "revert" and dropped.restore is not None:
                # A verdict to revert is kept across runs: the revert is queued again for the first tick boundary.
                again = Configuration.model_validate({**dropped.restore.model_dump(), "version": configuration.version + 1})
            elif dropped is not None and dropped.stage == "queued":
                # A change queued (an end-of-episode cycle's, say) is kept too: rebuilt from the configuration it
                # was queued against, which the fingerprint says this run starts from, as that version + 1.
                try:
                    again = apply_change(configuration, change_option(dropped.change, configuration))
                except (ValidationError, ValueError) as exc:
                    lost = f"; the queued {dropped.change} no longer applies ({str(exc).splitlines()[0][:120]}) and is dropped"
            if again is not None and dropped is not None:
                self.host.request_configuration(again)
                self.state.pending = dropped.model_copy(update={"version": again.version})
                lost = f"; {dropped.change} had not taken effect and is queued again as version {again.version}"
            elif dropped is not None and not lost:
                lost = f"; the pending {dropped.change} ({dropped.stage.replace('_', ' ')}) was not in play and is dropped"
            self._note("restored", f"System 2 restored at {saved.decisions} decisions, {saved.cycles} cycles{trial}{lost}", version=configuration.version)

    def on_tick(self, record: TickRecord) -> None:
        """A tick was kept in the history: count the decision, and feed the trial in flight."""
        with self._cond:
            self.state.decisions += 1
            trial = self.state.trial
            if trial is not None:
                trial.ticks.append(trial_tick(record, trial.instance, "during"))
                if trial.started_tick < 0:
                    trial.started_tick = record.tick
            self._dirty = True
            self._cond.notify_all()

    def on_episode_end(self, episode_id: str) -> None:
        """An episode ended: a cycle starts when no trial is in flight and a decision was made since the last."""
        with self._cond:
            if self.state.trial is None and self.state.pending is None and self.state.decisions > self.state.last_cycle_decision:
                self._episode_end = episode_id
            self.save()
            self._dirty = True
            self._cond.notify_all()

    def on_configuration_applied(self, old: Configuration, new: Configuration) -> None:
        """A configuration took effect at a tick boundary: start the trial it begins, or record what it was."""
        with self._cond:
            pending = self.state.pending
            added = [m.id for m in new.admitted_macros if m.id not in {o.id for o in old.admitted_macros}]
            if pending is not None and pending.stage == "queued" and new.version == pending.version:
                self._start_trial(pending, old, new)
            elif pending is not None and pending.stage == "revert" and new.version == pending.version:
                by = "safety revert" if pending.safety else ("revert with no verdict" if pending.no_verdict else "revert")
                self._log_change(ChangeLogEntry(version=new.version, change=pending.change, by=by, cycle_id=pending.cycle_id, decision=self.state.decisions))
                self.state.pending = None
                self._note("revert_applied", f"{pending.change} took effect: version {new.version} restores the configuration before the change", pending.cycle_id, new.version)
            elif pending is not None and pending.stage in ("macro_requested", "macro_admitted") and added:
                self._start_trial(pending.model_copy(update={"macro_id": added[0]}), old, new)
            else:
                diff = config_diff(old, new)
                self._log_change(
                    ChangeLogEntry(
                        version=new.version, change="; ".join(diff.changes) or "no visible change", by="outside System 2",
                        decision=self.state.decisions,
                    )
                )
                self._note("external_change", f"version {new.version} took effect, not made by System 2: {'; '.join(diff.changes) or 'no visible change'}", version=new.version)
            self.save()
            self._dirty = True
            self._cond.notify_all()

    def on_proposal(self, result: AdmissionDecisionResult) -> None:
        """The slow path finished a proposal: when it answers System 2's macro request, the admit instance decided."""
        with self._cond:
            pending = self.state.pending
            if pending is None or pending.stage != "macro_requested" or result.source_module != pending.target:
                return
            if result.admitted and result.admitted_action_id:
                pending.stage = "macro_admitted"
                pending.macro_id = result.admitted_action_id
                self._note("macro_admitted", f"the admit instance admitted {result.admitted_action_id} for {pending.change}; it takes effect at the next tick boundary", pending.cycle_id)
            else:
                self.state.pending = None
                self._note("macro_rejected", f"{pending.change}: the proposal was not admitted ({result.rejection_reason or 'no reason given'})", pending.cycle_id)
            self.save()
            self._dirty = True
            self._cond.notify_all()

    # ------------------------------------------------------------------------------------------------
    # Listeners, waiting, shutting down.

    def add_listener(self, listener: Callable[[Record], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[Record], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Wait until System 2 has nothing left to do for what it has been told so far. False on timeout."""
        with self._cond:
            return self._cond.wait_for(lambda: self._stop or (not self._dirty and not self._busy), timeout=timeout)

    def shutdown(self, wait_sec: float = 120.0) -> None:
        """Let the cycle or judge in flight finish (up to `wait_sec`), save, and stop the thread."""
        self.wait_idle(timeout=wait_sec)
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self._thread.join(timeout=5.0)
        with self._lock:
            if self._begun:
                self.save()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def summary(self, since: int = 0) -> System2EpisodeSummary:
        """What System 2 did from record `since` on (cycles, tests, trials, calls, cost)."""
        with self._lock:
            return summarize(self.records[since:])

    def status(self) -> System2Status:
        with self._lock:
            return self._status()

    # ------------------------------------------------------------------------------------------------
    # The thread.

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stop or self._dirty)
                if self._stop:
                    return
                self._dirty = False
                self._busy = True
            try:
                while not self._stop:
                    job = self._next_job()
                    if job is None:
                        break
                    try:
                        job()
                    except Exception as exc:  # noqa: BLE001 - System 2 must never take play down
                        self._note("error", f"{type(exc).__name__}: {str(exc)[:300]}")
                        break
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def _next_job(self) -> Optional[Callable[[], None]]:
        with self._lock:
            if not self._begun:
                return None
            s = self.state
            bounds = self.host.configuration.bounds
            if s.trial is not None:
                breach = safety_breach(s.trial, self.host.configuration)
                if breach is not None:
                    return lambda: self._safety_revert(breach)
                if s.trial.during() >= s.trial.of:
                    return self._judge
                self._episode_end = None
                return None
            if s.pending is not None:
                if s.pending.stage == "macro_requested" and s.decisions - s.pending.decision >= bounds.trial_decisions:
                    return self._abandon_macro
                self._episode_end = None
                return None
            new = s.decisions - s.last_cycle_decision
            if new >= bounds.system2_cadence:
                return lambda: self._cycle("decisions")
            if self._episode_end is not None and new > 0:
                return lambda: self._cycle("episode_end")
            self._episode_end = None
            return None

    # ------------------------------------------------------------------------------------------------
    # A cycle.

    def _cycle(self, trigger: CycleTrigger) -> None:
        host = self.host
        started_at = DecisionLogger.now_iso()
        with self._lock:
            self._episode_end = None
            self.state.cycles += 1
            number = self.state.cycles
            cycle_id = f"cycle-{number}"
            decision = self.state.decisions
            self.state.last_cycle_decision = decision
            status = self._status()
            cooling = dict(self.state.cooling)
        episode_id = host.episode_id
        configuration = host.next_configuration()
        bounds = configuration.bounds
        archive = host.archive_lines()
        records = host.history.records()
        inputs = history_inputs(records, configuration, archive=archive, status=status)
        state = BoundsState(
            decisions=decision, cooling=cooling, trials=0, slow_path_available=host.slow_path_available(),
            archive_ids=tuple(a.strategy_id for a in archive),
        )
        head: Dict[str, Any] = dict(
            cycle_id=cycle_id, started_at=started_at, trigger=trigger, episode_id=episode_id, decision=decision,
            configuration_version=configuration.version, windows=list(inputs.windows),
        )
        notes: List[str] = []

        # The reflectors: each one's finite menu, filtered by the bounds, then one call each on the pool.
        offered: Dict[str, List[str]] = {}
        blocked: Dict[str, Dict[str, str]] = {}
        skipped: Dict[str, str] = {}
        asked: List[Tuple[Any, List[ChangeOption]]] = []
        futures = []
        for spec in REFLECTORS:
            allowed, why = filter_changes(change_menu(spec, configuration, state.archive_ids), configuration, state)
            if why:
                blocked[spec.name] = why
            if not offers_a_change(allowed, configuration):
                first = next(iter(why.values()), "")
                skipped[spec.name] = "the bounds leave it no change to propose" + (f" ({first})" if first else "")
                continue
            offered[spec.name] = [o.id for o in allowed]
            evidence = render_history_scope(inputs, spec.scope)
            questions = reflector_questions(spec, allowed)
            asked.append((spec, allowed))
            futures.append(
                self._executor.submit(
                    run_system2_instance, host.slow_client, spec.instance_spec(), evidence, questions,
                    budget=bounds.call_budget_sec, yes_at=bounds.yes_at, tolerance=bounds.probability_tolerance,
                )
            )
        reflectors: Dict[str, InstanceResult] = {}
        for (spec, _), future in zip(asked, futures):
            reflectors[spec.name] = future.result()
        calls = len(reflectors)
        assert calls <= len(REFLECTORS)
        if skipped:
            notes.append(f"{len(skipped)} reflector(s) not called: the bounds left them no change ({', '.join(skipped)})")
        proposals: List[Proposal] = []
        for spec, allowed in asked:
            proposal = proposal_of(spec, reflectors[spec.name], allowed, configuration)
            if proposal is not None and proposal.change not in {p.change for p in proposals}:
                proposals.append(proposal)
        used: List[InstanceResult] = list(reflectors.values())

        def finish(outcome: CycleOutcome, **fields: Any) -> None:
            # Every call of the cycle: the reflectors, System 2's central, the history test. Asserted against the bound.
            all_calls = calls
            assert all_calls <= bounds.system2_calls_per_cycle, f"{all_calls} System 2 calls in one cycle; the bound is {bounds.system2_calls_per_cycle}"
            usage = total_usage(used + ([fields["central"]] if fields.get("central") is not None else []))
            if fields.get("history_test") is not None:
                test_usage: Usage = fields["history_test"].usage
                usage = Usage(
                    input_tokens=usage.input_tokens + test_usage.input_tokens,
                    output_tokens=usage.output_tokens + test_usage.output_tokens,
                    cost=round(usage.cost + test_usage.cost, 12),
                )
            trace = ReflectionTrace(
                **head, finished_at=DecisionLogger.now_iso(), offered=offered, blocked=blocked, skipped=skipped,
                reflectors=reflectors, messages=proposals, outcome=outcome, calls=all_calls, usage=usage,
                notes=notes, **fields,
            )
            with self._lock:
                self.save()
            self._emit(trace)

        # No proposal: no central call.
        if not proposals:
            notes.append("no reflector proposed a change the bounds allow; System 2's central was not called")
            finish("no_proposal")
            return

        # System 2's central: the proposed changes the bounds still allow, and none.
        still_state = state.model_copy(update={"slow_path_available": host.slow_path_available()})
        still: List[Proposal] = []
        for p in proposals:
            reason = blocked_by(change_option(p.change, configuration), configuration, still_state)
            if reason is None:
                still.append(p)
            else:
                notes.append(f"{p.change} was proposed but the bounds no longer allow it: {reason}")
        if not still:
            finish("no_proposal")
            return
        criteria = {p.change: p.description for p in still}
        criteria[NONE] = NONE_DESCRIPTION
        evidence = render_history_scope(inputs.model_copy(update={"proposals": tuple(still)}), CENTRAL_SPEC.scope)
        central = run_system2_instance(
            host.slow_client, CENTRAL_SPEC, evidence,
            {"configure": ChoiceQuestion(instructions=f"{preamble(CENTRAL_SPEC)} {CENTRAL_QUESTION}", criteria=criteria)},
            budget=bounds.call_budget_sec, yes_at=bounds.yes_at, tolerance=bounds.probability_tolerance,
        )
        calls += 1
        central_fields: Dict[str, Any] = dict(central=central, central_criteria=list(criteria))
        if central.missed or central.change is None:
            notes.append(f"System 2's central missed ({central.miss_reason}); no change this cycle")
            finish("central_missed", **central_fields)
            return
        best = max(central.change_probabilities.values())
        tied = [k for k in criteria if central.change_probabilities.get(k) == best]
        choice = central.change
        central_fields.update(choice=choice, tie=len(tied) > 1, tied=tied if len(tied) > 1 else [])
        if len(tied) > 1:
            notes.append(f"tie between {', '.join(tied)}; the first in criteria order, {choice}, was taken")
        if choice == NONE:
            finish("none_chosen", **central_fields)
            return
        option = change_option(choice, configuration)
        proposal = next(p for p in still if p.change == choice)
        kind = kind_of(option)

        if option.kind == "macro":
            assert option.target is not None
            description = macro_description(proposal, option.target, configuration)
            with self._lock:
                enqueued = host.request_expansion(source=option.target, description=description)
                if enqueued:
                    self.state.pending = PendingChange(
                        cycle_id=cycle_id, change=option.id, kind=kind, stage="macro_requested", target=option.target,
                        description=option.description, decision=decision, cooling_key=option.cooling_key,
                    )
            applied = AppliedChange(change=option.id, kind=kind, description=description, queued=False)
            if not enqueued:
                notes.append("the slow path could not take the request (off or busy); no change this cycle")
            finish("macro_requested" if enqueued else "macro_not_enqueued", applied=applied, **central_fields)
            return

        new_configuration = apply_change(configuration, option)
        test: Optional[HistoryTestResult] = None
        prediction: Optional[str] = None
        if option.is_scope_change:
            assert option.instance is not None
            needed = bounds.history_test_sample + bounds.history_test_noise
            left = bounds.system2_calls_per_cycle - calls
            if needed > left:
                notes.append(f"the history test needs {needed} calls and the cycle's bound leaves {left}; the change waits")
                finish("test_waiting", **central_fields)
                return
            test = run_history_test(
                host.slow_client, records, option.instance, option.id, configuration, new_configuration,
                seed=self.seed * 1000 + number, frame_of=host.history.frame, executor=self._executor,
            )
            calls += test.calls
            with self._lock:
                self.state.tests = (self.state.tests + [test_summary(cycle_id, test)])[-TESTS_KEPT:]
            if test.status == "waiting":
                notes.append("too few stored ticks for the history test; the change waits")
                finish("test_waiting", history_test=test, **central_fields)
                return
            if not test.passed:
                notes.append(f"the history test rejected {option.id}")
                finish("test_failed", history_test=test, **central_fields)
                return
            prediction = prediction_of(test)

        # Queue the change: it takes effect at the next tick boundary and becomes the trial.
        diff = config_diff(configuration, new_configuration)
        with self._lock:
            now = host.next_configuration()
            queued = now.version == configuration.version
            if queued:
                host.request_configuration(new_configuration)
                self.state.pending = PendingChange(
                    cycle_id=cycle_id, change=option.id, kind=kind, stage="queued", instance=option.instance,
                    description=option.description, decision=decision, version=new_configuration.version,
                    cooling_key=option.cooling_key, prediction=prediction,
                    before=[trial_tick(r, option.instance, "before") for r in records[-bounds.trial_decisions :]],
                )
            else:
                notes.append(f"the configuration moved to version {now.version} during the cycle; {option.id} was not queued")
        applied = AppliedChange(change=option.id, kind=kind, instance=option.instance, description=option.description, diff=diff, queued=queued)
        finish("queued", history_test=test, applied=applied, **central_fields)

    # ------------------------------------------------------------------------------------------------
    # Trials.

    def _start_trial(self, pending: PendingChange, old: Configuration, new: Configuration) -> None:
        bounds = new.bounds
        before = [trial_tick(r, pending.instance, "before") for r in self.host.history.records()[-bounds.trial_decisions :]]
        if len(before) < bounds.trial_decisions and pending.before:
            # A change queued before a restore: this process's history does not hold the decisions before it,
            # and the ticks saved with the change do.
            held = {(t.episode_id, t.tick) for t in before}
            before = ([t for t in pending.before if (t.episode_id, t.tick) not in held] + before)[-bounds.trial_decisions :]
        detail = f"admitted as {pending.macro_id}" if pending.macro_id else ""
        trial = TrialState(
            cycle_id=pending.cycle_id, change=pending.change, kind=pending.kind, instance=pending.instance,
            description=pending.description, detail=detail, cooling_key=pending.cooling_key, previous=old,
            version=new.version, diff=config_diff(old, new), started_at=DecisionLogger.now_iso(),
            started_decision=self.state.decisions, started_episode=self.host.episode_id, of=bounds.trial_decisions,
            before_wanted=bounds.trial_decisions, prediction=pending.prediction, ticks=before,
        )
        self.state.trial = trial
        self.state.pending = None
        change = pending.change + (f" ({pending.macro_id})" if pending.macro_id else "")
        self._log_change(ChangeLogEntry(version=new.version, change=change, by="system 2", cycle_id=pending.cycle_id, decision=self.state.decisions, status="trial"))
        self._note(
            "trial_started",
            f"{change} took effect as version {new.version}; observed for {trial.of} decisions against the {len(before)} before it",
            pending.cycle_id,
            new.version,
        )

    def _judge(self) -> None:
        host = self.host
        with self._lock:
            trial = self.state.trial
            if trial is None:
                return
            configuration = host.configuration
            bounds = configuration.bounds
            table = trial_table(trial, bounds.return_steps, bounds.return_gamma)
        questions = {"verdict": ChoiceQuestion(instructions=f"{preamble(JUDGE_SPEC)} {JUDGE_QUESTION}", criteria=VERDICT_CRITERIA)}
        result = run_system2_instance(
            host.slow_client, JUDGE_SPEC, table.text, questions,
            budget=bounds.call_budget_sec, yes_at=bounds.yes_at, tolerance=bounds.probability_tolerance,
        )
        with self._lock:
            trial = self.state.trial
            if trial is None:
                return
            trial.judge.append(result)
            if result.missed or result.verdict is None:
                misses = sum(1 for r in trial.judge if r.missed or r.verdict is None)
                if misses >= bounds.judge_extensions_max:
                    self._note(
                        "no_verdict",
                        f"the trial judge never answered ({misses} misses, the last {result.miss_reason}); the trial of "
                        f"{trial.change} ends as revert with no verdict, and the configuration before it is restored",
                        trial.cycle_id,
                        trial.version,
                    )
                    self._finish_trial(trial, "revert", table, by="no verdict")
                    return
                trial.extensions += 1
                trial.of += bounds.judge_extension
                self._note(
                    "judge_missed",
                    f"the trial judge missed ({result.miss_reason}); the trial of {trial.change} is extended by "
                    f"{bounds.judge_extension} decisions to {trial.of}",
                    trial.cycle_id,
                    trial.version,
                )
                self.save()
                return
            self._finish_trial(trial, result.verdict, table, by="the trial judge")  # type: ignore[arg-type]

    def _safety_revert(self, why: str) -> None:
        with self._lock:
            trial = self.state.trial
            if trial is None:
                return
            bounds = self.host.configuration.bounds
            table = trial_table(trial, bounds.return_steps, bounds.return_gamma)
            table = table.model_copy(update={"text": table.text + f"\nsafety bound: {why}"})
            self._finish_trial(trial, "revert", table, by="the safety bound")

    def _finish_trial(self, trial: TrialState, verdict: Literal["keep", "revert"], table: TrialTable, *, by: TrialBy) -> None:
        """Record the verdict; on revert, queue the previous configuration exactly, with the version bumped."""
        safety = by == "the safety bound"
        s = self.state
        bounds = self.host.configuration.bounds
        revert: Optional[ConfigDiff] = None
        if verdict == "revert":
            base = self.host.next_configuration()
            restored = Configuration.model_validate({**trial.previous.model_dump(), "version": base.version + 1})
            revert = config_diff(base, restored)
            self.host.request_configuration(restored)
            s.pending = PendingChange(
                cycle_id=trial.cycle_id, change=f"revert:{trial.change}", kind=trial.kind, stage="revert",
                instance=trial.instance, decision=s.decisions, version=restored.version, safety=safety,
                no_verdict=by == "no verdict", restore=trial.previous,
            )
        s.change_log = [
            e.model_copy(update={"status": "kept" if verdict == "keep" else "reverted"}) if e.version == trial.version and e.status == "trial" else e
            for e in s.change_log
        ]
        s.verdicts = (s.verdicts + [VerdictSummary(cycle_id=trial.cycle_id, change=trial.change, version=trial.version, verdict=verdict, by=by)])[-VERDICTS_KEPT:]
        if trial.cooling_key is not None:
            s.cooling[trial.cooling_key] = s.decisions + bounds.cooling_decisions
        s.trial = None
        record = TrialRecord(
            cycle_id=trial.cycle_id, change=trial.change, kind=trial.kind, instance=trial.instance, detail=trial.detail,
            previous_version=trial.previous.version, version=trial.version, started_at=trial.started_at,
            started_decision=trial.started_decision, started_episode=trial.started_episode, started_tick=trial.started_tick,
            due_decision=trial.started_decision + trial.of, extensions=trial.extensions, judged_at=DecisionLogger.now_iso(),
            judged_decision=s.decisions, judge=list(trial.judge), table=table, verdict=verdict, safety_revert=safety, by=by,
            revert=revert,
        )
        self.save()
        self._emit(
            TrialVerdictTrace(
                cycle_id=trial.cycle_id, timestamp=DecisionLogger.now_iso(), episode_id=self.host.episode_id, trial=record,
                calls=len(trial.judge), usage=total_usage(trial.judge),
            )
        )

    def _abandon_macro(self) -> None:
        with self._lock:
            pending = self.state.pending
            if pending is None or pending.stage != "macro_requested":
                return
            self.state.pending = None
            self._note(
                "macro_abandoned",
                f"{pending.change}: no answer from the slow path within {self.host.configuration.bounds.trial_decisions} decisions; the request is dropped",
                pending.cycle_id,
            )
            self.save()

    # ------------------------------------------------------------------------------------------------
    # Records and state.

    def _status(self) -> System2Status:
        s = self.state
        trial = s.trial
        pending = s.pending
        return System2Status(
            decisions=s.decisions,
            cooling_left={k: max(0, v - s.decisions) for k, v in s.cooling.items()},
            change_log=tuple(s.change_log),
            trial=TrialStatus(cycle_id=trial.cycle_id, change=trial.change, version=trial.version, observed=trial.during(), of=trial.of) if trial else None,
            pending=f"{pending.change} ({pending.stage.replace('_', ' ')})" if pending else None,
            tests=tuple(s.tests),
            verdicts=tuple(s.verdicts),
        )

    def _log_change(self, entry: ChangeLogEntry) -> None:
        self.state.change_log = (self.state.change_log + [entry])[-CHANGE_LOG_KEPT:]

    def _note(self, kind: NoteKind, detail: str, cycle_id: Optional[str] = None, version: Optional[int] = None) -> None:
        self._emit(
            System2Note(
                cycle_id=cycle_id, timestamp=DecisionLogger.now_iso(), episode_id=getattr(self.host, "episode_id", ""),
                kind=kind, detail=detail, version=version,
            )
        )

    def _emit(self, record: Record) -> None:
        with self._lock:
            self.records.append(record)
            listeners = list(self._listeners)
            self.host.logger.log_reflection(record)
        for listener in listeners:
            try:
                listener(record)
            except Exception:  # noqa: BLE001 - a listener (the live page) never stops System 2
                pass

    def save(self) -> None:
        """Write `system2.json` (atomically) when a path is set."""
        if self.state_path is None or not self._begun:
            return
        configuration = self.host.configuration
        self.state.fingerprint = fingerprint(configuration)
        self.state.configuration_version = configuration.version
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(self.state.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(self.state_path)
