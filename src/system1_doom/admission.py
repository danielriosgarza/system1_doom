"""Admission of a proposed macro-action: bounds first, then d1-ultra's admit instance decides.

A proposal (from the slow worker's Codex call or template) passes three hand-written bounds before any
instance sees it: it must parse into the typed schema, be legal (a safe id, known primitives only, a
finite duration that is not a built-in's), and survive a sandbox rollout in the bounded simulator.
Then the admit instance, one d1-ultra call over the proposal and its sandbox summary, gives one noul:
the proposal is admitted when that probability is d1's own yes (0.5 or more). There is no quality
score and no threshold of our own; a missed admit call rejects the proposal, because nothing stands in
for d1's answer.

An admitted macro does not enter the menu here: the controller adds it to the configuration's admitted
macros, which take effect at the next tick boundary.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from system1_doom.actions import (
    MAX_ALLOWED_MACRO_DURATION,
    PRIMITIVE_ACTION_IDS,
    ActionSpec,
    ActionVocabulary,
    PreconditionSpec,
)
from system1_doom.archive import StrategyEntry
from system1_doom.d1_client import D1UltraClient
from system1_doom.instance import ADMIT_SPEC, InstanceResult, run_admit
from system1_doom.simulator import BoundedSimulator, ProjectedOutcome
from system1_doom.state import WorldState


class MacroActionProposal(BaseModel):
    """Typed schema that LLM-generated proposals must parse into (Spec Section 13)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=2, max_length=64)
    description: str = Field(min_length=5, max_length=256)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    preconditions: PreconditionSpec = Field(default_factory=PreconditionSpec)
    maximum_duration: int = Field(ge=1, le=MAX_ALLOWED_MACRO_DURATION)
    termination_condition: str = Field(min_length=2, max_length=128)
    primitive_expansion: List[str]
    strategy_id: Optional[str] = None


AdmissionStage = Literal["parse", "legality", "sandbox", "d1", "admit"]


class AdmissionStageResult(BaseModel):
    """Outcome of one admission stage, for traces: parse, legality, sandbox (bounds), d1 (the admit
    instance's yes or no), admit (the macro handed to the configuration)."""

    model_config = ConfigDict(frozen=True)

    stage: AdmissionStage
    passed: bool
    skipped: bool = False
    reason: str = ""


class AdmissionDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    admitted: bool
    raw_proposal: str
    parsed_proposal: Optional[MacroActionProposal] = None
    admitted_action_id: Optional[str] = None
    admitted_strategy_id: Optional[str] = None
    admitted_action: Optional[ActionSpec] = None
    admitted_strategy: Optional[StrategyEntry] = None
    sandbox_outcome: Optional[ProjectedOutcome] = None
    d1_admission_probability: Optional[float] = None
    admit_instance: Optional[InstanceResult] = None
    rejection_reason: str = ""
    stage_results: List[AdmissionStageResult] = Field(default_factory=list)
    # Set by the slow worker: which generator wrote the proposal and which module asked for it.
    source: Optional[Literal["codex", "template", "custom"]] = None
    source_module: Optional[str] = None


def admit_evidence(
    action: ActionSpec, outcome: ProjectedOutcome, problem_description: str, existing_action_ids: List[str]
) -> str:
    """The admit instance's state text: the proposal, its sandbox summary, the request, the menu as it is."""
    pre = action.preconditions.model_dump(exclude_defaults=True)
    lines = [
        "[proposal]",
        f"id {action.id}: {action.description}",
        f"primitives in order: {', '.join(action.primitive_expansion)}",
        f"maximum duration {action.maximum_duration} primitives; ends when {action.termination_condition}",
        f"preconditions: {', '.join(f'{k} {v}' for k, v in sorted(pre.items())) if pre else 'none'}",
        "",
        "[sandbox]",
        "a rough projection from a hand-written simulator, not the game: "
        f"expected value {outcome.expected_value:+.2f}, damage in {outcome.expected_damage_taken:.1f}, "
        f"damage out {outcome.expected_damage_dealt:.1f}, survival {outcome.survival_probability:.2f}, "
        f"progress {outcome.expected_positional_progress:.2f}",
        "",
        "[request]",
        problem_description or "a new macro-action was requested",
        "",
        "[menu]",
        f"the actions that exist now: {', '.join(existing_action_ids)}",
    ]
    return "\n".join(lines)


class ProposalAdmissionPipeline:
    """
    Admission of a slow-path proposal (Spec Section 13):
      proposal -> parse into the typed schema -> legality (safe id, known primitives, finite duration,
      not a built-in) -> sandbox rollout in the bounded simulator -> the admit instance's yes or no.
    """

    def __init__(
        self,
        vocabulary: ActionVocabulary,
        simulator: BoundedSimulator,
        d1_client: D1UltraClient,
        call_budget_sec: float = 5.0,
        yes_at: float = 0.5,
    ) -> None:
        self.vocabulary = vocabulary
        self.simulator = simulator
        self.d1_client = d1_client
        self.call_budget_sec = call_budget_sec
        self.yes_at = yes_at

    @staticmethod
    def _extract_json_object(raw_text: str) -> Dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("No JSON object found in proposal output.")
        return json.loads(match.group(0))

    def evaluate_and_admit(
        self,
        raw_proposal: str,
        reference_state: WorldState,
        problem_description: str = "",
    ) -> AdmissionDecisionResult:
        stages: List[AdmissionStageResult] = []

        def fail(stage: AdmissionStage, reason: str) -> List[AdmissionStageResult]:
            return stages + [AdmissionStageResult(stage=stage, passed=False, reason=reason)]

        # Step 1: Parse into typed schema
        try:
            data = self._extract_json_object(raw_proposal)
            proposal = MacroActionProposal.model_validate(data)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                rejection_reason=f"Schema parse error: {exc}",
                stage_results=fail("parse", f"Schema parse error: {exc}"),
            )
        stages.append(AdmissionStageResult(stage="parse", passed=True, reason="Parsed into MacroActionProposal."))

        # Step 2: Verify identifier safety and verify referenced primitives exist & finite execution bounds
        if not re.match(r"^[a-z][a-z0-9_]{1,62}$", proposal.id):
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                rejection_reason=f"Invalid action id '{proposal.id}'.",
                stage_results=fail("legality", f"Invalid action id '{proposal.id}'."),
            )

        if proposal.id in PRIMITIVE_ACTION_IDS:
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                rejection_reason=f"Proposal '{proposal.id}' cannot overwrite built-in primitive action.",
                stage_results=fail("legality", f"Proposal '{proposal.id}' cannot overwrite built-in primitive action."),
            )

        try:
            action_spec = ActionSpec(
                id=proposal.id,
                description=proposal.description,
                is_macro=True,
                parameters=proposal.parameters,
                preconditions=proposal.preconditions,
                maximum_duration=proposal.maximum_duration,
                termination_condition=proposal.termination_condition,
                primitive_expansion=tuple(proposal.primitive_expansion),
            )
        except ValidationError as exc:
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                rejection_reason=f"ActionSpec finite/primitive validation failed: {exc}",
                stage_results=fail("legality", f"ActionSpec finite/primitive validation failed: {exc}"),
            )
        stages.append(
            AdmissionStageResult(
                stage="legality",
                passed=True,
                reason=(
                    f"Valid id, known primitives only, {len(action_spec.primitive_expansion)} steps "
                    f"within maximum_duration {action_spec.maximum_duration}."
                ),
            )
        )

        # Step 3: Sandbox evaluation via BoundedSimulator
        sandbox_outcome = self.simulator.project_action(reference_state, action_spec)
        if sandbox_outcome.survival_probability <= 0.0 and reference_state.observation.health > 25.0:
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                sandbox_outcome=sandbox_outcome,
                rejection_reason="Sandbox rollout predicted fatal outcome from non-critical state.",
                stage_results=fail("sandbox", "Sandbox rollout predicted fatal outcome from non-critical state."),
            )
        stages.append(
            AdmissionStageResult(
                stage="sandbox",
                passed=True,
                reason=(
                    f"Rollout survives (survival {sandbox_outcome.survival_probability:.2f}, "
                    f"expected value {sandbox_outcome.expected_value:+.2f})."
                ),
            )
        )

        # Step 4: the admit instance, one d1-ultra call over the proposal and its sandbox summary
        evidence = admit_evidence(
            action_spec, sandbox_outcome, problem_description, [a.id for a in self.vocabulary.all_actions()]
        )
        answer = run_admit(self.d1_client, evidence, budget=self.call_budget_sec, spec=ADMIT_SPEC)
        if answer.missed or answer.admit is None:
            reason = f"The admit instance missed ({answer.miss_reason}); nothing stands in for its answer."
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                sandbox_outcome=sandbox_outcome,
                admit_instance=answer,
                rejection_reason=reason,
                stage_results=fail("d1", reason),
            )
        if answer.admit < self.yes_at:
            reason = f"The admit instance said no (p={answer.admit:.3f})."
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                sandbox_outcome=sandbox_outcome,
                d1_admission_probability=answer.admit,
                admit_instance=answer,
                rejection_reason=reason,
                stage_results=fail("d1", reason),
            )
        stages.append(AdmissionStageResult(stage="d1", passed=True, reason=f"The admit instance said yes (p={answer.admit:.3f})."))

        # Step 5: hand the macro and its strategy to the configuration (applied at the next tick boundary)
        strat_id = proposal.strategy_id or f"strat_{action_spec.id}"
        strategy = StrategyEntry(
            strategy_id=strat_id,
            context_signature=reference_state.context_signature(),
            action_sequence=(action_spec.id,) + action_spec.primitive_expansion[:2],
            observed_reward=0.0,
            success_rate=0.5,
            failure_modes=(),
            usage_count=0,
            novelty_signature=f"llm_admitted:{action_spec.id}",
        )
        stages.append(
            AdmissionStageResult(
                stage="admit",
                passed=True,
                reason=f"'{action_spec.id}' joins the configuration's admitted macros at the next tick boundary, with '{strat_id}'.",
            )
        )
        return AdmissionDecisionResult(
            admitted=True,
            raw_proposal=raw_proposal,
            parsed_proposal=proposal,
            admitted_action_id=action_spec.id,
            admitted_strategy_id=strat_id,
            admitted_action=action_spec,
            admitted_strategy=strategy,
            sandbox_outcome=sandbox_outcome,
            d1_admission_probability=answer.admit,
            admit_instance=answer,
            stage_results=stages,
        )
