from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict

from system1_doom.actions import PRIMITIVE_ACTION_IDS
from system1_doom.admission import AdmissionDecisionResult, ProposalAdmissionPipeline
from system1_doom.state import WorldState


class ExpansionRequest(BaseModel):
    """Bounded request emitted by a module when action expansion is needed (Spec Section 12)."""

    model_config = ConfigDict(frozen=True)

    source_module: str
    problem_description: str
    world_state: WorldState
    existing_action_ids: Tuple[str, ...]


PROPOSAL_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "description",
        "maximum_duration",
        "termination_condition",
        "primitive_expansion",
        "strategy_id",
    ],
    "properties": {
        "id": {
            "type": "string",
            "description": "Snake_case identifier for the new macro-action (e.g. weave_fire_retreat)",
        },
        "description": {
            "type": "string",
            "description": "Concise tactical description of what the macro-action accomplishes",
        },
        "maximum_duration": {
            "type": "integer",
            "minimum": 2,
            "maximum": 8,
        },
        "termination_condition": {
            "type": "string",
        },
        "primitive_expansion": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {
                "type": "string",
                "enum": list(PRIMITIVE_ACTION_IDS),
            },
        },
        "strategy_id": {
            "type": "string",
        },
    },
}


class SlowLLMWorker:
    """
    Asynchronous slow-path worker (Spec Section 12).
    Never blocks the synchronous game control loop.
    Uses `codex exec` (OpenAI Codex CLI from subscription) to synthesize new bounded
    macro-actions and passes every output through `ProposalAdmissionPipeline`.
    """

    def __init__(
        self,
        admission_pipeline: ProposalAdmissionPipeline,
        use_codex_cli: bool = True,
        codex_timeout_sec: float = 20.0,
        custom_generator: Optional[Callable[[ExpansionRequest], str]] = None,
        enabled: bool = True,
    ) -> None:
        self.admission_pipeline = admission_pipeline
        self.use_codex_cli = use_codex_cli and bool(shutil.which("codex"))
        self.codex_timeout_sec = codex_timeout_sec
        self.custom_generator = custom_generator
        self.enabled = enabled

        self._lock = threading.Lock()
        self._busy = False
        self._completed: List[AdmissionDecisionResult] = []
        self._proposal_counter = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slow-llm-codex")

    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def _fallback_template_proposal(self, req: ExpansionRequest, seq_num: int) -> str:
        """Deterministic bounded proposal synthesizer used when Codex CLI is offline/timed out."""
        mod = req.source_module
        if mod in ("survival", "combat"):
            action_id = f"evasive_burst_{seq_num}"
            expansion = ["strafe_right", "shoot", "strafe_left", "move_backward"]
            desc = "Sidestep right, fire weapon at threat, sidestep left, and backpedal out of projectile line"
            precond = {"min_ammo": 1, "requires_visible_enemy": True}
        elif mod == "navigation":
            action_id = f"corner_clear_step_{seq_num}"
            expansion = ["use", "turn_left", "move_forward", "strafe_right"]
            desc = "Interact with obstacle/door, pivot left, advance forward, and sidestep clear of wall"
            precond = {"min_ammo": 0, "requires_visible_enemy": False}
        else:
            action_id = f"sweep_and_collect_{seq_num}"
            expansion = ["strafe_left", "move_forward", "move_forward", "strafe_right"]
            desc = "Strafe-advance toward resource pickup while evading crossfire"
            precond = {"min_ammo": 0, "requires_visible_pickup": False}

        return json.dumps(
            {
                "id": action_id,
                "description": desc,
                "parameters": {"source_module": mod, "duration": len(expansion)},
                "preconditions": precond,
                "maximum_duration": len(expansion),
                "termination_condition": "sequence_completed_or_threat_cleared",
                "primitive_expansion": expansion,
                "strategy_id": f"strat_{action_id}",
            }
        )

    def _invoke_codex_cli(self, req: ExpansionRequest, seq_num: int) -> str:
        prompt = (
            "You are the asynchronous Slow LLM Worker for a bounded Doom controller.\n"
            f"Source Module: {req.source_module}\n"
            f"Problem Description: {req.problem_description}\n"
            f"World State Snapshot:\n{req.world_state.to_d1_state_text()}\n"
            f"Existing Actions (do not reuse these IDs): {list(req.existing_action_ids)}\n"
            f"Allowed Primitive Actions ONLY: {list(PRIMITIVE_ACTION_IDS)}\n"
            "Propose ONE new bounded macro-action as a JSON object matching the output schema. "
            "Ensure `id` is lowercase snake_case, `primitive_expansion` has 3 to 5 allowed primitives, "
            "`maximum_duration` equals or exceeds the length of `primitive_expansion`, `description` is under "
            "200 characters, and `termination_condition` is a short phrase under 100 characters."
        )

        with tempfile.TemporaryDirectory(prefix="doom_codex_") as tmpdir:
            schema_path = Path(tmpdir) / "schema.json"
            out_path = Path(tmpdir) / "output.json"
            schema_path.write_text(json.dumps(PROPOSAL_JSON_SCHEMA), encoding="utf-8")

            cmd = [
                "codex",
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "-s",
                "read-only",
                "-c",
                'model_reasoning_effort="low"',
                "--output-schema",
                str(schema_path),
                "-o",
                str(out_path),
                prompt,
            ]
            subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.codex_timeout_sec,
                check=True,
                text=True,
            )
            if out_path.is_file():
                content = out_path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        raise RuntimeError("Codex CLI did not produce an output JSON file.")

    def generate_and_validate_sync(self, req: ExpansionRequest) -> AdmissionDecisionResult:
        with self._lock:
            self._proposal_counter += 1
            seq_num = self._proposal_counter

        raw_proposal: str
        if self.custom_generator is not None:
            raw_proposal = self.custom_generator(req)
        elif self.use_codex_cli:
            try:
                raw_proposal = self._invoke_codex_cli(req, seq_num)
            except Exception:
                raw_proposal = self._fallback_template_proposal(req, seq_num)
        else:
            raw_proposal = self._fallback_template_proposal(req, seq_num)

        return self.admission_pipeline.evaluate_and_admit(
            raw_proposal=raw_proposal,
            reference_state=req.world_state,
            problem_description=req.problem_description,
        )

    def enqueue_request(self, req: ExpansionRequest) -> bool:
        """Non-blocking enqueue of an action-expansion request from the fast loop."""
        if not self.enabled:
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def _job() -> None:
            try:
                result = self.generate_and_validate_sync(req)
                with self._lock:
                    self._completed.append(result)
            finally:
                with self._lock:
                    self._busy = False

        self._executor.submit(_job)
        return True

    def drain_completed_results(self) -> List[AdmissionDecisionResult]:
        with self._lock:
            items = list(self._completed)
            self._completed.clear()
            return items

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
