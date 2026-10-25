"""Pictures of play: a split-screen HUD per tick, GIF/MP4 export, and the live side panel.

Both panels show the tick's six d1-ultra instances: each sense spoke, silent or missed with its
strength, action and reason, and the central's pick (`top`, `drawn` or `missed`).
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from typing import List, Optional, Sequence, Tuple, Union
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from system1_doom.logger import ProposalTrace, TickTrace


def _ensure_hwc_uint8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[2] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    return arr


SENSE_ORDER = ("survival", "combat", "navigation", "resource", "goal")


def instance_rows(trace: TickTrace) -> List[Tuple[str, str, str, float]]:
    """One row per instance for the panels: (name, state, detail, bar), the five senses then the central.

    A sense is `spoke`, `silent` or `missed`, its bar its strength; the central's bar is d1's probability
    of the executed action, and its state says how the pick was made (`top`, `drawn`, `missed`).
    """
    rows: List[Tuple[str, str, str, float]] = []
    for name in SENSE_ORDER:
        r = trace.instances.get(name)
        if r is None:
            continue
        if r.missed:
            rows.append((name, "missed", str(r.miss_reason), 0.0))
        else:
            state = "spoke" if r.spoke else "silent"
            rows.append((name, state, f"{r.action} ({(r.reason or '').replace('_', ' ')})", float(r.strength or 0.0)))
    central = trace.instances.get("central")
    if central is not None:
        if trace.pick.kind == "missed":
            rows.append(("central", "missed", str(central.miss_reason), 0.0))
        else:
            tie = ", tie" if trace.pick.tie else ""
            rows.append(("central", trace.pick.kind, f"{trace.pick.action}{tie}", float(trace.pick.probability or 0.0)))
    return rows


def render_hud_frame(
    screen_rgb: np.ndarray,
    trace: TickTrace,
    health: float = 100.0,
    armor: float = 0.0,
    ammo: int = 50,
    prim_step_label: Optional[str] = None,
) -> Image.Image:
    """
    Compose a 1080x480 split-screen frame:
    - Left (640x480): ViZDoom game viewport with the executed action
    - Right (440x480): the tick's six d1-ultra instances, five senses and the central
    """
    hwc = _ensure_hwc_uint8(screen_rgb)
    doom_img = Image.fromarray(hwc).resize((640, 480), Image.Resampling.NEAREST)

    canvas = Image.new("RGB", (1080, 480), (18, 20, 26))
    canvas.paste(doom_img, (0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rectangle([0, 0, 640, 30], fill=(12, 14, 18))
    badge, badge_color = ("CENTRAL MISSED: NO KEYS", (241, 196, 15)) if trace.missed else ("d1-ultra decided", (46, 204, 113))
    draw.text((10, 8), f"TICK {trace.tick:03d} | {badge} | HP:{health:.0f} ARM:{armor:.0f} AMMO:{ammo}", fill=badge_color)

    draw.rectangle([0, 446, 640, 480], fill=(12, 14, 18))
    step_str = f" -> [{prim_step_label}]" if prim_step_label else f" -> {trace.primitive_steps_executed}"
    draw.text((10, 456), f"EXECUTED: {trace.executed_action or 'nothing (missed)'}{step_str}", fill=(88, 214, 255))

    px = 654
    draw.line([(640, 0), (640, 480)], fill=(60, 68, 82), width=2)
    draw.text((px, 12), "SYSTEM 1: SIX d1-ultra INSTANCES", fill=(235, 240, 248))
    draw.text((px, 30), f"Context: {trace.context_signature[:46]}", fill=(145, 155, 172))
    draw.text(
        (px, 46),
        f"Config v{trace.configuration_version} | {trace.exploration_level} | {trace.active_strategy}"[:60],
        fill=(170, 200, 255),
    )

    y = 72
    for name, state, detail, bar in instance_rows(trace):
        color = {"spoke": (46, 204, 113), "missed": (231, 76, 60), "silent": (145, 155, 172)}.get(state, (88, 214, 255))
        draw.text((px, y), f"{name.upper():10s} {state:7s}", fill=color)
        draw.text((px + 14, y + 16), str(detail)[:44], fill=(200, 210, 225))
        bar_w = int(80 * min(1.0, max(0.0, bar)))
        draw.rectangle([px + 310, y + 3, px + 390, y + 11], outline=(70, 80, 95), fill=(30, 34, 44))
        if bar_w:
            draw.rectangle([px + 310, y + 3, px + 310 + bar_w, y + 11], fill=color)
        y += 40

    y += 6
    spoken = ", ".join(m.sense for m in trace.messages) or "no sense spoke"
    draw.text((px, y), f"Messages: {spoken}"[:60], fill=(220, 225, 235))
    y += 18
    draw.text(
        (px, y),
        f"Step reward {trace.reward_outcome:+.1f} | tick {trace.timing_ms.get('total', 0.0):.0f} ms | "
        f"${trace.usage.cost:.6f}",
        fill=(245, 185, 110),
    )
    return canvas


class EpisodeRecorder:
    """Collects rendered HUD frames across ticks and exports animated GIF or MP4 video."""

    def __init__(self) -> None:
        self.frames: List[Image.Image] = []

    def add_step(
        self,
        raw_frames: Sequence[np.ndarray],
        trace: TickTrace,
        health: float = 100.0,
        armor: float = 0.0,
        ammo: int = 50,
    ) -> None:
        if not raw_frames:
            return
        steps = trace.primitive_steps_executed or [trace.executed_action or "idle"]
        for idx, raw in enumerate(raw_frames):
            prim_lbl = steps[min(idx, len(steps) - 1)]
            self.frames.append(
                render_hud_frame(
                    screen_rgb=raw,
                    trace=trace,
                    health=health,
                    armor=armor,
                    ammo=ammo,
                    prim_step_label=f"{prim_lbl} ({idx + 1}/{len(raw_frames)})",
                )
            )

    def save_gif(self, path: Union[str, Path], fps: int = 8) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.frames:
            raise ValueError("No frames recorded to save.")
        duration_ms = max(40, int(1000 / max(1, fps)))
        self.frames[0].save(
            out_path,
            save_all=True,
            append_images=self.frames[1:],
            duration=duration_ms,
            loop=0,
            optimize=False,
        )
        return out_path

    def save_mp4(self, path: Union[str, Path], fps: int = 8) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.frames:
            raise ValueError("No frames recorded to save.")
        with tempfile.TemporaryDirectory(prefix="doom_vid_") as tmpdir:
            for i, img in enumerate(self.frames):
                img.save(Path(tmpdir) / f"frame_{i:05d}.png")
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-framerate",
                    str(fps),
                    "-i",
                    str(Path(tmpdir) / "frame_%05d.png"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(out_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        return out_path


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> List[str]:
    words = text.replace("\n", " ").split()
    if not words:
        return []
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_decision_dashboard(
    trace: TickTrace,
    proposals: Sequence[ProposalTrace] = (),
    health: float = 100.0,
    armor: float = 0.0,
    ammo: int = 50,
    codex_enabled: bool = True,
    codex_busy: bool = False,
    pending_request: str = "",
) -> Image.Image:
    """Side panel of this tick's six d1-ultra instances and the slow path's proposals."""
    width, height = 560, 760
    image = Image.new("RGB", (width, height), (18, 20, 26))
    draw = ImageDraw.Draw(image)
    title_font = _load_font(20)
    font = _load_font(15)
    small = _load_font(13)
    y = 16

    def heading(text: str, color: tuple = (235, 240, 248)) -> None:
        nonlocal y
        draw.text((16, y), text, fill=color, font=title_font)
        y += 28

    def line(text: str, color: tuple = (200, 210, 225), face: ImageFont.ImageFont = font, gap: int = 22) -> None:
        nonlocal y
        draw.text((16, y), text, fill=color, font=face)
        y += gap

    def wrapped(text: str, color: tuple, face: ImageFont.ImageFont, max_lines: int = 2) -> None:
        nonlocal y
        for row in _wrap_text(draw, text, face, width - 32)[:max_lines]:
            draw.text((16, y), row, fill=color, font=face)
            y += 18
        y += 4

    def meter(fraction: float, color: tuple, row_y: int) -> None:
        draw.rectangle([330, row_y + 4, 530, row_y + 14], fill=(30, 34, 44), outline=(70, 80, 95))
        filled = int(200 * min(1.0, max(0.0, fraction)))
        if filled > 0:
            draw.rectangle([330, row_y + 4, 330 + filled, row_y + 14], fill=color)

    heading("SYSTEM 1  ·  d1-ultra")
    line(f"Tick {trace.tick:03d}    HP {health:.0f}   ARM {armor:.0f}   AMMO {ammo}", (170, 200, 255), small, 20)
    line(f"Executing  {trace.executed_action or 'nothing: the central missed'}", (88, 214, 255), font, 24)
    line(
        f"configuration v{trace.configuration_version}, level {trace.exploration_level}, strategy {trace.active_strategy}",
        (145, 155, 172),
        small,
        22,
    )

    line("THE SIX INSTANCES", (220, 225, 235), small, 20)
    for name, state, detail, bar in instance_rows(trace):
        color = {"spoke": (46, 204, 113), "missed": (231, 76, 60), "silent": (145, 155, 172)}.get(state, (88, 214, 255))
        row_y = y
        line(f"{name.upper():10} {state:7} {str(detail)[:26]}", color, small, 22)
        meter(bar, color, row_y)
    y += 6
    line(
        f"tick {trace.timing_ms.get('total', 0.0):.0f} ms, senses {trace.timing_ms.get('senses', 0.0):.0f} ms, "
        f"central {trace.timing_ms.get('central', 0.0):.0f} ms, ${trace.usage.cost:.6f}",
        (145, 155, 172),
        small,
        22,
    )

    y += 6
    line("SLOW PATH PROPOSALS", (220, 225, 235), small, 20)
    if not codex_enabled:
        line("slow worker off", (241, 196, 15), small, 20)
    elif codex_busy:
        line("a macro is being written…", (241, 196, 15), small, 20)
        if pending_request:
            wrapped(pending_request.split(":")[-1][:180], (185, 195, 210), small, 2)
    elif not proposals:
        line("No proposal yet.", (145, 155, 172), small, 20)
    for proposal in list(proposals)[-3:]:
        parsed = proposal.parsed_proposal or {}
        action_id = proposal.admitted_action_id or str(parsed.get("id") or "proposal")
        admitted = proposal.admission_decision
        tag = "ADMITTED" if admitted else "REJECTED"
        tag_color = (46, 204, 113) if admitted else (231, 76, 60)
        admit_p = proposal.d1_admission_probability
        admit_txt = f"  admit {admit_p * 100:.0f}%" if admit_p is not None else ""
        line(f"{tag:9} {action_id[:24]}{admit_txt}", tag_color, small, 18)
        detail = str(parsed.get("description") or proposal.validation_result or "")
        wrapped(detail, (185, 195, 210), small, 2)

    return image


class LiveDecisionDashboard:
    """Tk window placed to the right of the ViZDoom view."""

    def __init__(self) -> None:
        self._root = None
        self._label = None
        self._photo = None
        self._closed = False

    def update(self, image: Image.Image) -> None:
        if self._closed:
            return
        import tkinter as tk
        from PIL import ImageTk

        if self._root is None:
            self._root = tk.Tk()
            self._root.title("System 1: d1-ultra instances")
            self._root.configure(bg="#12141a")
            self._root.geometry("+680+24")
            self._label = tk.Label(self._root, bg="#12141a", borderwidth=0)
            self._label.pack()
            self._root.protocol("WM_DELETE_WINDOW", self.close)
        self._photo = ImageTk.PhotoImage(image)
        self._label.configure(image=self._photo)
        self._root.update_idletasks()
        self._root.update()

    def close(self) -> None:
        self._closed = True
        root = self._root
        self._root = None
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
