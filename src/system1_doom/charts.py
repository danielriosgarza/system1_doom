"""Learning-curve charts rendered from a run folder's per-episode metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

BACKGROUND = "#12141a"
PANEL = "#1a1d24"
GRID = "#2a2f3a"
TEXT = "#dfe4ee"
MUTED = "#8a93a6"
BLUE = "#58b4ff"
GREEN = "#2ecc71"
ORANGE = "#f5a623"
RED = "#e74c3c"
MODULE_COLORS = {
    "survival": "#e74c3c",
    "combat": "#f5a623",
    "navigation": "#58b4ff",
    "resource": "#2ecc71",
    "goal": "#b38cff",
}


def rolling_mean(values: Sequence[float], window: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return arr
    csum = np.cumsum(np.insert(arr, 0, 0.0))
    out = np.empty_like(arr)
    for i in range(arr.size):
        lo = max(0, i + 1 - window)
        out[i] = (csum[i + 1] - csum[lo]) / (i + 1 - lo)
    return out


def _style(ax: Any, title: str) -> None:
    ax.set_facecolor(PANEL)
    ax.set_title(title, color=TEXT, fontsize=11, loc="left", pad=8)
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)
    ax.set_xlabel("episode", color=MUTED, fontsize=8)


def render_learning_curves(rows: List[Dict[str, Any]], path: Union[str, Path], title: str) -> Optional[Path]:
    if not rows:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    episodes = np.asarray([r["episode"] for r in rows])
    window = int(min(20, max(3, len(rows) // 8)))
    reward = [float(r["reward"]) for r in rows]
    cleared = [1.0 if r.get("cleared") else 0.0 for r in rows]
    survived = [0.0 if r.get("died") else 1.0 for r in rows]
    health = [float(r.get("health", 0.0)) for r in rows]
    kills = [float(r.get("kills", 0.0)) for r in rows]
    missed = [float(r.get("missed_ticks", 0)) for r in rows]

    fig, axes = plt.subplots(2, 2, figsize=(12, 7.2), dpi=110)
    fig.patch.set_facecolor(BACKGROUND)

    ax = axes[0][0]
    _style(ax, "Episode reward")
    ax.scatter(episodes, reward, s=9, color=BLUE, alpha=0.35, linewidths=0)
    ax.plot(episodes, rolling_mean(reward, window), color=BLUE, linewidth=2.2, label=f"rolling mean ({window})")
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=8, loc="lower right")

    ax = axes[0][1]
    _style(ax, "Success and survival rate (%)")
    ax.plot(episodes, 100.0 * rolling_mean(cleared, window), color=GREEN, linewidth=2.2, label="level cleared")
    ax.plot(episodes, 100.0 * rolling_mean(survived, window), color=ORANGE, linewidth=1.6, label="survived")
    ax.set_ylim(-3, 103)
    ax.legend(facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=8, loc="lower right")

    ax = axes[1][0]
    _style(ax, "Health left and kills")
    ax.plot(episodes, rolling_mean(health, window), color=RED, linewidth=2.0, label="health left")
    ax.set_ylabel("health", color=RED, fontsize=8)
    ax.set_ylim(bottom=0, top=max(10.0, max(health) * 1.1))
    twin = ax.twinx()
    twin.plot(episodes, rolling_mean(kills, window), color=ORANGE, linewidth=2.0, label="kills")
    twin.set_ylabel("kills", color=ORANGE, fontsize=8)
    twin.set_ylim(bottom=0, top=max(1.0, max(kills) * 1.1))
    twin.tick_params(colors=MUTED, labelsize=8)

    ax = axes[1][1]
    _style(ax, "Missed ticks and value-network loss")
    ax.fill_between(episodes, missed, color=MUTED, alpha=0.18, linewidth=0)
    ax.plot(episodes, missed, color=MUTED, linewidth=1.4, label="missed ticks")
    ax.set_ylim(bottom=0, top=max(1.0, max(missed) * 1.1))
    twin = ax.twinx()
    twin.set_yscale("log")
    twin.tick_params(colors=MUTED, labelsize=8)
    for name, color in MODULE_COLORS.items():
        points = [(r["episode"], r["losses"][name]) for r in rows if r.get("losses", {}).get(name, 0.0) > 0.0]
        if points:
            xs, ys = zip(*points)
            twin.plot(xs, ys, color=color, linewidth=1.1, alpha=0.9, label=name)
    handles, labels = twin.get_legend_handles_labels()
    if handles:
        twin.legend(handles, labels, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, fontsize=7, ncol=3, loc="lower right")

    fig.suptitle(f"{title}  ·  {len(rows)} episodes", color=TEXT, fontsize=13, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BACKGROUND)
    plt.close(fig)
    return out
