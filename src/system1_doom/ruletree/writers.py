"""Rule writers: who reads a failure's dossier and proposes one rule.

A writer gets the whole prompt (the instructions, the dossier, and its earlier attempts on the same failure with
what the check said) and returns its answer as text; the loop reads the JSON proposal out of it. Writers are called
without memory between calls.

- `CodexWriter` runs the Codex CLI (`codex exec`), read-only, in the run's folder so it can open the frames.
- `ClaudeWriter` runs Claude Code in print mode (`claude -p`), allowed to read files only.
- `FileWriter` leaves the prompt in a file and waits for a person or another program to put the answer next to it.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

CODEX_CMD = "codex exec --skip-git-repo-check --sandbox read-only --output-last-message {out} -"
CLAUDE_CMD = "claude -p --allowedTools Read --output-format text"


class Writer(Protocol):
    name: str

    def write(self, prompt: str, name: str, folder: Path) -> str:
        """The writer's answer to `prompt`; `name` and `folder` say where to keep its files."""


class CommandWriter:
    """A command that reads the prompt on standard input and answers on standard output, or in the file `{out}`."""

    def __init__(self, cmd: str, name: str = "command", cwd: Optional[Path] = None, timeout: float = 1800.0) -> None:
        self.cmd = cmd
        self.name = name
        self.cwd = cwd
        self.timeout = timeout

    def write(self, prompt: str, name: str, folder: Path) -> str:
        out = folder / f"{name}.answer.txt"
        cmd = [part.replace("{out}", str(out)) for part in shlex.split(self.cmd)]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=self.cwd or folder, timeout=self.timeout)
        (folder / f"{name}.stdout.txt").write_text(proc.stdout[-200000:] + "\n--- stderr ---\n" + proc.stderr[-20000:], encoding="utf-8")
        if out.is_file() and out.read_text(encoding="utf-8").strip():
            return out.read_text(encoding="utf-8")
        out.write_text(proc.stdout, encoding="utf-8")
        return proc.stdout


class CodexWriter(CommandWriter):
    def __init__(self, cmd: str = CODEX_CMD, cwd: Optional[Path] = None, timeout: float = 1800.0) -> None:
        super().__init__(cmd, "codex", cwd, timeout)


class ClaudeWriter(CommandWriter):
    def __init__(self, cmd: str = CLAUDE_CMD, cwd: Optional[Path] = None, timeout: float = 1800.0) -> None:
        super().__init__(cmd, "claude", cwd, timeout)


class FileWriter:
    """Writes `<name>.prompt.md` and waits for `<name>.answer.json` (or `.txt`) in the same folder."""

    name = "file"

    def __init__(self, poll: float = 2.0, timeout: float = 24 * 3600.0) -> None:
        self.poll = poll
        self.timeout = timeout

    def write(self, prompt: str, name: str, folder: Path) -> str:
        (folder / f"{name}.prompt.md").write_text(prompt, encoding="utf-8")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            for suffix in (".answer.json", ".answer.txt"):
                p = folder / f"{name}{suffix}"
                if p.is_file() and p.read_text(encoding="utf-8").strip():
                    return p.read_text(encoding="utf-8")
            time.sleep(self.poll)
        raise TimeoutError(f"no answer in {folder / name}.answer.json after {self.timeout:g} s")


def writer_named(name: str, cmd: Optional[str] = None) -> Writer:
    if name == "codex":
        return CodexWriter(cmd or CODEX_CMD)
    if name == "claude":
        return ClaudeWriter(cmd or CLAUDE_CMD)
    if name == "file":
        return FileWriter()
    raise ValueError(f"unknown writer {name!r}; the writers are codex, claude and file")


def parse(answer: str) -> Dict[str, Any]:
    """The JSON object in a writer's answer (bare, or in a fenced block)."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", answer, re.S)
    candidates = blocks + [answer[answer.find("{"): answer.rfind("}") + 1]]
    for c in candidates:
        try:
            value = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object in the answer")
