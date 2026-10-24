from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from system1_doom.actions import (
    MAX_ALLOWED_MACRO_DURATION,
    PRIMITIVE_ACTION_IDS,
    ActionSpec,
    ActionVocabulary,
    PreconditionSpec,
)
from system1_doom.archive import StrategyArchive, StrategyEntry
from system1_doom.d1_client import D1UltraClient, NoulQuestion, ScoreQuestion
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


class AdmissionDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    admitted: bool
    raw_proposal: str
    parsed_proposal: Optional[MacroActionProposal] = None
    admitted_action_id: Optional[str] = None
    admitted_strategy_id: Optional[str] = None
    sandbox_outcome: Optional[ProjectedOutcome] = None
    d1_admission_probability: Optional[float] = None
    d1_quality_score: Optional[float] = None
    used_d1_ultra: bool = False
    rejection_reason: str = ""


class ProposalAdmissionPipeline:
    """
    Deterministic + d1-ultra admission gate for LLM proposals (Spec Section 13):
      LLM proposal
        -> parse into typed schema
        -> verify referenced primitives exist
        -> verify finite execution & resource/time bounds
        -> reject illegal game actions
        -> sandbox evaluation via BoundedSimulator
        -> decision: admit / reject (with d1-ultra safety & tactical gate)
    """

    def __init__(
        self,
        vocabulary: ActionVocabulary,
        archive: StrategyArchive,
        simulator: BoundedSimulator,
        d1_client: Optional[D1UltraClient] = None,
        min_d1_admission_prob: float = 0.40,
    ) -> None:
        self.vocabulary = vocabulary
        self.archive = archive
        self.simulator = simulator
        self.d1_client = d1_client
        self.min_d1_admission_prob = min_d1_admission_prob

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
        # Step 1: Parse into typed schema
        try:
            data = self._extract_json_object(raw_proposal)
            proposal = MacroActionProposal.model_validate(data)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                rejection_reason=f"Schema parse error: {exc}",
            )

        # Step 2: Verify identifier safety and verify referenced primitives exist & finite execution bounds
        if not re.match(r"^[a-z][a-z0-9_]{1,62}$", proposal.id):
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                rejection_reason=f"Invalid action id '{proposal.id}'.",
            )

        if proposal.id in PRIMITIVE_ACTION_IDS:
            return AdmissionDecisionResult(
                admitted=False,
                raw_proposal=raw_proposal,
                parsed_proposal=proposal,
                rejection_reason=f"Proposal '{proposal.id}' cannot overwrite built-in primitive action.",
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
            )

        # Step 4: Bounded d1-ultra admission decision (when d1-ultra client is enabled)
        d1_prob: Optional[float] = None
        d1_score: Optional[float] = None
        used_d1 = False
        if self.d1_client is not None and self.d1_client.enabled:
            state_str = (
                f"{reference_state.to_d1_state_text()}\n"
                f"Problem Trigger: {problem_description or 'Tactical action expansion requested'}\n"
                f"Candidate Macro-Action Proposal: id={action_spec.id}, desc={action_spec.description}, "
                f"expansion={list(action_spec.primitive_expansion)}, max_duration={action_spec.maximum_duration}, "
                f"termination={action_spec.termination_condition}\n"
                f"Sandbox Rollout: E[val]={sandbox_outcome.expected_value:+.2f}, "
                f"dmg_in={sandbox_outcome.expected_damage_taken:.1f}, dmg_out={sandbox_outcome.expected_damage_dealt:.1f}, "
                f"survival_prob={sandbox_outcome.survival_probability:.2f}"
            )
            resp = self.d1_client.decide(
                state=state_str,
                questions={
                    "admit_proposal": NoulQuestion(
                        instructions=(
                            "Should this bounded macro-action proposal be admitted into the Doom controller's "
                            "active action vocabulary as a safe, finite, tactically useful procedure?"
                        )
                    ),
                    "tactical_quality": ScoreQuestion(
                        instructions="Rate the tactical soundness of this macro-action sequence.",
                        criteria=[
                            "Harmful or redundant macro sequence",
                            "Acceptable bounded tactical macro sequence",
                            "Strong tactical macro sequence well-suited to the state",
                        ],
                    ),
                },
                timeout=5.0,
            )
            if resp is not None and "admit_proposal" in resp.raw_answers:
                used_d1 = True
                d1_prob = resp.noul("admit_proposal").noul
                if "tactical_quality" in resp.raw_answers:
                    d1_score = resp.score("tactical_quality").score
                if d1_prob < self.min_d1_admission_prob and (d1_score is None or d1_score < 0.85 or d1_prob < 0.20):
                    return AdmissionDecisionResult(
                        admitted=False,
                        raw_proposal=raw_proposal,
                        parsed_proposal=proposal,
                        sandbox_outcome=sandbox_outcome,
                        d1_admission_probability=d1_prob,
                        d1_quality_score=d1_score,
                        used_d1_ultra=True,
                        rejection_reason=f"Rejected by d1-ultra admission gate (p={d1_prob:.3f} < {self.min_d1_admission_prob}).",
                    )

        # Step 5: Admit into ActionVocabulary and StrategyArchive
        self.vocabulary.register_admitted_macro(action_spec)
        strat_id = proposal.strategy_id or f"strat_{action_spec.id}"
        self.archive.admit_strategy(
            StrategyEntry(
                strategy_id=strat_id,
                context_signature=reference_state.context_signature(),
                action_sequence=(action_spec.id,) + action_spec.primitive_expansion[:2],
                observed_reward=max(0.5, sandbox_outcome.expected_value),
                success_rate=0.65,
                failure_modes=(),
                usage_count=0,
                novelty_signature=f"llm_admitted:{action_spec.id}",
            )
        )

        return AdmissionDecisionResult(
            admitted=True,
            raw_proposal=raw_proposal,
            parsed_proposal=proposal,
            admitted_action_id=action_spec.id,
            admitted_strategy_id=strat_id,
            sandbox_outcome=sandbox_outcome,
            d1_admission_probability=d1_prob,
            d1_quality_score=d1_score,
            used_d1_ultra=used_d1,
        )
