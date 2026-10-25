"""The decision log: one TickTrace per tick (`ticks.jsonl`), one ProposalTrace per proposal, and System 2's records.

Schema version 2 (design spec, section 10): a tick is the record of six d1-ultra instances, the five
senses and the central, each with its scope, its verbatim evidence, its full answers, whether it
spoke or missed, its timing and usage; the messages the central heard; the pick (`top`, `drawn` or
`missed`); and the executed action, its primitives and what it changed. System 2's cycles, trial verdicts
and notes go to `reflections.jsonl` (`reflection.py`), written from System 2's thread under a lock.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.admission import AdmissionStageResult
from system1_doom.configuration import ExplorationLevel
from system1_doom.d1_client import Usage
from system1_doom.evidence import Message
from system1_doom.instance import InstanceResult
from system1_doom.system1 import Pick, Targets
from system1_doom.tracing import (
    OutcomeTrace,
    ProjectionChainTrace,
    SlowPathRequestTrace,
    StateTrace,
)

TRACE_SCHEMA_VERSION = 2


class TickTrace(BaseModel):
    """One tick (schema version 2): the evidence, the six instances, the pick, and what it did."""

    model_config = ConfigDict(frozen=True)

    timestamp: str
    tick: int
    episode_id: str
    configuration_version: int = Field(description="The configuration this tick was decided under")
    configuration_changed: bool = Field(default=False, description="A pending configuration was applied at this tick's boundary")
    state_hash: str
    context_signature: str
    state: StateTrace
    available_actions: List[str] = Field(description="The legal menu, in menu order")
    pruned_actions: Dict[str, str] = Field(default_factory=dict, description="Every other action and the first bound it failed")
    instances: Dict[str, InstanceResult] = Field(description="The five senses in sense order, then the central")
    messages: List[Message] = Field(default_factory=list, description="What the senses that spoke sent the central")
    pick: Pick
    targets: Targets = Field(default_factory=Targets, description="The enemy and the pickup the senses chose for the motor")
    executed_action: Optional[str] = Field(description="The central's pick; None when the central missed and the tick idled")
    primitive_steps_executed: List[str]
    outcome: OutcomeTrace
    reward_outcome: float
    missed: bool = Field(description="The central missed: no keys were held for the decision")
    exploration_level: ExplorationLevel
    active_strategy: str
    projection_results_used: Dict[str, Dict[str, float]] = Field(default_factory=dict, description="The projections channel's numbers")
    projection_chain: Optional[ProjectionChainTrace] = None
    slow_path_request: Optional[SlowPathRequestTrace] = None
    timing_ms: Dict[str, float] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage, description="Summed over the tick's six calls")


class ProposalTrace(BaseModel):
    """A slow-path proposal and its admission: the bounds' stage results and the admit instance's answer."""

    model_config = ConfigDict(frozen=True)

    timestamp: str
    request_context: str
    raw_proposal: str
    parsed_proposal: Optional[Dict[str, Any]] = None
    validation_result: str
    admission_decision: bool
    admitted_action_id: Optional[str] = None
    d1_admission_probability: Optional[float] = Field(default=None, description="The admit instance's probability")
    admit_instance: Optional[InstanceResult] = Field(default=None, description="The admit instance's call, in full")
    subsequent_performance: List[float] = Field(default_factory=list)
    tick: Optional[int] = None
    source: Optional[Literal["codex", "template", "custom"]] = None
    source_module: Optional[str] = Field(default=None, description="Who asked for the proposal")
    stage_results: List[AdmissionStageResult] = Field(default_factory=list)
    sandbox_summary: Optional[Dict[str, float]] = None
    admitted_strategy_id: Optional[str] = None


class DecisionLogger:
    """Writes structured JSONL decision traces for both ticks and LLM proposals."""

    def __init__(self, log_dir: Optional[Union[str, Path]] = None) -> None:
        self.log_dir = Path(log_dir) if log_dir is not None else Path("logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.ticks_path = self.log_dir / "ticks.jsonl"
        self.proposals_path = self.log_dir / "proposals.jsonl"
        self.reflections_path = self.log_dir / "reflections.jsonl"
        self._tick_traces: List[TickTrace] = []
        self._proposal_traces: List[ProposalTrace] = []
        self._reflections: List[BaseModel] = []
        self._reflection_lock = threading.Lock()

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_tick(self, trace: TickTrace) -> None:
        self._tick_traces.append(trace)
        with self.ticks_path.open("a", encoding="utf-8") as f:
            f.write(trace.model_dump_json() + "\n")

    def log_proposal(self, trace: ProposalTrace) -> None:
        self._proposal_traces.append(trace)
        with self.proposals_path.open("a", encoding="utf-8") as f:
            f.write(trace.model_dump_json() + "\n")

    def log_reflection(self, record: BaseModel) -> None:
        """Append one of System 2's records (a cycle, a verdict or a note) to `reflections.jsonl`."""
        line = record.model_dump_json()
        with self._reflection_lock:
            self._reflections.append(record)
            with self.reflections_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def record_macro_performance(self, action_id: str, reward: float) -> None:
        for idx, pt in enumerate(self._proposal_traces):
            if pt.admitted_action_id == action_id:
                updated_perf = list(pt.subsequent_performance) + [round(reward, 4)]
                updated = pt.model_copy(update={"subsequent_performance": updated_perf})
                self._proposal_traces[idx] = updated
                with self.proposals_path.open("a", encoding="utf-8") as f:
                    f.write(updated.model_dump_json() + "\n")

    @property
    def tick_traces(self) -> List[TickTrace]:
        return list(self._tick_traces)

    @property
    def proposal_traces(self) -> List[ProposalTrace]:
        return list(self._proposal_traces)

    @property
    def reflection_records(self) -> List[BaseModel]:
        with self._reflection_lock:
            return list(self._reflections)
