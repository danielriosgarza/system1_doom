"""The five senses: d1-ultra instances that each see one scope and decide whether to speak.

Design spec, section 4. Each sense (survival, combat, navigation, resource, goal) is one call per tick
with its own scope, concern and reason vocabulary, all taken from the configuration. The five calls
run in parallel on System 1's pool, each inside the per-call budget. A sense whose `speak` probability
is d1's own yes (0.5 or more) sends a message: its sense, its top action, its top reason and its
strength, which is the `speak` probability unscaled. A silent sense and a missed sense both reach the
central as silence; a missed sense is kept in the trace as missed, and nothing stands in for it.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Dict, Mapping, Optional, Tuple

from system1_doom.configuration import Configuration
from system1_doom.d1_client import D1UltraClient
from system1_doom.evidence import EvidenceInputs, Message, render_scope
from system1_doom.instance import InstanceResult, InstanceSpec, run_instance, sense_spec

# How long past its own budget System 1 waits for a sense's thread before recording it as a timeout.
# The client already bounds every call by the budget; this only guards against a starved pool.
POOL_GRACE_SEC = 2.0


def sense_specs(config: Configuration) -> Tuple[InstanceSpec, ...]:
    """The five sense instances of a configuration, in sense order."""
    return tuple(sense_spec(name, sense) for name, sense in config.senses.items())


def message_of(result: InstanceResult) -> Optional[Message]:
    """The message a sense sends, or None when it was silent or missed."""
    if result.kind != "sense" or result.missed or not result.spoke:
        return None
    assert result.action is not None and result.reason is not None and result.strength is not None
    return Message(sense=result.name, action=result.action, reason=result.reason, strength=result.strength)


def messages_of(results: Mapping[str, InstanceResult]) -> Tuple[Message, ...]:
    """The messages of the senses that spoke, in sense order."""
    return tuple(m for m in (message_of(r) for r in results.values()) if m is not None)


def _starved(spec: InstanceSpec, inputs: EvidenceInputs, budget: float) -> InstanceResult:
    rendered = render_scope(inputs, spec.scope)
    return InstanceResult(
        name=spec.name,
        kind=spec.kind,
        scope=rendered.scope,
        evidence=rendered.text,
        image_ref=rendered.image_ref,
        missed=True,
        miss_reason="timeout",
        error=f"no answer within {budget:g} s (the call never started in time)",
        latency_ms=round((budget + POOL_GRACE_SEC) * 1000.0, 3),
    )


def run_senses(
    client: D1UltraClient,
    config: Configuration,
    inputs: EvidenceInputs,
    pool: ThreadPoolExecutor,
    *,
    frame_b64: Optional[str] = None,
) -> Dict[str, InstanceResult]:
    """Call the five senses in parallel on `pool`; every result is an answer or a typed miss."""
    bounds = config.bounds
    budget = bounds.call_budget_sec
    specs = sense_specs(config)
    futures: Dict[str, Future] = {
        spec.name: pool.submit(
            run_instance,
            client,
            spec,
            inputs,
            frame_b64=frame_b64,
            budget=budget,
            yes_at=bounds.yes_at,
            tolerance=bounds.probability_tolerance,
        )
        for spec in specs
    }
    results: Dict[str, InstanceResult] = {}
    for spec in specs:
        try:
            results[spec.name] = futures[spec.name].result(timeout=budget + POOL_GRACE_SEC)
        except FutureTimeout:
            futures[spec.name].cancel()
            results[spec.name] = _starved(spec, inputs, budget)
    return results
