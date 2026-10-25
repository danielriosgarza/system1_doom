"""An instance: one d1-ultra call with its own scope of evidence and its own finite questions.

Design spec, sections 4 and 5. An `InstanceSpec` is data: a name, a kind (`sense`, `central`, `admit`),
a scope, the concern its instructions name, and (for a sense) its reason vocabulary. Running an
instance builds exactly one payload:

- `state` is the rendered scope text, and nothing else;
- the questions are the kind's finite questions: a sense asks `speak` (noul), `action` (a choice over
  the legal menu) and `reason` (a choice over its reasons); a sense that chooses a motor target also
  asks `target`, a choice over the visible enemies (the combat sense: which one the aim locks onto) or
  the remembered pickups (the resource sense: which one a pickup-seeking action walks to), asked only
  when its scope shows them (`threats`, `landmarks`) and there are two or more (a choice needs two
  options; a lone candidate is the target without a question); the central asks
  `choose` (a choice over the legal menu); the admit instance asks `admit` (noul) over a proposal and
  its sandbox summary;
- the choice criteria for `action` and `choose` are exactly the legal menu, in menu order, id ->
  description; projections and values appear in the state text when in scope, never in the criteria;
- `images` carries the screen only when `frame` is in scope.

System 2's instances (design spec, section 8) are the same part: a reflector asks `speak` (noul),
`change` (a choice over the configuration changes the bounds allow) and `reason` (a choice over its
reasons); System 2's central asks `configure` (a choice over the proposed changes and `none`); the trial
judge asks `verdict` (`keep` or `revert`). Their questions are built in `reflectors.py` and
`system2.py`; `run_system2_instance` sends one and reads it here, with the same misses.

The instructions name the instance, its concern and that it sees only the evidence given; they never
say how to weigh anything. The answer is recorded in full. A call that times out, fails, names an action
(or a change) outside its criteria, or returns malformed probabilities (negative, or not summing to 1
within the bound's tolerance) is a miss, kept with its raw answer and never repaired.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from system1_doom.configuration import CentralConfig, SenseConfig, TargetKind, reason_words
from system1_doom.d1_client import (
    ChoiceQuestion,
    D1CallResult,
    D1UltraClient,
    MissReason,
    NoulQuestion,
    QuestionSpec,
    Usage,
)
from system1_doom.evidence import (
    EvidenceInputs,
    MenuItem,
    enemy_line,
    landmark_line,
    render_scope,
    shown_enemies,
    shown_landmarks,
)

InstanceKind = Literal["sense", "central", "admit", "reflector", "system2_central", "judge"]

ADMIT_CONCERN = "whether a proposed macro-action is a safe, finite and useful addition to the legal menu"


class InstanceSpec(BaseModel):
    """What an instance is: data, from the configuration."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: InstanceKind
    scope: Tuple[str, ...] = ()
    concern: str
    reasons: Tuple[str, ...] = ()
    target: Optional[TargetKind] = Field(default=None, description="The motor target a sense chooses, if any")
    title: str = Field(default="", description="How a reflector's instructions name it, e.g. 'survival auditor'")


def sense_spec(name: str, config: SenseConfig) -> InstanceSpec:
    return InstanceSpec(
        name=name, kind="sense", scope=config.scope, concern=config.concern, reasons=config.reasons, target=config.target
    )


def central_spec(config: CentralConfig, scope: Optional[Sequence[str]] = None) -> InstanceSpec:
    return InstanceSpec(name="central", kind="central", scope=tuple(scope if scope is not None else config.scope), concern=config.concern)


ADMIT_SPEC = InstanceSpec(name="admit", kind="admit", scope=(), concern=ADMIT_CONCERN)


class InstanceResult(BaseModel):
    """Everything one instance call produced, as the trace and the history keep it."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: InstanceKind
    scope: Tuple[str, ...] = ()
    evidence: str = Field(description="The state text exactly as sent")
    image_ref: Optional[str] = Field(default=None, description="The screen sent as the call's image, when frame was in scope")
    answers: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Every answer in full, as returned")
    speak: Optional[float] = Field(default=None, description="A sense's speak probability")
    spoke: bool = False
    strength: Optional[float] = Field(default=None, description="A sense's strength: its speak probability, unscaled")
    action: Optional[str] = Field(default=None, description="The action d1 gave the highest probability (first in menu order on a tie)")
    action_probabilities: Dict[str, float] = Field(default_factory=dict)
    reason: Optional[str] = None
    reason_probabilities: Dict[str, float] = Field(default_factory=dict)
    target: Optional[str] = Field(default=None, description="The enemy or pickup a sense chose for the motor (first in criteria order on a tie)")
    target_probabilities: Dict[str, float] = Field(default_factory=dict)
    target_kind: Optional[TargetKind] = Field(default=None, description="What a sense's target is (enemy or pickup), from its configuration")
    target_line: Optional[str] = Field(default=None, description="The chosen target's criterion: the line the sense saw it in")
    admit: Optional[float] = Field(default=None, description="The admit instance's probability")
    change: Optional[str] = Field(default=None, description="A reflector's or System 2's central's top change (first in criteria order on a tie)")
    change_probabilities: Dict[str, float] = Field(default_factory=dict)
    verdict: Optional[str] = Field(default=None, description="The trial judge's top answer: keep or revert")
    verdict_probabilities: Dict[str, float] = Field(default_factory=dict)
    missed: bool = False
    miss_reason: Optional[MissReason] = None
    error: Optional[str] = None
    raw_answer: Optional[Any] = Field(default=None, description="The answer as returned, when it was malformed or off the menu")
    latency_ms: float = 0.0
    retries: int = 0
    usage: Usage = Field(default_factory=Usage)


def _preamble(spec: InstanceSpec) -> str:
    who = {
        "sense": f"You are the {spec.name} sense of a Doom agent",
        "central": "You are the central action chooser of a Doom agent",
        "admit": "You are the admission instance of a Doom agent",
        "reflector": f"You are the {spec.title or spec.name} of a Doom agent's slow system",
        "system2_central": "You are the central of a Doom agent's slow system",
        "judge": "You are the trial judge of a Doom agent's slow system",
    }[spec.kind]
    return f"{who}; your concern is {spec.concern}. You see only the evidence given."


def preamble(spec: InstanceSpec) -> str:
    """The opening of every instruction of `spec`: who it is, its concern, and that it sees only the evidence given."""
    return _preamble(spec)


def menu_criteria(menu: Sequence[MenuItem]) -> Dict[str, str]:
    """The criteria of an action choice: exactly the legal menu, in menu order, id -> description."""
    return {item.id: item.description for item in menu}


TARGET_QUESTIONS: Dict[str, str] = {
    "enemy": "Which visible enemy should the agent's aim lock onto?",
    "pickup": (
        "When the agent walks to a pickup, which one should it walk to, given where each lies and whether "
        "walking at it has got the agent any closer?"
    ),
}


def target_criteria(spec: InstanceSpec, inputs: EvidenceInputs) -> Dict[str, str]:
    """The criteria of a sense's `target` question: the candidates its scope shows, id -> the channel's line.

    Visible enemies when `threats` is in scope, remembered pickups when `landmarks` is; empty (no question)
    when the sense chooses no target, its scope does not show the candidates, or there are none.
    """
    if spec.kind != "sense" or spec.target is None:
        return {}
    if spec.target == "enemy" and "threats" in spec.scope:
        return {e.id: enemy_line(e, inputs.state.screen_width) for e in shown_enemies(inputs)}
    if spec.target == "pickup" and "landmarks" in spec.scope:
        return {m.id: landmark_line(m, inputs.state.tick) for m in shown_landmarks(inputs)}
    return {}


def build_questions(
    spec: InstanceSpec, menu: Sequence[MenuItem] = (), targets: Optional[Dict[str, str]] = None
) -> Dict[str, QuestionSpec]:
    """The finite questions of an instance of this kind; `targets` are a sense's target criteria, if any."""
    pre = _preamble(spec)
    if spec.kind == "sense":
        questions: Dict[str, QuestionSpec] = {
            "speak": NoulQuestion(instructions=f"{pre} Must the action chooser hear from you before the next decision?"),
            "action": ChoiceQuestion(instructions=f"{pre} Which legal action do you recommend now?", criteria=menu_criteria(menu)),
            "reason": ChoiceQuestion(
                instructions=f"{pre} Which reason best describes why?",
                criteria={r: reason_words(r) for r in spec.reasons},
            ),
        }
        if targets and len(targets) >= 2 and spec.target is not None:
            questions["target"] = ChoiceQuestion(instructions=f"{pre} {TARGET_QUESTIONS[spec.target]}", criteria=dict(targets))
        return questions
    if spec.kind == "central":
        return {
            "choose": ChoiceQuestion(instructions=f"{pre} Choose the action the agent executes now.", criteria=menu_criteria(menu))
        }
    return {"admit": NoulQuestion(instructions=f"{pre} Should this proposed macro-action enter the agent's legal menu?")}


class _Miss(Exception):
    def __init__(self, reason: MissReason, message: str, raw: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.raw = raw


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def read_noul(answers: Dict[str, Dict[str, Any]], name: str) -> float:
    answer = answers.get(name)
    value = answer.get("noul") if isinstance(answer, dict) else None
    if not _is_number(value) or not 0.0 <= float(value) <= 1.0:
        raise _Miss("malformed", f"{name}: no probability in [0, 1]", answer)
    return float(value)


def read_choice(
    answers: Dict[str, Dict[str, Any]], name: str, allowed: Sequence[str], tolerance: float, outside: MissReason
) -> Tuple[str, Dict[str, float]]:
    """The top option and the distribution of a choice answer, or a miss. Ties go to the first allowed option."""
    answer = answers.get(name)
    if not isinstance(answer, dict) or not isinstance(answer.get("probabilities"), dict):
        raise _Miss("malformed", f"{name}: no probabilities", answer)
    probs = answer["probabilities"]
    choice = answer.get("choice")
    strays = [k for k in probs if k not in allowed]
    if (choice is not None and choice not in allowed) or strays:
        raise _Miss(outside, f"{name}: {choice if choice not in allowed else strays} is not among the options", answer)
    if not all(_is_number(v) for v in probs.values()):
        raise _Miss("malformed", f"{name}: a probability is not a number", answer)
    if any(float(v) < 0.0 for v in probs.values()):
        raise _Miss("malformed", f"{name}: a negative probability", answer)
    total = sum(float(v) for v in probs.values())
    if abs(total - 1.0) > tolerance:
        raise _Miss("malformed", f"{name}: probabilities sum to {total:.4f}", answer)
    distribution = {k: float(probs.get(k, 0.0)) for k in allowed}
    best = max(distribution.values())
    top = next(k for k in allowed if distribution[k] == best)
    return top, distribution


def _image(frame_b64: Optional[str]) -> Optional[List[str]]:
    return [f"data:image/jpeg;base64,{frame_b64}"] if frame_b64 else None


def run_instance(
    client: D1UltraClient,
    spec: InstanceSpec,
    inputs: EvidenceInputs,
    *,
    frame_b64: Optional[str] = None,
    budget: float = 5.0,
    yes_at: float = 0.5,
    tolerance: float = 0.02,
    counter_name: Optional[str] = None,
) -> InstanceResult:
    """Run a sense or the central: render its scope, ask its questions in one call, read the answers.

    `counter_name` is the name the client counts the call under (the instance's own name by default; the
    history test's re-runs are counted as `history_test:<instance>`). It changes nothing in the payload.
    """
    rendered = render_scope(inputs, spec.scope)
    targets = target_criteria(spec, inputs)
    questions = build_questions(spec, inputs.menu, targets)
    images = _image(frame_b64) if rendered.image_ref is not None else None
    counted = counter_name or spec.name
    call = client.call(counted, rendered.text, questions, images=images, budget=budget)
    base = dict(
        name=spec.name,
        kind=spec.kind,
        scope=rendered.scope,
        evidence=rendered.text,
        image_ref=rendered.image_ref if images else None,
        latency_ms=call.latency_ms,
        retries=call.retries,
        usage=call.usage,
    )
    if not call.answered or call.response is None:
        return InstanceResult(**base, missed=True, miss_reason=call.miss_reason, error=call.error)
    answers = call.response.raw_answers
    menu_ids = inputs.menu_ids()
    try:
        if spec.kind == "sense":
            speak = read_noul(answers, "speak")
            action, action_probs = read_choice(answers, "action", menu_ids, tolerance, "off_menu")
            reason, reason_probs = read_choice(answers, "reason", spec.reasons, tolerance, "malformed")
            if len(targets) >= 2:
                target, target_probs = read_choice(answers, "target", list(targets), tolerance, "off_menu")
            else:  # a lone candidate is the target; there was nothing to choose between, so no question
                target, target_probs = (next(iter(targets)) if targets else None), {}
            return InstanceResult(
                **base,
                answers=answers,
                speak=speak,
                spoke=speak >= yes_at,
                strength=speak,
                action=action,
                action_probabilities=action_probs,
                reason=reason,
                reason_probabilities=reason_probs,
                target=target,
                target_kind=spec.target if target is not None else None,
                target_line=targets.get(target) if target is not None else None,
                target_probabilities=target_probs,
            )
        action, action_probs = read_choice(answers, "choose", menu_ids, tolerance, "off_menu")
        return InstanceResult(**base, answers=answers, action=action, action_probabilities=action_probs)
    except _Miss as miss:
        client.note_miss(counted, miss.reason)
        return InstanceResult(**base, answers=answers, missed=True, miss_reason=miss.reason, error=str(miss), raw_answer=miss.raw)


def run_admit(client: D1UltraClient, evidence: str, *, budget: float = 5.0, spec: InstanceSpec = ADMIT_SPEC) -> InstanceResult:
    """Run the admit instance on a proposal and its sandbox summary: one call, one `admit` noul."""
    call: D1CallResult = client.call(spec.name, evidence, build_questions(spec), budget=budget)
    base = dict(name=spec.name, kind=spec.kind, scope=(), evidence=evidence, latency_ms=call.latency_ms, retries=call.retries, usage=call.usage)
    if not call.answered or call.response is None:
        return InstanceResult(**base, missed=True, miss_reason=call.miss_reason, error=call.error)
    answers = call.response.raw_answers
    try:
        return InstanceResult(**base, answers=answers, admit=read_noul(answers, "admit"))
    except _Miss as miss:
        client.note_miss(spec.name, miss.reason)
        return InstanceResult(**base, answers=answers, missed=True, miss_reason=miss.reason, error=str(miss), raw_answer=miss.raw)


# How each of System 2's questions is read into an `InstanceResult` field, and the miss for an answer
# outside its criteria (a reason outside the vocabulary is malformed, as for a sense).
SYSTEM2_CHOICES: Dict[str, Tuple[str, MissReason]] = {
    "change": ("change", "off_menu"),
    "configure": ("change", "off_menu"),
    "verdict": ("verdict", "off_menu"),
    "reason": ("reason", "malformed"),
}


def run_system2_instance(
    client: D1UltraClient,
    spec: InstanceSpec,
    evidence: str,
    questions: Dict[str, QuestionSpec],
    *,
    budget: float = 5.0,
    yes_at: float = 0.5,
    tolerance: float = 0.02,
) -> InstanceResult:
    """Run one of System 2's instances: one call with its evidence text and finite questions, read in full.

    `speak` (noul) gives the speak probability and whether it spoke (at `yes_at`, d1's own yes); every
    choice is read with its distribution, its top option first in criteria order on a tie. A failed call,
    an answer outside the criteria or a malformed distribution is a miss, and nothing stands in for it.
    """
    call = client.call(spec.name, evidence, questions, budget=budget)
    base = dict(
        name=spec.name, kind=spec.kind, scope=spec.scope, evidence=evidence,
        latency_ms=call.latency_ms, retries=call.retries, usage=call.usage,
    )
    if not call.answered or call.response is None:
        return InstanceResult(**base, missed=True, miss_reason=call.miss_reason, error=call.error)
    answers = call.response.raw_answers
    fields: Dict[str, Any] = {}
    try:
        if "speak" in questions:
            speak = read_noul(answers, "speak")
            fields.update(speak=speak, spoke=speak >= yes_at, strength=speak)
        for name, question in questions.items():
            if name not in SYSTEM2_CHOICES or not isinstance(question, ChoiceQuestion):
                continue
            field, outside = SYSTEM2_CHOICES[name]
            top, distribution = read_choice(answers, name, list(question.criteria), tolerance, outside)
            fields[field] = top
            fields[f"{field}_probabilities"] = distribution
    except _Miss as miss:
        client.note_miss(spec.name, miss.reason)
        return InstanceResult(**base, answers=answers, missed=True, miss_reason=miss.reason, error=str(miss), raw_answer=miss.raw)
    return InstanceResult(**base, answers=answers, **fields)
