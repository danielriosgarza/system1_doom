from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import threading
from typing import Any, Callable, Dict, List, Literal, Optional, Union
import requests
from pydantic import BaseModel, ConfigDict, Field


DEFAULT_LIQUID_DECISIONS_URL = "https://api.liquid.ai/decisions/v1/systemone"
DEFAULT_DECISION_MODEL = "d1-ultra"


def load_api_key(dotenv_path: Optional[Union[str, Path]] = None) -> Optional[str]:
    """Load LIQUID_API_KEY from environment or local .env file."""
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
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["score"] = "score"
    instructions: str
    criteria: List[str]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "type": "score",
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


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


TransportFn = Callable[[str, Dict[str, str], Dict[str, Any], float], Dict[str, Any]]


def _default_requests_transport(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class D1UltraClient:
    """
    Client for Liquid AI's d1-ultra decision model (`POST /decisions/v1/systemone`).

    Supports:
    - Synchronous structured decisions (`decide`) for step-by-step evaluation
    - Asynchronous non-blocking cache refresh (`submit_async` + `get_cached`) so the real-time
      35Hz game loop never blocks on network I/O
    - Graceful disable (`enabled=False`) so Doom runs normally even when offline
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_DECISION_MODEL,
        endpoint_url: str = DEFAULT_LIQUID_DECISIONS_URL,
        enabled: bool = True,
        default_timeout: float = 4.0,
        max_workers: int = 2,
        transport: Optional[TransportFn] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else load_api_key()
        self.model = model
        self.endpoint_url = endpoint_url
        self.enabled = enabled and bool(self.api_key)
        self.default_timeout = default_timeout
        self._transport: TransportFn = transport or _default_requests_transport

        self._lock = threading.Lock()
        self._cache: Dict[str, D1Response] = {}
        self._inflight: set[str] = set()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="d1-ultra-worker")
        self.call_count: int = 0
        self.error_count: int = 0

    def decide(
        self,
        state: str,
        questions: Dict[str, QuestionSpec],
        images: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[D1Response]:
        if not self.enabled or not self.api_key or not questions:
            return None

        payload: Dict[str, Any] = {
            "model": self.model,
            "state": state,
            "questions": {k: q.to_payload() for k, q in questions.items()},
        }
        if images:
            payload["images"] = list(images[:8])

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "system1-doom/0.1",
        }

        try:
            raw = self._transport(
                self.endpoint_url,
                headers,
                payload,
                timeout if timeout is not None else self.default_timeout,
            )
            with self._lock:
                self.call_count += 1
            return D1Response(
                model=raw.get("model", self.model),
                raw_answers=raw.get("answers", {}),
                usage=raw.get("usage", {}),
            )
        except Exception:
            with self._lock:
                self.error_count += 1
            return None

    def submit_async(
        self,
        context_key: str,
        state: str,
        questions: Dict[str, QuestionSpec],
        images: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        """Schedule a non-blocking background d1-ultra decision update for `context_key`."""
        if not self.enabled or not self.api_key:
            return False

        with self._lock:
            if context_key in self._inflight:
                return False
            self._inflight.add(context_key)

        def _worker() -> None:
            try:
                resp = self.decide(state=state, questions=questions, images=images, timeout=timeout)
                if resp is not None:
                    with self._lock:
                        self._cache[context_key] = resp
                        self._cache["__latest__"] = resp
            finally:
                with self._lock:
                    self._inflight.discard(context_key)

        self._executor.submit(_worker)
        return True

    def get_cached(self, context_key: str, fallback_to_latest: bool = False) -> Optional[D1Response]:
        with self._lock:
            if context_key in self._cache:
                return self._cache[context_key]
            if fallback_to_latest:
                return self._cache.get("__latest__")
            return None

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
