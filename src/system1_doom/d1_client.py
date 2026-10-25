"""Client for Liquid AI's d1-ultra decision model (`POST https://api.liquid.ai/decisions/v1/systemone`).

d1-ultra is the decision maker: every instance is one call with its own evidence and finite questions.
This client sends a call and reports exactly what happened: the response, or a typed miss
(`timeout`, `error`, `http_429_exhausted`; the instance layer adds `off_menu` and `malformed`), with the
call's latency, retries and token usage, counted per instance name. It never invents an answer.

The transport is injectable (`TransportFn(url, headers, payload, timeout) -> dict`), so tests answer
from a fake without a key; the default posts with `requests`. Calls run on a worker pool sized by the
caller, and the caller's budget bounds each call from start to answer, retries included: an HTTP 429
waits per `Retry-After` only while the budget lasts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from email.utils import parsedate_to_datetime
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Union

import requests
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LIQUID_DECISIONS_URL = "https://api.liquid.ai/decisions/v1/systemone"
DEFAULT_DECISION_MODEL = "d1-ultra"
MAX_IMAGES = 8
# How long to wait after a 429 that names no Retry-After; still only within the call's budget.
DEFAULT_RETRY_AFTER_SEC = 0.5

MissReason = Literal["timeout", "error", "http_429_exhausted", "off_menu", "malformed"]
MISS_REASONS = ("timeout", "error", "http_429_exhausted", "off_menu", "malformed")


def load_api_key(dotenv_path: Optional[Union[str, Path]] = None) -> Optional[str]:
    """Load LIQUID_API_KEY from the environment or a local .env file."""
    env_val = os.environ.get("LIQUID_API_KEY")
    if env_val:
        return env_val.strip()

    candidates = [Path(dotenv_path)] if dotenv_path else [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    for path in candidates:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                if k.strip() == "LIQUID_API_KEY":
                    return v.strip().strip('"').strip("'")
    return None


class NoulQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["noul"] = "noul"
    instructions: str

    def to_payload(self) -> Dict[str, Any]:
        return {"type": "noul", "instructions": self.instructions}


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["choice"] = "choice"
    instructions: str
    criteria: Dict[str, str]

    def to_payload(self) -> Dict[str, Any]:
        return {"type": "choice", "instructions": self.instructions, "criteria": dict(self.criteria)}


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["score"] = "score"
    instructions: str
    criteria: List[str]

    def to_payload(self) -> Dict[str, Any]:
        return {"type": "score", "instructions": self.instructions, "criteria": list(self.criteria)}


QuestionSpec = Union[NoulQuestion, ChoiceQuestion, ScoreQuestion]


class NoulAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["noul"] = "noul"
    noul: float


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["choice"] = "choice"
    choice: str
    probabilities: Dict[str, float]
    confidence: float = 0.0


class ScoreAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["score"] = "score"
    score: float
    probabilities: Dict[str, float]
    legend: Dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0


class Usage(BaseModel):
    """Token usage and cost of one call, as the response's `usage` block reports it."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    @classmethod
    def parse(cls, raw: Any) -> "Usage":
        if not isinstance(raw, dict):
            return cls()

        def number(key: str, kind: type) -> Any:
            try:
                return kind(raw.get(key) or 0)
            except (TypeError, ValueError):
                return kind(0)

        return cls(input_tokens=number("input_tokens", int), output_tokens=number("output_tokens", int), cost=number("cost", float))


class D1Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    raw_answers: Dict[str, Dict[str, Any]]
    usage: Dict[str, Any] = Field(default_factory=dict)

    def noul(self, name: str) -> NoulAnswer:
        return NoulAnswer.model_validate(self.raw_answers[name])

    def choice(self, name: str) -> ChoiceAnswer:
        return ChoiceAnswer.model_validate(self.raw_answers[name])

    def score(self, name: str) -> ScoreAnswer:
        return ScoreAnswer.model_validate(self.raw_answers[name])


class D1CallResult(BaseModel):
    """One call's outcome: a response, or a typed miss; never a stand-in answer."""

    model_config = ConfigDict(frozen=True)

    instance: str
    response: Optional[D1Response] = None
    miss_reason: Optional[MissReason] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    retries: int = 0
    usage: Usage = Field(default_factory=Usage)

    @property
    def answered(self) -> bool:
        return self.response is not None and self.miss_reason is None


class InstanceCounters(BaseModel):
    """What the client has seen of one instance name: calls, misses by reason, retries, latency, usage."""

    calls: int = 0
    answered: int = 0
    misses: Dict[str, int] = Field(default_factory=dict)
    retries: int = 0
    latency_ms_total: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    @property
    def mean_latency_ms(self) -> float:
        return self.latency_ms_total / self.calls if self.calls else 0.0


class D1HTTPError(Exception):
    """An HTTP error from the endpoint; a transport raises it so the client can honour 429 Retry-After."""

    def __init__(self, status: int, retry_after: Optional[float] = None, message: str = "") -> None:
        super().__init__(f"HTTP {status}: {message}" if message else f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


TransportFn = Callable[[str, Dict[str, str], Dict[str, Any], float], Dict[str, Any]]


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Seconds to wait from a Retry-After header: delta-seconds or an HTTP date; None when absent or unreadable."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _default_requests_transport(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code == 429:
        raise D1HTTPError(429, parse_retry_after(resp.headers.get("Retry-After")), resp.text[:200])
    if resp.status_code >= 400:
        raise D1HTTPError(resp.status_code, None, resp.text[:200])
    return resp.json()


class D1UltraClient:
    """d1-ultra calls with a per-call budget, typed misses, usage and per-instance counters."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_DECISION_MODEL,
        endpoint_url: str = DEFAULT_LIQUID_DECISIONS_URL,
        default_timeout: float = 5.0,
        max_workers: int = 6,
        transport: Optional[TransportFn] = None,
        enabled: bool = True,  # LEGACY-SHIM: removed with modules/arbiter in this PR
    ) -> None:
        self.api_key = api_key if api_key is not None else load_api_key()
        self.enabled = enabled and bool(self.api_key)  # LEGACY-SHIM
        self._legacy_cache: Dict[str, D1Response] = {}  # LEGACY-SHIM
        self._legacy_inflight: set = set()  # LEGACY-SHIM
        self.error_count = 0  # LEGACY-SHIM
        self.model = model
        self.endpoint_url = endpoint_url
        self.default_timeout = default_timeout
        self.max_workers = max(1, max_workers)
        self._transport: TransportFn = transport or _default_requests_transport
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="d1-ultra-call")
        self._counters: Dict[str, InstanceCounters] = {}

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    def payload(self, state: str, questions: Dict[str, QuestionSpec], images: Optional[List[str]] = None) -> Dict[str, Any]:
        """The request body exactly as sent: model, state, questions and, when given, the images."""
        body: Dict[str, Any] = {
            "model": self.model,
            "state": state,
            "questions": {k: q.to_payload() for k, q in questions.items()},
        }
        if images:
            body["images"] = list(images[:MAX_IMAGES])
        return body

    def call(
        self,
        instance: str,
        state: str,
        questions: Dict[str, QuestionSpec],
        images: Optional[List[str]] = None,
        budget: Optional[float] = None,
    ) -> D1CallResult:
        """One call, bounded by `budget` seconds from start to answer. Never raises."""
        budget = self.default_timeout if budget is None else budget
        start = time.monotonic()
        deadline = start + budget
        retries = 0

        def done(**fields: Any) -> D1CallResult:
            result = D1CallResult(instance=instance, latency_ms=round((time.monotonic() - start) * 1000.0, 3), retries=retries, **fields)
            self._count(result)
            return result

        if not self.api_key:
            return done(miss_reason="error", error="no LIQUID_API_KEY")
        if not questions:
            return done(miss_reason="error", error="no questions")
        body = self.payload(state, questions, images)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "system1-doom/0.3",
        }
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return done(miss_reason="timeout", error=f"budget of {budget:g} s spent")
            future = self._pool.submit(self._transport, self.endpoint_url, headers, body, remaining)
            try:
                raw = future.result(timeout=remaining)
            except FutureTimeout:
                return done(miss_reason="timeout", error=f"no answer within {budget:g} s")
            except D1HTTPError as exc:
                if exc.status != 429:
                    return done(miss_reason="error", error=str(exc)[:300])
                wait = DEFAULT_RETRY_AFTER_SEC if exc.retry_after is None else exc.retry_after
                if wait >= deadline - time.monotonic():
                    return done(miss_reason="http_429_exhausted", error=f"429, Retry-After {wait:g} s exceeds the budget")
                time.sleep(wait)
                retries += 1
                continue
            except requests.Timeout as exc:
                return done(miss_reason="timeout", error=f"{type(exc).__name__}: {exc}"[:300])
            except Exception as exc:  # noqa: BLE001 - every failure is a typed miss, never an exception in play
                return done(miss_reason="error", error=f"{type(exc).__name__}: {exc}"[:300])
            if not isinstance(raw, dict) or not isinstance(raw.get("answers"), dict):
                return done(miss_reason="malformed", error="response has no answers object")
            response = D1Response(
                model=str(raw.get("model", self.model)),
                raw_answers={k: v for k, v in raw["answers"].items() if isinstance(v, dict)},
                usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else {},
            )
            return done(response=response, usage=Usage.parse(raw.get("usage")))

    def _count(self, result: D1CallResult) -> None:
        with self._lock:
            c = self._counters.setdefault(result.instance, InstanceCounters())
            c.calls += 1
            c.retries += result.retries
            c.latency_ms_total += result.latency_ms
            c.input_tokens += result.usage.input_tokens
            c.output_tokens += result.usage.output_tokens
            c.cost += result.usage.cost
            if result.miss_reason is None:
                c.answered += 1
            else:
                c.misses[result.miss_reason] = c.misses.get(result.miss_reason, 0) + 1

    def note_miss(self, instance: str, reason: MissReason) -> None:
        """Count a miss the instance layer found in an answered call (an off-menu or malformed answer)."""
        with self._lock:
            c = self._counters.setdefault(instance, InstanceCounters())
            c.answered = max(0, c.answered - 1)
            c.misses[reason] = c.misses.get(reason, 0) + 1

    def counters(self) -> Dict[str, InstanceCounters]:
        with self._lock:
            return {k: v.model_copy(deep=True) for k, v in self._counters.items()}

    @property
    def call_count(self) -> int:
        with self._lock:
            return sum(c.calls for c in self._counters.values())

    @property
    def miss_count(self) -> int:
        with self._lock:
            return sum(sum(c.misses.values()) for c in self._counters.values())

    # LEGACY-SHIM: the cached and blocking calls of the module/arbiter design, removed with them in this PR.
    def decide(self, state: str, questions: Dict[str, QuestionSpec], images: Optional[List[str]] = None, timeout: Optional[float] = None) -> Optional[D1Response]:
        if not self.enabled:
            return None
        result = self.call("legacy", state, questions, images=images, budget=(timeout or self.default_timeout) + 5.0)
        if result.response is None:
            self.error_count += 1
        return result.response

    def submit_async(self, context_key: str, state: str, questions: Dict[str, QuestionSpec], images: Optional[List[str]] = None, timeout: Optional[float] = None) -> bool:
        if not self.enabled or context_key in self._legacy_inflight:
            return False
        self._legacy_inflight.add(context_key)

        def _worker() -> None:
            try:
                resp = self.decide(state, questions, images, timeout)
                if resp is not None:
                    self._legacy_cache[context_key] = resp
            finally:
                self._legacy_inflight.discard(context_key)

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def get_cached(self, context_key: str, fallback_to_latest: bool = False) -> Optional[D1Response]:
        return self._legacy_cache.get(context_key)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
