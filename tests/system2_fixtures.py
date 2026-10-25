"""A synthetic history for System 2's pure tests: `TickRecord`s built without a call, with known rewards.

Every record re-renders like a played tick: each instance's evidence is its scope rendered from the
record's own inputs (the golden fixture state of `test_evidence.py`, with the tick, the context and the
messages filled in), so the history test can re-run any instance on it under another scope.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from system1_doom.configuration import CENTRAL_NAME, SENSE_NAMES, Configuration, default_configuration
from system1_doom.evidence import Message, render_scope
from system1_doom.history import TickRecord
from system1_doom.instance import InstanceResult
from system1_doom.system1 import Pick, central_scope
from system1_doom.tracing import OutcomeTrace
from tests.test_evidence import golden_inputs

CONFIG = default_configuration()
MENU = ("shoot", "strafe_left", "approach_pickup")
_BASE = golden_inputs()


def distribution(chosen: str, options: Sequence[str] = MENU, p: float = 0.7) -> Dict[str, float]:
    rest = (1.0 - p) / (len(options) - 1)
    return {o: (p if o == chosen else rest) for o in options}


def make_record(
    episode_id: str,
    tick: int,
    reward: float,
    *,
    executed: Optional[str] = "shoot",
    spoken: Optional[Dict[str, Tuple[str, float]]] = None,
    context: str = "ctx_a",
    kills: float = 0.0,
    damage: float = 0.0,
    died: bool = False,
    stalled: bool = False,
    displacement: float = 0.0,
    new_cells: int = 0,
    novelty: Optional[Dict[str, int]] = None,
    pick_kind: str = "top",
    tie: bool = False,
    sense_missed: Iterable[str] = (),
    central_action: Optional[str] = None,
    config: Configuration = CONFIG,
    frame_ref: Optional[str] = None,
) -> TickRecord:
    """One stored tick. `spoken` maps a sense to (action, strength); `executed` None is a missed central."""
    spoken = dict(spoken or {})
    missed = set(sense_missed)
    messages = tuple(
        Message(sense=s, action=a, reason=config.senses[s].reasons[0], strength=st)
        for s, (a, st) in spoken.items()
        if s not in missed
    )
    inputs = _BASE.model_copy(
        update={
            "tick": tick,
            "context": context,
            "messages": messages,
            "novelty": dict(novelty) if novelty is not None else dict(_BASE.novelty),
            "frame_ref": frame_ref,
            "exploration_level": config.exploration_level,
        }
    )
    instances: Dict[str, InstanceResult] = {}
    for sense in SENSE_NAMES:
        rendered = render_scope(inputs, config.senses[sense].scope)
        base = dict(name=sense, kind="sense", scope=rendered.scope, evidence=rendered.text, image_ref=rendered.image_ref, latency_ms=300.0)
        if sense in missed:
            instances[sense] = InstanceResult(**base, missed=True, miss_reason="timeout", error="fixture")
            continue
        action, strength = spoken.get(sense, (executed or MENU[0], 0.2))
        instances[sense] = InstanceResult(
            **base,
            speak=strength,
            spoke=sense in spoken,
            strength=strength,
            action=action,
            action_probabilities=distribution(action),
            reason=config.senses[sense].reasons[0],
            reason_probabilities=distribution(config.senses[sense].reasons[0], config.senses[sense].reasons),
        )
    rendered = render_scope(inputs, central_scope(config))
    base = dict(name=CENTRAL_NAME, kind="central", scope=rendered.scope, evidence=rendered.text, latency_ms=250.0)
    if executed is None:
        instances[CENTRAL_NAME] = InstanceResult(**base, missed=True, miss_reason="error", error="fixture")
        pick = Pick(kind="missed")
    else:
        top = central_action or executed
        instances[CENTRAL_NAME] = InstanceResult(**base, action=top, action_probabilities=distribution(top))
        pick = Pick(kind=pick_kind, action=executed, probability=0.7, tie=tie, tied=MENU[:2] if tie else ())  # type: ignore[arg-type]
    return TickRecord(
        episode_id=episode_id,
        tick=tick,
        configuration_version=config.version,
        exploration_level=config.exploration_level,
        active_strategy=config.active_strategy,
        inputs=inputs,
        instances=instances,
        messages=messages,
        pick=pick,
        executed_action=executed,
        primitives=("shoot",) if executed else ("idle",) * 4,
        reward=reward,
        done=False,
        outcome=OutcomeTrace(
            reward=reward, kills_delta=kills, damage_taken=damage, died=died, displacement=displacement, new_cells=new_cells
        ),
        stalled=stalled,
    )


def episode(episode_id: str, rewards: Sequence[float], **kwargs) -> List[TickRecord]:
    return [make_record(episode_id, t, r, **kwargs) for t, r in enumerate(rewards)]
