"""Client for the decision model: Liquid AI's d1-ultra (`POST https://api.liquid.ai/decisions/v1/systemone`),
with `decider="jev"` TypeSafe's Jev (`POST https://api.typesafe.ai/v1/systemone`), or with `decider="laya"`
Convai Innovations' open-weight Laya, served on this machine by `laya-serve` (`POST http://127.0.0.1:8000/v1/systemone`).

The decision model is the decision maker: every instance is one call with its own evidence and finite
questions. This client sends a call and reports exactly what happened: the response, or a typed miss
(`timeout`, `error`, `http_429_exhausted`; the instance layer adds `off_menu` and `malformed`), with the
call's latency, retries and token usage, counted per instance name. It never invents an answer.

The models answer the same System One request (`model`, `state`, `questions` of type `noul`, `choice`
and `score`) with the same answer shapes, so the hierarchy is identical on each; a `Decider` is the
data that differs: the endpoint, the model name, the key's variable, how a screen is sent (d1-ultra
takes `images` as data URLs; Jev takes `assets` referenced from the state, scaled up to its minimum
side, under its images header; Laya reads text only and is sent no screen), the published input price,
which stands in for the `cost` a Jev usage block does not report, and any fields of its own the request
carries (Laya's `max_len`).

The transport is injectable (`TransportFn(url, headers, payload, timeout) -> dict`), so tests answer
from a fake without a key; the default posts with `requests`. Calls run on a worker pool sized by the
caller, and the caller's budget bounds each call from start to answer, retries included: an HTTP 429
waits per `Retry-After` only while the budget lasts.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from email.utils import parsedate_to_datetime
import io
import math
import os
from pathlib import Path
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from PIL import Image
import requests
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LIQUID_DECISIONS_URL = "https://api.liquid.ai/decisions/v1/systemone"
DEFAULT_DECISION_MODEL = "d1-ultra"
TYPESAFE_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
# The alias of TypeSafe's current release; each response's `model` names the version that answered.
DEFAULT_JEV_MODEL = "jev-latest"
MAX_IMAGES = 8
# How long to wait after a 429 that names no Retry-After; still only within the call's budget.
DEFAULT_RETRY_AFTER_SEC = 0.5
# TypeSafe rejects an image with a side under 280 px: the 320x240 screen is scaled up by a whole factor.
JEV_MIN_IMAGE_SIDE = 280
JEV_IMAGES_HEADER = "TypeSafe-Danger-Zone-Images"
# The channel-like label under which a Jev state ends with the screen's asset reference.
JEV_SCREEN_LABEL = "screen image"
# `laya-serve` on this machine (`LAYA_HOST=127.0.0.1`); with LAYA_API_KEY set there, the same key here.
DEFAULT_LAYA_URL = "http://127.0.0.1:8000/v1/systemone"
# The English checkpoint (ModernBERT-large); unnamed, the server routes each state by its language.
DEFAULT_LAYA_MODEL = "english"
# Laya's English checkpoint reads 512 tokens by default and drops the rest of a long state silently. A rule-tree
# state runs to about 800 tokens and ends with the [focus] channel the aim skill's conditions read, so every
# request asks for a window that holds all of it (ModernBERT's positions reach 8,192).
LAYA_MAX_LEN = 2048

MissReason = Literal["timeout", "error", "http_429_exhausted", "off_menu", "malformed"]
MISS_REASONS = ("timeout", "error", "http_429_exhausted", "off_menu", "malformed")

DeciderName = Literal["d1-ultra", "jev", "laya"]
DECIDER_NAMES = ("d1-ultra", "jev", "laya")


class Decider(BaseModel):
    """A decision model the hierarchy can run on: where its calls go, how they are keyed and what they cost."""

    model_config = ConfigDict(frozen=True)

    name: DeciderName
    vendor: str
    endpoint_url: str
    model: str
    key_env: str = Field(description="The environment variable (or .env entry) holding the API key")
    key_required: bool = Field(default=True, description="False for a server on this machine that may run without a key")
    images: Literal["data_urls", "assets", "none"] = Field(
        description="How a screen is sent: d1's `images` list, TypeSafe's `assets`, or not at all (a text-only model)"
    )
    input_usd_per_mtok: Optional[float] = Field(
        default=None, description="Published input price; reported as a call's cost when its usage block names none"
    )
    request: Dict[str, Any] = Field(default_factory=dict, description="Fields of the decider's own that every request carries")


DECIDERS: Dict[str, Decider] = {
    "d1-ultra": Decider(
        name="d1-ultra",
        vendor="Liquid AI",
        endpoint_url=DEFAULT_LIQUID_DECISIONS_URL,
        model=DEFAULT_DECISION_MODEL,
        key_env="LIQUID_API_KEY",
        images="data_urls",
    ),
    "jev": Decider(
        name="jev",
        vendor="TypeSafe",
        endpoint_url=TYPESAFE_SYSTEMONE_URL,
        model=DEFAULT_JEV_MODEL,
        key_env="TYPESAFE_API_KEY",
        images="assets",
        # $42 per billion input tokens; output tokens are free (docs.typesafe.ai/models, October 2026).
        input_usd_per_mtok=0.042,
    ),
    "laya": Decider(
        name="laya",
        vendor="Convai Innovations (open weights, on this machine)",
        endpoint_url=DEFAULT_LAYA_URL,
        model=DEFAULT_LAYA_MODEL,
        key_env="LAYA_API_KEY",
        key_required=False,
        images="none",
        request={"max_len": LAYA_MAX_LEN},
    ),
}


def decider_of(decider: Union[str, Decider]) -> Decider:
    """The `Decider` named, or given."""
    if isinstance(decider, Decider):
        return decider
    try:
        return DECIDERS[decider]
    except KeyError:
        raise ValueError(f"unknown decider {decider!r}; the deciders are {list(DECIDERS)}") from None


def load_api_key(decider: Union[str, Decider] = "d1-ultra", dotenv_path: Optional[Union[str, Path]] = None) -> Optional[str]:
    """Load the decider's key (LIQUID_API_KEY, TYPESAFE_API_KEY for Jev, LAYA_API_KEY for Laya) from the environment
    or a local .env file."""
    key_env = decider_of(decider).key_env
    env_val = os.environ.get(key_env)
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
                if k.strip() == key_env:
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
    """Token usage and cost of one call, as the response's `usage` block reports it.

    When the block names no `cost` (Jev's does not) and the decider has a published input price, the cost
    is the input tokens at that price; output tokens are free there.
    """

    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    @classmethod
    def parse(cls, raw: Any, input_usd_per_mtok: Optional[float] = None) -> "Usage":
        if not isinstance(raw, dict):
            return cls()

        def number(key: str, kind: type) -> Any:
            try:
                return kind(raw.get(key) or 0)
            except (TypeError, ValueError):
                return kind(0)

        input_tokens = number("input_tokens", int)
        if raw.get("cost") is None and input_usd_per_mtok is not None:
            cost = round(input_tokens * input_usd_per_mtok / 1_000_000, 12)
        else:
            cost = number("cost", float)
        return cls(input_tokens=input_tokens, output_tokens=number("output_tokens", int), cost=cost)


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


def jev_asset(data_url: str) -> Dict[str, Any]:
    """A TypeSafe image asset from a `data:image/...;base64,` URL: the same screen, scaled up by the smallest
    whole factor that clears TypeSafe's minimum side (320x240 becomes 640x480), as a baseline JPEG."""
    _, _, data = data_url.partition(",")
    with Image.open(io.BytesIO(base64.b64decode(data))) as img:
        factor = max(1, math.ceil(JEV_MIN_IMAGE_SIDE / min(img.size)))
        scaled = img.convert("RGB")
        if factor > 1:
            scaled = scaled.resize((img.width * factor, img.height * factor), Image.Resampling.BILINEAR)
        out = io.BytesIO()
        scaled.save(out, format="JPEG", quality=90)
    return {"type": "image", "format": "jpeg", "data_base64": base64.b64encode(out.getvalue()).decode("ascii")}


class D1UltraClient:
    """Decision-model calls (d1-ultra, Jev with `decider="jev"`, or Laya with `decider="laya"`) with a per-call
    budget, typed misses, usage and per-instance counters."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        decider: Union[str, Decider] = "d1-ultra",
        model: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        default_timeout: float = 5.0,
        max_workers: int = 6,
        transport: Optional[TransportFn] = None,
    ) -> None:
        self.decider = decider_of(decider)
        self.api_key = api_key if api_key is not None else load_api_key(self.decider)
        self.model = model or self.decider.model
        self.endpoint_url = endpoint_url or self.decider.endpoint_url
        self.default_timeout = default_timeout
        self.max_workers = max(1, max_workers)
        self._transport: TransportFn = transport or _default_requests_transport
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix=f"{self.decider.name}-call")
        self._counters: Dict[str, InstanceCounters] = {}
        self._models: Dict[str, int] = {}

    @property
    def has_key(self) -> bool:
        return bool(self.api_key) or not self.decider.key_required

    def payload(self, state: str, questions: Dict[str, QuestionSpec], images: Optional[List[str]] = None) -> Dict[str, Any]:
        """The request body exactly as sent: model, state, questions, the decider's own fields and, when given,
        the images.

        d1-ultra takes the images as a list of data URLs. Jev takes them as `assets`, each referenced from
        the end of the state under `[screen image]`, where the model reads the screen in the reference's place.
        Laya reads text only: its state is sent as it is, without the screen.
        """
        body: Dict[str, Any] = {
            "model": self.model,
            "state": state,
            "questions": {k: q.to_payload() for k, q in questions.items()},
            **self.decider.request,
        }
        if images and self.decider.images == "assets":
            refs = [str(uuid.uuid4()) for _ in images[:MAX_IMAGES]]
            body["state"] = f"{state}\n\n[{JEV_SCREEN_LABEL}]\n" + "\n".join(refs)
            body["assets"] = {ref: jev_asset(url) for ref, url in zip(refs, images)}
        elif images and self.decider.images == "data_urls":
            body["images"] = list(images[:MAX_IMAGES])
        return body

    def headers(self, body: Dict[str, Any]) -> Dict[str, str]:
        """The request's headers: the bearer key (when there is one), and TypeSafe's images header when the body
        carries assets."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "system1-doom/0.4",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "assets" in body:
            headers[JEV_IMAGES_HEADER] = "true"
        return headers

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

        if not self.has_key:
            return done(miss_reason="error", error=f"no {self.decider.key_env}")
        if not questions:
            return done(miss_reason="error", error="no questions")
        try:
            body = self.payload(state, questions, images)
        except Exception as exc:  # noqa: BLE001 - an unreadable screen is a miss of this call, never an exception in play
            return done(miss_reason="error", error=f"{type(exc).__name__}: {exc}"[:300])
        headers = self.headers(body)
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
            with self._lock:
                self._models[response.model] = self._models.get(response.model, 0) + 1
            return done(response=response, usage=Usage.parse(raw.get("usage"), self.decider.input_usd_per_mtok))

    def models_answered(self) -> Dict[str, int]:
        """Answers per model name as the responses reported it (an alias such as `jev-latest` answers as its version)."""
        with self._lock:
            return dict(self._models)

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

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
