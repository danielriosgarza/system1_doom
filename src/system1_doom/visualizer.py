from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
from typing import List, Optional, Sequence, Union
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from system1_doom.logger import ProposalTrace, TickTrace


def _ensure_hwc_uint8(frame: np.ndarray) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.uint8)
    if arr.ndim == 3 and arr.shape[0] in (1, 3, 4) and arr.shape[2] not in (1, 3, 4):
        arr = np.transpose(arr, (1, 2, 0))
    return arr


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
    - Left (640x480): ViZDoom game viewport with action banner
    - Right (440x480): Live Liquid AI d1-ultra Decision Controller HUD
    """
    hwc = _ensure_hwc_uint8(screen_rgb)
    doom_img = Image.fromarray(hwc).resize((640, 480), Image.Resampling.NEAREST)

    canvas = Image.new("RGB", (1080, 480), (18, 20, 26))
    canvas.paste(doom_img, (0, 0))
    draw = ImageDraw.Draw(canvas)

    # Top banner on Doom viewport
    draw.rectangle([0, 0, 640, 30], fill=(12, 14, 18))
    d1_badge = "d1-ultra LIVE" if trace.used_d1_ultra else "LOCAL REFLEX"
    badge_color = (46, 204, 113) if trace.used_d1_ultra else (241, 196, 15)
    draw.text((10, 8), f"TICK {trace.tick:03d} | {d1_badge} | HP:{health:.0f} ARM:{armor:.0f} AMMO:{ammo}", fill=badge_color)

    # Bottom action banner on Doom viewport
    draw.rectangle([0, 446, 640, 480], fill=(12, 14, 18))
    step_str = f" -> [{prim_step_label}]" if prim_step_label else f" -> {trace.primitive_steps_executed}"
    draw.text(
        (10, 456),
        f"SELECTED: {trace.selected_action}{step_str}",
        fill=(88, 214, 255),
    )

    # Right panel background & divider
    px = 654
    draw.line([(640, 0), (640, 480)], fill=(60, 68, 82), width=2)
    draw.text((px, 12), "SYSTEM-1 DOOM DECISION CONTROLLER (d1-ultra)", fill=(235, 240, 248))
    draw.text((px, 30), f"Context: {trace.context_signature[:46]}", fill=(145, 155, 172))
    draw.text((px, 46), f"Strategy: {trace.active_strategy} | Budget: {trace.budget_mode}", fill=(170, 200, 255))

    # Section 1: 5 Independent Decision Modules
    y = 72
    draw.text((px, y), "MODULE PROPOSALS (5 WORKERS):", fill=(220, 225, 235))
    y += 18
    for mod_name in ("survival", "combat", "navigation", "resource", "goal"):
        m_info = trace.module_outputs.get(mod_name, {})
        top_act = m_info.get("top_action", "-")
        conf = float(m_info.get("confidence", 0.0))
        req_exp = bool(m_info.get("request_action_expansion", False))
        draw.text((px, y), f"{mod_name.upper():10s}: {str(top_act)[:20]:20s} c={conf:.2f}", fill=(200, 210, 225))
        bar_w = int(80 * min(1.0, max(0.0, conf)))
        draw.rectangle([px + 310, y + 3, px + 390, y + 11], outline=(70, 80, 95), fill=(30, 34, 44))
        draw.rectangle([px + 310, y + 3, px + 310 + bar_w, y + 11], fill=(52, 152, 219))
        if req_exp:
            draw.text((px + 394, y), "EXP!", fill=(231, 76, 60))
        y += 18

    # Section 2: Final Arbiter Probability Distribution (Top 6 actions)
    y += 10
    draw.text((px, y), "FINAL ARBITER DISTRIBUTION:", fill=(220, 225, 235))
    y += 18
    sorted_arb = sorted(trace.arbiter_distribution.items(), key=lambda kv: kv[1], reverse=True)[:6]
    for act_id, prob in sorted_arb:
        is_sel = act_id == trace.selected_action
        label_color = (46, 204, 113) if is_sel else (185, 195, 210)
        bar_color = (46, 204, 113) if is_sel else (100, 115, 140)
        prefix = ">> " if is_sel else "   "
        draw.text((px, y), f"{prefix}{act_id[:22]:22s} {prob * 100:5.1f}%", fill=label_color)
        bar_w = int(140 * min(1.0, max(0.0, prob)))
        draw.rectangle([px + 250, y + 3, px + 390, y + 12], outline=(70, 80, 95), fill=(30, 34, 44))
        draw.rectangle([px + 250, y + 3, px + 250 + bar_w, y + 12], fill=bar_color)
        y += 20

    # Section 3: Bounded Projection & Exploration State
    y += 8
    draw.text((px, y), "PROJECTION & EXPLORATION:", fill=(220, 225, 235))
    y += 18
    sel_proj = trace.projection_results_used.get(trace.selected_action, {})
    if sel_proj:
        draw.text(
            (px, y),
            f"Proj({trace.selected_action[:14]}): E[V]={sel_proj.get('expected_value', 0.0):+.2f} "
            f"DmgIn={sel_proj.get('expected_damage_taken', 0.0):.1f} Surv={sel_proj.get('survival_probability', 0.0):.2f}",
            fill=(165, 215, 185),
        )
        y += 18
    exp = trace.exploration_state
    draw.text(
        (px, y),
        f"Explore Pressure={exp.get('exploration_pressure', 0.0):.2f} | Temp={exp.get('temperature', 0.0):.2f} | "
        f"Step Reward={trace.reward_outcome:+.1f}",
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
        steps = trace.primitive_steps_executed or [trace.selected_action]
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


def _top_choice(probabilities: dict) -> tuple[str, float]:
    if not probabilities:
        return "-", 0.0
    action_id = max(probabilities, key=probabilities.get)
    return str(action_id), float(probabilities[action_id])


def render_decision_dashboard(
    trace: TickTrace,
    proposals: Sequence[ProposalTrace] = (),
    health: float = 100.0,
    armor: float = 0.0,
    ammo: int = 50,
    d1_enabled: bool = True,
    codex_enabled: bool = True,
    codex_busy: bool = False,
    pending_request: str = "",
    execution_mode: str = "sync_d1",
) -> Image.Image:
    """Side panel of this tick's d1-ultra choices and Codex macro recommendations."""
    width, height = 560, 760
    image = Image.new("RGB", (width, height), (18, 20, 26))
    draw = ImageDraw.Draw(image)
    title_font = _load_font(20)
    font = _load_font(15)
    small = _load_font(13)
    y = 16

    def heading(text: str, color: tuple[int, int, int] = (235, 240, 248)) -> None:
        nonlocal y
        draw.text((16, y), text, fill=color, font=title_font)
        y += 28

    def line(text: str, color: tuple[int, int, int] = (200, 210, 225), face: ImageFont.ImageFont = font, gap: int = 22) -> None:
        nonlocal y
        draw.text((16, y), text, fill=color, font=face)
        y += gap

    def wrapped(text: str, color: tuple[int, int, int], face: ImageFont.ImageFont, max_lines: int = 2) -> None:
        nonlocal y
        for row in _wrap_text(draw, text, face, width - 32)[:max_lines]:
            draw.text((16, y), row, fill=color, font=face)
            y += 18
        y += 4

    def meter(fraction: float, color: tuple[int, int, int], row_y: int) -> None:
        draw.rectangle([330, row_y + 4, 530, row_y + 14], fill=(30, 34, 44), outline=(70, 80, 95))
        filled = int(200 * min(1.0, max(0.0, fraction)))
        if filled > 0:
            draw.rectangle([330, row_y + 4, 330 + filled, row_y + 14], fill=color)

    heading("D1  ·  CODEX")
    line(
        f"Tick {trace.tick:03d}    HP {health:.0f}   ARM {armor:.0f}   AMMO {ammo}",
        (170, 200, 255),
        small,
        20,
    )
    line(f"Playing  {trace.selected_action}", (88, 214, 255), font, 24)

    if not d1_enabled:
        d1_status, d1_color = "d1-ultra off", (241, 196, 15)
    elif trace.used_d1_ultra:
        d1_status, d1_color = "d1-ultra answered this tick", (46, 204, 113)
    elif execution_mode == "async_cached":
        d1_status, d1_color = "waiting for d1-ultra cache", (241, 196, 15)
    else:
        d1_status, d1_color = "local reflex this tick", (241, 196, 15)
    line(d1_status, d1_color, small, 22)

    line("D1 MODULE DECISIONS", (220, 225, 235), small, 20)
    for mod_name in ("survival", "combat", "navigation", "resource", "goal"):
        info = trace.module_outputs.get(mod_name, {})
        d1_probs = info.get("d1_probabilities") or {}
        if info.get("used_d1_ultra") and d1_probs:
            action_id, prob = _top_choice(d1_probs)
            label = f"{mod_name.upper():8} {action_id[:14]:14} {prob * 100:3.0f}%"
            color = (46, 204, 113)
        else:
            action_id = str(info.get("top_action") or "-")
            label = f"{mod_name.upper():8} local {action_id[:14]}"
            prob = float((info.get("probabilities") or {}).get(action_id, 0.0))
            color = (185, 195, 210)
        row_y = y
        line(label, color, small, 22)
        meter(prob, color, row_y)
        if info.get("request_action_expansion"):
            line("  asked Codex for a new macro", (231, 76, 60), small, 18)
    y += 6

    d1_action, d1_prob = _top_choice(trace.d1_arbiter_distribution)
    line("D1 ARBITER", (220, 225, 235), small, 20)
    if trace.d1_arbiter_distribution:
        row_y = y
        line(f"d1 pick   {d1_action[:18]:18} {d1_prob * 100:4.0f}%", (46, 204, 113), small, 22)
        meter(d1_prob, (46, 204, 113), row_y)
    else:
        line("no d1 arbiter answer yet", (145, 155, 172), small, 20)
    chosen, chosen_prob = _top_choice(
        {trace.selected_action: trace.arbiter_distribution.get(trace.selected_action, 0.0)}
    )
    line(f"executed  {chosen[:22]:22} {chosen_prob * 100:4.0f}%", (88, 214, 255), small, 22)

    y += 6
    line("CODEX RECOMMENDATIONS", (220, 225, 235), small, 20)
    if not codex_enabled:
        line("Codex worker off", (241, 196, 15), small, 20)
    elif codex_busy:
        line("Codex is writing a macro…", (241, 196, 15), small, 20)
        if pending_request:
            wrapped(pending_request.split(":")[-1][:180], (185, 195, 210), small, 2)
    elif not proposals:
        line("No recommendation yet.", (145, 155, 172), small, 20)
        line("A module asks Codex after repeated failures.", (145, 155, 172), small, 20)
    for proposal in list(proposals)[-3:]:
        parsed = proposal.parsed_proposal or {}
        action_id = proposal.admitted_action_id or str(parsed.get("id") or "proposal")
        admitted = proposal.admission_decision
        tag = "ADMITTED" if admitted else "REJECTED"
        tag_color = (46, 204, 113) if admitted else (231, 76, 60)
        admit_p = proposal.d1_admission_probability
        admit_txt = f"  d1 {admit_p * 100:.0f}%" if admit_p is not None else ""
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
            self._root.title("D1 and Codex decisions")
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
