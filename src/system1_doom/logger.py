from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

from system1_doom.admission import AdmissionStageResult
from system1_doom.tracing import (
    ArbiterTrace,
    ModuleTrace,
    OutcomeTrace,
    ProjectionChainTrace,
    SlowPathRequestTrace,
    StateTrace,
    SteeringTrace,
)

TRACE_SCHEMA_VERSION = 1


class TickTrace(BaseModel):
    """Compact per-tick decision trace (Spec Section 17).

    The fields after `learning` are the decision's anatomy (see `tracing.py`). They are optional,
    so traces written before they existed still parse.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: str
    tick: int
    state_hash: str
    context_signature: str
    budget_mode: Literal["full", "reduced", "critical"]
    available_actions: List[str]
    module_outputs: Dict[str, ModuleTrace]
    projection_results_used: Dict[str, Dict[str, float]]
    arbiter_distribution: Dict[str, float]
    selected_action: str
    primitive_steps_executed: List[str]
    exploration_state: Dict[str, Any]
    active_strategy: str
    reward_outcome: float
    used_d1_ultra: bool = False
    d1_arbiter_distribution: Dict[str, float] = Field(default_factory=dict)
    learning: Dict[str, Any] = Field(default_factory=dict)
    state: Optional[StateTrace] = None
    pruned_actions: Dict[str, str] = Field(default_factory=dict)
    arbiter: Optional[ArbiterTrace] = None
    projection_chain: Optional[ProjectionChainTrace] = None
    steering: Optional[SteeringTrace] = None
    outcome: Optional[OutcomeTrace] = None
    slow_path_request: Optional[SlowPathRequestTrace] = None
    budget_sec: Optional[float] = None
    timing_ms: Dict[str, float] = Field(default_factory=dict)


class ProposalTrace(BaseModel):
    """Audit trace for asynchronous LLM proposals and admission decisions (Spec Section 17)."""

    model_config = ConfigDict(frozen=True)

    timestamp: str
    request_context: str
    raw_proposal: str
    parsed_proposal: Optional[Dict[str, Any]] = None
    validation_result: str
    admission_decision: bool
    admitted_action_id: Optional[str] = None
    d1_admission_probability: Optional[float] = None
    subsequent_performance: List[float] = Field(default_factory=list)
    tick: Optional[int] = None
    source: Optional[Literal["codex", "template", "custom"]] = None
    source_module: Optional[str] = None
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
        self._tick_traces: List[TickTrace] = []
        self._proposal_traces: List[ProposalTrace] = []

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
