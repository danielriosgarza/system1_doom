"""A deterministic stand-in for d1-ultra, answering from the payload alone.

`FakeD1` is a transport (`TransportFn(url, headers, payload, timeout) -> dict`) for `D1UltraClient`. It
reads only what the real API receives: the question names, their instructions and criteria, and the
state text. It follows a scripted policy, records every (instance name, payload) pair, and can be told,
for a chosen call of a chosen instance, to exceed the budget, raise, answer off the menu, return
malformed probabilities, or answer HTTP 429.

Calls are counted per instance name from 0, and every instance is called once per tick, so "call k of
the central" is the central of the k-th tick played with this fake.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from system1_doom.d1_client import D1HTTPError

Answers = Dict[str, Dict[str, Any]]
Policy = Callable[[str, Dict[str, Any]], Answers]

FAULTS = ("timeout", "raise", "off_menu", "malformed", "negative", "http_429")


def section(state: str, channel: str) -> str:
    """The body of one channel in a rendered state text, or '' when the channel is not in it."""
    match = re.search(rf"^\[{re.escape(channel)}\]\n(.*?)(?=\n\n\[|\Z)", state, flags=re.S | re.M)
    return match.group(1) if match else ""


def distribution(options: Sequence[str], chosen: str, p: float = 0.7) -> Dict[str, float]:
    """`chosen` at `p`, the rest sharing what is left equally; one option gets everything."""
    if len(options) == 1:
        return {options[0]: 1.0}
    rest = (1.0 - p) / (len(options) - 1)
    return {o: (p if o == chosen else rest) for o in options}


def choice(options: Sequence[str], chosen: str, p: float = 0.7) -> Dict[str, Any]:
    probs = distribution(options, chosen, p)
    return {"type": "choice", "choice": chosen, "probabilities": probs, "confidence": max(probs.values())}


def noul(value: float) -> Dict[str, Any]:
    return {"type": "noul", "noul": value}


def instance_name(payload: Dict[str, Any]) -> str:
    questions = payload["questions"]
    if "choose" in questions:
        return "central"
    if "admit" in questions:
        return "admit"
    match = re.search(r"You are the (\w+) sense", questions["speak"]["instructions"])
    assert match, questions["speak"]["instructions"]
    return match.group(1)


def menu_of(payload: Dict[str, Any]) -> List[str]:
    questions = payload["questions"]
    key = "choose" if "choose" in questions else "action"
    return list(questions[key]["criteria"])


def health(state: str) -> Optional[float]:
    match = re.search(r"health (\d+)", section(state, "vitals"))
    return float(match.group(1)) if match else None


def aimed(state: str) -> bool:
    return "under the crosshair" in section(state, "threats")


def first_message_action(state: str) -> Optional[str]:
    match = re.search(r"^(\w+) says (\S+), strength", section(state, "messages"), flags=re.M)
    return match.group(2) if match else None


def nearest_enemy_side(state: str) -> Optional[str]:
    match = re.search(r"^- .* at distance \d+, (?:\d+ deg (left|right)|straight ahead)", section(state, "threats"), flags=re.M)
    if not match:
        return None
    return match.group(1) or "ahead"


def _sense(payload: Dict[str, Any], speak: float, action: str, reason: Optional[str] = None) -> Answers:
    questions = payload["questions"]
    menu = menu_of(payload)
    reasons = list(questions["reason"]["criteria"])
    return {
        "speak": noul(speak),
        "action": choice(menu, action if action in menu else menu[0]),
        "reason": choice(reasons, reason if reason in reasons else reasons[0]),
    }


def _central(payload: Dict[str, Any]) -> Answers:
    menu = menu_of(payload)
    wanted = first_message_action(payload["state"])
    return {"choose": choice(menu, wanted if wanted in menu else menu[0])}


def default_policy(name: str, payload: Dict[str, Any]) -> Answers:
    """Combat speaks at 0.9 when an enemy is under the crosshair, survival at 0.95 under 30 health, others 0.2.

    The central picks the first message's action, else the first menu action.
    """
    state = payload["state"]
    if name == "central":
        return _central(payload)
    if name == "admit":
        return {"admit": noul(0.8)}
    menu = menu_of(payload)
    if name == "combat":
        hit = aimed(state)
        return _sense(payload, 0.9 if hit else 0.2, "shoot" if hit else menu[0], "target_aimed" if hit else "no_target")
    if name == "survival":
        hp = health(state)
        low = hp is not None and hp < 30
        return _sense(payload, 0.95 if low else 0.2, menu[0], "health_critical" if low else "no_threat")
    return _sense(payload, 0.2, menu[0])


def shoot_when_aimed(name: str, payload: Dict[str, Any]) -> Answers:
    """Combat shoots when an enemy is under the crosshair and otherwise turns or strafes toward it; the rest stay silent."""
    state = payload["state"]
    if name == "central":
        return _central(payload)
    if name == "admit":
        return {"admit": noul(0.8)}
    menu = menu_of(payload)
    if name != "combat":
        return _sense(payload, 0.1, menu[0])
    if aimed(state) and "shoot" in menu:
        return _sense(payload, 0.9, "shoot", "target_aimed")
    side = nearest_enemy_side(state)
    if side in ("left", "right"):
        toward = next((a for a in (f"turn_{side}", f"strafe_{side}") if a in menu), menu[0])
        return _sense(payload, 0.9, toward, "target_off_centre")
    if side == "ahead" and "shoot" in menu:
        return _sense(payload, 0.9, "shoot", "target_aimed")
    return _sense(payload, 0.1, menu[0], "no_target")


def spread_central(name: str, payload: Dict[str, Any]) -> Answers:
    """Senses as `default_policy`; the central spreads its probability over the menu: 0.4, 0.3, then the rest."""
    if name != "central":
        return default_policy(name, payload)
    menu = menu_of(payload)
    if len(menu) == 1:
        return {"choose": choice(menu, menu[0])}
    if len(menu) == 2:
        probs = {menu[0]: 0.6, menu[1]: 0.4}
    else:
        rest = 0.3 / (len(menu) - 2)
        probs = {a: (0.4 if i == 0 else 0.3 if i == 1 else rest) for i, a in enumerate(menu)}
    return {"choose": {"type": "choice", "choice": menu[0], "probabilities": probs, "confidence": 0.4}}


class FakeD1:
    """A thread-safe scripted transport. `fail(instance, calls, kind)` scripts a fault on chosen calls."""

    def __init__(self, policy: Policy = default_policy, timeout_overrun: float = 0.2, retry_after: float = 0.05) -> None:
        self.policy = policy
        self.timeout_overrun = timeout_overrun
        self.retry_after = retry_after
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {}
        self._faults: Dict[Tuple[str, int], str] = {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.timeouts: List[float] = []

    def fail(self, instance: str, calls: Iterable[int], kind: str) -> "FakeD1":
        assert kind in FAULTS, kind
        with self._lock:
            for index in calls:
                self._faults[(instance, index)] = kind
        return self

    def payloads(self, instance: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [p for n, p in self.calls if n == instance]

    def count(self, instance: str) -> int:
        with self._lock:
            return self._counts.get(instance, 0)

    def __call__(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        name = instance_name(payload)
        with self._lock:
            index = self._counts.get(name, 0)
            self._counts[name] = index + 1
            self.calls.append((name, payload))
            self.timeouts.append(timeout)
            fault = self._faults.pop((name, index), None)
        if fault == "raise":
            raise RuntimeError("fake d1-ultra outage")
        if fault == "http_429":
            raise D1HTTPError(429, retry_after=self.retry_after, message="rate limited")
        if fault == "timeout":
            time.sleep(timeout + self.timeout_overrun)
        answers = self.policy(name, payload)
        key = "choose" if "choose" in answers else "action"
        if fault == "off_menu" and key in answers:
            answers[key] = {"type": "choice", "choice": "teleport_hack", "probabilities": {"teleport_hack": 1.0}, "confidence": 1.0}
        if fault == "malformed" and key in answers:
            probs = {k: v * 1.5 for k, v in answers[key]["probabilities"].items()}
            answers[key] = {**answers[key], "probabilities": probs}
        if fault == "negative" and key in answers:
            probs = dict(answers[key]["probabilities"])
            first = next(iter(probs))
            probs[first] = -0.1
            answers[key] = {**answers[key], "probabilities": probs}
        tokens = max(1, len(payload["state"]) // 4)
        return {
            "model": "d1-ultra",
            "answers": answers,
            "usage": {"input_tokens": tokens, "output_tokens": 0, "cost": round(tokens * 4.2e-8, 12)},
        }
