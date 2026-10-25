"""System 2's records: `reflections.jsonl`, one line per cycle, per trial verdict and per note.

Design spec, sections 8 and 10. Every System 2 cycle writes a `ReflectionTrace`: when and why it ran, the
windows, each reflector's instance result (its verbatim evidence and full answers), the change criteria
each was offered and the bounds that removed the rest, the messages, System 2's central's result and
choice, the history test's whole table when one ran, the change queued with its configuration diff, and
the calls and cost. A trial's verdict is appended later as its own `TrialVerdictTrace`, referring to the
cycle that made the change, with the trial record (started at, judged at, every judge attempt, the
before-and-during table, the verdict, and whether the safety bound reverted it without asking). Short
`System2Note`s mark what happens between: a trial starting at a tick boundary, a missed judge, a macro the
admit instance admitted or rejected, a revert taking effect, a change System 2 did not make, a restore.

The three are told apart by `record` (`cycle`, `verdict`, `note`); `ReflectionRecordAdapter` reads any line.
Trace schema version stays 2: this is a new file, and every other model only gained optional fields.
"""

from __future__ import annotations

from typing import Annotated, Dict, Iterable, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from system1_doom.d1_client import Usage
from system1_doom.history_channels import Window
from system1_doom.history_test import HistoryTestResult
from system1_doom.instance import InstanceResult
from system1_doom.reflectors import ConfigDiff, Proposal

REFLECTIONS_FILE = "reflections.jsonl"
CycleTrigger = Literal["decisions", "episode_end"]
CycleOutcome = Literal[
    "no_proposal",  # no reflector proposed a change the bounds allow: no central call
    "central_missed",  # System 2's central missed: no change this cycle
    "none_chosen",  # the central chose `none`
    "test_waiting",  # a scope change with too few stored ticks (or calls left) for a test: it waits
    "test_failed",  # the history test blocked the scope change
    "queued",  # a change was queued and takes effect at the next tick boundary, as a trial
    "macro_requested",  # the slow path was asked for a macro; the admit instance decides
    "macro_not_enqueued",  # the slow path could not take the request
]
ChangeKindName = Literal["scope", "macro", "retire", "strategy", "level"]
NoteKind = Literal[
    "trial_started",
    "judge_missed",
    "macro_admitted",
    "macro_rejected",
    "macro_abandoned",
    "revert_applied",
    "external_change",
    "restored",
    "fresh_start",
    "error",
]


class TrialRow(BaseModel):
    """One period of a trial's before-and-during table."""

    model_config = ConfigDict(frozen=True)

    decisions: int = 0
    reward_per_decision: float = 0.0
    damage_per_decision: float = 0.0
    kills: float = 0.0
    deaths: int = 0
    missed_ticks: int = 0
    followed: Optional[int] = Field(default=None, description="The changed instance's followed messages (picks, for the central)")
    paid_off: Optional[int] = None
    paid_off_rate: Optional[float] = None


class TrialTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    before: TrialRow
    during: TrialRow
    instance: Optional[str] = Field(default=None, description="The changed instance; None for menu, strategy and level changes")
    prediction: Optional[str] = Field(default=None, description="The history test's prediction, when there was one")
    text: str = Field(description="The table as the trial judge was shown it")


class TrialRecord(BaseModel):
    """A trial from the change taking effect to its verdict."""

    model_config = ConfigDict(frozen=True)

    cycle_id: str
    change: str
    kind: ChangeKindName
    instance: Optional[str] = None
    detail: str = ""
    previous_version: int
    version: int
    started_at: str
    started_decision: int
    started_episode: str
    started_tick: int
    due_decision: int
    extensions: int = Field(default=0, description="Times a missed judge extended the trial")
    judged_at: Optional[str] = None
    judged_decision: Optional[int] = None
    judge: List[InstanceResult] = Field(default_factory=list, description="Every judge call, misses included")
    table: Optional[TrialTable] = None
    verdict: Optional[Literal["keep", "revert"]] = None
    safety_revert: bool = Field(default=False, description="Reverted by the safety bound, without asking the judge")
    revert: Optional[ConfigDiff] = Field(default=None, description="The revert queued: previous configuration restored, version bumped")


class AppliedChange(BaseModel):
    """The change a cycle set in motion."""

    model_config = ConfigDict(frozen=True)

    change: str
    kind: ChangeKindName
    instance: Optional[str] = None
    description: str = ""
    diff: Optional[ConfigDiff] = Field(default=None, description="None for a macro request: the admit instance decides later")
    queued: bool = Field(default=False, description="Queued through request_configuration, for the next tick boundary")


class ReflectionTrace(BaseModel):
    """One System 2 cycle."""

    model_config = ConfigDict(frozen=True)

    record: Literal["cycle"] = "cycle"
    cycle_id: str
    started_at: str
    finished_at: str
    trigger: CycleTrigger
    episode_id: str
    decision: int = Field(description="System 2's decision count when the cycle started")
    configuration_version: int
    windows: List[Window] = Field(default_factory=list)
    offered: Dict[str, List[str]] = Field(default_factory=dict, description="Reflector -> the change criteria it was asked over")
    blocked: Dict[str, Dict[str, str]] = Field(default_factory=dict, description="Reflector -> change -> the bound that removed it")
    skipped: Dict[str, str] = Field(default_factory=dict, description="Reflector -> why it was not called")
    reflectors: Dict[str, InstanceResult] = Field(default_factory=dict)
    messages: List[Proposal] = Field(default_factory=list)
    central_criteria: List[str] = Field(default_factory=list)
    central: Optional[InstanceResult] = None
    choice: Optional[str] = None
    tie: bool = False
    tied: List[str] = Field(default_factory=list)
    outcome: CycleOutcome
    history_test: Optional[HistoryTestResult] = None
    applied: Optional[AppliedChange] = None
    trial: Optional[TrialRecord] = Field(default=None, description="Always None here: the verdict is its own record")
    calls: int = 0
    usage: Usage = Field(default_factory=Usage)
    notes: List[str] = Field(default_factory=list)


class TrialVerdictTrace(BaseModel):
    """A trial's verdict, referring to the cycle that made the change."""

    model_config = ConfigDict(frozen=True)

    record: Literal["verdict"] = "verdict"
    cycle_id: str
    timestamp: str
    episode_id: str
    trial: TrialRecord
    calls: int = 0
    usage: Usage = Field(default_factory=Usage)


class System2Note(BaseModel):
    model_config = ConfigDict(frozen=True)

    record: Literal["note"] = "note"
    cycle_id: Optional[str] = None
    timestamp: str
    episode_id: str
    kind: NoteKind
    detail: str
    version: Optional[int] = None


ReflectionRecord = Annotated[Union[ReflectionTrace, TrialVerdictTrace, System2Note], Field(discriminator="record")]
ReflectionRecordAdapter: TypeAdapter = TypeAdapter(ReflectionRecord)


class System2EpisodeSummary(BaseModel):
    """What System 2 did while an episode was played, counted from its records (`episode.json`)."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    cycles: int = 0
    tests: int = Field(default=0, description="History tests that ran (not those that waited)")
    tests_passed: int = 0
    trials_started: int = 0
    trials_judged: int = 0
    kept: int = 0
    reverted: int = 0
    calls: int = 0
    usd: float = 0.0


def summarize(records: Iterable[Union[ReflectionTrace, TrialVerdictTrace, System2Note]], enabled: bool = True) -> System2EpisodeSummary:
    cycles = tests = passed = started = judged = kept = reverted = calls = 0
    usd = 0.0
    for r in records:
        if isinstance(r, ReflectionTrace):
            cycles += 1
            calls += r.calls
            usd += r.usage.cost
            if r.history_test is not None and r.history_test.status != "waiting":
                tests += 1
                passed += 1 if r.history_test.passed else 0
        elif isinstance(r, TrialVerdictTrace):
            judged += 1
            calls += r.calls
            usd += r.usage.cost
            kept += 1 if r.trial.verdict == "keep" else 0
            reverted += 1 if r.trial.verdict == "revert" else 0
        elif r.kind == "trial_started":
            started += 1
    return System2EpisodeSummary(
        enabled=enabled, cycles=cycles, tests=tests, tests_passed=passed, trials_started=started,
        trials_judged=judged, kept=kept, reverted=reverted, calls=calls, usd=round(usd, 9),
    )


def load_reflections(text: str) -> List[Union[ReflectionTrace, TrialVerdictTrace, System2Note]]:
    """Every record of a `reflections.jsonl` text, in order."""
    return [ReflectionRecordAdapter.validate_json(line) for line in text.splitlines() if line.strip()]
